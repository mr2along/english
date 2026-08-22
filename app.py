import html
import json
import os
import re
from urllib.parse import parse_qs, urlparse

import gradio as gr


APP_TITLE = "English Lab"
MAX_TRANSCRIPT_CHARS = 2_000_000


def video_id(value: str):
    value = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value

    p = urlparse(value)
    host = (p.hostname or "").lower()

    if host == "youtu.be":
        candidate = p.path.strip("/").split("/")[0]
        return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else None

    if "youtube.com" in host or "youtube-nocookie.com" in host:
        candidate = parse_qs(p.query).get("v", [None])[0]
        if candidate and re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
            return candidate

        parts = [x for x in p.path.split("/") if x]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            candidate = parts[1]
            return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else None

    return None


def parse_time(value: str):
    value = value.strip().replace(",", ".")
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return float(value)

    parts = value.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
    except ValueError:
        return None
    return None


def clean_text(text: str):
    text = html.unescape(str(text))
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_timestamped_text(text: str):
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r"(?:WEBVTT|NOTE|STYLE|REGION)", line, flags=re.I):
            continue

        m = re.match(
            r"^\s*(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\s*-->\s*"
            r"(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\s*(.*)$", line
        )
        if m:
            start = parse_time(m.group(1))
            end = parse_time(m.group(2))
            txt = clean_text(m.group(3))
            if start is not None and txt:
                lines.append({"start": start, "duration": max(0.0, (end or start) - start), "text": txt})
            continue

        m = re.match(
            r"^\s*\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\]?\s*(?:[-–—|]\s*)?(.*)$",
            line,
        )
        if m:
            start = parse_time(m.group(1))
            txt = clean_text(m.group(2))
            if start is not None and txt:
                lines.append({"start": start, "duration": 0.0, "text": txt})

    for i, item in enumerate(lines):
        if i + 1 < len(lines) and item["duration"] <= 0:
            item["duration"] = max(0.0, lines[i + 1]["start"] - item["start"])
    return lines


def parse_json_transcript(text: str):
    try:
        data = json.loads(text)
    except Exception:
        return []

    events = data.get("events") if isinstance(data, dict) else None
    if isinstance(events, list):
        result = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            segs = ev.get("segs") or []
            txt = "".join(str(s.get("utf8", "")) for s in segs if isinstance(s, dict))
            start = ev.get("tStartMs")
            dur = ev.get("dDurationMs", 0)
            if txt.strip() and start is not None:
                result.append({
                    "start": float(start) / 1000,
                    "duration": float(dur or 0) / 1000,
                    "text": clean_text(txt),
                })
        return result

    if isinstance(data, list):
        result = []
        for item in data:
            if not isinstance(item, dict):
                continue
            txt = item.get("text") or item.get("content")
            start = item.get("start", item.get("startTime"))
            if txt is None or start is None:
                continue
            if isinstance(start, str):
                start = parse_time(start)
            if start is None:
                continue
            result.append({
                "start": float(start),
                "duration": float(item.get("duration", 0) or 0),
                "text": clean_text(txt),
            })
        return result

    return []


def normalize_segments(lines):
    result = []
    for i, item in enumerate(lines, 1):
        txt = clean_text(item.get("text", ""))
        if txt:
            result.append({
                "index": i,
                "start": float(item.get("start", 0) or 0),
                "duration": float(item.get("duration", 0) or 0),
                "text": txt,
            })

    for i, item in enumerate(result):
        if item["duration"] <= 0 and i + 1 < len(result):
            item["duration"] = max(0, result[i + 1]["start"] - item["start"])
    return result


def parse_transcript(text: str):
    text = (text or "").strip()
    if not text:
        return []

    lines = parse_timestamped_text(text)
    if lines:
        return normalize_segments(lines)

    lines = parse_json_transcript(text)
    if lines:
        return normalize_segments(lines)

    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text))
    return normalize_segments([{"start": 0.0, "duration": 0.0, "text": s} for s in sentences if s.strip()])


