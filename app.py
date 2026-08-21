"""English Learning Lab — adaptive production entrypoint."""
import os
import re
import html
import requests
import gradio as gr
from core import APP_NAME, DEFAULT_PLAYLIST, load_library, load_lesson as _core_load_lesson, select_sentence, translate, check_speaking, stats, runtime_status
from learning.progress import save_teacher_result, learning_stats

INVIDIOUS_INSTANCES = tuple(x.strip().rstrip("/") for x in os.getenv("INVIDIOUS_INSTANCES", "https://inv.nadeko.net,https://invidious.nerdvpn.de,https://yt.chocolatemoo53.com,https://invidious.tiekoetter.com,https://invidious.f5.si").split(",") if x.strip())

def _selected_video(choice, items):
    if not choice or not items:
        return None
    try:
        i = int(str(choice).split("|", 1)[0]) - 1
        return items[i] if 0 <= i < len(items) else None
    except Exception:
        return None

def _caption_sentences(video_id):
    """Fetch English captions through Invidious without touching YouTube/yt-dlp SSL."""
    errors = []
    for base in INVIDIOUS_INSTANCES:
        try:
            r = requests.get(
                f"{base}/api/v1/captions/{video_id}",
                params={"label": "English"},
                headers={"User-Agent": "EnglishLearningLab/2.7", "Accept": "application/json"},
                timeout=(5, 12),
            )
            r.raise_for_status()
            data = r.json()
            captions = data.get("captions") or []
            cap = next((c for c in captions if str(c.get("languageCode", "")).lower().startswith("en") and c.get("url")), None)
            if not cap:
                errors.append(f"{base}: no English captions")
                continue
            cr = requests.get(cap["url"], headers={"User-Agent": "EnglishLearningLab/2.7"}, timeout=(5, 15))
            cr.raise_for_status()
            text = cr.text
            pieces = []
            if text.lstrip().startswith("{"):
                events = cr.json().get("events") or []
                for ev in events:
                    txt = " ".join(str(seg.get("utf8", "")) for seg in (ev.get("segs") or [])).strip()
                    txt = re.sub(r"\s+", " ", txt)
                    if txt:
                        s = float(ev.get("tStartMs", 0)) / 1000.0
                        e = s + float(ev.get("dDurationMs", 0)) / 1000.0
                        pieces.append((txt, s, e))
            else:
                for m in re.finditer(r'<text[^>]*start="([0-9.]+)"[^>]*dur="([0-9.]+)"[^>]*>(.*?)</text>', text, re.S):
                    txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(3)))).strip()
                    if txt:
                        s = float(m.group(1)); e = s + float(m.group(2)); pieces.append((txt, s, e))
            if not pieces:
                errors.append(f"{base}: empty caption response")
                continue
            result = []
            buf = []
            start = end = None
            for txt, s, e in pieces:
                start = s if start is None else start
                end = e
                buf.append(txt)
                sentence = re.sub(r"\s+", " ", " ".join(buf)).strip()
                if re.search(r"[.!?…]$", sentence) or len(sentence) >= 180:
                    result.append({"index": len(result), "text": sentence, "start": start, "end": end})
                    buf = []; start = end = None
            if buf:
                result.append({"index": len(result), "text": re.sub(r"\s+", " ", " ".join(buf)).strip(), "start": start or 0, "end": end or 0})
            return result, f"✅ {len(result)} câu · nguồn: Invidious {base}"
        except Exception as e:
            errors.append(f"{base}: {type(e).__name__}")
    return [], ""

def load_lesson(choice, items):
    """Load lesson with Invidious captions first; only fall back to core."""
    video = _selected_video(choice, items)
    if not video:
        return "", [], "❌ Chưa chọn video.", ""
    vid = str(video.get("id", ""))
    sentences, caption_status = _caption_sentences(vid)
    embed = f'<div class="player"><iframe src="https://www.youtube.com/embed/{vid}?enablejsapi=1&rel=0" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div>'
    if sentences:
        return embed, sentences, caption_status, f"### {video.get('title', vid)}"
    # Preserve the existing multi-source fallback if the proxy has no captions.
    player, ss, status, title = _core_load_lesson(choice, items)
    return player or embed, ss, status or "❌ Không lấy được English transcript.", title or f"### {video.get('title', vid)}"

def analyze_teacher(sentence, idx):
    if not sentence: return "⚠️ Chưa có câu để phân tích.", {}, learning_stats()
    from ai.teacher import AITeacher
    result=AITeacher().analyze(sentence); save_teacher_result(None,int(idx or 0),result)
    return result.markdown(),result.quiz or {},learning_stats()

