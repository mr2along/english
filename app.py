import asyncio
import html
import re
from typing import Any
from urllib.parse import quote

import gradio as gr

APP_NAME = "English Learning Lab"
DEFAULT_PLAYLIST = "https://youtube.com/playlist?list=PLRDC-DZ_uWhpbeuja5CFDhkVVKElpRje7"


def video_id(value: str) -> str | None:
    value = (value or "").strip()
    patterns = [
        r"(?:v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/embed/)([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        m = re.search(pattern, value)
        if m:
            return m.group(1)
    return value if re.fullmatch(r"[A-Za-z0-9_-]{11}", value) else None


def youtube_embed(vid: str | None) -> str:
    if not vid:
        return "<div class='yt-empty'>🎬 Chọn video để bắt đầu.</div>"
    safe = html.escape(vid, quote=True)
    return (
        "<div class='yt-wrap'><iframe "
        f"src='https://www.youtube.com/embed/{safe}?enablejsapi=1&rel=0' "
        "title='YouTube video' frameborder='0' allow='accelerometer; autoplay; "
        "clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share' "
        "allowfullscreen></iframe></div>"
    )


def clean_line(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_sentences(text: str) -> list[dict[str, Any]]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?…])\s+", text)
    if len(parts) == 1:
        words = text.split()
        parts = [" ".join(words[i:i + 24]) for i in range(0, len(words), 24)]
    out = []
    cursor = 0.0
    for part in parts:
        part = clean_line(part)
        if len(part) < 2:
            continue
        duration = max(2.0, min(12.0, len(part.split()) * 0.48))
        out.append({"start": cursor, "end": cursor + duration, "text": part})
        cursor += duration
    return out


async def _tactiq_transcript(url: str) -> tuple[list[dict[str, Any]], str]:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

    target = "https://tactiq.io/tools/youtube_transcript?yt=" + quote(url, safe="")

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
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)

            # Tactiq has changed button labels over time. Try several labels.
            labels = [
                r"get\s+transcript",
                r"generate\s+transcript",
                r"transcribe",
                r"get\s+text",
                r"generate",
            ]
            for label in labels:
                try:
                    loc = page.get_by_role("button", name=re.compile(label, re.I))
                    if await loc.count():
                        await loc.first.click(timeout=4000)
                        await page.wait_for_timeout(3000)
                        break
                except Exception:
                    pass

            # Give the client-side application time to finish its request.
            try:
                await page.wait_for_load_state("networkidle", timeout=12000)
            except PlaywrightTimeoutError:
                pass
            await page.wait_for_timeout(2500)

            # Prefer transcript-specific DOM nodes when available.
            selectors = [
                "[data-testid*='transcript']",
                "[class*='transcript']",
                "[id*='transcript']",
                "main",
            ]
            candidates: list[str] = []
            for selector in selectors:
                try:
                    texts = await page.locator(selector).all_inner_texts()
                    candidates.extend(texts)
                except Exception:
                    pass

            body = await page.locator("body").inner_text()
            candidates.append(body)

            # Remove navigation/UI noise and choose the text block with the most
            # sentence-like English content. This makes the integration resilient
            # to Tactiq CSS/class changes.
            noise = {
                "youtube transcript", "youtube transcriber", "copy", "download",
                "sign in", "log in", "login", "pricing", "blog", "contact",
                "privacy policy", "terms of service", "cookie policy",
                "get started", "transcript", "generate transcript",
            }
            best = ""
            best_score = 0
            for candidate in candidates:
                lines = [clean_line(x) for x in candidate.splitlines()]
                lines = [x for x in lines if x and x.lower() not in noise]
                lines = [x for x in lines if not re.fullmatch(r"[0-9:.,\- ]+", x)]
                text = " ".join(lines)
                if len(text) > 20000:
                    text = text[-20000:]
                english_words = len(re.findall(r"\b(the|a|an|is|are|to|of|and|you|I|we|it|this|that|for|in)\b", text, re.I))
                sentence_marks = len(re.findall(r"[.!?]", text))
                score = english_words * 3 + sentence_marks + min(len(text), 10000) / 1000
                if score > best_score:
                    best_score = score
                    best = text

            # If a Transcript heading exists, extract the following text as a
            # second-pass heuristic.
            match = re.search(r"(?is)transcript\s*[:\n]\s*(.{150,})", body)
            if match:
                tail = clean_line(match.group(1))
                if len(tail) > 200:
                    best = tail[:30000]

            # Strip common Tactiq footer fragments.
            best = re.split(r"(?i)\b(?:privacy policy|terms of service|cookie policy)\b", best)[0]
            best = clean_line(best)

            # Avoid returning the application's own UI as a transcript.
            bad = ["youtube transcript generator", "paste a youtube", "enter a youtube url"]
            if any(x in best.lower() for x in bad) and len(best) < 1000:
                best = ""

            sentences = split_sentences(best)
            if not sentences:
                raise RuntimeError(
                    "Tactiq đã mở được nhưng không tìm thấy transcript trong DOM. "
                    "Có thể giao diện Tactiq đã thay đổi hoặc video không có transcript."
                )
            return sentences, "Tactiq + Playwright"
        finally:
            await browser.close()


