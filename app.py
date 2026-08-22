import os
import re
import html
import tempfile
import subprocess
from dataclasses import dataclass
from typing import Any

import gradio as gr

APP_NAME = "English Learning Lab"
DEFAULT_PLAYLIST = "https://youtube.com/playlist?list=PLRDC-DZ_uWhpbeuja5CFDhkVVKElpRje7"


def video_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else None


def normalize_caption_text(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def split_sentences(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    buf = ""
    start = None
    end = None
    for x in items:
        t = normalize_caption_text(x.get("text", ""))
        if not t:
            continue
        if start is None:
            start = float(x.get("start", 0))
        end = float(x.get("start", 0)) + float(x.get("duration", 0))
        buf = (buf + " " + t).strip()
        # Keep short learner-friendly sentence units.
        if re.search(r"[.!?…]$", buf) or len(buf.split()) >= 24:
            out.append({"start": start, "end": end, "text": buf})
            buf, start = "", None
    if buf:
        out.append({"start": start or 0, "end": end or 0, "text": buf})
    return out


def fetch_youtube_captions(url: str):
    """Prefer YouTube's own caption tracks. No Invidious dependency."""
    vid = video_id(url)
    if not vid:
        raise ValueError("Không nhận diện được YouTube video ID.")

    # youtube-transcript-api supports YouTube manual and auto-generated tracks.
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        # Prefer English; the API can select generated English tracks.
        try:
            transcript = api.fetch(vid, languages=["en", "en-US", "en-GB"])
        except Exception:
            # Explicitly search the transcript list for an English generated track.
            transcripts = api.list(vid)
            chosen = None
            for t in transcripts:
                lang = getattr(t, "language_code", "")
                if lang in {"en", "en-US", "en-GB"}:
                    chosen = t
                    break
            if chosen is None:
                raise RuntimeError("YouTube không trả English caption track.")
            transcript = chosen.fetch()

        rows = []
        for x in transcript:
            if hasattr(x, "text"):
                rows.append({"text": x.text, "start": x.start, "duration": x.duration})
            else:
                rows.append(dict(x))
        return split_sentences(rows), "YouTube English captions (including auto-generated)"
    except Exception as e:
        return None, f"YouTube captions unavailable: {type(e).__name__}: {e}"


def get_audio_with_ytdlp(url: str, outdir: str) -> str:
    out = os.path.join(outdir, "audio.%(ext)s")
    cmd = [
        "yt-dlp", "--no-playlist", "--extract-audio", "--audio-format", "wav",
        "--socket-timeout", "20", "--retries", "3", "--fragment-retries", "3",
        "--force-ipv4", "-o", out, url,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout)[-4000:])
    for f in os.listdir(outdir):
        if f.endswith(".wav"):
            return os.path.join(outdir, f)
    raise RuntimeError("yt-dlp không tạo được file audio.")


def whisper_fallback(url: str):
    """Last resort: download audio and transcribe locally."""
    try:
        import whisper
    except Exception as e:
        return None, f"Whisper chưa cài: {e}"
    with tempfile.TemporaryDirectory() as td:
        audio = get_audio_with_ytdlp(url, td)
        model_name = os.getenv("WHISPER_MODEL", "small")
        model = whisper.load_model(model_name)
        result = model.transcribe(audio, language="en", fp16=False, verbose=False)
        items = []
        for s in result.get("segments", []):
            items.append({"text": s.get("text", ""), "start": s.get("start", 0), "duration": s.get("end", 0) - s.get("start", 0)})
        return split_sentences(items), f"Whisper fallback ({model_name})"


def load_video(url: str):
    vid = video_id(url)
    if not vid:
        return "❌ URL YouTube không hợp lệ.", None, [], ""

    sentences, source = fetch_youtube_captions(url)
    if sentences:
        title = f"🎬 Video `{vid}`\n\n✅ Transcript: **{source}**\n\n{len(sentences)} câu đã sẵn sàng."
        return title, {"url": url, "id": vid, "sentences": sentences, "index": 0}, sentences, ""

    # Auto-generated captions may be blocked by a network/provider. Fall back to Whisper.
    try:
        sentences, ws = whisper_fallback(url)
        if sentences:
            title = f"🎬 Video `{vid}`\n\n⚠️ YouTube caption không truy cập được.\n✅ Đã chuyển sang **{ws}**.\n\n{len(sentences)} câu đã sẵn sàng."
            return title, {"url": url, "id": vid, "sentences": sentences, "index": 0}, sentences, ""
    except Exception as e:
        source += f"\nWhisper error: {e}"

    return f"❌ Không lấy được transcript.\n\n{source}", {"url": url, "id": vid, "sentences": [], "index": 0}, [], ""


def choose_sentence(state, index):
    if not state or not state.get("sentences"):
        return "⚠️ Chưa có bài học.", "", "", "", 0
    sents = state["sentences"]
    i = max(0, min(int(index), len(sents) - 1))
    state["index"] = i
    s = sents[i]
    return f"### Câu {i+1}/{len(sents)} · {s['start']:.1f}s", s["text"], "🔒 Transcript đang ẩn.", "", i


def next_sentence(state):
    if not state or not state.get("sentences"):
        return choose_sentence(state, 0)
    return choose_sentence(state, state.get("index", 0) + 1)


def prev_sentence(state):
    if not state or not state.get("sentences"):
        return choose_sentence(state, 0)
    return choose_sentence(state, state.get("index", 0) - 1)


def reveal(text, visible):
    return (text if not visible else "🔒 Transcript đang ẩn.", not visible)


def translate(text):
    if not text:
        return "⚠️ Chưa có câu."
    # Keep this deterministic when no external LLM is configured.
    return "🇻🇳 Hãy dùng AI Teacher để dịch và giải thích câu này."


def teacher(text):
    if not text:
        return "⚠️ Chưa có câu để phân tích."
    return f"### 🧑‍🏫 AI Teacher\n**Sentence:** {text}\n\n- Nghe kỹ trọng âm và nối âm.\n- Xác định chủ ngữ, động từ và cấu trúc chính.\n- Đọc lại 2–3 lần theo audio trước khi shadowing."

with gr.Blocks(title=APP_NAME, theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🇬🇧 English Learning Lab\nListening · Shadowing · Speaking · Grammar · Vocabulary · Quiz · Progress")
    state = gr.State({"sentences": [], "index": 0})

    with gr.Tab("📚 Library"):
        url = gr.Textbox(value=DEFAULT_PLAYLIST, label="YouTube video / playlist URL")
        import_btn = gr.Button("📥 Import / Load video", variant="primary")
        status = gr.Markdown()
        # A simple video URL field is deliberately supported in addition to playlist import.
        selected = gr.Dropdown(label="🎬 Chọn video để luyện", choices=[], interactive=True)
        gr.Markdown("Dán **URL video cụ thể** vào ô trên để mở trực tiếp một video. Playlist import có thể được bổ sung bằng yt-dlp riêng.")

    with gr.Tab("🎯 Learning Session"):
        lesson_title = gr.Markdown("🎬 Chọn video để luyện\n\nChưa có bài học.\nChọn video để bắt đầu.")
        with gr.Row():
            prev_btn = gr.Button("◀ Câu trước")
            next_btn = gr.Button("Câu tiếp ▶")
        progress = gr.Number(value=0, label="Sentence", precision=0)
        sentence = gr.Textbox(label="Câu hiện tại", interactive=False)
        hidden = gr.Markdown("🔒 Transcript đang ẩn.")
        show = gr.Checkbox(label="👁 Hiện câu", value=False)
        translate_btn = gr.Button("🇻🇳 Dịch câu")
        translation = gr.Markdown("")
        gr.Markdown("### 3️⃣ Shadowing — Đọc theo")
        audio = gr.Audio(sources=["microphone"], type="filepath", label="🎙 Đọc câu")
        score_btn = gr.Button("🎯 Chấm phát âm")
        score = gr.Markdown("")
        teacher_btn = gr.Button("🧑‍🏫 Phân tích câu")
        teacher_out = gr.Markdown("")
        gr.Markdown("### 5️⃣ Quick Quiz")
        quiz = gr.Markdown("Quiz sẽ xuất hiện sau AI Teacher.")

    import_btn.click(load_video, inputs=url, outputs=[lesson_title, state, gr.State([]), status])
    # Re-load the currently selected video when the user enters a concrete URL.
    selected.change(load_video, inputs=selected, outputs=[lesson_title, state, gr.State([]), status])
    next_btn.click(next_sentence, inputs=state, outputs=[lesson_title, sentence, hidden, translation, progress])
    prev_btn.click(prev_sentence, inputs=state, outputs=[lesson_title, sentence, hidden, translation, progress])
    show.change(lambda text, v: (text if v else "🔒 Transcript đang ẩn."), inputs=[sentence, show], outputs=hidden)
    translate_btn.click(translate, inputs=sentence, outputs=translation)
    teacher_btn.click(teacher, inputs=sentence, outputs=teacher_out)
    score_btn.click(lambda: "🎯 Chấm phát âm cần microphone khả dụng trên thiết bị.", outputs=score)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")), ssr_mode=False)
