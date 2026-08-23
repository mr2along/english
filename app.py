#!/usr/bin/env python3
import html, os
from pathlib import Path
import gradio as gr
from core.library import load, video_id
from core.transcript import format_time, parse_manual, to_json
from core.progress import ProgressStore
from core.practice import make_quiz
from core.learning_engine import make_practice_items
from core.ai_tutor import grammar_request, vocabulary_request
from core.qwen_mapper import map_video

BASE=Path(__file__).resolve().parent
LIB,SOURCE,ERROR=load(BASE); VIDEOS=LIB.get('videos',[])
PROGRESS=ProgressStore(BASE/'data'/'progress.json')
MAP={v['video_id']:v for v in VIDEOS}; MAPPED={}; TOTAL=sum(len(v.get('transcript',[])) for v in VIDEOS)
DEFAULT=VIDEOS[0]['video_id'] if VIDEOS else 'vxtvWovNKKE'

def choices(): return [(f"{i+1:03d} · {v.get('title',v['video_id'])}",v['video_id']) for i,v in enumerate(VIDEOS)]
def yt(vid):
    if not vid:return '<div class="empty">Chưa chọn video.</div>'
    e=html.escape(vid,quote=True)
    return f'<div class="video"><iframe id="ytplayer" src="https://www.youtube.com/embed/{e}?enablejsapi=1&playsinline=1&rel=0" allow="autoplay; encrypted-media; microphone; picture-in-picture" allowfullscreen></iframe></div><div class="video-link">🎬 {e} · <a target="_blank" href="https://www.youtube.com/watch?v={e}">Mở YouTube</a></div>'
def transcript_html(segs):
    if not segs:return '<div class="panel"><div class="panel-title">📝 Transcript</div><div class="empty">Chưa có transcript.</div></div>'
    body=''.join(f'<button class="line" data-index="{i}" data-start="{s["start"]:.3f}"><span class="time">{format_time(s["start"])}</span><span>{html.escape(s["text"])}</span></button>' for i,s in enumerate(segs))
    return f'<div class="panel"><div class="panel-title"><span>📝 Transcript</span><span class="count">{len(segs):,} câu</span></div><div class="lines">{body}</div></div>'
def mapped_video(vid):
    if vid not in MAPPED: MAPPED[vid]=map_video(MAP[vid])
    return MAPPED[vid]
def select(vid):
    v=MAP.get(vid)
    if not v:return '❌ Không tìm thấy bài học.',yt(vid),transcript_html([]),'[]',None
    try: v=mapped_video(vid)
    except Exception as exc: return f'❌ Qwen mapper: {exc}',yt(vid),transcript_html(v.get('transcript',[])),'[]',vid
    seg=v.get('transcript',[]); raw=len(v.get('raw_transcript',[])); PROGRESS.mark_view(vid)
    st=f"### 🎯 {v.get('position','')} · {html.escape(v.get('title',vid))}\n`{vid}` · {v.get('language','en')} · **{len(seg):,} câu tự nhiên** · raw **{raw:,} segments**\n\n🤖 **Qwen Sentence Mapper** · timestamp đồng bộ từ transcript gốc"
    return st,yt(vid),transcript_html(seg),to_json(seg),vid
def open_url(value):
    vid=video_id(value); return select(vid) if vid else ('❌ URL/Video ID không hợp lệ.',yt(''),transcript_html([]),'[]',None)
def search(q):
    q=(q or '').lower().strip(); c=choices() if not q else [(f"{i+1:03d} · {v['title']}",v['video_id']) for i,v in enumerate(VIDEOS) if q in f"{v['title']} {v['video_id']}".lower()]; return gr.update(choices=c,value=None)
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
    try: seg=parse_manual(raw); return f'✅ {len(seg):,} câu',to_json(seg),transcript_html(seg)
    except Exception as e:return f'❌ Parse lỗi: {e}','[]',transcript_html([])
def quiz(vid):
    v=MAPPED.get(vid) or MAP.get(vid); q=make_quiz(v.get('transcript',[])) if v else None
    return 'Chưa có dữ liệu quiz.' if not q else f"### 🧠 Mini Quiz\n**{q['question']}**\n\nĐáp án: `{q['answer']}`"
def ai(vid,task):
    v=MAPPED.get(vid) or MAP.get(vid); text=(v.get('transcript') or [{}])[0].get('text','') if v else ''
    if task=='grammar': return grammar_request(text)['prompt']
    return vocabulary_request(text)['prompt']
def practice(vid):
    v=MAPPED.get(vid) or MAP.get(vid); items=make_practice_items(v.get('transcript',[])) if v else []; return f"### 🎧 Listening / Shadowing\n**{len(items):,} câu luyện tập**\n\nChọn câu trong transcript để phát lại, sau đó dùng mic của trình duyệt để shadowing."

