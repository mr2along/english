import json
import re
from urllib.parse import urlparse, parse_qs, urlencode

import gradio as gr
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

TACTIQ_URL = "https://tactiq.io/tools/youtube-transcript"


def extract_video_id(value):
    value = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    p = urlparse(value)
    host = (p.hostname or "").lower()
    if host == "youtu.be":
        x = p.path.strip("/").split("/")[0]
        return x if re.fullmatch(r"[A-Za-z0-9_-]{11}", x) else None
    if "youtube.com" in host or "youtube-nocookie.com" in host:
        x = parse_qs(p.query).get("v", [None])[0]
        if x and re.fullmatch(r"[A-Za-z0-9_-]{11}", x):
            return x
        parts = [x for x in p.path.split("/") if x]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            return parts[1] if re.fullmatch(r"[A-Za-z0-9_-]{11}", parts[1]) else None
    return None


def clean_text(text):
    noise = {"Copy", "Download", "Share", "Get Video Transcript", "Settings", "SettingsSettings", "Built with Gradio", "Use via API"}
    out, seen = [], set()
    for raw in (text or "").replace("\r", "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or line in noise or line in seen:
            continue
        if line.startswith("Frequently Asked Questions"):
            break
        out.append(line)
        seen.add(line)
    return "\n".join(out)


def extract_strings(value, found):
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, str):
                s = clean_text(v)
                if len(s) >= 80 and k.lower() not in {"url", "html", "message", "error"}:
                    found.append(s)
            else:
                extract_strings(v, found)
    elif isinstance(value, list):
        for v in value:
            extract_strings(v, found)


async def get_transcript(video_url):
    video_id = extract_video_id(video_url)
    if not video_id:
        return "❌ Link YouTube không hợp lệ."

    # Tactiq accepts the YouTube URL through its own page/API workflow.
    target = TACTIQ_URL + "?" + urlencode({"yt": video_url})

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = await browser.new_context(
            locale="en-US",
            viewport={"width": 1440, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        network_texts = []

        async def capture_response(response):
            try:
                ct = (response.headers.get("content-type") or "").lower()
                if "json" not in ct and "text" not in ct and "javascript" not in ct:
                    return
                u = response.url.lower()
                if any(x in u for x in ["transcript", "transcribe", "youtube", "api"]):
                    text = await response.text()
                    if text and len(text) >= 80:
                        network_texts.append(text[:2_000_000])
            except Exception:
                pass

        page.on("response", capture_response)

        try:
            response = await page.goto(target, wait_until="domcontentloaded", timeout=60000)
            if response and response.status >= 400:
                return f"❌ Tactiq HTTP {response.status}: {page.url}"

            # First try the direct Tactiq URL. If it presents an input form,
            # submit the video URL as the normal user-facing workflow.
            await page.wait_for_timeout(2500)

            inputs = [
                page.locator("input[type='url']").first,
                page.get_by_placeholder(re.compile("YouTube|URL|video", re.I)).first,
                page.locator("input").first,
            ]
            filled = False
            for loc in inputs:
                try:
                    if await loc.is_visible(timeout=1500):
                        current = await loc.input_value()
                        if not current:
                            await loc.fill(video_url)
                            filled = True
                        else:
                            filled = True
                        break
                except Exception:
                    pass

            if filled:
                for loc in [
                    page.get_by_role("button", name=re.compile("Get Video Transcript|Transcript|Generate", re.I)).first,
                    page.locator("button[type='submit']").first,
                ]:
                    try:
                        if await loc.is_visible(timeout=2000):
                            await loc.click()
                            break
                    except Exception:
                        pass

            best = ""
            for _ in range(45):
                await page.wait_for_timeout(1000)

                # 1. Inspect network JSON returned by Tactiq.
                for raw in list(network_texts):
                    try:
                        data = json.loads(raw)
                        candidates = []
                        extract_strings(data, candidates)
                        for candidate in candidates:
                            if len(candidate) > len(best):
                                best = candidate
                    except Exception:
                        pass

                # 2. Inspect rendered transcript DOM.
                selectors = [
                    "[data-testid*='transcript']",
                    "[class*='transcript']",
                    "textarea",
                    "[contenteditable='true']",
                    "main",
                ]
                for selector in selectors:
                    try:
                        loc = page.locator(selector)
                        for i in range(min(await loc.count(), 10)):
                            txt = clean_text(await loc.nth(i).inner_text(timeout=1000))
                            if len(txt) > len(best):
                                best = txt
                    except Exception:
                        pass

                # Do not mistake the static Tactiq page for a transcript.
                lower = best.lower()
                if len(best) >= 300 and "use via api" not in lower:
                    return best

            if len(best) >= 120 and "use via api" not in best.lower():
                return best

            body = clean_text(await page.locator("body").inner_text(timeout=5000))
            if "something went wrong" in body.lower():
                return "❌ Tactiq báo lỗi khi xử lý video."
            return (
                "❌ Tactiq không trả transcript. Đã mở trang và theo dõi cả DOM + "
                "network/API nhưng chưa nhận được nội dung transcript."
            )
        except PlaywrightTimeoutError as exc:
            return f"❌ Playwright timeout: {exc}"
        except Exception as exc:
            return f"❌ Tactiq/Playwright: {type(exc).__name__}: {exc}"
        finally:
            await page.close()
            await context.close()
            await browser.close()


async def run(url):
    result = await get_transcript(url)
    if result.startswith("❌"):
        return "⚠️ Chưa lấy được transcript", result
    return "✅ Đã lấy transcript", result


with gr.Blocks(title="English Lab — Tactiq Transcript") as demo:
    gr.Markdown("# 🎧 English Lab — YouTube Transcript")
    gr.Markdown("Tactiq + Playwright Async — không dùng yt-dlp, youtube-transcript-api hoặc Invidious.")
    with gr.Row():
        url = gr.Textbox(label="YouTube URL", placeholder="https://www.youtube.com/watch?v=vxtvWovNKKE", scale=5)
        button = gr.Button("🚀 Lấy English Transcript", variant="primary", scale=2)
    status = gr.Markdown("Sẵn sàng.")
    output = gr.Textbox(label="Transcript", lines=24, show_copy_button=True)
    button.click(run, inputs=url, outputs=[status, output])
    url.submit(run, inputs=url, outputs=[status, output])


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, ssr_mode=False)
