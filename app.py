import os
import re
import html
import json
import tempfile
import subprocess
from typing import Any

import gradio as gr

APP_NAME = "English Learning Lab"
DEFAULT_PLAYLIST = "https://youtube.com/playlist?list=PLRDC-DZ_uWhpbeuja5CFDhkVVKElpRje7"


def video_id(value: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", value or "")
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", (value or "").strip()):
        return value.strip()
    return None


def normalize_caption_text(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def split_sentences(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    buf = ""
    start = None
    end = None
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


def _ytt_rows(transcript) -> list[dict[str, Any]]:
    rows = []
    for item in transcript:
        if hasattr(item, "text"):
            rows.append({"text": item.text, "start": item.start, "duration": item.duration})
        else:
            rows.append(dict(item))
    return rows


def fetch_youtube_captions(url: str):
    """Use YouTube caption tracks, explicitly allowing auto-generated English."""
    vid = video_id(url)
    if not vid:
        raise ValueError("Không nhận diện được YouTube video ID.")

    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    errors = []
    try:
        transcript_list = api.list(vid)
        candidates = list(transcript_list)
        # Prefer manual English, then generated English.
        candidates.sort(key=lambda t: (
            0 if getattr(t, "language_code", "") in {"en", "en-US", "en-GB"} and not getattr(t, "is_generated", False) else
            1 if getattr(t, "language_code", "") in {"en", "en-US", "en-GB"} else 2
        ))
        for t in candidates:
            code = getattr(t, "language_code", "")
            if code in {"en", "en-US", "en-GB"} or code.startswith("en"):
                try:
                    fetched = t.fetch()
                    rows = _ytt_rows(fetched)
                    sentences = split_sentences(rows)
                    if sentences:
                        kind = "auto-generated" if getattr(t, "is_generated", False) else "manual"
                        return sentences, f"YouTube English captions ({kind})"
                except Exception as exc:
                    errors.append(f"{code}: {exc}")
    except Exception as exc:
        errors.append(f"list: {type(exc).__name__}: {exc}")

    # Direct fetch is useful with versions/providers where list() is restricted.
    try:
        fetched = api.fetch(vid, languages=["en", "en-US", "en-GB"])
        sentences = split_sentences(_ytt_rows(fetched))
        if sentences:
            return sentences, "YouTube English captions"
    except Exception as exc:
        errors.append(f"fetch: {type(exc).__name__}: {exc}")

    raise RuntimeError("; ".join(errors)[-3500:] or "YouTube không trả English captions.")


def fetch_ytdlp_subtitles(url: str):
    """Second caption path: yt-dlp asks YouTube directly for auto-generated VTT."""
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "captions.%(ext)s")
        cmd = [
            "yt-dlp", "--skip-download", "--no-playlist",
            "--write-auto-subs", "--write-subs",
            "--sub-langs", "en,en-US,en-GB,en.*",
            "--sub-format", "vtt", "--force-ipv4",
            "--socket-timeout", "20", "--retries", "2", "--fragment-retries", "2",
            "-o", out, url,
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        files = [os.path.join(td, f) for f in os.listdir(td) if f.endswith(".vtt")]
        if p.returncode != 0 and not files:
            raise RuntimeError((p.stderr or p.stdout)[-3000:])
        if not files:
            raise RuntimeError("yt-dlp không tìm thấy English subtitle track.")

        rows = []
        for path in files:
            raw = open(path, "r", encoding="utf-8", errors="ignore").read()
            blocks = re.split(r"\n\s*\n", raw)
            for block in blocks:
                lines = [x.strip() for x in block.splitlines() if x.strip()]
                times = next((x for x in lines if "-->" in x), None)
                if not times:
                    continue
                try:
                    a, b = [x.strip().split()[0] for x in times.split("-->", 1)]
                    def sec(x):
                        h, m, s = x.replace(",", ".").split(":")
                        return int(h) * 3600 + int(m) * 60 + float(s)
                    text_lines = [x for x in lines[lines.index(times) + 1:] if not re.fullmatch(r"\d+", x)]
                    rows.append({"text": " ".join(text_lines), "start": sec(a), "duration": max(0, sec(b) - sec(a))})
                except Exception:
                    continue
        sentences = split_sentences(rows)
        if not sentences:
            raise RuntimeError("VTT English captions rỗng.")
        return sentences, "yt-dlp YouTube auto/manual captions"


def playlist_videos(url: str):
    """Read playlist metadata without downloading the videos."""
    cmd = [
        "yt-dlp", "--flat-playlist", "--dump-single-json", "--skip-download",
        "--force-ipv4", "--socket-timeout", "20", "--retries", "2", url,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout)[-3500:])
    data = json.loads(p.stdout)
    entries = data.get("entries") or []
    result = []
    for i, e in enumerate(entries, 1):
        vid = e.get("id")
        if not vid:
            continue
        title = e.get("title") or f"Video {i}"
        result.append({"title": title, "id": vid, "url": f"https://www.youtube.com/watch?v={vid}"})
    return result


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
        return (*empty_learning()[:1], *empty_learning()[1:6], "❌ Hãy nhập URL video YouTube cụ thể.", [])

    errors = []
    try:
        sentences, source = fetch_youtube_captions(url)
    except Exception as exc:
        errors.append(f"YouTube Transcript API: {exc}")
        try:
            sentences, source = fetch_ytdlp_subtitles(url)
        except Exception as exc2:
            errors.append(f"yt-dlp captions: {exc2}")
            return (
                f"### 🎬 `{vid}`\n\n❌ **Không lấy được English captions.**\n\nYouTube có thể đang chặn request từ IP cloud của Space.\n\n`{' | '.join(errors)[-3000:]}`",
                {"sentences": [], "index": 0, "url": url, "id": vid},
                "", "🔒 Transcript đang ẩn.", "", 0,
                "⚠️ Không có transcript cho video này.", []
            )

    state = {"sentences": sentences, "index": 0, "url": url, "id": vid}
    first = sentences[0]
    title = f"### 🎬 Video `{vid}`\n\n✅ **{source}** · **{len(sentences)} câu**"
    return title, state, first["text"], "🔒 Transcript đang ẩn.", "", 0, "", []


def import_source(url: str):
    if video_id(url):
        title, state, text, hidden, trans, pos, status, _ = load_video(url)
        choice = [(f"1. {video_id(url)}", url)]
        return title, state, text, hidden, trans, pos, status, gr.update(choices=choice, value=url)

    try:
        videos = playlist_videos(url)
    except Exception as exc:
        return (*empty_learning(), gr.update(choices=[], value=None), f"❌ Playlist import failed: {exc}")

    choices = [(f"{i}. {v['title']}", v["url"]) for i, v in enumerate(videos, 1)]
    if not choices:
        return (*empty_learning(), gr.update(choices=[], value=None), "❌ Playlist không có video.")
    first_url = choices[0][1]
    title, state, text, hidden, trans, pos, status, _ = load_video(first_url)
    return title, state, text, hidden, trans, pos, f"✅ {len(choices)} video được đưa vào thư viện.", gr.update(choices=choices, value=first_url)


def select_video(url: str):
    if not url:
        return empty_learning()
    return load_video(url)[:7]


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
    return (text if visible else "🔒 Transcript đang ẩn.")


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

    import_btn.click(
        import_source, inputs=url,
        outputs=[lesson_title, state, sentence, hidden, translation, progress, status, selected]
    )
    selected.change(
        select_video, inputs=selected,
        outputs=[lesson_title, state, sentence, hidden, translation, progress, status]
    )
    next_btn.click(next_sentence, inputs=state, outputs=[lesson_title, sentence, hidden, translation, progress])
    prev_btn.click(prev_sentence, inputs=state, outputs=[lesson_title, sentence, hidden, translation, progress])
    show.change(reveal, inputs=[sentence, show], outputs=hidden)
    translate_btn.click(translate, inputs=sentence, outputs=translation)
    teacher_btn.click(teacher, inputs=sentence, outputs=teacher_out)
    score_btn.click(lambda: "🎯 Cần microphone khả dụng trên thiết bị để chấm phát âm.", outputs=score)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")), ssr_mode=False)
