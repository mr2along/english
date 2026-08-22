#!/usr/bin/env python3
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import gradio as gr
import requests
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi

try:
    import truststore
except ImportError:
    truststore = None

APP_TITLE = "English Lab"
DEFAULT_URL = "https://www.youtube.com/watch?v=vxtvWovNKKE"
PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLRDC-DZ_uWhpbeuja5CFDhkVVKElpRje7"


def configure_ssl():
    if truststore is not None:
        try:
            truststore.inject_into_ssl()
        except Exception:
            pass


configure_ssl()


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
        if hasattr(item, "text"):
            text = clean_text(item.text)
            start = float(getattr(item, "start", 0) or 0)
            duration = float(getattr(item, "duration", 0) or 0)
        elif isinstance(item, dict):
            text = clean_text(item.get("text") or item.get("utf8") or "")
            start = float(item.get("start", item.get("startMs", 0)) or 0)
            if item.get("startMs") is not None:
                start /= 1000
            duration = float(item.get("duration", item.get("dDurationMs", 0)) or 0)
            if item.get("dDurationMs") is not None:
                duration /= 1000
        else:
            continue
        if text:
            out.append({"index": i, "start": start, "duration": duration, "text": text})
    for i in range(len(out) - 1):
        if not out[i]["duration"]:
            out[i]["duration"] = max(0, out[i + 1]["start"] - out[i]["start"])
    return out


def fetch_transcript(video_id, language="en"):
    api = YouTubeTranscriptApi()
    transcripts = list(api.list(video_id))
    if not transcripts:
        return [], None

    wanted = (language or "en").lower()
    chosen = None
    if wanted != "auto":
        chosen = next((x for x in transcripts if x.language_code.lower() == wanted), None)
        if chosen is None:
            chosen = next((x for x in transcripts if x.language_code.lower().startswith(wanted)), None)
    if chosen is None:
        chosen = next((x for x in transcripts if x.language_code.lower() == "en"), transcripts[0])

    return normalize_segments(chosen.fetch().to_raw_data()), chosen.language_code


def get_playlist_videos(playlist_url, limit=3):
    options = {"extract_flat": True, "quiet": True, "skip_download": True, "ignoreerrors": True}
    with yt_dlp.YoutubeDL(options) as downloader:
        playlist = downloader.extract_info(playlist_url, download=False)
    return [
        {"id": e["id"], "title": e.get("title") or ""}
        for e in playlist.get("entries", [])
        if e and e.get("id")
    ][:limit]


def fetch_playlist(playlist_url, limit=3, language="en"):
    videos = get_playlist_videos(playlist_url, int(limit))
    result = {"playlist_url": playlist_url, "videos": []}
    for number, video in enumerate(videos, 1):
        try:
            segments, actual_language = fetch_transcript(video["id"], language)
            error = None
        except Exception as exc:
            segments, actual_language, error = [], None, str(exc)
        result["videos"].append({
            "position": number,
            "video_id": video["id"],
            "title": video["title"],
            "url": f"https://youtu.be/{video['id']}",
            "language": actual_language,
            "transcript": segments,
            "error": error,
        })
    return result


def player_html(video_id):
    v = html.escape(video_id, quote=True)
    src = f"https://www.youtube.com/embed/{v}?enablejsapi=1&playsinline=1&rel=0"
    return f'''<div class="yt-wrap" data-video-id="{v}">
<div class="yt-status">YouTube video: <b>{v}</b></div>
<div class="yt-frame"><iframe id="englishlab-youtube" src="{src}" title="YouTube video player" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe></div>
<div class="yt-links"><a href="https://www.youtube.com/watch?v={v}" target="_blank" rel="noopener">↗ Mở video trực tiếp trên YouTube</a> · <a href="https://www.youtube.com/embed/{v}" target="_blank" rel="noopener">Mở URL embed</a></div>
</div>'''


