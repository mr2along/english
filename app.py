import html
import json
import os
import re
from urllib.parse import parse_qs, urlparse

import gradio as gr
import requests

APP_TITLE = "English Lab"
DEFAULT_URL = "https://www.youtube.com/watch?v=vxtvWovNKKE"
TRANSCRIPT_BACKEND_URL = os.getenv("TRANSCRIPT_BACKEND_URL", "http://127.0.0.1:8765")


def get_video_id(value: str):
    value = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    p = urlparse(value)
    host = (p.hostname or "").lower()
    if host == "youtu.be":
        x = p.path.strip("/").split("/")[0]
        return x if re.fullmatch(r"[A-Za-z0-9_-]{11}", x) else None
    x = parse_qs(p.query).get("v", [None])[0]
    if x and re.fullmatch(r"[A-Za-z0-9_-]{11}", x):
        return x
    parts = [x for x in p.path.split("/") if x]
    if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live"}:
        return parts[1] if re.fullmatch(r"[A-Za-z0-9_-]{11}", parts[1]) else None
    return None


def parse_time(s):
    s = s.strip().replace(",", ".")
    try:
        p = s.split(":")
        if len(p) == 3:
            return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])
        if len(p) == 2:
            return int(p[0]) * 60 + float(p[1])
        return float(s)
    except Exception:
        return None


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", "", str(s)))).strip()


def parse_transcript(text):
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.upper() in {"WEBVTT", "NOTE", "STYLE", "REGION"}:
            continue
        m = re.match(r"^(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\s*-->\s*(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\s*(.*)$", line)
        if m:
            a, b = parse_time(m.group(1)), parse_time(m.group(2))
            t = clean(m.group(3))
            if a is not None and t:
                out.append({"start": a, "duration": max(0, (b or a) - a), "text": t})
            continue
        m = re.match(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\]?\s*(.*)$", line)
        if m:
            a, t = parse_time(m.group(1)), clean(m.group(2))
            if a is not None and t:
                out.append({"start": a, "duration": 0, "text": t})
    for i in range(len(out) - 1):
        if not out[i]["duration"]:
            out[i]["duration"] = max(0, out[i + 1]["start"] - out[i]["start"])
    if out:
        return out
    try:
        data = json.loads(text)
        events = data.get("events", []) if isinstance(data, dict) else []
        for e in events:
            segs = e.get("segs", [])
            t = clean("".join(str(x.get("utf8", "")) for x in segs))
            if t and e.get("tStartMs") is not None:
                out.append({"start": float(e["tStartMs"]) / 1000, "duration": float(e.get("dDurationMs", 0)) / 1000, "text": t})
    except Exception:
        pass
    return out


def player_html(vid, segments=None):
    v = html.escape(vid, quote=True)
    src = f"https://www.youtube.com/embed/{v}?enablejsapi=1&playsinline=1&rel=0"
    rows = []
    for i, x in enumerate(segments or []):
        start = float(x.get("start", 0))
        rows.append(f'<button class="el-line" data-start="{start:.3f}" onclick="window.englishLabSeek({start:.3f})"><span>{i+1}. {int(start//60):02d}:{int(start%60):02d}</span> {html.escape(x.get("text", ""))}</button>')
    transcript = '<div class="el-lines">' + ''.join(rows) + '</div>' if rows else ''
    return f'''<div class="yt-wrap" data-video-id="{v}">
<div class="yt-status">YouTube video: <b>{v}</b></div>
<div class="yt-frame"><iframe id="englishlab-youtube" src="{src}" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe></div>
<div class="yt-links"><a href="https://www.youtube.com/watch?v={v}" target="_blank" rel="noopener">↗ Mở video trực tiếp trên YouTube</a> · <a href="https://www.youtube.com/embed/{v}" target="_blank" rel="noopener">Mở URL embed</a></div>
{transcript}</div>'''


def load_video(url):
    vid = get_video_id(url)
    if not vid:
        return "❌ URL/Video ID YouTube không hợp lệ.", ""
    return f"✅ Đã tạo player cho Video ID: `{vid}`", player_html(vid)