def read_uploaded_file(file_obj):
    if file_obj is None:
        return ""
    path = getattr(file_obj, "name", file_obj)
    if not path:
        return ""
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Không đọc được file transcript: {path}")


def build_player(vid, lines):
    safe_vid = html.escape(vid, quote=True)
    data = html.escape(json.dumps(lines, ensure_ascii=False), quote=True)
    return f'''
<div id="english-lab-player" class="el-shell" data-video-id="{safe_vid}" data-lines="{data}">
<style>
.el-shell{{font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#172033}}
.el-grid{{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(300px,.85fr);gap:18px}}
.el-card{{background:#fff;border:1px solid #e5e9f0;border-radius:18px;box-shadow:0 8px 30px rgba(20,35,60,.07);overflow:hidden}}
.el-video{{aspect-ratio:16/9;background:#080b10}}
.el-video iframe{{width:100%;height:100%;border:0;display:block}}
.el-head{{padding:14px 16px;border-bottom:1px solid #edf0f4;display:flex;align-items:center;justify-content:space-between;gap:10px}}
.el-title{{font-weight:750;font-size:16px}} .el-sub{{font-size:12px;color:#748096;margin-top:2px}}
.el-transcript{{height:min(66vh,620px);overflow:auto;padding:10px}}
.el-line{{display:flex;width:100%;gap:10px;text-align:left;border:0;border-radius:12px;background:transparent;padding:10px 11px;margin:2px 0;cursor:pointer;color:#263247;line-height:1.45;font-size:14px}}
.el-line:hover{{background:#f5f7fb}} .el-line.active{{background:#eaf1ff;box-shadow:inset 3px 0 0 #2563eb}}
.el-time{{font:600 11px ui-monospace,SFMono-Regular,Menlo,monospace;color:#718096;min-width:52px;padding-top:2px}}
.el-text{{flex:1}} .el-num{{color:#a0a9b8;font-size:11px;margin-right:4px}}
.el-tools{{display:flex;gap:8px;flex-wrap:wrap;padding:12px 16px;border-top:1px solid #edf0f4}}
.el-btn{{border:1px solid #dce2ea;background:#fff;border-radius:10px;padding:8px 12px;font-weight:650;cursor:pointer}}
.el-btn.primary{{background:#2563eb;color:#fff;border-color:#2563eb}}
.el-tip{{padding:10px 16px;font-size:12px;color:#69768a;background:#f8fafc}}
.el-empty{{padding:28px;color:#69768a;text-align:center}}
@media(max-width:850px){{.el-grid{{grid-template-columns:1fr}}.el-transcript{{height:420px}}}}
</style>
<div class="el-grid">
<section class="el-card">
  <div class="el-head"><div><div class="el-title">🎬 Video lesson</div><div class="el-sub">Video nhúng trực tiếp từ YouTube</div></div></div>
  <div class="el-video"><iframe id="el-youtube-frame" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div>
  <div class="el-tools"><button id="el-play" class="el-btn primary">▶ Phát câu</button><button id="el-replay" class="el-btn">↺ Phát lại</button><button id="el-top" class="el-btn">↑ Về đầu</button></div>
  <div class="el-tip">💡 Click một câu để nhảy đến timestamp. Server không tải video YouTube.</div>
</section>
<section class="el-card">
  <div class="el-head"><div><div class="el-title">📝 English transcript</div><div class="el-sub">Manual import · click câu để seek</div></div><div id="el-count" class="el-sub"></div></div>
  <div id="el-lines" class="el-transcript"></div>
</section>
</div>
<script>
(function(){{
 const root=document.getElementById('english-lab-player'); if(!root)return;
 const vid=root.dataset.videoId; let lines=[]; try{{lines=JSON.parse(root.dataset.lines||'[]')}}catch(e){{}}
 const frame=document.getElementById('el-youtube-frame');
 frame.src='https://www.youtube.com/embed/'+encodeURIComponent(vid)+'?enablejsapi=1&playsinline=1&rel=0';
 const list=document.getElementById('el-lines'), buttons=[]; let active=-1;
 const hasTimes=lines.some(x=>Number(x.start)>0);
 const fmt=t=>{{t=Math.max(0,Number(t)||0);const h=Math.floor(t/3600),m=Math.floor((t%3600)/60),s=Math.floor(t%60);return (h?String(h).padStart(2,'0')+':':'')+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0')}};
 document.getElementById('el-count').textContent=lines.length+' câu';
 function esc(s){{return String(s).replace(/[&<>\"]/g,m=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}}[m]))}}
 function cmd(func,args){{try{{frame.contentWindow.postMessage(JSON.stringify({{event:'command',func:func,args:args||[]}}),'*')}}catch(e){{}}}}
 function seek(t){{if(!hasTimes)return;cmd('seekTo',[Number(t)||0,true]);cmd('playVideo',[])}}
 lines.forEach((x,i)=>{{const b=document.createElement('button');b.className='el-line';b.type='button';const tm=Number(x.start)>0?fmt(x.start):'—';b.innerHTML='<span class="el-time">'+tm+'</span><span class="el-text"><span class="el-num">#'+(i+1)+'</span>'+esc(x.text)+'</span>';b.onclick=()=>seek(x.start);list.appendChild(b);buttons.push(b)}});
 if(!lines.length)list.innerHTML='<div class="el-empty">Chưa có transcript. Hãy import TXT/SRT/VTT/JSON hoặc dán transcript.</div>';
 if(!hasTimes&&lines.length){{const tip=document.createElement('div');tip.className='el-empty';tip.textContent='Transcript không có timestamp. Import SRT/VTT hoặc dạng [00:12] câu để click-to-seek hoạt động.';list.prepend(tip)}}
 function setActive(i){{if(i===active)return;active=i;buttons.forEach((b,j)=>b.classList.toggle('active',j===i));if(i>=0)buttons[i]?.scrollIntoView({{block:'nearest',behavior:'smooth'}})}}
 function current(t){{let i=-1;for(let j=0;j<lines.length;j++){{const a=+lines[j].start||0,b=j+1<lines.length?(+lines[j+1].start||Infinity):Infinity;if(t>=a&&t<b){{i=j;break}}}}return i}}
 window.addEventListener('message',e=>{{if(typeof e.data!=='string')return;let d;try{{d=JSON.parse(e.data)}}catch(_){{return}};const t=d?.info?.currentTime??d?.infoDelivery?.currentTime;if(typeof t==='number')setActive(current(t))}});
 document.getElementById('el-play').onclick=()=>seek(lines[Math.max(active,0)]?.start||0);
 document.getElementById('el-replay').onclick=()=>{{if(active>=0)seek(lines[active].start)}};
 document.getElementById('el-top').onclick=()=>seek(0);
 setInterval(()=>cmd('getCurrentTime',[]),700);
}})();
</script>
</div>'''


