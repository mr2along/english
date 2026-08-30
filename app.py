#!/usr/bin/env python3
import html, os, re, difflib, json
from pathlib import Path
import gradio as gr
from core.library import load, video_id
from core.transcript import format_time, parse_manual, to_json
from core.progress import ProgressStore
from core.practice import make_quiz, spaced_repetition_box
from core.learning_engine import make_practice_items
from core.ai_tutor import grammar_request, vocabulary_request

BASE=Path(__file__).resolve().parent
LIB,SOURCE,ERROR=load(BASE)
VIDEOS=LIB.get('videos',[])
MAP={v.get('video_id'):v for v in VIDEOS if v.get('video_id')}
PROGRESS=ProgressStore(BASE/'data'/'progress.json')
TOTAL=sum(len(v.get('transcript',[])) for v in VIDEOS)
DEFAULT=VIDEOS[0]['video_id'] if VIDEOS else ''

def choices(): return [(f"{i+1:03d} · {v.get('title',v['video_id'])}",v['video_id']) for i,v in enumerate(VIDEOS)]
def yt(vid):
    if not vid:return '<div class="empty">Chưa chọn video.</div>'
    e=html.escape(vid,quote=True)
    return f'<div class="video"><iframe id="ytplayer" src="https://www.youtube.com/embed/{e}?enablejsapi=1&playsinline=1&rel=0" allow="autoplay; encrypted-media; microphone; picture-in-picture" allowfullscreen></iframe></div><div class="video-link">🎬 {e} · <a target="_blank" href="https://www.youtube.com/watch?v={e}">Mở YouTube</a></div>'
def transcript_html(segs):
    if not segs:return '<div class="panel"><div class="panel-title">📝 Transcript</div><div class="empty">Chưa có transcript.</div></div>'
    body=''.join(f'<button class="line" data-index="{i}" data-start="{float(s.get("start",0)):.3f}"><span class="time">{format_time(float(s.get("start",0)))}</span><span>{html.escape(str(s.get("text","")))}</span></button>' for i,s in enumerate(segs))
    return f'<div class="panel"><div class="panel-title"><span>📝 Transcript</span><span class="count">{len(segs):,} câu</span></div><div class="lines">{body}</div></div>'
def select(vid):
    v=MAP.get(vid)
    if not v:return '❌ Không tìm thấy bài học.',yt(vid),transcript_html([]),'[]',None
    seg=v.get('transcript',[]); p=PROGRESS.lesson(vid); done=sum(bool(x) for x in p.get('sentences',{}).values()); pct=round(done/len(seg)*100) if seg else 0; PROGRESS.mark_view(vid)
    raw=len(v.get('raw_transcript',seg)); source=v.get('transcript_source','final_transcript'); align=v.get('alignment','final_alignment')
    st=f"### 🎯 {v.get('position','')} · {html.escape(v.get('title',vid))}\n`{vid}` · {v.get('language','en')} · **{len(seg):,} câu** · **{pct}% đã luyện**\n\n📦 Source: `{source}` · 🔗 Alignment: `{align}` · Raw: `{raw:,}`"
    return st,yt(vid),transcript_html(seg),to_json(seg),vid

def open_url(value):
    vid=video_id(value); return select(vid) if vid else ('❌ URL/Video ID không hợp lệ.',yt(''),transcript_html([]),'[]',None)
def search(q):
    q=(q or '').lower().strip(); c=choices() if not q else [(f"{i+1:03d} · {v.get('title',v['video_id'])}",v['video_id']) for i,v in enumerate(VIDEOS) if q in f"{v.get('title','')} {v['video_id']}".lower()]; return gr.update(choices=c,value=(c[0][1] if len(c)==1 else None))
def move(vid,d):
    ids=list(MAP); 
    if not ids:return None
    try:i=ids.index(vid)
    except ValueError:i=0
    return ids[(i+d)%len(ids)]
def sentence_for(vid,index):
    v=MAP.get(vid); seg=v.get('transcript',[]) if v else []
    if not seg:return ''
    try:i=max(0,min(int(index),len(seg)-1))
    except Exception:i=0
    return seg[i].get('text','')
def mark_sentence(vid,index):
    if not vid:return 'Chưa chọn bài.'
    try:i=max(0,int(index))
    except Exception:i=0
    p=PROGRESS.lesson(vid); p['sentences'][str(i)]=True; PROGRESS.save(); return f'✅ Đã đánh dấu câu {i+1}.'
