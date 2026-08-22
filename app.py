import os
import re
import html
import json
import subprocess
import tempfile
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


def _yt_dlp_caption_fallback(vid: str):
    """Fallback for HF/cloud IPs where youtube-transcript-api is blocked.

    yt-dlp is used only for the subtitle track, not for audio/video download.
    Android clients are tried first because YouTube can expose caption metadata
    differently to different clients.
    """
    workdir = tempfile.mkdtemp(prefix="ytcaps-")
    url = f"https://www.youtube.com/watch?v={vid}"
    errors = []
    clients = ["android", "web_safari", "web"]

    for client in clients:
        outtmpl = os.path.join(workdir, "caption.%(ext)s")
        cmd = [
            "yt-dlp", url,
            "--skip-download",
            "--write-auto-subs",
            "--write-subs",
            "--sub-langs", "en,en-US,en-GB",
            "--sub-format", "vtt",
            "--output", outtmpl,
            "--no-playlist",
            "--force-ipv4",
            "--socket-timeout", "20",
            "--retries", "2",
            "--extractor-args", f"youtube:player_client={client}",
            "--no-warnings",
        ]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            files = [os.path.join(workdir, x) for x in os.listdir(workdir) if x.endswith(".vtt")]
            if p.returncode == 0 and files:
                # Prefer English auto-generated track when yt-dlp produced more than one.
                chosen = next((f for f in files if ".en." in f or ".en-US." in f or ".en-GB." in f), files[0])
                rows = []
                block_re = re.compile(
                    r"(?m)^(\d{2}:\d{2}:\d{2}[\.,]\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}[\.,]\d{3}).*?\n(.*?)(?=\n\n|\Z)",
                    re.S,
                )

                def ts(v):
                    v = v.replace(",", ".")
                    h, m, s = v.split(":")
                    return int(h) * 3600 + int(m) * 60 + float(s)

                raw = open(chosen, "r", encoding="utf-8", errors="ignore").read()
                for m in block_re.finditer(raw):
                    text = re.sub(r"<[^>]+>", " ", m.group(3))
                    text = normalize_caption_text(text)
                    if text and text.lower() not in {"♪", "[music]"}:
                        rows.append({"text": text, "start": ts(m.group(1)), "duration": max(0.1, ts(m.group(2)) - ts(m.group(1)))})
                sentences = split_sentences(rows)
                if sentences:
                    return sentences, f"yt-dlp YouTube English ({client})"
            errors.append(f"yt-dlp {client}: {(p.stderr or p.stdout)[-900:]}")
        except Exception as exc:
            errors.append(f"yt-dlp {client}: {type(exc).__name__}: {exc}")
    raise RuntimeError("; ".join(errors)[-3500:])


def fetch_youtube_captions(url: str):
    """Fetch English captions, preferring YouTube English auto-generated tracks."""
    vid = video_id(url)
    if not vid:
        raise ValueError("Không nhận diện được YouTube video ID.")

    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    errors = []

    # Primary path: youtube-transcript-api. It supports generated captions.
    try:
        tracks = list(api.list(vid))
        generated_en = [t for t in tracks if getattr(t, "is_generated", False) and str(getattr(t, "language_code", "")).startswith("en")]
        manual_en = [t for t in tracks if not getattr(t, "is_generated", False) and str(getattr(t, "language_code", "")).startswith("en")]
        for t in generated_en + manual_en:
            try:
                sentences = split_sentences(_ytt_rows(t.fetch()))
                if sentences:
                    kind = "auto-generated" if getattr(t, "is_generated", False) else "manual"
                    return sentences, f"YouTube English ({kind})"
            except Exception as exc:
                errors.append(f"track {getattr(t, 'language_code', '?')}: {type(exc).__name__}: {exc}")
    except Exception as exc:
        errors.append(f"youtube-transcript-api list: {type(exc).__name__}: {exc}")

    # Some environments block transcript listing but allow direct fetch.
    for languages in (["en"], ["en-US"], ["en-GB"]):
        try:
            sentences = split_sentences(_ytt_rows(api.fetch(vid, languages=languages)))
            if sentences:
                return sentences, "YouTube English captions"
        except Exception as exc:
            errors.append(f"fetch {languages[0]}: {type(exc).__name__}: {exc}")

    # HF/cloud fallback: try yt-dlp subtitle extraction with alternate clients.
    try:
        return _yt_dlp_caption_fallback(vid)
    except Exception as exc:
        errors.append(f"yt-dlp fallback: {type(exc).__name__}: {exc}")

    raise RuntimeError(
        "YouTube không trả được English captions từ môi trường hiện tại. "
        "Video có thể có English (auto-generated) trên trình duyệt nhưng IP cloud của Space bị YouTube chặn.\n\n"
        + "\n".join(errors)[-5000:]
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
    """Playlist metadata only. Transcript extraction is independent of Invidious."""
    cmd = [
        "yt-dlp", "--flat-playlist", "--dump-single-json", "--skip-download", url,
        "--force-ipv4", "--socket-timeout", "20", "--retries", "2",
        "--extractor-args", "youtube:player_client=android",
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout)[-3500:])
    data = json.loads(p.stdout)
    return [
        {"title": e.get("title") or f"Video {i}", "id": e["id"], "url": f"https://www.youtube.com/watch?v={e['id']}"}
        for i, e in enumerate(data.get("entries") or [], 1) if e.get("id")
    ]


def import_source(url: str):
    if video_id(url):
        title, state, text, hidden, trans, pos, status = load_video(url)
        return title, state, text, hidden, trans, pos, status, gr.update(choices=[(f"1. {video_id(url)}", url)], value=url)
    try:
        videos = playlist_videos(url)
    except Exception as exc:
        title, state, text, hidden, trans, pos, _ = empty_learning()
        return title, state, text, hidden, trans, pos, f"❌ Playlist import failed: {exc}", gr.update(choices=[], value=None)
    choices = [(f"{i}. {v['title']}", v["url"]) for i, v in enumerate(videos, 1)]
    if not choices:
        title, state, text, hidden, trans, pos, _ = empty_learning()
        return title, state, text, hidden, trans, pos, "❌ Playlist không có video.", gr.update(choices=[], value=None)
    first_url = choices[0][1]
    title, state, text, hidden, trans, pos, status = load_video(first_url)
    return title, state, text, hidden, trans, pos, f"✅ {len(choices)} video được đưa vào thư viện.", gr.update(choices=choices, value=first_url)


def select_video(url: str):
    if not url:
        title, state, text, hidden, trans, pos, status = empty_learning()
        return title, state, text, hidden, trans, pos, status
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