def process_lesson(url, transcript_text, transcript_file):
    vid = video_id(url)
    if not vid:
        return "❌ YouTube URL/Video ID không hợp lệ.", "", "", ""
    try:
        if transcript_file is not None:
            transcript_text = read_uploaded_file(transcript_file)
        transcript_text = (transcript_text or "").strip()
        if len(transcript_text) > MAX_TRANSCRIPT_CHARS:
            return "❌ Transcript quá lớn.", "", "", ""
        if not transcript_text:
            return "⚠️ Video đã sẵn sàng. Hãy dán transcript hoặc import file.", build_player(vid, []), "", ""
        segments = parse_transcript(transcript_text)
        if not segments:
            return "❌ Không đọc được transcript.", "", "", ""
        mode = "timestamp" if any(x["start"] > 0 for x in segments) else "text-only"
        return (f"✅ Đã nạp video {vid} · {len(segments)} câu · mode={mode}", build_player(vid, segments), transcript_text, json.dumps(segments, ensure_ascii=False, indent=2))
    except Exception as exc:
        return f"❌ Lỗi import transcript: {type(exc).__name__}: {exc}", "", "", ""


def load_video_only(url):
    vid = video_id(url)
    if not vid:
        return "❌ YouTube URL/Video ID không hợp lệ.", ""
    return f"✅ Video sẵn sàng: {vid}", build_player(vid, [])


