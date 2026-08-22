#!/usr/bin/env python3
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import gradio as gr

APP_TITLE = "English Lab"
DEFAULT_URL = "https://www.youtube.com/watch?v=vxtvWovNKKE"
TRANSCRIPT_FILE = Path(__file__).parent / "Transcription" / "playlist_transcripts.json"


def get_video_id(value: str):
    value = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    try:
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
    except Exception:
        pass
    return None


def clean_text(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]*>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_segments(raw):
    out = []
    for i, item in enumerate(raw or [], 1):
        if not isinstance(item, dict):
            continue
        text = clean_text(item.get("text") or item.get("utf8") or "")
        try:
            start = float(item.get("start", item.get("startMs", 0)) or 0)
            duration = float(item.get("duration", item.get("dDurationMs", 0)) or 0)
            if item.get("startMs") is not None:
                start /= 1000
            if item.get("dDurationMs") is not None:
                duration /= 1000
        except (TypeError, ValueError):
            start, duration = 0.0, 0.0
        if text:
            out.append({"index": i, "start": start, "duration": duration, "text": text})
    for i in range(len(out) - 1):
        if not out[i]["duration"]:
            out[i]["duration"] = max(0, out[i + 1]["start"] - out[i]["start"])
    return out


def load_library():
    if not TRANSCRIPT_FILE.exists():
        return {"playlist_url": "", "videos": []}
    try:
        data = json.loads(TRANSCRIPT_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data["videos"] = data.get("videos") or []
            return data
    except Exception:
        pass
    return {"playlist_url": "", "videos": []}


LIBRARY = load_library()
VIDEOS = LIBRARY.get("videos", [])


def video_choices():
    return [(f"{i + 1:02d} · {v.get('title') or v.get('video_id')}", v.get("video_id")) for i, v in enumerate(VIDEOS) if v.get("video_id")]


def format_time(seconds):
    seconds = max(0, float(seconds or 0))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def player_html(video_id):
    v = html.escape(video_id or "", quote=True)
    if not v:
        return "<div class='empty'>Chưa chọn video.</div>"
    src = f"https://www.youtube.com/embed/{v}?enablejsapi=1&playsinline=1&rel=0"
    return f'''<div class="yt-wrap" data-video-id="{v}">
<div class="yt-frame"><iframe id="englishlab-youtube" src="{src}" title="YouTube video player" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe></div>
<div class="yt-links"><span>🎬 {v}</span> · <a href="https://www.youtube.com/watch?v={v}" target="_blank" rel="noopener">Mở YouTube</a></div></div>'''


def transcript_html(segments):
    segments = normalize_segments(segments)
    if not segments:
        return '<div class="transcript-panel"><div class="transcript-head">📝 Transcript</div><div class="empty">Chưa có transcript cho bài này.</div></div>'
    rows = []
    for s in segments:
        start = float(s.get("start", 0))
        rows.append(f'<button class="tline" data-start="{start:.3f}"><span class="tstamp">{format_time(start)}</span><span class="ttext">{html.escape(s.get("text", ""))}</span></button>')
    return '<div class="transcript-panel"><div class="transcript-head">📝 Transcript · %d câu</div><div class="transcript-list">%s</div></div>' % (len(rows), "".join(rows))


def select_video(video_id):
    video = next((v for v in VIDEOS if v.get("video_id") == video_id), None)
    if not video:
        return "❌ Không tìm thấy bài học.", player_html(video_id), transcript_html([]), "[]", ""
    segs = normalize_segments(video.get("transcript"))
    title = video.get("title") or video_id
    lang = video.get("language") or "unknown"
    status = f"### 🎯 {html.escape(title)}\n`{video_id}` · **{lang}** · **{len(segs)} câu**"
    return status, player_html(video_id), transcript_html(segs), json.dumps(segs, ensure_ascii=False, indent=2), video.get("url") or f"https://www.youtube.com/watch?v={video_id}"


def select_from_url(url):
    vid = get_video_id(url)
    if not vid:
        return "❌ URL/Video ID không hợp lệ.", player_html(""), transcript_html([]), "[]"
    video = next((v for v in VIDEOS if v.get("video_id") == vid), None)
    if video:
        a, b, c, d, _ = select_video(vid)
        return a, b, c, d
    return f"ℹ️ Video `{vid}` chưa có transcript trong thư viện. Hãy import JSON/SRT/VTT hoặc cập nhật playlist trên Termux.", player_html(vid), transcript_html([]), "[]"


def search_library(query):
    q = (query or "").strip().lower()
    if not q:
        return gr.update(choices=video_choices())
    choices = []
    for i, v in enumerate(VIDEOS):
        hay = f"{v.get('title','')} {v.get('video_id','')} {v.get('language','')}".lower()
        if q in hay:
            choices.append((f"{i + 1:02d} · {v.get('title') or v.get('video_id')}", v.get("video_id")))
    return gr.update(choices=choices)


def manual_import(file_obj, text_value):
    raw = text_value or ""
    if file_obj:
        path = getattr(file_obj, "name", file_obj)
        raw = Path(path).read_text(encoding="utf-8-sig")
    if not raw.strip():
        return "[]", transcript_html([])
    if raw.lstrip().startswith("{") or raw.lstrip().startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                data = data.get("transcript") or data.get("segments") or []
            segs = normalize_segments(data)
            return json.dumps(segs, ensure_ascii=False, indent=2), transcript_html(segs)
        except Exception:
            pass
    rows = []
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\]?\s*(.*)$", line)
        if not m:
            continue
        p = m.group(1).replace(",", ".").split(":")
        try:
            start = float(p[-1]) + float(p[-2]) * 60 + (float(p[-3]) * 3600 if len(p) == 3 else 0)
        except ValueError:
            continue
        text = clean_text(m.group(2))
        if text:
            rows.append({"index": len(rows) + 1, "start": start, "duration": 0, "text": text})
    return json.dumps(rows, ensure_ascii=False, indent=2), transcript_html(rows)