def practice(vid):
    v=MAP.get(vid)
    if not v:return 'Chưa chọn bài.'
    items=make_practice_items(v.get('transcript',[])); return f"### 🎧 Listening / Shadowing\n**{len(items):,} câu luyện tập**\n\nBấm từng câu để nghe đúng timestamp → giảm tốc độ → shadowing → đánh dấu hoàn thành."
def grammar(vid):
    v=MAP.get(vid); text=(v.get('transcript') or [{}])[0].get('text','') if v else ''
    return grammar_request(text)['prompt'] if text else 'Chưa có câu để phân tích.'
def vocab(vid):
    v=MAP.get(vid); text=(v.get('transcript') or [{}])[0].get('text','') if v else ''
    return vocabulary_request(text)['prompt'] if text else 'Chưa có câu để phân tích.'
def quiz(vid):
    v=MAP.get(vid)
    if not v:return 'Chưa có dữ liệu quiz.'
    q=make_quiz(v.get('transcript',[]))
    return f"### 🧠 Mini Quiz\n**{q['question']}**\n\n<details><summary>Hiện đáp án</summary>{html.escape(q['answer'])}</details>" if q['type']=='fill_blank' else f"### 🧠 Repeat\n{html.escape(q['answer'])}"
def sr(vid,score):
    if not vid:return 'Chưa chọn bài.'
    b=spaced_repetition_box(score); p=PROGRESS.lesson(vid); p['score']=b['score']; p['next_review_days']=b['interval_days']; PROGRESS.save(); return f"### 🔁 Spaced Repetition\nĐiểm **{b['score']}/5** → ôn lại sau **{b['interval_days']} ngày**."
def pron_score(target,spoken):
    a=re.sub(r"[^a-z0-9' ]",'',(target or '').lower()).split(); b=re.sub(r"[^a-z0-9' ]",'',(spoken or '').lower()).split()
    if not a:return 'Chưa có câu mẫu.'
    score=round(difflib.SequenceMatcher(None,a,b).ratio()*100); missing=[w for w in a if w not in b][:10]
    return f"### 🎤 Pronunciation\n# {score}%\n\nSo khớp từ: **{len(a)} mẫu / {len(b)} đọc**\n\n{'Từ cần luyện: `'+', '.join(missing)+'`' if missing else '🎉 Câu đọc rất gần câu mẫu.'}"
def import_transcript(file,text):
    raw=text or ''
    if file:
        try:raw=Path(getattr(file,'name',file)).read_text(encoding='utf-8-sig')
        except Exception as e:return f'❌ {e}','[]',transcript_html([])
    try:seg=parse_manual(raw); return f'✅ {len(seg):,} câu',to_json(seg),transcript_html(seg)
    except Exception as e:return f'❌ Parse lỗi: {e}','[]',transcript_html([])

