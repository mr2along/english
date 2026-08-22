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
        if not line or re.fullmatch(r"(?:WEBVTT|NOTE|STYLE|REGION)", line, flags=re.I):
            continue
        m = re.match(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\s*-->\s*(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\s*(.*)$", line)
        if m:
            start, end, txt = parse_time(m.group(1)), parse_time(m.group(2)), clean_text(m.group(3))
            if start is not None and txt:
                lines.append({"start": start, "duration": max(0.0, (end or start) - start), "text": txt})
            continue
        m = re.match(r"^\s*\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\]?\s*(?:[-–—|]\s*)?(.*)$", line)
        if m:
            start, txt = parse_time(m.group(1)), clean_text(m.group(2))
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
            if txt.strip() and start is not None:
                result.append({"start": float(start) / 1000, "duration": float(ev.get("dDurationMs", 0) or 0) / 1000, "text": clean_text(txt)})
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
            result.append({"start": float(start), "duration": float(item.get("duration", 0) or 0), "text": clean_text(txt)})
        return result
    return []


def normalize_segments(lines):
    result = []
    for i, item in enumerate(lines, 1):
        txt = clean_text(item.get("text", ""))
        if txt:
            result.append({"index": i, "start": float(item.get("start", 0) or 0), "duration": float(item.get("duration", 0) or 0), "text": txt})
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


def fmt_time(seconds):
    seconds = max(0, int(float(seconds or 0)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def build_player(vid, lines):
    safe_vid = html.escape(vid, quote=True)
    iframe_src = f"https://www.youtube.com/embed/{safe_vid}?enablejsapi=1&playsinline=1&rel=0&origin=https%3A%2F%2Fhuggingface.co"
    rows = []
    for i, item in enumerate(lines):
        start = float(item.get("start", 0) or 0)
        safe_text = html.escape(item.get("text", ""))
        rows.append(
            f'<button type="button" class="el-line" data-start="{start:.3f}" data-index="{i}">'
            f'<span class="el-time">{fmt_time(start) if start > 0 else "—"}</span>'
            f'<span class="el-text"><span class="el-num">#{i + 1}</span>{safe_text}</span></button>'
        )
    body = "".join(rows) if rows else '<div class="el-empty">Chưa có transcript. Hãy import TXT/SRT/VTT/JSON hoặc dán transcript.</div>'
    if lines and not any(float(x.get("start", 0) or 0) > 0 for x in lines):
        body = '<div class="el-empty">Transcript không có timestamp. Import SRT/VTT hoặc dạng [00:12] câu để click-to-seek hoạt động.</div>' + body
    return f'''
<div class="el-shell" data-video-id="{safe_vid}">
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
.el-empty{{padding:20px;color:#69768a;text-align:center;font-size:13px}}
@media(max-width:850px){{.el-grid{{grid-template-columns:1fr}}.el-transcript{{height:420px}}}}
</style>
<div class="el-grid">
<section class="el-card">
  <div class="el-head"><div><div class="el-title">🎬 Video lesson</div><div class="el-sub">Video nhúng trực tiếp từ YouTube</div></div></div>
  <div class="el-video"><iframe class="el-youtube-frame" src="{iframe_src}" title="YouTube English Lesson" allow="autoplay; encrypted-media; picture-in-picture; web-share" allowfullscreen></iframe></div>
  <div class="el-tools"><button type="button" class="el-btn primary el-play">▶ Phát câu</button><button type="button" class="el-btn el-replay">↺ Phát lại</button><button type="button" class="el-btn el-top">↑ Về đầu</button></div>
  <div class="el-tip">💡 Click một câu để nhảy đến timestamp. Server không tải video YouTube.</div>
</section>
<section class="el-card">
  <div class="el-head"><div><div class="el-title">📝 English transcript</div><div class="el-sub">Manual import · click câu để seek</div></div><div class="el-sub">{len(lines)} câu</div></div>
  <div class="el-transcript el-lines">{body}</div>
</section>
</div>
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
            return f"⚠️ Video đã sẵn sàng: {vid}. Hãy dán transcript hoặc import file.", build_player(vid, []), "", ""
        segments = parse_transcript(transcript_text)
        if not segments:
            return "❌ Không đọc được transcript.", "", "", ""
        mode = "timestamp" if any(x["start"] > 0 for x in segments) else "text-only"
        return f"✅ Đã nạp video {vid} · {len(segments)} câu · mode={mode}", build_player(vid, segments), transcript_text, json.dumps(segments, ensure_ascii=False, indent=2)
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


CUSTOM_JS = r"""
(() => {
  const players = new WeakMap();
  const postCommand = (frame, func, args = []) => {
    if (!frame || !frame.contentWindow) return;
    frame.contentWindow.postMessage(JSON.stringify({event:'command', func, args}), '*');
  };
  const activate = (shell, index) => {
    shell.querySelectorAll('.el-line').forEach((b, i) => b.classList.toggle('active', i === index));
    const active = shell.querySelector('.el-line.active');
    if (active) active.scrollIntoView({block:'nearest', behavior:'smooth'});
  };
  const currentIndex = (shell, t) => {
    const rows = [...shell.querySelectorAll('.el-line')];
    let found = -1;
    rows.forEach((row, i) => {
      const a = Number(row.dataset.start || 0);
      const b = i + 1 < rows.length ? Number(rows[i+1].dataset.start || Infinity) : Infinity;
      if (t >= a && t < b) found = i;
    });
    return found;
  };
  const init = (shell) => {
    if (!shell || players.has(shell)) return;
    const frame = shell.querySelector('.el-youtube-frame');
    const rows = shell.querySelectorAll('.el-line');
    const hasTimes = [...rows].some(r => Number(r.dataset.start || 0) > 0);
    if (!frame) return;
    const state = {frame, timer:null, active:-1};
    players.set(shell, state);
    rows.forEach(row => row.addEventListener('click', () => {
      if (!hasTimes) return;
      const t = Number(row.dataset.start || 0);
      postCommand(frame, 'seekTo', [t, true]);
      postCommand(frame, 'playVideo', []);
      activate(shell, Number(row.dataset.index || 0));
    }));
    shell.querySelector('.el-play')?.addEventListener('click', () => {
      const row = shell.querySelector('.el-line.active') || rows[0];
      if (!row || !hasTimes) return;
      postCommand(frame, 'seekTo', [Number(row.dataset.start || 0), true]);
      postCommand(frame, 'playVideo', []);
    });
    shell.querySelector('.el-replay')?.addEventListener('click', () => {
      const row = shell.querySelector('.el-line.active');
      if (row) {
        postCommand(frame, 'seekTo', [Number(row.dataset.start || 0), true]);
        postCommand(frame, 'playVideo', []);
      }
    });
    shell.querySelector('.el-top')?.addEventListener('click', () => {
      postCommand(frame, 'seekTo', [0, true]);
      postCommand(frame, 'playVideo', []);
    });
    const poll = () => postCommand(frame, 'getCurrentTime', []);
    state.timer = setInterval(poll, 800);
  };
  const scan = (node = document) => {
    if (node.nodeType === 1 && node.matches?.('.el-shell')) init(node);
    node.querySelectorAll?.('.el-shell').forEach(init);
  };
  const observer = new MutationObserver(muts => muts.forEach(m => m.addedNodes.forEach(n => scan(n))));
  observer.observe(document.documentElement, {childList:true, subtree:true});
  scan();
  window.addEventListener('message', e => {
    if (typeof e.data !== 'string') return;
    let data;
    try { data = JSON.parse(e.data); } catch { return; }
    const t = data?.info?.currentTime ?? data?.infoDelivery?.currentTime;
    if (typeof t !== 'number') return;
    document.querySelectorAll('.el-shell').forEach(shell => {
      const state = players.get(shell);
      if (!state) return;
      const idx = currentIndex(shell, t);
      if (idx >= 0 && idx !== state.active) {
        state.active = idx;
        activate(shell, idx);
      }
    });
  });
})();
"""


with gr.Blocks(title=APP_TITLE, css=CUSTOM_CSS, js=CUSTOM_JS, theme=gr.themes.Soft()) as demo:
    gr.HTML('<div id="hero"><h1>🎧 English Lab</h1><div>Luyện nghe · đọc · phát âm với video YouTube và transcript nhập thủ công</div></div>')
    with gr.Tab("🎬 YouTube Lesson"):
        gr.Markdown("### 1. Nhập video → 2. Import transcript → 3. Click từng câu để nhảy đúng thời điểm\nServer **không tải video YouTube và không gọi YouTube Transcript API**.")
        yt_url = gr.Textbox(label="YouTube URL hoặc Video ID", placeholder="https://www.youtube.com/watch?v=... hoặc 11 ký tự Video ID")
        with gr.Row():
            load_btn = gr.Button("🎬 Nhúng video", variant="secondary")
            import_btn = gr.Button("🚀 Import transcript", variant="primary")
        with gr.Row():
            transcript_file = gr.File(label="📄 Import transcript — TXT / SRT / VTT / JSON", file_types=[".txt", ".srt", ".vtt", ".json"], type="filepath")
            transcript_text = gr.Textbox(label="📝 Hoặc dán transcript thủ công", placeholder="[00:00] Hello, welcome to English Lab.\n[00:05] Today we are going to practice listening.", lines=10)
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
2. Dùng chức năng Transcript của YouTube để sao chép/xuất transcript.
3. Trong English Lab, dán transcript hoặc import `.txt`, `.srt`, `.vtt`, `.json`.
4. Nếu transcript có timestamp, click từng câu để video nhảy tới đúng vị trí.
5. Dùng **Phát câu / Phát lại** để luyện nghe và đọc.

### Vì sao đổi kiến trúc?
HF Space không tải video hoặc transcript từ YouTube. Trình duyệt người dùng phát video trực tiếp từ YouTube, còn Space chỉ xử lý transcript do người dùng cung cấp.
""")

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