def load_transcript_from_backend(url, lang):
    vid = get_video_id(url)
    if not vid:
        return "❌ URL/Video ID YouTube không hợp lệ.", "", "[]"
    try:
        r = requests.get(f"{TRANSCRIPT_BACKEND_URL.rstrip('/')}/transcript", params={"video": vid, "lang": lang or "en"}, timeout=45)
        r.raise_for_status()
        data = r.json()
        segments = data.get("segments") or []
        if not segments:
            return f"⚠️ Backend không tìm thấy transcript cho `{vid}`.", player_html(vid), "[]"
        return f"✅ Đã lấy transcript `{lang}` cho `{vid}` · {len(segments)} câu", player_html(vid, segments), json.dumps(segments, ensure_ascii=False, indent=2)
    except requests.RequestException as e:
        return f"❌ Không kết nối được transcript backend `{TRANSCRIPT_BACKEND_URL}`: {e}", player_html(vid), "[]"
    except Exception as e:
        return f"❌ Backend transcript trả dữ liệu không hợp lệ: {e}", player_html(vid), "[]"


def import_transcript(url, text, file):
    vid = get_video_id(url)
    if not vid:
        return "❌ URL/Video ID YouTube không hợp lệ.", "", ""
    if file:
        path = getattr(file, "name", file)
        text = open(path, "r", encoding="utf-8-sig").read()
    segments = parse_transcript(text or "")
    if not segments:
        return f"⚠️ Video `{vid}` đã sẵn sàng nhưng transcript chưa có timestamp hoặc không đọc được.", player_html(vid), "[]"
    return f"✅ Video `{vid}` · {len(segments)} câu", player_html(vid, segments), json.dumps(segments, ensure_ascii=False, indent=2)


CSS = r'''
.gradio-container{max-width:1400px!important}
.yt-wrap{font-family:system-ui,sans-serif;background:#fff;border:1px solid #e3e7ee;border-radius:16px;overflow:hidden}
.yt-status{padding:10px 14px;font-size:13px;color:#526071;border-bottom:1px solid #e8ebf0}
.yt-frame{width:100%;aspect-ratio:16/9;background:#000}
.yt-frame iframe{width:100%;height:100%;display:block;border:0}
.yt-links{padding:10px 14px;font-size:12px;color:#64748b}
.yt-links a{color:#2563eb;text-decoration:none}
.el-lines{max-height:480px;overflow:auto;padding:8px}
.el-line{display:block;width:100%;text-align:left;border:0;background:#f8fafc;border-radius:8px;padding:9px;margin:4px 0;cursor:pointer}
.el-line:hover{background:#eaf1ff}
'''

JS = r'''() => {
  window.englishLabSeek = (seconds) => {
    const f = document.getElementById("englishlab-youtube");
    if (!f || !f.contentWindow) return;
    f.contentWindow.postMessage(JSON.stringify({event:"command",func:"seekTo",args:[seconds,true]}), "*");
    f.contentWindow.postMessage(JSON.stringify({event:"command",func:"playVideo",args:[]}), "*");
  };
}'''

with gr.Blocks(title=APP_TITLE, css=CSS, js=JS, theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🎧 English Lab\nLuyện nghe · đọc · phát âm với video YouTube và transcript")
    with gr.Row():
        url = gr.Textbox(label="YouTube URL hoặc Video ID", value=DEFAULT_URL, scale=5)
        embed = gr.Button("🎬 Nhúng video", variant="primary", scale=1)
    with gr.Row():
        lang = gr.Dropdown(["en", "vi", "ja", "ko", "zh", "auto"], value="en", label="Ngôn ngữ transcript", scale=1)
        get_transcript = gr.Button("🚀 Lấy transcript từ backend", variant="primary", scale=2)
    status = gr.Markdown("Sẵn sàng — video mẫu đã được điền sẵn.")
    player = gr.HTML(value=player_html("vxtvWovNKKE"), label="Video lesson")
    with gr.Row():
        with gr.Column():
            file = gr.File(label="📄 Transcript TXT / SRT / VTT / JSON", file_types=[".txt", ".srt", ".vtt", ".json"], type="filepath")
            text = gr.Textbox(label="📝 Dán transcript", lines=8, placeholder="[00:12] Hello...")
            imp = gr.Button("🚀 Import transcript thủ công", variant="secondary")
        with gr.Column():
            parsed = gr.Code(label="🔬 Parsed segments", language="json", lines=12)
    embed.click(load_video, url, [status, player])
    get_transcript.click(load_transcript_from_backend, [url, lang], [status, player, parsed])
    imp.click(import_transcript, [url, text, file], [status, player, parsed])

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))