def transcript_html(segments):
    if not segments:
        return '<div class="transcript-panel"><div class="transcript-head">📝 English transcript</div><div class="empty">Chưa có transcript.</div></div>'
    rows = []
    for i, s in enumerate(segments):
        start = float(s.get("start", 0))
        mins, secs = int(start // 60), int(start % 60)
        rows.append(f'<button class="tline" data-start="{start:.3f}"><span class="tstamp">{mins:02d}:{secs:02d}</span><span class="ttext">{html.escape(s.get("text", ""))}</span></button>')
    return '<div class="transcript-panel"><div class="transcript-head">📝 Transcript · %d câu</div><div class="transcript-list">%s</div></div>' % (len(rows), "".join(rows))


def load_video(url):
    vid = get_video_id(url)
    if not vid:
        return "❌ URL/Video ID YouTube không hợp lệ.", "", transcript_html([]), "[]"
    return f"✅ Video sẵn sàng: `{vid}`", player_html(vid), transcript_html([]), "[]"


def load_transcript(url, language):
    vid = get_video_id(url)
    if not vid:
        return "❌ URL/Video ID YouTube không hợp lệ.", "", transcript_html([]), "[]"
    try:
        segments, actual = fetch_transcript(vid, language)
        if not segments:
            return f"⚠️ `{vid}` không có caption phù hợp.", player_html(vid), transcript_html([]), "[]"
        return f"✅ Đã lấy transcript `{actual}` · {len(segments)} câu", player_html(vid), transcript_html(segments), json.dumps(segments, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"❌ Không lấy được transcript `{vid}`: `{exc}`", player_html(vid), transcript_html([]), "[]"


def load_playlist(playlist_url, limit, language):
    try:
        data = fetch_playlist(playlist_url, limit, language)
        ok = sum(1 for x in data["videos"] if x["transcript"])
        return f"✅ Đã xử lý {len(data['videos'])} video · {ok} video có transcript", json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"❌ Lỗi playlist: `{exc}`", "{}"


def manual_import(file_obj, text_value):
    raw = text_value or ""
    if file_obj:
        path = getattr(file_obj, "name", file_obj)
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = f.read()
    rows = []
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\]?\s*(.*)$", line)
        if not m:
            continue
        p = m.group(1).replace(",", ".").split(":")
        start = float(p[-1]) + float(p[-2]) * 60 + (float(p[-3]) * 3600 if len(p) == 3 else 0)
        rows.append({"index": len(rows) + 1, "start": start, "duration": 0, "text": clean_text(m.group(2))})
    return json.dumps(rows, ensure_ascii=False, indent=2), transcript_html(rows)


CSS = r'''
.gradio-container{max-width:1400px!important}.yt-wrap,.transcript-panel{font-family:system-ui,sans-serif;border:1px solid #e3e7ee;border-radius:16px;background:#fff;overflow:hidden}.yt-status,.transcript-head{padding:12px 14px;border-bottom:1px solid #e8ebf0;font-weight:600}.yt-frame{width:100%;aspect-ratio:16/9;background:#000}.yt-frame iframe{width:100%;height:100%;display:block;border:0}.yt-links{padding:10px 14px;font-size:12px}.yt-links a{color:#2563eb;text-decoration:none}.transcript-list{max-height:520px;overflow:auto;padding:8px}.tline{display:flex;gap:10px;width:100%;border:0;background:#f8fafc;border-radius:9px;padding:10px;margin:4px 0;text-align:left;cursor:pointer;font-size:14px;line-height:1.45}.tline:hover{background:#eaf1ff}.tstamp{min-width:58px;color:#2563eb;font:600 12px ui-monospace,monospace}.ttext{flex:1}.empty{padding:18px;color:#64748b}
'''

JS = r'''() => {
  const seek = (seconds) => { const f=document.getElementById('englishlab-youtube'); if(!f?.contentWindow)return; const msg=(func,args=[])=>f.contentWindow.postMessage(JSON.stringify({event:'command',func,args}),'*'); msg('seekTo',[Number(seconds)||0,true]); msg('playVideo'); };
  const wire=()=>document.querySelectorAll('.tline').forEach(b=>{if(!b.dataset.wired){b.dataset.wired='1';b.addEventListener('click',()=>seek(b.dataset.start));}});
  wire(); new MutationObserver(wire).observe(document.body,{childList:true,subtree:true}); window.englishLabSeek=seek;
}'''

with gr.Blocks(title=APP_TITLE, css=CSS, js=JS, theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🎧 English Lab\nLuyện nghe · đọc · phát âm với video YouTube và transcript")
    with gr.Row():
        url = gr.Textbox(label="YouTube URL hoặc Video ID", value=DEFAULT_URL, scale=5)
        embed = gr.Button("🎬 Nhúng video", variant="primary")
    with gr.Row():
        language = gr.Dropdown(["en", "vi", "ja", "ko", "zh", "auto"], value="en", label="Ngôn ngữ transcript", scale=1)
        get_transcript = gr.Button("🚀 Lấy transcript từ YouTube", variant="primary", scale=2)
    status = gr.Markdown("Sẵn sàng — transcript được xử lý bằng Python trên Space.")
    player = gr.HTML(value=player_html(get_video_id(DEFAULT_URL)), label="Video lesson")
    transcript = gr.HTML(value=transcript_html([]), label="English transcript")
    parsed = gr.Code(label="🔬 Parsed segments", language="json", lines=12)

    get_transcript.click(load_transcript, [url, language], [status, player, transcript, parsed])
    embed.click(load_video, url, [status, player, transcript, parsed])

    gr.Markdown("### 📚 Playlist mode")
    with gr.Row():
        playlist = gr.Textbox(label="YouTube Playlist URL", value=PLAYLIST_URL, scale=5)
        limit = gr.Number(label="Số video", value=3, minimum=1, maximum=50, precision=0, scale=1)
        playlist_btn = gr.Button("🚀 Lấy transcript playlist", variant="secondary", scale=2)
    playlist_status = gr.Markdown()
    playlist_json = gr.Code(label="Playlist transcripts JSON", language="json", lines=16)
    playlist_btn.click(load_playlist, [playlist, limit, language], [playlist_status, playlist_json])

    gr.Markdown("### 📄 Dự phòng thủ công")
    with gr.Row():
        file = gr.File(label="TXT / SRT / VTT / JSON", file_types=[".txt", ".srt", ".vtt", ".json"], type="filepath")
        text = gr.Textbox(label="Dán transcript", lines=6)
    imp = gr.Button("🚀 Import transcript thủ công")
    imp.click(manual_import, [file, text], [parsed, transcript])

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
