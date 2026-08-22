import os
import re
import html
from typing import Any

import gradio as gr

APP_NAME = "English Learning Lab"
DEFAULT_PLAYLIST = "https://youtube.com/playlist?list=PLRDC-DZ_uWhpbeuja5CFDhkVVKElpRje7"


def video_id(value: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", value or "")
    return m.group(1) if m else (value.strip() if re.fullmatch(r"[A-Za-z0-9_-]{11}", (value or "").strip()) else None)


def normalize_caption_text(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def _ytt_rows(transcript) -> list[dict[str, Any]]:
    rows = []
    for item in transcript:
        if hasattr(item, "text"):
            rows.append({"text": item.text, "start": item.start, "duration": item.duration})
        else:
            rows.append(dict(item))
    return rows


def split_sentences(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, buf = [], ""
    start = end = None
    for item in items:
        text = normalize_caption_text(str(item.get("text", "")))
        if not text:
            continue
        if start is None:
            start = float(item.get("start", 0))
        end = float(item.get("start", 0)) + float(item.get("duration", 0))
        buf = (buf + " " + text).strip()
        if re.search(r"[.!?…]$", buf) or len(buf.split()) >= 24:
            out.append({"start": start, "end": end, "text": buf})
            buf, start = "", None
    if buf:
        out.append({"start": start or 0, "end": end or 0, "text": buf})
    return out


def fetch_youtube_captions(url: str):
    """Fetch YouTube English captions, explicitly preferring YouTube auto-generated English."""
    vid = video_id(url)
    if not vid:
        raise ValueError("Không nhận diện được YouTube video ID.")

    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    errors = []

    # 1) Ask the API for the available tracks. Prefer generated English because
    # that is the same English (auto-generated) track shown by YouTube itself.
    try:
        tracks = api.list(vid)
        tracks = list(tracks)
        generated_en = [t for t in tracks if getattr(t, "is_generated", False) and str(getattr(t, "language_code", "")).startswith("en")]
        manual_en = [t for t in tracks if not getattr(t, "is_generated", False) and str(getattr(t, "language_code", "")).startswith("en")]

        for t in generated_en + manual_en:
            try:
                fetched = t.fetch()
                sentences = split_sentences(_ytt_rows(fetched))
                if sentences:
                    kind = "auto-generated" if getattr(t, "is_generated", False) else "manual"
                    return sentences, f"YouTube English ({kind})"
            except Exception as exc:
                errors.append(f"track {getattr(t, 'language_code', '?')}: {type(exc).__name__}: {exc}")
    except Exception as exc:
        errors.append(f"list: {type(exc).__name__}: {exc}")

    # 2) Direct fetch for environments where listing tracks is restricted.
    # This still uses YouTube's caption API and does NOT use Invidious.
    for languages in (["en"], ["en-US"], ["en-GB"]):
        try:
            fetched = api.fetch(vid, languages=languages)
            sentences = split_sentences(_ytt_rows(fetched))
            if sentences:
                return sentences, "YouTube English captions"
        except Exception as exc:
            errors.append(f"fetch {languages[0]}: {type(exc).__name__}: {exc}")

    msg = "\n".join(errors)[-5000:]
    raise RuntimeError(
        "YouTube không trả được English captions từ môi trường hiện tại. "
        "Video có thể có English (auto-generated) trên trình duyệt nhưng IP cloud của Space bị YouTube chặn.\n\n" + msg
    )


def empty_learning():
    return (
        "🎬 Chọn video để luyện\n\nChưa có bài học.",
        {"sentences": [], "index": 0},
        "",
        "🔒 Transcript đang ẩn.",
        "",
        0,
        "",
    )


def load_video(url: str):
    vid = video_id(url)
    if not vid:
        e = "❌ Hãy nhập URL video YouTube cụ thể."
        return e, {"sentences": [], "index": 0}, "", "🔒 Transcript đang ẩn.", "", 0, e

    try:
        sentences, source = fetch_youtube_captions(url)
    except Exception as exc:
        message = f"### 🎬 Video `{vid}`\n\n❌ **Không lấy được English captions.**\n\n{str(exc)[-4500:]}"
        return message, {"sentences": [], "index": 0, "url": url, "id": vid}, "", "🔒 Transcript đang ẩn.", "", 0, message

    state = {"sentences": sentences, "index": 0, "url": url, "id": vid}
    first = sentences[0]
    title = f"### 🎬 Video `{vid}`\n\n✅ **{source}** · **{len(sentences)} câu**"
    return title, state, first["text"], "🔒 Transcript đang ẩn.", "", 0, ""


def playlist_videos(url: str):
    """Playlist metadata only. Transcript extraction never depends on Invidious."""
    import subprocess, json
    cmd = ["yt-dlp", "--flat-playlist", "--dump-single-json", "--skip-download", "--force-ipv4", "--socket-timeout", "20", "--retries", "2", url]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout)[-3500:])
    data = json.loads(p.stdout)
    result = []
    for i, e in enumerate(data.get("entries") or [], 1):
        if e.get("id"):
            result.append({"title": e.get("title") or f"Video {i}", "id": e["id"], "url": f"https://www.youtube.com/watch?v={e['id']}"})
    return result


def import_source(url: str):
    if video_id(url):
        title, state, text, hidden, trans, pos, status = load_video(url)
        return title, state, text, hidden, trans, pos, status, gr.update(choices=[(f"1. {video_id(url)}", url)], value=url)
    try:
        videos = playlist_videos(url)
    except Exception as exc:
        return (*empty_learning(), gr.update(choices=[], value=None), f"❌ Playlist import failed: {exc}")
    choices = [(f"{i}. {v['title']}", v["url"]) for i, v in enumerate(videos, 1)]
    if not choices:
        return (*empty_learning(), gr.update(choices=[], value=None), "❌ Playlist không có video.")
    first_url = choices[0][1]
    title, state, text, hidden, trans, pos, status = load_video(first_url)
    return title, state, text, hidden, trans, pos, f"✅ {len(choices)} video được đưa vào thư viện.", gr.update(choices=choices, value=first_url)


def select_video(url: str):
    if not url:
        return empty_learning()
    return load_video(url)


def choose_sentence(state, index):
    if not state or not state.get("sentences"):
        return "🎬 Chưa có bài học.", "", "🔒 Transcript đang ẩn.", "", 0
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
    return "🇻🇳 Chức năng dịch sẽ dùng AI Teacher." if text else "⚠️ Chưa có câu."


def teacher(text):
    if not text:
        return "⚠️ Chưa có câu để phân tích."
    return f"### 🧑‍🏫 AI Teacher\n**Sentence:** {text}\n\n- Nghe trọng âm và nối âm.\n- Xác định chủ ngữ, động từ và cấu trúc chính.\n- Shadowing 2–3 lần rồi tự đọc lại."


with gr.Blocks(title=APP_NAME, theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🇬🇧 English Learning Lab\nListening · Shadowing · Speaking · Grammar · Vocabulary · Quiz · Progress")
    state = gr.State({"sentences": [], "index": 0})

    with gr.Tab("📚 Library"):
        url = gr.Textbox(value=DEFAULT_PLAYLIST, label="YouTube video / playlist URL")
        import_btn = gr.Button("📥 Import / Load", variant="primary")
        status = gr.Markdown()
        selected = gr.Dropdown(label="🎬 Chọn video để luyện", choices=[], interactive=True)

    with gr.Tab("🎯 Learning Session"):
        lesson_title = gr.Markdown("🎬 Chọn video để luyện\n\nChưa có bài học.")
        with gr.Row():
            prev_btn = gr.Button("◀ Câu trước")
            next_btn = gr.Button("Câu tiếp ▶")
        progress = gr.Number(value=0, label="Sentence", precision=0)
        sentence = gr.Textbox(label="Câu hiện tại", interactive=False, lines=2)
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

    import_btn.click(import_source, inputs=url, outputs=[lesson_title, state, sentence, hidden, translation, progress, status, selected])
    selected.change(select_video, inputs=selected, outputs=[lesson_title, state, sentence, hidden, translation, progress, status])
    next_btn.click(next_sentence, inputs=state, outputs=[lesson_title, sentence, hidden, translation, progress])
    prev_btn.click(prev_sentence, inputs=state, outputs=[lesson_title, sentence, hidden, translation, progress])
    show.change(reveal, inputs=[sentence, show], outputs=hidden)
    translate_btn.click(translate, inputs=sentence, outputs=translation)
    teacher_btn.click(teacher, inputs=sentence, outputs=teacher_out)
    score_btn.click(lambda: "🎯 Cần microphone khả dụng trên thiết bị để chấm phát âm.", outputs=score)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")), ssr_mode=False)