def fetch_transcript(url: str):
    if not video_id(url):
        raise ValueError("Không nhận diện được YouTube video ID.")
    try:
        return asyncio.run(_tactiq_transcript(url))
    except RuntimeError as exc:
        # asyncio.run() is normally safe for Gradio worker callbacks. If a host
        # already has a running event loop, execute the coroutine in a thread.
        if "cannot be called from a running event loop" not in str(exc):
            raise
        import threading
        result: dict[str, Any] = {}
        error: list[BaseException] = []

        def runner():
            try:
                result["value"] = asyncio.run(_tactiq_transcript(url))
            except BaseException as e:
                error.append(e)

        t = threading.Thread(target=runner, daemon=True)
        t.start(); t.join()
        if error:
            raise error[0]
        return result["value"]


def empty_learning():
    return (
        "🎬 Chọn video để luyện\n\nChưa có bài học.",
        {"sentences": [], "index": 0, "id": None},
        "", "🔒 Transcript đang ẩn.", "", 0, "", youtube_embed(None),
    )


def load_video(url: str):
    vid = video_id(url)
    if not vid:
        return (
            "❌ Hãy nhập URL video YouTube cụ thể.",
            {"sentences": [], "index": 0, "id": None},
            "", "🔒 Transcript đang ẩn.", "", 0, "❌ URL không hợp lệ.", youtube_embed(None),
        )
    embed = youtube_embed(vid)
    try:
        sentences, source = fetch_transcript(url)
    except Exception as exc:
        message = (
            f"### 🎬 Video `{vid}`\n\n⚠️ **Chưa lấy được transcript qua Tactiq.**\n\n"
            f"`{type(exc).__name__}: {str(exc)[-3500:]}`"
        )
        return message, {"sentences": [], "index": 0, "url": url, "id": vid}, "", "🔒 Transcript đang ẩn.", "", 0, message, embed
    state = {"sentences": sentences, "index": 0, "url": url, "id": vid}
    first = sentences[0]
    title = f"### 🎬 Video `{vid}`\n\n✅ **{source}** · **{len(sentences)} câu**"
    return title, state, first["text"], "🔒 Transcript đang ẩn.", "", 0, "", embed


def choose_sentence(state, index):
    if not state or not state.get("sentences"):
        return "🎬 Chưa có transcript.", "", "🔒 Transcript đang ẩn.", "", 0
    sents = state["sentences"]
    i = max(0, min(int(index), len(sents) - 1))
    state["index"] = i
    s = sents[i]
    return f"### Câu {i+1}/{len(sents)} · {s['start']:.1f}s", s["text"], "🔒 Transcript đang ẩn.", "", i


def next_sentence(state):
    return choose_sentence(state, (state or {}).get("index", 0) + 1)