CSS='''body{background:#f8fafc}.gradio-container{max-width:1480px!important;padding:18px 22px 40px!important}.hero{padding:28px 30px;border-radius:24px;border:1px solid #dbe4f0;background:linear-gradient(135deg,#eef6ff,#f5f3ff,#f8fafc);box-shadow:0 8px 30px rgba(15,23,42,.06);margin-bottom:14px}.hero h1{margin:0;font-size:34px}.hero .sub{margin-top:7px;color:#64748b;font-size:14px}.badge{display:inline-block;margin-top:13px;padding:5px 10px;border-radius:999px;background:#fff;border:1px solid #dbe4f0;color:#475569;font-size:12px;font-weight:700}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:12px 0}.stat{padding:16px;border:1px solid #e2e8f0;border-radius:18px;background:#fff}.num{font-size:24px;font-weight:800}.label{font-size:12px;color:#64748b}.toolbar{padding:14px;border:1px solid #e2e8f0;border-radius:18px;background:#fff;margin:10px 0}.video{aspect-ratio:16/9;background:#020617;border-radius:18px 18px 0 0;overflow:hidden}.video iframe{width:100%;height:100%;border:0}.video-link{padding:10px 14px;border:1px solid #e2e8f0;background:#fff;color:#64748b;font-size:12px}.video-link a{color:#2563eb;font-weight:700}.panel{border:1px solid #e2e8f0;border-radius:18px;background:#fff;overflow:hidden}.panel-title{padding:14px 16px;border-bottom:1px solid #e2e8f0;font-weight:800;display:flex;justify-content:space-between}.count{font-size:12px;color:#64748b}.lines{max-height:590px;overflow:auto;padding:8px}.line{display:flex;gap:12px;width:100%;border:0;background:transparent;padding:11px 12px;border-radius:12px;text-align:left;cursor:pointer;line-height:1.5}.line:hover,.line.active{background:#e0ecff}.time{min-width:64px;color:#2563eb;font:700 12px ui-monospace,monospace}.empty{padding:24px;color:#64748b;text-align:center}.score{font-size:30px;font-weight:800}.footer-note{text-align:center;color:#94a3b8;font-size:12px;margin-top:20px}@media(max-width:800px){.gradio-container{padding:10px!important}.hero{padding:20px}.hero h1{font-size:27px}.stats{grid-template-columns:1fr 1fr}.lines{max-height:460px}}'''
JS=r'''() => {let i=-1,n=[];const cmd=(f,a=[])=>{let x=document.getElementById('ytplayer');if(x?.contentWindow)x.contentWindow.postMessage(JSON.stringify({event:'command',func:f,args:a}),'*')};const wire=()=>{n=[...document.querySelectorAll('.line')];n.forEach((b,k)=>{if(b.dataset.wired)return;b.dataset.wired=1;b.onclick=()=>go(k)});if(i>=0&&i<n.length)n[i].classList.add('active')};const go=k=>{if(!n.length)return;i=Math.max(0,Math.min(k,n.length-1));n.forEach(x=>x.classList.remove('active'));let b=n[i];b.classList.add('active');b.scrollIntoView({behavior:'smooth',block:'center'});cmd('seekTo',[+b.dataset.start,true]);cmd('playVideo')};wire();new MutationObserver(wire).observe(document.body,{subtree:true,childList:true});window.EL={play:()=>cmd('playVideo'),pause:()=>cmd('pauseVideo'),back:()=>cmd('seekTo',[0,true]),speed:r=>cmd('setPlaybackRate',[+r]),prevSentence:()=>go(i<0?n.length-1:i-1),nextSentence:()=>go(i<0?0:i+1)}}'''