def quiz_options(q):
    if not q or not q.get("question"): return "Chưa có quiz. Hãy chạy AI Teacher.",gr.update(choices=[]),""
    return f"### 📝 {q['question']}",gr.update(choices=[f"{chr(65+i)}. {x}" for i,x in enumerate((q.get('options') or [])[:4])]),q.get("answer","A")

def grade_quiz(choice,answer,q):
    if not choice or not answer or not q:return "⚠️ Chọn một đáp án."
    ok=choice.split(".",1)[0].strip().upper()==answer.strip().upper()
    return ("## ✅ Correct!" if ok else f"## ❌ Chưa đúng — đáp án **{answer}**")+f"\n\n{q.get('explanation','')}"

def next_index(idx,ss): return min(len(ss)-1,int(idx or 0)+1) if ss else 0
def prev_index(idx,ss): return max(0,int(idx or 0)-1) if ss else 0

def session_status(idx,ss):
    if not ss:return "Chưa có bài học."
    i=max(0,min(int(idx or 0),len(ss)-1));return f"### Câu {i+1} / {len(ss)} · {round((i+1)/len(ss)*100)}%"

def import_library(url):
    video_update,items,status,dash=load_library(url)
    choices=video_update.get("choices",[]); value=video_update.get("value")
    return video_update,gr.update(choices=choices,value=value),items,status,dash

def render_sentence_zero(ss):
    if not ss:
        return "<div class='sentence-main'>Chưa có transcript cho video này.</div>","","",session_status(0,ss),0
    text,raw,timestamp,idx=select_sentence(0,ss)
    return text,raw,timestamp,session_status(0,ss),idx

def render_sentence(i,ss):
    if not ss:
        return "<div class='sentence-main'>Chưa có transcript cho video này.</div>","","",session_status(0,ss),0
    text,raw,timestamp,idx=select_sentence(i,ss)
    return text,raw,timestamp,session_status(i,ss),idx

def open_session(choice,items):
    if not choice or not items:
        return "","[]","❌ Chưa chọn video.","","<div class='sentence-main'>Chọn video để bắt đầu.</div>","","", "Chưa có bài học.",0
    player,ss,status,title=load_lesson(choice,items)
    if ss:
        text,raw,timestamp,idx=select_sentence(0,ss)
        progress=session_status(0,ss)
    else:
        text="<div class='sentence-main'>⚠️ Chưa lấy được English transcript.</div>"; raw=""; timestamp=""; idx=0; progress=status or "⚠️ Chưa lấy được transcript."
    return player,ss,status,title,text,raw,timestamp,progress,idx

CSS=""".gradio-container{max-width:1180px!important}.hero{padding:22px;border-radius:22px;margin-bottom:14px;background:linear-gradient(135deg,#0f172a,#334155);color:white}.hero h1{margin:0;font-size:30px}.hero p{margin:5px 0 0;opacity:.82}.runtime{padding:10px 14px;border-radius:12px;background:#f8fafc;border:1px solid #e2e8f0}.step{border:1px solid #e2e8f0;border-radius:18px;padding:18px;margin:8px 0}.sentence-main{font-size:26px;line-height:1.45;font-weight:600;padding:22px;border-radius:18px;border:1px solid #cbd5e1;min-height:100px}.player{position:relative;padding-top:56.25%;overflow:hidden;border-radius:18px;background:#000}.player iframe{position:absolute;inset:0;width:100%;height:100%;border:0}@media(max-width:700px){.gradio-container{padding:8px!important}.hero h1{font-size:24px}.sentence-main{font-size:21px}.step{padding:12px}}"""

