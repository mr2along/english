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
    value = (value or "").strip()
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", value)
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
        if not text or text.lower() in {"[music]", "♪"}:
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


def _fetch_ytt(vid: str):
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    errors = []
    try:
        tracks = list(api.list(vid))
        generated = [t for t in tracks if getattr(t, "is_generated", False) and str(getattr(t, "language_code", "")).lower().startswith("en")]
        manual = [t for t in tracks if not getattr(t, "is_generated", False) and str(getattr(t, "language_code", "")).lower().startswith("en")]
        for track in generated + manual:
            try:
                rows = _ytt_rows(track.fetch())
                sentences = split_sentences(rows)
                if sentences:
                    kind = "auto-generated" if getattr(track, "is_generated", False) else "manual"
                    return sentences, f"YouTube English ({kind})"
            except Exception as exc:
                errors.append(f"{getattr(track, 'language_code', '?')}: {type(exc).__name__}: {exc}")
    except Exception as exc:
        errors.append(f"list: {type(exc).__name__}: {exc}")

    for langs in (["en"], ["en-US"], ["en-GB"]):
        try:
            sentences = split_sentences(_ytt_rows(api.fetch(vid, languages=langs)))
            if sentences:
                return sentences, "YouTube English captions"
        except Exception as exc:
            errors.append(f"fetch {langs[0]}: {type(exc).__name__}: {exc}")
    return None, errors


def _yt_dlp_caption_fallback(vid: str):
    workdir = tempfile.mkdtemp(prefix="ytcaps-")
    url = f"https://www.youtube.com/watch?v={vid}"
    errors = []
    clients = ["android", "web_safari", "web"]
    for client in clients:
        cmd = [
            "yt-dlp", url, "--skip-download", "--write-auto-subs", "--write-subs",
            "--sub-langs", "en,en-US,en-GB", "--sub-format", "vtt",
            "--output", os.path.join(workdir, "caption.%(ext)s"), "--no-playlist",
            "--force-ipv4", "--socket-timeout", "20", "--retries", "2",
            "--extractor-args", f"youtube:player_client={client}", "--no-warnings",
        ]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            files = [os.path.join(workdir, x) for x in os.listdir(workdir) if x.endswith(".vtt")]
            if p.returncode == 0 and files:
                chosen = next((f for f in files if ".en." in f or ".en-US." in f or ".en-GB." in f), files[0])
                block_re = re.compile(
                    r"(?m)^(\d{2}:\d{2}:\d{2}[\.,]\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}[\.,]\d{3}).*?\n(.*?)(?=\n\n|\Z)",
                    re.S,
                )
                def ts(v):
                    h, m, s = v.replace(",", ".").split(":")
                    return int(h) * 3600 + int(m) * 60 + float(s)
                raw = open(chosen, "r", encoding="utf-8", errors="ignore").read()
                rows = []
                for m in block_re.finditer(raw):
                    text = normalize_caption_text(m.group(3))
                    if text and text.lower() not in {"♪", "[music]"}:
                        a, b = ts(m.group(1)), ts(m.group(2))
                        rows.append({"text": text, "start": a, "duration": max(0.1, b - a)})
                sentences = split_sentences(rows)
                if sentences:
                    return sentences, f"yt-dlp YouTube English ({client})"
            errors.append(f"{client}: {(p.stderr or p.stdout)[-700:]}")
        except Exception as exc:
            errors.append(f"{client}: {type(exc).__name__}: {exc}")
    raise RuntimeError("; ".join(errors)[-3000:])


def fetch_youtube_captions(url: str):
    vid = video_id(url)
    if not vid:
        raise ValueError("Không nhận diện được YouTube video ID.")
    sentences, errors = _fetch_ytt(vid)
    if sentences:
        return sentences, errors
    try:
        return _yt_dlp_caption_fallback(vid)
    except Exception as exc:
        errors.append(f"yt-dlp: {type(exc).__name__}: {exc}")
    raise RuntimeError(
        "YouTube có thể đang chặn IP cloud của Hugging Face. "
        "youtube-transcript-api đã thử English/English auto-generated và yt-dlp fallback.\n\n" + "\n".join(errors)[-4000:]
    )


def empty_learning():
    return "🎬 Chọn video để luyện\n\nChưa có bài học.", {"sentences": [], "index": 0, "id": None}, "", "🔒 Transcript đang ẩn.", "", 0, "", youtube_embed(None)


