#!/usr/bin/env python3
import html, os
from pathlib import Path
import gradio as gr
from core.library import load, find, video_id
from core.transcript import format_time, parse_manual, to_json
from core.progress import ProgressStore
from core.practice import make_quiz, spaced_repetition_box

BASE=Path(__file__).resolve().parent
LIB,SOURCE,ERROR=load(BASE); VIDEOS=LIB.get('videos',[])
PROGRESS=ProgressStore(BASE/'data'/'progress.json')
MAP={v['video_id']:v for v in VIDEOS}
TOTAL=sum(len(v.get('transcript',[])) for v in VIDEOS)
DEFAULT=VIDEOS[0]['video_id'] if VIDEOS else 'vxtvWovNKKE'

def choices(): return [(f"{i+1:03d} · {v.get('title',v['video_id'])}",v['video_id']) for i,v in enumerate(VIDEOS)]
def yt(vid):
    if not vid:return '<div class="empty">Chưa chọn video.</div>'
    e=html.escape(vid,quote=True)
    return f'<div class="video"><iframe id="ytplayer" src="https://www.youtube.com/embed/{e}?enablejsapi=1&playsinline=1&rel=0" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div><div class="video-link">🎬 {e} · <a target="_blank" href="https://www.youtube.com/watch?v={e}">Mở YouTube</a></div>'
def transcript_html(segs,hidden=False):
    if not segs:return '<div class="panel"><b>📝 Transcript</b><div class="empty">Chưa có transcript.</div></div>'
    body=''.join(f'<button class="line" data-start="{s["start"]:.3f}"><span class="time">{format_time(s["start"])}</span><span>{html.escape(s["text"])}</span></button>' for s in segs)
    return f'<div class="panel"><div class="head">📝 Transcript · {len(segs):,} câu</div><div class="lines">{body}</div></div>'

def select(vid):
    v=MAP.get(vid)
    if not v:return '❌ Không tìm thấy bài học.',yt(vid),transcript_html([]),'[]',None
    seg=v.get('transcript',[]); PROGRESS.mark_view(vid)
    st=f"### 🎯 {v.get('position','')} · {html.escape(v.get('title',vid))}\n`{vid}` · {v.get('language','en')} · **{len(seg):,} câu**"
    return st,yt(vid),transcript_html(seg),to_json(seg),vid

def open_url(value): return select(video_id(value)) if video_id(value) else ('❌ URL/Video ID không hợp lệ.',yt(''),'[]','[]',None)
def search(q):
    q=(q or '').lower().strip(); c=choices() if not q else [(f"{i+1:03d} · {v['title']}",v['video_id']) for i,v in enumerate(VIDEOS) if q in f"{v['title']} {v['video_id']}".lower()]
    return gr.update(choices=c,value=None)
def move(vid,d):
    ids=[v['video_id'] for v in VIDEOS]
    if not ids:return None
    try:i=ids.index(vid)
    except ValueError:i=0
    return ids[(i+d)%len(ids)]
def import_transcript(file,text):
    raw=text or ''
    if file:
        try: raw=Path(getattr(file,'name',file)).read_text(encoding='utf-8-sig')
        except Exception as e:return f'❌ {e}','[]',transcript_html([])
    try:
        seg=parse_manual(raw); return f'✅ {len(seg):,} câu',to_json(seg),transcript_html(seg)
    except Exception as e:return f'❌ Parse lỗi: {e}','[]',transcript_html([])
def quiz(vid):
    v=MAP.get(vid); q=make_quiz(v.get('transcript',[])) if v else None
    if not q:return 'Chưa có dữ liệu quiz.'
    return f"### 🧠 Mini Quiz\n**{q['question']}**\n\nĐáp án: `{q['answer']}`"

CSS='''.gradio-container{max-width:1450px!important}.hero{padding:24px;border-radius:20px;border:1px solid #e2e8f0;background:linear-gradient(135deg,#f8fafc,#eef2ff)}.hero h1{margin:0;font-size:32px}.muted{color:#64748b}.stat{padding:14px;border:1px solid #e2e8f0;border-radius:14px;text-align:center}.num{font-size:23px;font-weight:800}.label{font-size:12px;color:#64748b}.video{aspect-ratio:16/9;background:#000;border-radius:16px 16px 0 0;overflow:hidden}.video iframe{width:100%;height:100%;border:0}.video-link{padding:9px 14px;border:1px solid #e2e8f0;border-top:0;border-radius:0 0 16px 16px;font-size:12px}.panel{border:1px solid #e2e8f0;border-radius:16px;overflow:hidden}.head{padding:13px;border-bottom:1px solid #e2e8f0;font-weight:700}.lines{max-height:580px;overflow:auto;padding:7px}.line{display:flex;gap:12px;width:100%;border:0;background:transparent;padding:11px;border-radius:10px;text-align:left;cursor:pointer}.line:hover,.line.active{background:#eef2ff}.time{min-width:62px;color:#2563eb;font:700 12px monospace}.empty{padding:20px;color:#64748b}'''
JS=r'''() => {const cmd=(f,a=[])=>{const x=document.getElementById('ytplayer');if(x?.contentWindow)x.contentWindow.postMessage(JSON.stringify({event:'command',func:f,args:a}),'*')};const wire=()=>document.querySelectorAll('.line').forEach(b=>{if(b.dataset.wired)return;b.dataset.wired=1;b.onclick=()=>{document.querySelectorAll('.line.active').forEach(x=>x.classList.remove('active'));b.classList.add('active');cmd('seekTo',[+b.dataset.start,true]);cmd('playVideo')}});wire();new MutationObserver(wire).observe(document.body,{subtree:true,childList:true});window.EL={play:()=>cmd('playVideo'),pause:()=>cmd('pauseVideo'),back:()=>cmd('seekTo',[0,true]),speed:r=>cmd('setPlaybackRate',[+r])}}'''