def main():
    with gr.Blocks(title=f"{APP_NAME} V2.7",css=CSS,theme=gr.themes.Soft()) as ui:
        library=gr.State([]); sentences=gr.State([]); quiz_state=gr.State({})
        gr.HTML('<div class="hero"><h1>🇬🇧 English Learning Lab</h1><p>Listening · Shadowing · Speaking · Grammar · Vocabulary · Quiz · Progress</p></div>')
        gr.Markdown(runtime_status(),elem_classes=["runtime"]); dashboard=gr.Markdown(stats()+" · "+learning_stats())
        with gr.Tab("📚 Library"):
            with gr.Row():
                playlist=gr.Textbox(label="YouTube Playlist",value=DEFAULT_PLAYLIST,scale=8); import_btn=gr.Button("📥 Import",variant="primary",scale=2)
            status=gr.Markdown(); video=gr.Dropdown(label="Chọn video",choices=[]); title=gr.Markdown(); player=gr.HTML(); transcript_status=gr.Markdown()
        with gr.Tab("🎯 Learning Session"):
            session_video=gr.Dropdown(label="🎬 Chọn video để luyện",choices=[],interactive=True)
            session_progress=gr.Markdown("Chưa có bài học."); sentence_index=gr.Number(value=0,visible=False,elem_id="sentence_index")
            current_sentence=gr.Markdown("<div class='sentence-main'>Chọn video để bắt đầu.</div>"); current_text=gr.State(""); timestamp=gr.Markdown(); session_player=gr.HTML()
            with gr.Row(): prev_btn=gr.Button("◀ Câu trước"); next_btn=gr.Button("Câu tiếp ▶",variant="primary")
            with gr.Group(elem_classes="step"):
                gr.Markdown("### 1️⃣ Listen — Nghe trước"); hide_transcript=gr.Checkbox(label="🔒 Ẩn transcript",value=True); reveal=gr.Button("👁 Hiện câu"); transcript_reveal=gr.Markdown("Transcript đang ẩn.")
            with gr.Group(elem_classes="step"):
                gr.Markdown("### 2️⃣ Translate"); translate_btn=gr.Button("🇻🇳 Dịch câu"); translation=gr.Markdown()
            with gr.Group(elem_classes="step"):
                gr.Markdown("### 3️⃣ Shadowing — Đọc theo"); audio=gr.Audio(sources=["microphone"],type="filepath",label="🎙 Đọc câu"); speak_btn=gr.Button("🎯 Chấm phát âm",variant="primary"); speaking=gr.Markdown(); recognized=gr.Textbox(label="AI nhận được",interactive=False)
            with gr.Group(elem_classes="step"):
                gr.Markdown("### 4️⃣ AI Teacher — Local Qwen (auto hardware)"); teacher_btn=gr.Button("🧑‍🏫 Phân tích câu",variant="primary"); teacher=gr.Markdown(); teacher_progress=gr.Markdown()
            with gr.Group(elem_classes="step"):
                gr.Markdown("### 5️⃣ Quick Quiz"); quiz_question=gr.Markdown("Quiz sẽ xuất hiện sau AI Teacher."); quiz_choice=gr.Radio(label="Chọn đáp án",choices=[]); quiz_answer=gr.State(""); quiz_btn=gr.Button("✅ Kiểm tra"); quiz_result=gr.Markdown()
            complete=gr.Button("☑️ Hoàn thành câu & sang câu tiếp",variant="primary")
        with gr.Tab("📊 Progress"):
            progress=gr.Markdown(stats()+" · "+learning_stats()); refresh=gr.Button("🔄 Refresh")

        import_btn.click(import_library,playlist,[video,session_video,library,status,dashboard])
        video.change(open_session,[video,library],[session_player,sentences,transcript_status,title,current_sentence,current_text,timestamp,session_progress,sentence_index]).then(lambda v:gr.update(value=v),video,session_video)
        session_video.change(open_session,[session_video,library],[session_player,sentences,transcript_status,title,current_sentence,current_text,timestamp,session_progress,sentence_index])
        sentence_index.change(render_sentence,[sentence_index,sentences],[current_sentence,current_text,timestamp,session_progress,sentence_index])
        next_btn.click(next_index,[sentence_index,sentences],sentence_index); prev_btn.click(prev_index,[sentence_index,sentences],sentence_index)
        reveal.click(lambda hidden,text:text if not hidden else "🔒 Transcript đang ẩn. Hãy nghe và tự nhớ câu trước.",[hide_transcript,current_text],transcript_reveal)
        hide_transcript.change(lambda hidden:"🔒 Transcript đang ẩn." if hidden else "👁 Transcript đã bật.",hide_transcript,transcript_reveal)
        translate_btn.click(translate,current_text,translation); speak_btn.click(check_speaking,[current_text,audio,sentence_index],[speaking,recognized])
        teacher_btn.click(analyze_teacher,[current_text,sentence_index],[teacher,quiz_state,teacher_progress]).then(quiz_options,quiz_state,[quiz_question,quiz_choice,quiz_answer])
        quiz_btn.click(grade_quiz,[quiz_choice,quiz_answer,quiz_state],quiz_result)
        complete.click(next_index,[sentence_index,sentences],sentence_index).then(lambda:stats()+" · "+learning_stats(),outputs=dashboard); refresh.click(lambda:stats()+" · "+learning_stats(),outputs=progress)
    ui.launch(server_name="0.0.0.0",server_port=int(os.getenv("PORT","7860")),ssr_mode=False)

if __name__=="__main__": main()