CSS='''body{background:#f8fafc}.gradio-container{max-width:1480px!important;padding:18px 22px 40px!important}.hero{padding:28px 30px;border-radius:24px;border:1px solid #dbe4f0;background:linear-gradient(135deg,#eef6ff 0%,#f5f3ff 52%,#f8fafc 100%);box-shadow:0 8px 30px rgba(15,23,42,.06);margin-bottom:14px}.hero h1{margin:0;font-size:34px;letter-spacing:-.6px}.hero .sub{margin-top:7px;color:#64748b;font-size:14px}.badge{display:inline-block;margin-top:13px;padding:5px 10px;border-radius:999px;background:#fff;border:1px solid #dbe4f0;color:#475569;font-size:12px;font-weight:700}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:12px 0}.stat{padding:16px;border:1px solid #e2e8f0;border-radius:18px;background:#fff;box-shadow:0 4px 18px rgba(15,23,42,.04)}.num{font-size:24px;font-weight:800;color:#0f172a}.label{font-size:12px;color:#64748b;margin-top:2px}.toolbar{padding:14px;border:1px solid #e2e8f0;border-radius:18px;background:#fff;margin:10px 0}.video{aspect-ratio:16/9;background:#020617;border-radius:18px 18px 0 0;overflow:hidden;box-shadow:0 8px 25px rgba(15,23,42,.12)}.video iframe{width:100%;height:100%;border:0}.video-link{padding:10px 14px;border:1px solid #e2e8f0;border-top:0;border-radius:0 0 18px 18px;background:#fff;color:#64748b;font-size:12px}.video-link a{color:#2563eb;text-decoration:none;font-weight:700}.panel{border:1px solid #e2e8f0;border-radius:18px;background:#fff;overflow:hidden;box-shadow:0 5px 20px rgba(15,23,42,.04)}.panel-title{padding:14px 16px;border-bottom:1px solid #e2e8f0;font-weight:800;display:flex;justify-content:space-between}.count{font-size:12px;color:#64748b;font-weight:600}.lines{max-height:590px;overflow:auto;padding:8px}.line{display:flex;gap:12px;width:100%;border:0;background:transparent;padding:11px 12px;border-radius:12px;text-align:left;cursor:pointer;line-height:1.5;transition:.15s}.line:hover{background:#f1f5f9}.line.active{background:#e0ecff;box-shadow:inset 3px 0 #2563eb}.time{min-width:64px;color:#2563eb;font:700 12px ui-monospace,SFMono-Regular,Menlo,monospace}.empty{padding:24px;color:#64748b;text-align:center}.gradio-tabitem{border-radius:14px}.footer-note{text-align:center;color:#94a3b8;font-size:12px;margin-top:20px}@media(max-width:800px){.gradio-container{padding:10px!important}.hero{padding:20px}.hero h1{font-size:27px}.stats{grid-template-columns:1fr}.lines{max-height:460px}.line{padding:10px 8px}.time{min-width:55px}}'''
JS=r'''() => {let currentIndex=-1;let lineNodes=[];const cmd=(f,a=[])=>{const x=document.getElementById('ytplayer');if(x?.contentWindow)x.contentWindow.postMessage(JSON.stringify({event:'command',func:f,args:a}),'*')};const wire=()=>{lineNodes=[...document.querySelectorAll('.line')];lineNodes.forEach((b,i)=>{if(b.dataset.wired)return;b.dataset.wired=1;b.onclick=()=>selectSentence(i,true)});if(currentIndex>=0&&currentIndex<lineNodes.length)lineNodes[currentIndex].classList.add('active')};const selectSentence=(i,autoplay=true)=>{if(!lineNodes.length)return;currentIndex=Math.max(0,Math.min(i,lineNodes.length-1));lineNodes.forEach(x=>x.classList.remove('active'));const b=lineNodes[currentIndex];b.classList.add('active');b.scrollIntoView({behavior:'smooth',block:'center'});cmd('seekTo',[+b.dataset.start,true]);if(autoplay)cmd('playVideo')};const sentenceMove=d=>selectSentence(currentIndex<0?(d>0?0:lineNodes.length-1):currentIndex+d,true);wire();new MutationObserver(wire).observe(document.body,{subtree:true,childList:true});window.EL={play:()=>cmd('playVideo'),pause:()=>cmd('pauseVideo'),back:()=>cmd('seekTo',[0,true]),speed:r=>cmd('setPlaybackRate',[+r]),prevSentence:()=>sentenceMove(-1),nextSentence:()=>sentenceMove(1),rewire:()=>{currentIndex=-1;wire()}}}'''