def import_transcript(url, transcript_text, transcript_file):
    return process_lesson(url, transcript_text, transcript_file)


CUSTOM_CSS = """
.gradio-container { max-width: 1400px !important; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important; }
#hero { border-radius: 18px; padding: 28px 30px; background: linear-gradient(135deg,#111827 0%,#1e3a8a 55%,#2563eb 100%); color:white; margin-bottom:18px; }
#hero h1 { color:white !important; margin-bottom:6px; }
"""


with gr.Blocks(title=APP_TITLE, css=CUSTOM_CSS, theme=gr.themes.Soft()) as demo:
    gr.HTML('<div id="hero"><h1>🎧 English Lab</h1><div>Luyện nghe · đọc · phát âm với video YouTube và transcript nhập thủ công</div></div>')
    with gr.Tab("🎬 YouTube Lesson"):
        gr.Markdown("### 1. Nhập video → 2. Import transcript → 3. Click từng câu để nhảy đúng thời điểm\nServer **không tải video YouTube và không gọi YouTube Transcript API**.")
        yt_url = gr.Textbox(label="YouTube URL hoặc Video ID", placeholder="https://www.youtube.com/watch?v=... hoặc 11 ký tự Video ID")
        with gr.Row():
            load_btn = gr.Button("🎬 Nhúng video", variant="secondary")
            import_btn = gr.Button("🚀 Import transcript", variant="primary")
        with gr.Row():
            transcript_file = gr.File(label="📄 Import transcript — TXT / SRT / VTT / JSON", file_types=[".txt", ".srt", ".vtt", ".json"], type="filepath")
            transcript_text = gr.Textbox(label="📝 Hoặc dán transcript thủ công", placeholder="[00:00] Hello, welcome to English Lab.\n[00:05] Today we are going to practice listening.\n\nHoặc SRT/VTT: 00:00:05,000 --> 00:00:08,000", lines=10)
        status = gr.Markdown("Sẵn sàng.")
        player = gr.HTML(label="Video + Transcript")
        raw_output = gr.Textbox(label="📄 Transcript gốc", lines=10)
        parsed_output = gr.Code(label="🔬 Parsed segments", language="json", lines=12)
        load_btn.click(load_video_only, inputs=yt_url, outputs=[status, player])
        import_btn.click(import_transcript, inputs=[yt_url, transcript_text, transcript_file], outputs=[status, player, raw_output, parsed_output])
        gr.Markdown("#### Định dạng khuyến nghị\n`[00:12] Sentence...` · `00:12 Sentence...` · SRT/VTT `00:00:12,000 --> 00:00:15,000` · JSON3.\n\nNếu chỉ import text thuần không có timestamp, transcript vẫn hiển thị nhưng không thể click để seek chính xác.")
    with gr.Tab("ℹ️ Hướng dẫn"):
        gr.Markdown("""
### Quy trình mới
1. Mở video YouTube cần luyện.
2. Dùng chức năng **Transcript** của YouTube để sao chép/xuất transcript.
3. Trong English Lab, dán transcript hoặc import `.txt`, `.srt`, `.vtt`, `.json`.
4. Nếu transcript có timestamp, click từng câu để video nhảy tới đúng vị trí.
5. Dùng **Phát câu / Phát lại** để luyện nghe và đọc.

### Vì sao đổi kiến trúc?
HF Space trước đây cố tải `www.youtube.com` qua Webshare nhưng kết nối HTTPS tới YouTube bị `SSLEOFError`. Kiến trúc mới không phụ thuộc đường kết nối server → YouTube để lấy transcript: trình duyệt của người dùng phát video trực tiếp từ YouTube, còn Space chỉ xử lý transcript mà người dùng cung cấp.
""")

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
