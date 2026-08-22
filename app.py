import re
from urllib.parse import urlparse, parse_qs
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
    lines = []
    seen = set()
    noise = {"Copy", "Download", "Share", "Get Video Transcript", "Settings", "SettingsSettings", "Built with Gradio"}
    for raw in (text or "").replace("\r", "").split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or line in noise or line in seen:
            continue
        if line.startswith("Frequently Asked Questions"):
            break
        lines.append(line)
        seen.add(line)
    return "\n".join(lines)


async def get_transcript(video_url):
    video_id = extract_video_id(video_url)
    if not video_id:
        return "❌ Link YouTube không hợp lệ."
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(locale="en-US", viewport={"width": 1440, "height": 1000})
        page = await context.new_page()
        try:
            response = await page.goto(TACTIQ_URL, wait_until="domcontentloaded", timeout=60000)
            if response and response.status >= 400:
                return f"❌ Tactiq HTTP {response.status}: {page.url}"
            await page.wait_for_timeout(1500)

            inputs = [
                page.get_by_placeholder(re.compile("Enter YouTube URL", re.I)).first,
                page.locator("input[type='url']").first,
                page.locator("input").first,
            ]
            filled = False
            for loc in inputs:
                try:
                    await loc.wait_for(state="visible", timeout=5000)
                    await loc.fill(video_url)
                    filled = True
                    break
                except Exception:
                    pass
            if not filled:
                return "❌ Không tìm thấy ô nhập YouTube URL trên Tactiq."

            buttons = [
                page.get_by_role("button", name=re.compile("Get Video Transcript", re.I)).first,
                page.get_by_text(re.compile("Get Video Transcript", re.I)).first,
                page.locator("button[type='submit']").first,
            ]
            clicked = False
            for loc in buttons:
                try:
                    await loc.wait_for(state="visible", timeout=5000)
                    await loc.click()
                    clicked = True
                    break
                except Exception:
                    pass
            if not clicked:
                return "❌ Không tìm thấy nút Get Video Transcript trên Tactiq."

            best = ""
            for _ in range(35):
                await page.wait_for_timeout(1000)
                candidates = []
                for selector in ["textarea", "[contenteditable='true']", "[data-testid*='transcript']", "[class*='transcript']", "main", "body"]:
                    try:
                        loc = page.locator(selector)
                        for i in range(min(await loc.count(), 8)):
                            txt = clean_text(await loc.nth(i).inner_text(timeout=1500))
                            if len(txt) >= 120:
                                candidates.append(txt)
                    except Exception:
                        pass
                if candidates:
                    candidate = max(candidates, key=len)
                    if len(candidate) > len(best):
                        best = candidate
                    if len(best) >= 300:
                        return best

            if len(best) < 120:
                body = clean_text(await page.locator("body").inner_text(timeout=5000))
                if "something went wrong" in body.lower():
                    return "❌ Tactiq báo lỗi khi xử lý video."
                return "❌ Tactiq chỉ trả về giao diện, chưa có transcript."
            return best
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
    return ("❌ Lỗi" if result.startswith("❌") else "✅ Đã lấy transcript", result)


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