def load_video(url: str):
    vid = video_id(url)
    if not vid:
        return "❌ Hãy nhập URL video YouTube cụ thể.", {"sentences": [], "index": 0, "id": None}, "", "🔒 Transcript đang ẩn.", "", 0, "❌ URL không hợp lệ.", youtube_embed(None)
    embed = youtube_embed(vid)
    try:
        sentences, source = fetch_youtube_captions(url)
    except Exception as exc:
        message = f"### 🎬 Video `{vid}`\n\n⚠️ **Video đã được chọn nhưng chưa lấy được transcript.**\n\n{str(exc)[-4000:]}"
        return message, {"sentences": [], "index": 0, "url": url, "id": vid}, "", "🔒 Transcript đang ẩn.", "", 0, message, embed
    state = {"sentences": sentences, "index": 0, "url": url, "id": vid}
    first = sentences[0]
    title = f"### 🎬 Video `{vid}`\n\n✅ **{source}** · **{len(sentences)} câu**"
    return title, state, first["text"], "🔒 Transcript đang ẩn.", "", 0, "", embed


def playlist_videos(url: str):
    cmd = [
        "yt-dlp", "--flat-playlist", "--dump-single-json", "--skip-download", url,
        "--force-ipv4", "--socket-timeout", "20", "--retries", "2",
        "--extractor-args", "youtube:player_client=android",
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout)[-3000:])
    data = json.loads(p.stdout)
    return [
        {"title": e.get("title") or f"Video {i}", "id": e["id"], "url": f"https://www.youtube.com/watch?v={e['id']}"}
        for i, e in enumerate(data.get("entries") or [], 1) if e.get("id")
    ]


def import_source(url: str):
    if video_id(url):
        result = load_video(url)
        return (*result, gr.update(choices=[(f"1. {video_id(url)}", url)], value=url))
    try:
        videos = playlist_videos(url)
    except Exception as exc:
        title, state, text, hidden, trans, pos, _, embed = empty_learning()
        return title, state, text, hidden, trans, pos, f"❌ Playlist import failed: {exc}", embed, gr.update(choices=[], value=None)
    choices = [(f"{i}. {v['title']}", v["url"]) for i, v in enumerate(videos, 1)]
    if not choices:
        title, state, text, hidden, trans, pos, _, embed = empty_learning()
        return title, state, text, hidden, trans, pos, "❌ Playlist không có video.", embed, gr.update(choices=[], value=None)
    first_url = choices[0][1]
    result = load_video(first_url)
    return (*result, f"✅ {len(choices)} video được đưa vào thư viện.", result[-1], gr.update(choices=choices, value=first_url))


def select_video(url: str):
    return load_video(url) if url else empty_learning()


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
    return f"### 🧑‍🏫 AI Teacher\n**Sentence:** {text}\n\n- Xác định chủ ngữ, động từ và cấu trúc chính.\n- Chú ý trọng âm, nối âm và ngữ điệu.\n- Shadowing 2–3 lần rồi tự đọc lại."


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
        import_btn = gr.Button("📥 Import / Load", variant="primary")
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
        gr.Markdown("### 3️⃣ Shadowing — Đọc theo")
        audio = gr.Audio(sources=["microphone"], type="filepath", label="🎙 Đọc câu")
        score_btn = gr.Button("🎯 Chấm phát âm")
        score = gr.Markdown("")
        teacher_btn = gr.Button("🧑‍🏫 Phân tích câu")
        teacher_out = gr.Markdown("")
        gr.Markdown("### 5️⃣ Quick Quiz")
        quiz = gr.Markdown("Quiz sẽ xuất hiện sau AI Teacher.")

    import_btn.click(import_source, inputs=url, outputs=[lesson_title, state, sentence, hidden, translation, progress, status, video_frame, selected])
    selected.change(select_video, inputs=selected, outputs=[lesson_title, state, sentence, hidden, translation, progress, status, video_frame])
    next_btn.click(next_sentence, inputs=state, outputs=[lesson_title, sentence, hidden, translation, progress])
    prev_btn.click(prev_sentence, inputs=state, outputs=[lesson_title, sentence, hidden, translation, progress])
    show.change(reveal, inputs=[sentence, show], outputs=hidden)
    translate_btn.click(translate, inputs=sentence, outputs=translation)
    teacher_btn.click(teacher, inputs=sentence, outputs=teacher_out)
    score_btn.click(lambda: "🎯 Cần microphone khả dụng trên thiết bị để chấm phát âm.", outputs=score)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")), ssr_mode=False)
