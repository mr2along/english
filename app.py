import html
import os
import re
from typing import Any

import gradio as gr
from youtube_transcript_api import YouTubeTranscriptApi

APP_NAME = "English Learning Lab"
DEFAULT_VIDEO = "https://www.youtube.com/watch?v=0Cn9IBtazjs"
LANGS = ["en", "en-US", "en-GB", "fr", "de", "es", "it", "pt", "nl", "ja", "zh-Hans", "zh-Hant"]


def video_id(value: str) -> str | None:
    value = (value or "").strip()
    for pattern in [
        r"(?:v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/embed/)([A-Za-z0-9_-]{11})",
    ]:
        m = re.search(pattern, value)
        if m:
            return m.group(1)
    return value if re.fullmatch(r"[A-Za-z0-9_-]{11}", value) else None


def youtube_embed(vid: str | None) -> str:
    if not vid:
        return "<div class='yt-empty'>🎬 Chọn video để bắt đầu.</div>"
    safe = html.escape(vid, quote=True)
    return (
        "<div class='yt-wrap'><iframe id='english-youtube-player' "
        f"src='https://www.youtube.com/embed/{safe}?enablejsapi=1&origin=https://huggingface.co&rel=0&playsinline=1' "
        "title='YouTube video' frameborder='0' allow='accelerometer; autoplay; clipboard-write; encrypted-media; "
        "gyroscope; picture-in-picture; web-share' allowfullscreen></iframe></div>"
    )


def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_ytt() -> YouTubeTranscriptApi:
    username = os.getenv("WEBSHARE_PROXY_USERNAME", "").strip()
    password = os.getenv("WEBSHARE_PROXY_PASSWORD", "").strip()
    if not username or not password:
        raise RuntimeError("Thiếu WEBSHARE_PROXY_USERNAME hoặc WEBSHARE_PROXY_PASSWORD trong HF Secrets.")
    from youtube_transcript_api.proxies import WebshareProxyConfig
    return YouTubeTranscriptApi(proxy_config=WebshareProxyConfig(
        proxy_username=username, proxy_password=password))


def build_sentences(transcript: Any) -> list[dict[str, Any]]:
    rows = []
    for s in transcript.snippets:
        text = clean_text(getattr(s, "text", ""))
        if text:
            start = float(getattr(s, "start", 0) or 0)
            duration = float(getattr(s, "duration", 0) or 0)
            rows.append({"start": start, "end": start + max(duration, .1), "text": text})

    out, buf = [], None
    for row in rows:
        if buf is None:
            buf = dict(row)
            continue
        candidate = f"{buf['text']} {row['text']}".strip()
        sentence_end = bool(re.search(r"[.!?…][\"')\]]?$", row["text"]))
        if sentence_end or len(candidate.split()) >= 28:
            buf["text"] = candidate
            buf["end"] = row["end"]
            out.append(buf)
            buf = None
        else:
            buf["text"] = candidate
            buf["end"] = row["end"]
    if buf:
        out.append(buf)
    return out


def fetch_transcript(url: str):
    vid = video_id(url)
    if not vid:
        raise ValueError("Không nhận diện được YouTube video ID.")

    api = get_ytt()
    transcript_list = api.list(vid)
    try:
        transcript = transcript_list.find_transcript(LANGS)
    except Exception:
        try:
            transcript = next(iter(transcript_list))
        except StopIteration:
            raise RuntimeError("Video không có transcript/caption khả dụng.")

    sentences = build_sentences(transcript.fetch())
    if not sentences:
        raise RuntimeError("Transcript rỗng.")
    return sentences, getattr(transcript, "language_code", "unknown")


def empty_state():
    return {"sentences": [], "index": 0, "id": None, "url": ""}


def load_video(url: str):
    vid = video_id(url)
    if not vid:
        msg = "❌ Hãy nhập URL YouTube của một video cụ thể."
        return msg, empty_state(), "", "🔒 Transcript đang ẩn.", "", 0, 0, msg, youtube_embed(None)
    try:
        sentences, language = fetch_transcript(url)
    except Exception as exc:
        msg = f"### 🎬 Video `{vid}`\n\n❌ **Không lấy được transcript.**\n\n`{type(exc).__name__}: {str(exc)[:2500]}`"
        return msg, {"sentences": [], "index": 0, "id": vid, "url": url}, "", "🔒 Transcript đang ẩn.", "", 0, 0, msg, youtube_embed(vid)

    state = {"sentences": sentences, "index": 0, "id": vid, "url": url}
    first = sentences[0]
    title = f"### 🎬 Video `{vid}`\n\n✅ **youtube-transcript-api + Webshare** · language: **{language}** · **{len(sentences)} câu**"
    return title, state, first["text"], "🔒 Transcript đang ẩn.", "", 0, first["start"], "", youtube_embed(vid)


