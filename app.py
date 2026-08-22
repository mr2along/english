#!/usr/bin/env python3
import html
import json
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlparse

import gradio as gr

APP_TITLE = "English Lab"
DEFAULT_URL = "https://www.youtube.com/watch?v=vxtvWovNKKE"
REPO_RAW = "https://raw.githubusercontent.com/mr2along/english/feature/english-lab-v21/Transcription/playlist_transcripts.json"
LOCAL_FILE = Path(__file__).resolve().parent / "Transcription" / "playlist_transcripts.json"


def get_video_id(value):
    value = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value): return value
    try:
        p = urlparse(value); host = (p.hostname or "").lower()
        if host in {"youtu.be", "www.youtu.be"}:
            x = p.path.strip("/").split("/")[0]; return x if re.fullmatch(r"[A-Za-z0-9_-]{11}", x) else None
        x = parse_qs(p.query).get("v", [None])[0]
        if x and re.fullmatch(r"[A-Za-z0-9_-]{11}", x): return x
        parts = [x for x in p.path.split("/") if x]
        if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live"} and re.fullmatch(r"[A-Za-z0-9_-]{11}", parts[1]): return parts[1]
    except Exception: pass
    return None


def clean_text(value):
    value = html.unescape(str(value or "")); value = re.sub(r"<[^>]*>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_segments(raw):
    out=[]
    for item in raw or []:
        if not isinstance(item, dict): continue
        text=clean_text(item.get("text") or item.get("utf8") or "")
        try: start=float(item.get("start",0) or 0); duration=float(item.get("duration",0) or 0)
        except (TypeError,ValueError): continue
        if text: out.append({"index":len(out)+1,"start":start,"duration":duration,"text":text})
    for i in range(len(out)-1):
        if not out[i]["duration"]: out[i]["duration"]=max(0,out[i+1]["start"]-out[i]["start"])
    return out


def validate_library(data):
    if not isinstance(data,dict) or not isinstance(data.get("videos"),list): raise ValueError("JSON không có trường videos dạng list")
    videos=[]
    for v in data["videos"]:
        if not isinstance(v,dict) or not v.get("video_id"): continue
        item=dict(v); item["video_id"]=str(item["video_id"]); item["title"]=clean_text(item.get("title") or item["video_id"]); item["transcript"]=normalize_segments(item.get("transcript")); videos.append(item)
    data["videos"]=videos; return data


def load_library():
    errors=[]
    if LOCAL_FILE.exists():
        try: return validate_library(json.loads(LOCAL_FILE.read_text(encoding="utf-8-sig"))),"local",None
        except Exception as exc: errors.append(f"local: {exc}")
    try:
        req=Request(REPO_RAW,headers={"User-Agent":"EnglishLab/1.0"})
        with urlopen(req,timeout=15) as response: data=json.loads(response.read().decode("utf-8-sig"))
        return validate_library(data),"github",None
    except Exception as exc: errors.append(f"github: {exc}")
    return {"playlist_url":"","videos":[]},"error"," | ".join(errors)


LIBRARY,SOURCE,LOAD_ERROR=load_library(); VIDEOS=LIBRARY.get("videos",[]); VIDEO_MAP={v["video_id"]:v for v in VIDEOS}; TOTAL_SEGMENTS=sum(len(v.get("transcript",[])) for v in VIDEOS)


def choices(): return [(f"{i+1:03d} · {v['title']}",v["video_id"]) for i,v in enumerate(VIDEOS)]
def time_text(seconds):
    h,rem=divmod(int(max(0,float(seconds or 0))),3600); m,s=divmod(rem,60); return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def player(video_id):
    if not video_id:return "<div class='empty'>Chưa chọn video.</div>"
    v=html.escape(video_id,quote=True); src=f"https://www.youtube.com/embed/{v}?enablejsapi=1&playsinline=1&rel=0&origin=https%3A%2F%2Fhuggingface.co"
    return f'''<div class="yt"><div class="frame"><iframe id="englishlab-youtube" src="{src}" title="English Lab YouTube lesson" allow="autoplay; encrypted-media; picture-in-picture; web-share" allowfullscreen></iframe></div><div class="links">🎬 {v} · <a href="https://www.youtube.com/watch?v={v}" target="_blank">Mở YouTube</a></div></div>'''


def transcript(segments):
    if not segments:return '<div class="panel"><div class="head">📝 Transcript</div><div class="empty">Chưa có transcript.</div></div>'
    rows=[f'<button type="button" class="line" data-start="{s["start"]:.3f}"><span class="stamp">{time_text(s["start"])}</span><span>{html.escape(s["text"])}</span></button>' for s in segments]
    return f'<div class="panel"><div class="head">📝 Transcript <span>{len(rows):,} câu</span></div><div class="list">{"".join(rows)}</div></div>'


def select_video(video_id):
    v=VIDEO_MAP.get(video_id)
    if not v:return "❌ Không tìm thấy bài học.",player(video_id),transcript([]),"[]",video_id or ""
    segs=v.get("transcript",[]); status=f"### Bài {v.get('position','—')} · {html.escape(v['title'])}\n`{v['video_id']}` · **{v.get('language','en')}** · **{len(segs):,} câu**"
    return status,player(v["video_id"]),transcript(segs),json.dumps(segs,ensure_ascii=False,indent=2),v.get("url","")


def open_url(value):
    vid=get_video_id(value)
    if not vid:return "❌ URL/Video ID không hợp lệ.",player(""),transcript([]),"[]",""
    return select_video(vid)


def search_library(q):
    q=(q or "").strip().lower(); result=choices() if not q else [(f"{i+1:03d} · {v['title']}",v['video_id']) for i,v in enumerate(VIDEOS) if q in f"{v['title']} {v['video_id']} {v.get('language','')}".lower()]
    return gr.update(choices=result,value=None)


def move(video_id,step):
    ids=[v["video_id"] for v in VIDEOS]
    if not ids:return None
    try:i=ids.index(video_id)
    except ValueError:i=0
    return ids[(i+step)%len(ids)]


def manual_import(file_obj,text):
    raw=text or ""
    if file_obj:
        try:raw=Path(getattr(file_obj,"name",file_obj)).read_text(encoding="utf-8-sig")
        except Exception as exc:return f"❌ {exc}","[]",transcript([])
    if not raw.strip():return "⚠️ Chưa có dữ liệu.","[]",transcript([])
    try:
        if raw.lstrip().startswith(("{","[")):
            data=json.loads(raw); data=data.get("transcript") or data.get("segments") or [] if isinstance(data,dict) else data; segs=normalize_segments(data)
        else:
            segs=[]
            for line in raw.splitlines():
                m=re.match(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\]?\s*(.*)$",line.strip())
                if m:
                    p=m.group(1).replace(",",".").split(":"); start=float(p[-1])+float(p[-2])*60+(float(p[-3])*3600 if len(p)==3 else 0)
                    if m.group(2).strip():segs.append({"index":len(segs)+1,"start":start,"duration":0,"text":clean_text(m.group(2))})
        return f"✅ Đã parse {len(segs):,} câu.",json.dumps(segs,ensure_ascii=False,indent=2),transcript(segs)
    except Exception as exc:return f"❌ Parse lỗi: {exc}","[]",transcript([])


CSS='''.gradio-container{max-width:1440px!important}.hero{padding:24px;border:1px solid #e2e8f0;border-radius:20px;background:linear-gradient(135deg,#f8fafc,#eef2ff);margin-bottom:16px}.hero h1{margin:0 0 6px;font-size:32px}.muted{color:#64748b}.stat{padding:14px;border:1px solid #e2e8f0;border-radius:14px;text-align:center;flex:1}.num{font-size:24px;font-weight:800}.label{font-size:12px;color:#64748b}.yt,.panel{border:1px solid #e2e8f0;border-radius:16px;overflow:hidden;background:var(--body-background-fill)}.frame{aspect-ratio:16/9;background:#000}.frame iframe{width:100%;height:100%;border:0}.links{padding:10px 14px;font-size:12px;color:#64748b}.links a{color:#2563eb}.head{padding:13px 15px;border-bottom:1px solid #e2e8f0;font-weight:700;display:flex;justify-content:space-between}.list{max-height:580px;overflow:auto;padding:8px}.line{display:flex;gap:12px;width:100%;border:0;background:transparent;border-radius:10px;padding:11px 10px;margin:2px 0;text-align:left;cursor:pointer;line-height:1.5}.line:hover{background:#eef2ff}.line.active{background:#dbeafe}.stamp{min-width:62px;color:#2563eb;font:700 12px ui-monospace,monospace}.empty{padding:20px;color:#64748b}.tools{display:flex;gap:8px;flex-wrap:wrap}'''

JS=r'''() => {let timer=null;const f=()=>document.getElementById('englishlab-youtube');const cmd=(fn,args=[])=>{const x=f();if(x?.contentWindow)x.contentWindow.postMessage(JSON.stringify({event:'command',func:fn,args}),'*')};const seek=s=>{cmd('seekTo',[Number(s)||0,true]);cmd('playVideo')};const wire=()=>document.querySelectorAll('.line').forEach(b=>{if(b.dataset.wired)return;b.dataset.wired='1';b.onclick=()=>{document.querySelectorAll('.line.active').forEach(x=>x.classList.remove('active'));b.classList.add('active');seek(b.dataset.start)}});wire();new MutationObserver(wire).observe(document.body,{subtree:true,childList:true});window.englishLab={play:()=>cmd('playVideo'),pause:()=>cmd('pauseVideo'),stop:()=>cmd('stopVideo'),back:()=>cmd('seekTo',[0,true]),speed:r=>cmd('setPlaybackRate',[Number(r)])};}'''

source_note=f"**📦 Library:** `{SOURCE.upper()}` · **{len(VIDEOS)} bài** · **{TOTAL_SEGMENTS:,} câu**"
if LOAD_ERROR: source_note+=f"\n\n⚠️ `{LOAD_ERROR}`"

with gr.Blocks(title=APP_TITLE,css=CSS,js=JS,theme=gr.themes.Soft()) as demo:
    gr.HTML("<div class='hero'><h1>🎧 English Lab</h1><div class='muted'>Luyện nghe · đọc · phát âm · học theo transcript · thư viện YouTube</div></div>")
    gr.Markdown(source_note)
    with gr.Row():
        gr.HTML(f"<div class='stat'><div class='num'>{len(VIDEOS)}</div><div class='label'>Bài học</div></div>")
        gr.HTML(f"<div class='stat'><div class='num'>{TOTAL_SEGMENTS:,}</div><div class='label'>Câu transcript</div></div>")
        gr.HTML(f"<div class='stat'><div class='num'>{SOURCE.upper()}</div><div class='label'>Nguồn dữ liệu</div></div>")
    with gr.Row():
        search=gr.Textbox(label="🔎 Tìm bài học",placeholder="Tên bài, Video ID...")
        lesson=gr.Dropdown(choices=choices(),label="📚 Chọn bài học",scale=2)
        open_btn=gr.Button("▶ Học bài",variant="primary")
    with gr.Row():
        prev_btn=gr.Button("← Bài trước"); next_btn=gr.Button("Bài tiếp →")
    with gr.Row():
        url=gr.Textbox(label="YouTube URL / Video ID",value=DEFAULT_URL,scale=4); url_btn=gr.Button("🎬 Mở video")
    status=gr.Markdown("Chọn một bài học để bắt đầu.")
    initial_id=VIDEOS[0]["video_id"] if VIDEOS else get_video_id(DEFAULT_URL)
    player_box=gr.HTML(player(initial_id)); transcript_box=gr.HTML(transcript(VIDEOS[0].get("transcript",[]) if VIDEOS else [])); parsed=gr.Code(value="[]",label="🔬 Dữ liệu transcript",language="json",lines=10)
    gr.Markdown("### 🎛️ Điều khiển luyện nghe")
    with gr.Row():
        play=gr.Button("▶ Phát"); pause=gr.Button("⏸ Tạm dừng"); back=gr.Button("↺ Về đầu"); speed=gr.Dropdown([("0.5x",0.5),("0.75x",0.75),("1x",1.0),("1.25x",1.25),("1.5x",1.5)],value=1.0,label="Tốc độ",scale=1)
    search.change(search_library,search,lesson); lesson.change(select_video,lesson,[status,player_box,transcript_box,parsed,url]); open_btn.click(select_video,lesson,[status,player_box,transcript_box,parsed,url]); url_btn.click(open_url,url,[status,player_box,transcript_box,parsed,url])
    prev_btn.click(lambda x:move(x,-1),lesson,lesson).then(select_video,lesson,[status,player_box,transcript_box,parsed,url]); next_btn.click(lambda x:move(x,1),lesson,lesson).then(select_video,lesson,[status,player_box,transcript_box,parsed,url])
    play.click(None,js="() => window.englishLab?.play()"); pause.click(None,js="() => window.englishLab?.pause()"); back.click(None,js="() => window.englishLab?.back()"); speed.change(None,js="(r) => window.englishLab?.speed(r)")
    gr.Markdown("### 📥 Import transcript dự phòng")
    gr.Markdown("Transcript chính được lấy từ file playlist đã upload; HF Space không gọi YouTube Transcript API.")
    with gr.Row(): file=gr.File(label="TXT / SRT / VTT / JSON",file_types=[".txt",".srt",".vtt",".json"],type="filepath"); text=gr.Textbox(label="Hoặc dán transcript",lines=5)
    imp=gr.Button("🚀 Import transcript"); import_status=gr.Markdown(); imp.click(manual_import,[file,text],[import_status,parsed,transcript_box])

if __name__=="__main__": demo.launch(server_name="0.0.0.0",server_port=int(os.getenv("PORT","7860")))