with gr.Blocks(title='English Learning Lab V2.5') as demo:
    gr.HTML(f"<div class='hero'><h1>🎧 English Learning Lab</h1><div class='sub'>Listening · Reading · Shadowing · Pronunciation · Grammar · Vocabulary · Quiz · Spaced Repetition</div><span class='badge'>V2.5 · Qwen Sentence Mapper · {len(VIDEOS)} lessons · {TOTAL:,} raw segments</span></div>")
    with gr.Row(elem_classes='stats'):
        gr.HTML(f"<div class='stat'><div class='num'>{len(VIDEOS):,}</div><div class='label'>📚 Bài học</div></div>"); gr.HTML(f"<div class='stat'><div class='num'>{TOTAL:,}</div><div class='label'>📝 Raw segments</div></div>"); gr.HTML(f"<div class='stat'><div class='num'>{len(PROGRESS.data['lessons']):,}</div><div class='label'>📈 Đã học</div></div>")
    gr.Markdown(f"**📦 Library:** `{SOURCE.upper()}`"+(f" · ⚠️ {ERROR}" if ERROR else ' · Dữ liệu sẵn sàng'))
    with gr.Row(elem_classes='toolbar'):
        search_box=gr.Textbox(label='🔎 Tìm bài học',placeholder='Tên bài hoặc Video ID',scale=2); lesson=gr.Dropdown(choices=choices(),label='📚 Chọn bài học',scale=3); open_btn=gr.Button('▶ Học bài',variant='primary')
    with gr.Row(): prev=gr.Button('← Bài trước'); nxt=gr.Button('Bài tiếp →'); show=gr.Checkbox(value=True,label='👁️ Hiện toàn bộ script')
    with gr.Row(): url=gr.Textbox(label='YouTube URL / Video ID',value=f'https://www.youtube.com/watch?v={DEFAULT}',scale=4); url_btn=gr.Button('🎬 Mở video')
    status=gr.Markdown('Chọn bài học để bắt đầu.')
    with gr.Row():
        with gr.Column(scale=7): player=gr.HTML(yt(DEFAULT))
        with gr.Column(scale=5): trans=gr.HTML(transcript_html(MAP.get(DEFAULT,{}).get('transcript',[])))
    with gr.Row():
        prev_sentence=gr.Button('⏮ Câu trước'); play=gr.Button('▶ Phát'); pause=gr.Button('⏸ Dừng'); next_sentence=gr.Button('Câu kế tiếp ⏭'); back=gr.Button('↺ Về đầu'); speed=gr.Dropdown([0.5,0.75,1,1.25,1.5],value=1,label='⚡ Tốc độ')
    with gr.Tabs():
        with gr.Tab('🎧 Listening / Shadowing'): practice_out=gr.Markdown(); practice_btn=gr.Button('🚀 Chuẩn bị luyện tập',variant='primary')
        with gr.Tab('🎤 Pronunciation'): gr.Markdown('**🎙️ Microphone**\n\nDùng mic của trình duyệt để luyện shadowing. Hệ thống sẽ bổ sung scoring phát âm ở phiên bản tiếp theo.')
        with gr.Tab('🤖 AI Tutor'):
            with gr.Row(): grammar_btn=gr.Button('📖 Grammar'); vocab_btn=gr.Button('📚 Vocabulary')
            ai_out=gr.Markdown('Chọn một bài rồi yêu cầu AI phân tích câu học.')
        with gr.Tab('🧠 Quiz'): quiz_btn=gr.Button('🎯 Tạo Quiz',variant='primary'); quiz_out=gr.Markdown()
        with gr.Tab('📦 Data'): parsed=gr.Code(to_json(MAP.get(DEFAULT,{}).get('transcript',[])),language='json',label='Mapped Transcript JSON',lines=10)
    gr.Markdown('### 📥 Import transcript dự phòng')
    with gr.Row(): file=gr.File(file_types=['.txt','.srt','.vtt','.json'],type='filepath',label='TXT / SRT / VTT / JSON'); text=gr.Textbox(label='Hoặc dán transcript',lines=4)
    imp=gr.Button('🚀 Import transcript'); imp_status=gr.Markdown(); gr.HTML("<div class='footer-note'>English Learning Lab · Qwen chỉ xác định ranh giới câu; timestamp lấy từ transcript gốc · HF Space không tải YouTube</div>")
    search_box.change(search,search_box,lesson); lesson.change(select,lesson,[status,player,trans,parsed,url]); open_btn.click(select,lesson,[status,player,trans,parsed,url]); url_btn.click(open_url,url,[status,player,trans,parsed,url]); prev.click(lambda x:move(x,-1),lesson,lesson).then(select,lesson,[status,player,trans,parsed,url]); nxt.click(lambda x:move(x,1),lesson,lesson).then(select,lesson,[status,player,trans,parsed,url]); show.change(lambda s,vid: transcript_html((MAPPED.get(vid) or MAP.get(vid,{})).get('transcript',[])) if s else '<div class="panel"><div class="empty">Toàn bộ script đang ẩn. Dùng ⏮ / ⏭ để luyện từng câu.</div></div>',[show,lesson],trans); practice_btn.click(practice,lesson,practice_out); grammar_btn.click(lambda x:ai(x,'grammar'),lesson,ai_out); vocab_btn.click(lambda x:ai(x,'vocab'),lesson,ai_out); quiz_btn.click(quiz,lesson,quiz_out); imp.click(import_transcript,[file,text],[imp_status,parsed,trans]); play.click(None,js='() => window.EL?.play()'); pause.click(None,js='() => window.EL?.pause()'); back.click(None,js='() => window.EL?.back()'); speed.change(None,js='r => window.EL?.speed(r)'); prev_sentence.click(None,js='() => window.EL?.prevSentence()'); next_sentence.click(None,js='() => window.EL?.nextSentence()')

demo.launch(server_name='0.0.0.0',server_port=int(os.getenv('PORT','7860')),css=CSS,js=JS,theme=gr.themes.Soft())