CSS = r'''
:root{--el-radius:16px}.gradio-container{max-width:1440px!important}.hero{padding:22px;border:1px solid #e5e7eb;border-radius:20px;background:linear-gradient(135deg,#f8fafc,#eef2ff);margin-bottom:16px}.hero h1{margin:0 0 6px;font-size:30px}.muted{color:#64748b}.yt-wrap,.transcript-panel{font-family:system-ui,sans-serif;border:1px solid #e2e8f0;border-radius:16px;background:#fff;overflow:hidden}.yt-frame{width:100%;aspect-ratio:16/9;background:#000}.yt-frame iframe{width:100%;height:100%;display:block;border:0}.yt-links{padding:10px 14px;font-size:12px;color:#64748b}.yt-links a{color:#2563eb;text-decoration:none}.transcript-head{padding:13px 15px;border-bottom:1px solid #e8ebf0;font-weight:700}.transcript-list{max-height:560px;overflow:auto;padding:8px}.tline{display:flex;gap:12px;width:100%;border:0;background:transparent;border-radius:10px;padding:11px 10px;margin:2px 0;text-align:left;cursor:pointer;font-size:14px;line-height:1.5}.tline:hover,.tline.active{background:#eef4ff}.tstamp{min-width:60px;color:#2563eb;font:700 12px ui-monospace,monospace}.ttext{flex:1}.empty{padding:20px;color:#64748b}.stat-card{padding:12px;border:1px solid #e5e7eb;border-radius:12px;background:#fff;text-align:center}.stat-number{font-size:22px;font-weight:800}.stat-label{font-size:12px;color:#64748b}
'''

JS = r'''() => {
  const getFrame=()=>document.getElementById('englishlab-youtube');
  const command=(func,args=[])=>{const f=getFrame();if(!f?.contentWindow)return;f.contentWindow.postMessage(JSON.stringify({event:'command',func,args}),'*');};
  const seek=(s)=>{command('seekTo',[Number(s)||0,true]);command('playVideo');};
  const wire=()=>document.querySelectorAll('.tline').forEach(b=>{if(!b.dataset.wired){b.dataset.wired='1';b.addEventListener('click',()=>seek(b.dataset.start));}});
  wire();new MutationObserver(wire).observe(document.body,{childList:true,subtree:true});
}'''

with gr.Blocks(title=APP_TITLE, css=CSS, js=JS, theme=gr.themes.Soft()) as demo:
    gr.HTML("<div class='hero'><h1>🎧 English Lab</h1><div class='muted'>Luyện nghe · đọc · phát âm · học theo transcript với thư viện bài học YouTube</div></div>")
    with gr.Row():
        stat_total = gr.HTML(f"<div class='stat-card'><div class='stat-number'>{len(VIDEOS)}</div><div class='stat-label'>Bài học</div></div>")
        stat_segments = gr.HTML(f"<div class='stat-card'><div class='stat-number'>{sum(len(v.get('transcript') or []) for v in VIDEOS):,}</div><div class='stat-label'>Câu transcript</div></div>")
        stat_source = gr.HTML(f"<div class='stat-card'><div class='stat-number'>LOCAL</div><div class='stat-label'>Nguồn transcript</div></div>")

    with gr.Row():
        search = gr.Textbox(label="🔎 Tìm bài học", placeholder="Tên bài, Video ID...", scale=3)
        lesson = gr.Dropdown(choices=video_choices(), label="📚 Chọn bài học", scale=5)
        open_btn = gr.Button("▶ Học bài", variant="primary", scale=1)

    with gr.Row():
        url = gr.Textbox(label="YouTube URL / Video ID", value=DEFAULT_URL, scale=5)
        url_btn = gr.Button("🎬 Mở video", scale=1)

    status = gr.Markdown("Chọn một bài học để bắt đầu.")
    player = gr.HTML(value=player_html(VIDEOS[0].get("video_id") if VIDEOS else get_video_id(DEFAULT_URL)))
    transcript = gr.HTML(value=transcript_html(VIDEOS[0].get("transcript") if VIDEOS else []))
    parsed = gr.Code(label="🔬 Dữ liệu transcript", language="json", lines=10)

    search.change(search_library, search, lesson)
    open_btn.click(select_video, lesson, [status, player, transcript, parsed, url])
    lesson.change(select_video, lesson, [status, player, transcript, parsed, url])
    url_btn.click(select_from_url, url, [status, player, transcript, parsed])

    gr.Markdown("### 📥 Cập nhật transcript")
    gr.Markdown("HF Space chỉ đọc dữ liệu transcript đã upload. Hãy lấy playlist bằng Termux rồi upload lại `Transcription/playlist_transcripts.json`.")
    with gr.Row():
        file = gr.File(label="TXT / SRT / VTT / JSON", file_types=[".txt", ".srt", ".vtt", ".json"], type="filepath")
        text = gr.Textbox(label="Hoặc dán transcript", lines=5)
    imp = gr.Button("🚀 Import transcript", variant="secondary")
    imp.click(manual_import, [file, text], [parsed, transcript])

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