def choose_sentence(state, index):
    if not state or not state.get("sentences"):
        return "🎬 Chưa có transcript.", "", "🔒 Transcript đang ẩn.", "", 0, 0
    sentences = state["sentences"]
    i = max(0, min(int(index), len(sentences) - 1))
    state["index"] = i
    s = sentences[i]
    return f"### Câu {i + 1}/{len(sentences)} · {s['start']:.1f}s → {s['end']:.1f}s", s["text"], "🔒 Transcript đang ẩn.", "", i, s["start"]


def next_sentence(state):
    return choose_sentence(state, (state or {}).get("index", 0) + 1)


def prev_sentence(state):
    return choose_sentence(state, (state or {}).get("index", 0) - 1)


def reveal(text, visible):
    return text if visible and text else "🔒 Transcript đang ẩn."


def translate(text):
    return "🇻🇳 **Dịch:** Chức năng dịch AI sẽ được nối ở bước AI Teacher." if text else "⚠️ Chưa có câu."


def teacher(text):
    if not text:
        return "⚠️ Chưa có câu để phân tích."
    return (f"### 🧑‍🏫 AI Teacher\n**Sentence:** {text}\n\n"
            "- Xác định chủ ngữ, động từ và cấu trúc chính.\n"
            "- Chú ý trọng âm, nối âm và ngữ điệu.\n"
            "- Shadowing 2–3 lần rồi tự đọc lại.")


CSS = """
.yt-wrap{position:relative;width:100%;padding-top:56.25%;overflow:hidden;border-radius:14px;background:#000}
.yt-wrap iframe{position:absolute;inset:0;width:100%;height:100%;border:0}
.yt-empty{padding:60px 20px;text-align:center;background:#111;color:#aaa;border-radius:14px}
#seek-time{display:none!important}
"""

# Runs in the browser. It talks to the YouTube IFrame Player API through
# postMessage, so no YouTube API key is required. The server only sends the
# timestamp; the browser performs the seek.
YOUTUBE_JS = """
() => {
  const seekToSentence = (seconds) => {
    const iframe = document.getElementById('english-youtube-player');
    if (!iframe || !Number.isFinite(Number(seconds))) return;
    const message = JSON.stringify({
      event: 'command',
      func: 'seekTo',
      args: [Number(seconds), true]
    });
    iframe.contentWindow.postMessage(message, 'https://www.youtube.com');
    // Retry once after the iframe has had time to initialize/re-render.
    setTimeout(() => {
      const current = document.getElementById('english-youtube-player');
      if (current) current.contentWindow.postMessage(message, 'https://www.youtube.com');
    }, 350);
  };

  window.__englishLabSeek = seekToSentence;
  return [];
}
"""

SEEK_JS = """
(seconds) => {
  if (window.__englishLabSeek) {
    window.__englishLabSeek(Number(seconds));
  }
  return [];
}
"""

with gr.Blocks(title=APP_NAME, theme=gr.themes.Soft(), css=CSS, js=YOUTUBE_JS) as demo:
    gr.Markdown("# 🇬🇧 English Learning Lab\nListening · Shadowing · Speaking · Grammar · Vocabulary · Quiz · Progress")
    state = gr.State(empty_state())

    with gr.Tab("📚 Library"):
        url = gr.Textbox(value=DEFAULT_VIDEO, label="YouTube video URL")
        import_btn = gr.Button("📥 Lấy English Transcript", variant="primary")
        status = gr.Markdown()

    with gr.Tab("🎯 Learning Session"):
        lesson_title = gr.Markdown("🎬 Chọn video để luyện\n\nChưa có bài học.")
        video_frame = gr.HTML(youtube_embed(None), label="Video")
        with gr.Row():
            prev_btn = gr.Button("◀ Câu trước")
            next_btn = gr.Button("Câu tiếp ▶")
        progress = gr.Number(value=0, label="Sentence", precision=0)
        # Hidden numeric output carrying the real YouTube timestamp of the
        # currently selected sentence. JS observes its value and seeks the player.
        seek_time = gr.Number(value=0, elem_id="seek-time", visible=False)
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

    import_btn.click(
        load_video,
        inputs=url,
        outputs=[lesson_title, state, sentence, hidden, translation, progress, seek_time, status, video_frame],
    )
    seek_time.change(fn=None, inputs=seek_time, outputs=None, js=SEEK_JS)
    show.change(reveal, inputs=[sentence, show], outputs=hidden)
    prev_btn.click(prev_sentence, inputs=state, outputs=[lesson_title, sentence, hidden, translation, progress, seek_time])
    next_btn.click(next_sentence, inputs=state, outputs=[lesson_title, sentence, hidden, translation, progress, seek_time])
    translate_btn.click(translate, inputs=sentence, outputs=translation)
    teacher_btn.click(teacher, inputs=sentence, outputs=teacher_out)
    score_btn.click(lambda: "🎧 Chấm phát âm sẽ được nối với Whisper/phoneme scoring ở bước tiếp theo.", outputs=score)


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