with gr.Blocks(title='English Learning Lab V3',css=CSS,js=JS,theme=gr.themes.Soft()) as demo:
    gr.HTML(f"<div class='hero'><h1>🎧 English Learning Lab</h1><div class='sub'>Listening · Reading · Shadowing · Pronunciation · Grammar · Vocabulary · Quiz · Spaced Repetition</div><span class='badge'>V3 · Final Transcript · {len(VIDEOS)} lessons · {TOTAL:,} sentence segments</span></div>")
    with gr.Row(elem_classes='stats'):
        gr.HTML(f"<div class='stat'><div class='num'>{len(VIDEOS):,}</div><div class='label'>📚 Bài học</div></div>"); gr.HTML(f"<div class='stat'><div class='num'>{TOTAL:,}</div><div class='label'>📝 Sentence segments</div></div>"); gr.HTML(f"<div class='stat'><div class='num'>{len(PROGRESS.data.get('lessons',{})):,}</div><div class='label'>📈 Đã học</div></div>"); gr.HTML(f"<div class='stat'><div class='num'>{'FINAL' if SOURCE.startswith('final') else SOURCE.upper()}</div><div class='label'>📦 Library source</div></div>")
    gr.Markdown(f"**📦 Library:** `{SOURCE}`"+(f" · ⚠️ {ERROR}" if ERROR else ' · Dữ liệu sẵn sàng'))
    with gr.Row(elem_classes='toolbar'):
        search_box=gr.Textbox(label='🔎 Tìm bài học',placeholder='Tên bài hoặc Video ID',scale=2); lesson=gr.Dropdown(choices=choices(),value=DEFAULT,label='📚 Chọn bài học',scale=3); open_btn=gr.Button('▶ Học bài',variant='primary')
    with gr.Row():prev=gr.Button('← Bài trước'); nxt=gr.Button('Bài tiếp →'); show=gr.Checkbox(value=True,label='👁️ Hiện toàn bộ script')
    with gr.Row():url=gr.Textbox(label='YouTube URL / Video ID',value=(f'https://www.youtube.com/watch?v={DEFAULT}' if DEFAULT else '')); url_btn=gr.Button('🎬 Mở video')
    status=gr.Markdown('Chọn bài học để bắt đầu.')
    with gr.Row():
        with gr.Column(scale=7):player=gr.HTML(yt(DEFAULT))
        with gr.Column(scale=5):trans=gr.HTML(transcript_html(MAP.get(DEFAULT,{}).get('transcript',[])))
    with gr.Row():prev_sentence=gr.Button('⏮ Câu trước'); play=gr.Button('▶ Phát'); pause=gr.Button('⏸ Dừng'); next_sentence=gr.Button('Câu kế tiếp ⏭'); back=gr.Button('↺ Về đầu'); speed=gr.Dropdown([0.5,0.75,1,1.25,1.5],value=1,label='⚡ Tốc độ')
    with gr.Tabs():
        with gr.Tab('🎧 Listening / Shadowing'):
            practice_out=gr.Markdown(); practice_btn=gr.Button('🚀 Chuẩn bị luyện tập',variant='primary'); sentence_no=gr.Number(value=0,precision=0,label='Số câu (0 = câu đầu)'); mark_btn=gr.Button('✅ Đánh dấu câu đã luyện'); mark_out=gr.Markdown()
        with gr.Tab('🎤 Pronunciation'):
            target=gr.Textbox(label='Câu mẫu',lines=2); spoken=gr.Textbox(label='Câu bạn đọc / Speech-to-text',lines=2); pron_btn=gr.Button('🎯 Chấm độ khớp',variant='primary'); pron_out=gr.Markdown(); gr.Markdown('Dùng mic/Speech-to-text của trình duyệt rồi chấm độ khớp từ. Không giả lập điểm chất lượng âm thanh.')
        with gr.Tab('🤖 AI Tutor'):
            with gr.Row():grammar_btn=gr.Button('📖 Grammar'); vocab_btn=gr.Button('📚 Vocabulary')
            ai_out=gr.Markdown('Chọn bài rồi yêu cầu AI phân tích.')
        with gr.Tab('🧠 Quiz'):quiz_btn=gr.Button('🎯 Tạo Quiz',variant='primary'); quiz_out=gr.Markdown()
        with gr.Tab('🔁 Spaced Repetition'):sr_score=gr.Slider(0,5,value=3,step=1,label='Mức nhớ 0–5'); sr_btn=gr.Button('📅 Lập lịch ôn',variant='primary'); sr_out=gr.Markdown()
        with gr.Tab('📦 Data'):parsed=gr.Code(to_json(MAP.get(DEFAULT,{}).get('transcript',[])),language='json',label='Final Transcript JSON',lines=12)
    gr.Markdown('### 📥 Import transcript dự phòng')
    with gr.Row():file=gr.File(file_types=['.txt','.srt','.vtt','.json'],type='filepath',label='TXT / SRT / VTT / JSON'); text=gr.Textbox(label='Hoặc dán transcript',lines=4)
    imp=gr.Button('🚀 Import transcript'); imp_status=gr.Markdown(); gr.HTML("<div class='footer-note'>English Learning Lab V3 · production ưu tiên final_transcripts.json · HF Space không tải YouTube</div>")
    search_box.change(search,search_box,lesson); lesson.change(select,lesson,[status,player,trans,parsed,url]); open_btn.click(select,lesson,[status,player,trans,parsed,url]); url_btn.click(open_url,url,[status,player,trans,parsed,url]); prev.click(lambda x:move(x,-1),lesson,lesson).then(select,lesson,[status,player,trans,parsed,url]); nxt.click(lambda x:move(x,1),lesson,lesson).then(select,lesson,[status,player,trans,parsed,url]); show.change(lambda s,vid:transcript_html(MAP.get(vid,{}).get('transcript',[])) if s else '<div class="panel"><div class="empty">Script đang ẩn.</div></div>',[show,lesson],trans); practice_btn.click(practice,lesson,practice_out); sentence_no.change(sentence_for,[lesson,sentence_no],target); mark_btn.click(mark_sentence,[lesson,sentence_no],mark_out); grammar_btn.click(grammar,lesson,ai_out); vocab_btn.click(vocab,lesson,ai_out); quiz_btn.click(quiz,lesson,quiz_out); sr_btn.click(sr,[lesson,sr_score],sr_out); pron_btn.click(pron_score,[target,spoken],pron_out); imp.click(import_transcript,[file,text],[imp_status,parsed,trans]); play.click(None,js='() => window.EL?.play()'); pause.click(None,js='() => window.EL?.pause()'); back.click(None,js='() => window.EL?.back()'); speed.change(None,js='r => window.EL?.speed(r)'); prev_sentence.click(None,js='() => window.EL?.prevSentence()'); next_sentence.click(None,js='() => window.EL?.nextSentence()')

demo.launch(server_name='0.0.0.0',server_port=int(os.getenv('PORT','7860')))
