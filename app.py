import os
import re
import subprocess
import sys
from urllib.parse import quote, urlparse, parse_qs

import gradio as gr
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

TACTIQ_URL = "https://tactiq.io/tools/youtube_transcript?yt="


def ensure_playwright_browser():
    """Install Chromium only when its executable is actually missing."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            executable = p.chromium.executable_path
            if executable and os.path.exists(executable):
                return
    except Exception:
        pass

    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
        timeout=600,
    )


ensure_playwright_browser()


def extract_video_id(value: str) -> str | None:
    value = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    try:
        p = urlparse(value)
        if p.hostname == "youtu.be":
            return p.path.strip("/").split("/")[0][:11] or None
        if p.hostname and ("youtube.com" in p.hostname or "youtube-nocookie.com" in p.hostname):
            vid = parse_qs(p.query).get("v", [None])[0]
            if vid and re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
                return vid
            parts = [x for x in p.path.split("/") if x]
            if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
                return parts[1][:11]
    except Exception:
        pass
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})", value)
    return m.group(1) if m else None


def clean_text(text: str) -> str:
    text = re.sub(r"\r", "", text or "")
    lines, seen = [], set()
    skip = {"Copy", "Download", "Share", "Get Video Transcript", "Enter YouTube URL"}
    for raw in text.split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or line in skip or line in seen:
            continue
        lines.append(line)
        seen.add(line)
    return "\n".join(lines)


async def _tactiq_transcript(video_url: str) -> str:
    target = TACTIQ_URL + quote(video_url, safe="")

    # IMPORTANT: this coroutine is awaited directly by Gradio. Do not call
    # asyncio.run() here; doing so creates/closes a second event loop and can
    # leave Playwright's Connection.run() task pending.
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
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
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)

            for marker in (
                "text=Get Video Transcript",
                "text=Transcript",
                "text=Copy",
                "text=Download",
            ):
                try:
                    await page.locator(marker).first.wait_for(timeout=8000, state="visible")
                    break
                except Exception:
                    pass

            await page.wait_for_timeout(4000)
            candidates = []
            selectors = [
                "[data-testid*='transcript']",
                "[class*='transcript']",
                "[id*='transcript']",
                "main article",
                "main",
            ]
            for selector in selectors:
                try:
                    loc = page.locator(selector)
                    for i in range(min(await loc.count(), 8)):
                        txt = clean_text(await loc.nth(i).inner_text(timeout=3000))
                        if len(txt) >= 120:
                            candidates.append(txt)
                except Exception:
                    continue

            candidates.append(clean_text(await page.locator("body").inner_text(timeout=10000)))

            def score(text: str) -> tuple[int, int]:
                lines = text.splitlines()
                sentence_lines = sum(
                    1 for x in lines if len(x) > 20 and re.search(r"[.!?]$", x)
                )
                return sentence_lines, min(len(text), 20000)

            best = max(candidates, key=score, default="")
            for marker in (
                "How to get the transcript of a YouTube video",
                "Frequently Asked Questions",
            ):
                if marker in best and best.count(marker) == 1:
                    best = best.split(marker, 1)[0].strip()

            if len(best) < 80:
                raise RuntimeError(
                    "Tactiq không trả về transcript. Có thể video không có transcript "
                    "hoặc Tactiq đã thay đổi giao diện."
                )
            return best
        finally:
            # Explicitly close page/context/browser before leaving the async
            # Playwright context, avoiding TargetClosedError/pending tasks.
            try:
                await page.close()
            except Exception:
                pass
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass


async def get_transcript(video_url: str) -> str:
    if not (video_url or "").strip():
        return "⚠️ Hãy nhập link YouTube."
    video_id = extract_video_id(video_url)
    if not video_id:
        return "❌ Link YouTube không hợp lệ."
    try:
        return await _tactiq_transcript(video_url)
    except PlaywrightTimeoutError as exc:
        return f"❌ Tactiq/Playwright timeout khi lấy video {video_id}.\n\nChi tiết: {exc}"
    except Exception as exc:
        return (
            f"❌ Không lấy được transcript cho {video_id}.\n\n"
            f"Nguồn: Tactiq → Playwright Async\n"
            f"Chi tiết: {type(exc).__name__}: {exc}"
        )


CSS = """
.gradio-container { max-width: 1100px !important; }
textarea { font-size: 16px !important; line-height: 1.65 !important; }
"""

with gr.Blocks(title="English Lab — Tactiq Transcript", css=CSS) as demo:
    gr.Markdown("# 🎧 English Lab — YouTube Transcript")
    gr.Markdown(
        "Lấy transcript qua **Tactiq + Playwright Async**. "
        "Không dùng yt-dlp, youtube-transcript-api hay Invidious."
    )
    with gr.Row():
        url = gr.Textbox(
            label="YouTube URL",
            placeholder="https://www.youtube.com/watch?v=vxtvWovNKKE",
            scale=5,
        )
        button = gr.Button("🚀 Lấy English Transcript", variant="primary", scale=2)
    status = gr.Markdown("Sẵn sàng.")
    output = gr.Textbox(
        label="Transcript",
        lines=24,
        show_copy_button=True,
        placeholder="Transcript sẽ xuất hiện ở đây...",
    )

    # Gradio natively awaits async callbacks. Keeping this callback async avoids
    # asyncio.run() inside an already-running event loop.
    async def run(url_value):
        result = await get_transcript(url_value)
        if result.startswith(("❌", "⚠️")):
            return "❌ Lỗi", result
        return "✅ Đã lấy transcript", result

    button.click(run, inputs=url, outputs=[status, output])
    url.submit(run, inputs=url, outputs=[status, output])


if __name__ == "__main__":
    # SSR currently produces POST 405 errors in this Space. Disable it and use
    # the stable Gradio server-rendering path.
    demo.launch(server_name="0.0.0.0", server_port=7860, ssr_mode=False)