def prev_sentence(state):
    return choose_sentence(state, (state or {}).get("index", 0) - 1)


def reveal(text, visible):
    return text if visible and text else "🔒 Transcript đang ẩn."


def translate(text):
    return "🇻🇳 Dịch: Chức năng dịch AI sẽ được xử lý ở bước AI Teacher." if text else "⚠️ Chưa có câu."


def teacher(text):
    if not text:
        return "⚠️ Chưa có câu để phân tích."
    return (
        f"### 🧑‍🏫 AI Teacher\n**Sentence:** {text}\n\n"
        "- Xác định chủ ngữ, động từ và cấu trúc chính.\n"
        "- Chú ý trọng âm, nối âm và ngữ điệu.\n"
        "- Shadowing 2–3 lần rồi tự đọc lại."
    )


CSS = """
.yt-wrap{position:relative;width:100%;padding-top:56.25%;overflow:hidden;border-radius:14px;background:#000}
.yt-wrap iframe{position:absolute;inset:0;width:100%;height:100%;border:0}
.yt-empty{padding:60px 20px;text-align:center;background:#111;color:#aaa;border-radius:14px}
"""

with gr.Blocks(title=APP_NAME, theme=gr.themes.Soft(), css=CSS) as demo:
    gr.Markdown("# 🇬🇧 English Learning Lab\nListening · Shadowing · Speaking · Grammar · Vocabulary · Quiz · Progress")
    state = gr.State({"sentences": [], "index": 0, "id": None})

    with gr.Tab("📚 Library"):
        url = gr.Textbox(value=DEFAULT_PLAYLIST, label="YouTube video / playlist URL")
        import_btn = gr.Button("📥 Load YouTube transcript", variant="primary")
        status = gr.Markdown()
        selected = gr.Dropdown(label="🎬 Chọn video để luyện", choices=[], interactive=True)

    with gr.Tab("🎯 Learning Session"):
        lesson_title = gr.Markdown("🎬 Chọn video để luyện\n\nChưa có bài học.")
        video_frame = gr.HTML(youtube_embed(None), label="Video")
        with gr.Row():
            prev_btn = gr.Button("◀ Câu trước")
            next_btn = gr.Button("Câu tiếp ▶")
        progress = gr.Number(value=0, label="Sentence", precision=0)
        sentence = gr.Textbox(label="Câu hiện tại", interactive=False, lines=2)
        hidden = gr.Markdown("🔒 Transcript đang ẩn.")
        show = gr.Checkbox(label="👁 Hiện câu", value=False)
        translate_btn = gr.Button("🇻🇳 Dịch câu")
        translation = gr.Markdown("")
        gr.Markdown("### 🎙 Shadowing — Đọc theo")
        audio = gr.Audio(sources=["microphone"], type="filepath", label="Đọc câu")
        score_btn = gr.Button("🎯 Chấm phát âm")
        score = gr.Markdown("")
        teacher_btn = gr.Button("🧑‍🏫 Phân tích câu")
        teacher_out = gr.Markdown("")

    def load_result(url_value):
        result = load_video(url_value)
        return result

    import_btn.click(
        load_result,
        inputs=url,
        outputs=[lesson_title, state, sentence, hidden, translation, progress, status, video_frame],
    )
    selected.change(
        load_result,
        inputs=selected,
        outputs=[lesson_title, state, sentence, hidden, translation, progress, status, video_frame],
    )
    show.change(reveal, inputs=[sentence, show], outputs=hidden)
    prev_btn.click(prev_sentence, inputs=state, outputs=[lesson_title, sentence, hidden, translation, progress])
    next_btn.click(next_sentence, inputs=state, outputs=[lesson_title, sentence, hidden, translation, progress])
    translate_btn.click(translate, inputs=sentence, outputs=translation)
    teacher_btn.click(teacher, inputs=sentence, outputs=teacher_out)
    score_btn.click(lambda: "🎧 Chấm phát âm sẽ được nối với Whisper/phoneme scoring ở bước tiếp theo.", outputs=score)


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