with gr.Blocks(title='English Learning Lab V2.1',css=CSS,js=JS,theme=gr.themes.Soft()) as demo:
    gr.HTML("<div class='hero'><h1>🎧 English Learning Lab V2.1</h1><div class='muted'>Listening · Reading · Shadowing · Pronunciation · Grammar · Vocabulary · Quiz · Spaced Repetition</div></div>")
    gr.Markdown(f"**📦 Library:** `{SOURCE.upper()}` · **{len(VIDEOS)} bài** · **{TOTAL:,} câu**"+(f" · ⚠️ {ERROR}" if ERROR else ''))
    with gr.Row():
        for n,label in [(len(VIDEOS),'Bài học'),(TOTAL,'Câu transcript'),(len(PROGRESS.data['lessons']),'Đã học')]: gr.HTML(f"<div class='stat'><div class='num'>{n:,}</div><div class='label'>{label}</div></div>")
    with gr.Row():
        search_box=gr.Textbox(label='🔎 Tìm bài học',placeholder='Tên bài hoặc Video ID')
        lesson=gr.Dropdown(choices=choices(),label='📚 Lesson',scale=2)
        open_btn=gr.Button('▶ Học bài',variant='primary')
    with gr.Row(): prev=gr.Button('← Bài trước'); nxt=gr.Button('Bài tiếp →')
    with gr.Row(): url=gr.Textbox(label='YouTube URL / Video ID',value=f'https://www.youtube.com/watch?v={DEFAULT}',scale=4); url_btn=gr.Button('🎬 Mở video')
    status=gr.Markdown('Chọn bài học để bắt đầu.')
    player=gr.HTML(yt(DEFAULT)); trans=gr.HTML(transcript_html(MAP.get(DEFAULT,{}).get('transcript',[]))); parsed=gr.Code(to_json(MAP.get(DEFAULT,{}).get('transcript',[])),language='json',label='🔬 Transcript JSON',lines=8)
    with gr.Row(): play=gr.Button('▶ Phát'); pause=gr.Button('⏸ Dừng'); back=gr.Button('↺ Về đầu'); speed=gr.Dropdown([0.5,0.75,1,1.25,1.5],value=1,label='Tốc độ')
    show=gr.Checkbox(value=True,label='👁️ Hiện transcript')
    quiz_btn=gr.Button('🧠 Tạo Quiz'); quiz_out=gr.Markdown()
    gr.Markdown('### 📥 Import transcript dự phòng')
    with gr.Row(): file=gr.File(file_types=['.txt','.srt','.vtt','.json'],type='filepath',label='TXT / SRT / VTT / JSON'); text=gr.Textbox(label='Hoặc dán transcript',lines=4)
    imp=gr.Button('🚀 Import transcript'); imp_status=gr.Markdown()
    search_box.change(search,search_box,lesson); lesson.change(select,lesson,[status,player,trans,parsed,url]); open_btn.click(select,lesson,[status,player,trans,parsed,url]); url_btn.click(open_url,url,[status,player,trans,parsed,url]); prev.click(lambda x:move(x,-1),lesson,lesson).then(select,lesson,[status,player,trans,parsed,url]); nxt.click(lambda x:move(x,1),lesson,lesson).then(select,lesson,[status,player,trans,parsed,url]); quiz_btn.click(quiz,lesson,quiz_out); imp.click(import_transcript,[file,text],[imp_status,parsed,trans]); show.change(lambda s,vid: transcript_html(MAP.get(vid,{}).get('transcript',[]),not s),[show,lesson],trans)
    play.click(None,js='() => window.EL?.play()'); pause.click(None,js='() => window.EL?.pause()'); back.click(None,js='() => window.EL?.back()'); speed.change(None,js='r => window.EL?.speed(r)')

if __name__=='__main__': demo.launch(server_name='0.0.0.0',server_port=int(os.getenv('PORT','7860')))
