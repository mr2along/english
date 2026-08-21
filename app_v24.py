"""English Learning Lab V2.4 entrypoint.
Adds persistent vocabulary, spaced repetition and interactive AI quiz on top of V2.3."""
import os
import gradio as gr

from app_v23 import main as _unused
from app import APP_NAME, DEFAULT_PLAYLIST, cards, load_library, load_lesson, select_sentence, translate, check_speaking, stats
from ai.teacher import AITeacher
from learning.progress import save_teacher_result, due_words, all_words, review_word, save_quiz, learning_stats


def teacher_markdown_and_save(sentence, sentence_index):
    result = AITeacher().analyze(sentence)
    saved = save_teacher_result(None, int(sentence_index or 0), result)
    return result.markdown(), learning_stats(), saved, result.quiz


def vocab_html(rows):
    if not rows:
        return '<div class="empty">🎉 Không có từ đến hạn. Hãy học thêm bài hoặc quay lại sau.</div>'
    out = ['<div class="vocab-grid">']
    for r in rows:
        out.append(f'''<div class="vocab-card"><div class="word">{r['word']}</div><div>{r['meaning']}</div><small>{r['word_type']} · {r['interval_days']} ngày · {r['repetitions']} lần</small></div>''')
    return ''.join(out) + '</div>'


def quiz_view(q):
    if not q or not q.get('question'):
        return '<div class="empty">Hãy phân tích câu bằng AI Teacher để tạo quiz.</div>', gr.update(choices=[]), ""
    opts = q.get('options') or []
    return f"### 📝 {q['question']}", gr.update(choices=[f"{chr(65+i)}. {x}" for i,x in enumerate(opts[:4])]), q.get('answer','A')


def check_quiz(selected, answer, q, sentence_index):
    if not selected or not q or not q.get('question'):
        return '⚠️ Chưa có câu hỏi.'
    letter = selected.split('.',1)[0].strip().upper()
    ok = save_quiz(None, int(sentence_index or 0), q.get('question',''), letter, answer)
    return ('✅ **Correct!** ' if ok else '❌ **Chưa đúng.** ') + f"Đáp án: **{answer}**.\n\n{q.get('explanation','')}\n\n{learning_stats()}"


def review_selected(vocab_id, quality):
    if not vocab_id:
        return '⚠️ Chọn một từ để ôn.'
    row = review_word(int(vocab_id), int(quality))
    if not row:
        return '❌ Không tìm thấy từ.'
    return f"✅ **{row['word']}** — lần ôn tiếp theo sau **{row['interval_days']} ngày**.\n\n{learning_stats()}"


def refresh_vocab():
    rows = due_words(30)
    choices = [f"{r['id']} | {r['word']} — {r['meaning']}" for r in rows]
    return vocab_html(rows), gr.update(choices=choices, value=choices[0] if choices else None), learning_stats()


def parse_vocab_id(choice):
    try: return int(choice.split('|')[0].strip())
    except Exception: return None


def main():
    library_state=gr.State([]); sentence_state=gr.State([]); quiz_state=gr.State({})
    css='''.gradio-container{max-width:1200px!important}.hero{padding:24px;border-radius:20px;margin-bottom:16px;background:linear-gradient(135deg,#111827,#334155);color:white}.player{position:relative;padding-top:56.25%;overflow:hidden;border-radius:18px;background:#000}.player iframe{position:absolute;inset:0;width:100%;height:100%;border:0}.transcript{max-height:510px;overflow:auto}.sentence{width:100%;display:flex;gap:12px;text-align:left;border:1px solid #ddd;border-radius:14px;padding:12px;margin:7px 0;background:transparent}.hidden,.empty{padding:42px;text-align:center;border:1px dashed #999;border-radius:16px}.vocab-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.vocab-card{border:1px solid #ddd;border-radius:16px;padding:16px}.word{font-size:22px;font-weight:700;margin-bottom:6px}'''
    js="""function englishLabSelect(i){const el=document.querySelector('#sentence_index input');if(!el)return;el.value=i;el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true));}"""
    with gr.Blocks(title=f'{APP_NAME} V2.4',css=css,js=js,theme=gr.themes.Soft()) as ui:
        gr.HTML('<div class="hero"><h1>🇬🇧 English Learning Lab V2.4</h1><p>Listen · Shadow · Speak · AI Teacher · Vocabulary · Spaced Repetition · Quiz</p></div>')
        dashboard=gr.Markdown(stats()+"  ·  "+learning_stats())
        with gr.Tab('🎧 Listening'):
            with gr.Row():
                playlist_url=gr.Textbox(label='YouTube Playlist',value=DEFAULT_PLAYLIST,scale=8); load_btn=gr.Button('📥 Import',variant='primary',scale=2)
            library_status=gr.Markdown(); video_choice=gr.Dropdown(label='Video Library',choices=[]); video_title=gr.Markdown(); video_html=gr.HTML(); transcript_status=gr.Markdown()
            with gr.Row(): show=gr.Checkbox(label='👁 Show transcript',value=True); focus=gr.Checkbox(label='🎯 Focus current sentence',value=False)
            transcript_html=gr.HTML(); sentence_index=gr.Number(value=0,visible=False,elem_id='sentence_index')
            with gr.Row(): sentence_text=gr.Textbox(label='Current sentence',lines=3,interactive=False,scale=7); sentence_info=gr.Markdown(scale=2)
            sentence_time=gr.Textbox(label='Timestamp',interactive=False)
            with gr.Row(): prev_btn=gr.Button('◀ Previous'); next_btn=gr.Button('Next ▶'); translate_btn=gr.Button('🇻🇳 Translate')
            translate_out=gr.Markdown()
        with gr.Tab('🤖 AI Teacher'):
            teacher_btn=gr.Button('🧑‍🏫 Analyze + save vocabulary',variant='primary'); teacher_out=gr.Markdown(); saved_out=gr.Markdown()
        with gr.Tab('📝 Quiz'):
            quiz_state=gr.State({}); quiz_question=gr.Markdown('Hãy phân tích câu để tạo quiz.'); quiz_options=gr.Radio(label='Chọn đáp án',choices=[]); quiz_answer=gr.State(''); quiz_btn=gr.Button('✅ Check answer',variant='primary'); quiz_out=gr.Markdown()
        with gr.Tab('🧠 Vocabulary Review'):
            learning_summary=gr.Markdown(learning_stats()); refresh_vocab_btn=gr.Button('🔄 Load words due today'); vocab_cards=gr.HTML(); vocab_choice=gr.Dropdown(label='Từ cần ôn',choices=[]); quality=gr.Slider(0,5,value=4,step=1,label='Mức độ nhớ (0=quên hoàn toàn, 5=rất dễ)'); review_btn=gr.Button('📅 Schedule review',variant='primary'); review_out=gr.Markdown()
        with gr.Tab('🎤 Speaking'):
            audio=gr.Audio(sources=['microphone'],type='filepath',label='🎙 Record your voice'); check_btn=gr.Button('🎯 Analyze pronunciation',variant='primary'); speaking_out=gr.Markdown(); recognized=gr.Textbox(label='Speech recognition',interactive=False)
        with gr.Tab('📊 Progress'):
            progress=gr.Markdown(stats()+"  ·  "+learning_stats()); refresh=gr.Button('🔄 Refresh')
        load_btn.click(load_library,playlist_url,[video_choice,library_state,library_status,dashboard]).then(lambda:stats()+"  ·  "+learning_stats(),outputs=progress)
        video_choice.change(load_lesson,[video_choice,library_state],[video_html,sentence_state,transcript_status,video_title]).then(lambda s:cards(s,True),sentence_state,transcript_html)
        show.change(lambda s,v,f:cards(s,v,None if not f else 0),[sentence_state,show,focus],transcript_html); focus.change(lambda s,v,f:cards(s,v,None if not f else 0),[sentence_state,show,focus],transcript_html)
        sentence_index.change(select_sentence,[sentence_index,sentence_state],[sentence_text,sentence_info,sentence_time,sentence_index]); prev_btn.click(lambda i,s:max(0,int(i or 0)-1),[sentence_index,sentence_state],sentence_index); next_btn.click(lambda i,s:min(len(s)-1,int(i or 0)+1) if s else 0,[sentence_index,sentence_state],sentence_index); translate_btn.click(translate,sentence_text,translate_out)
        teacher_btn.click(teacher_markdown_and_save,[sentence_text,sentence_index],[teacher_out,learning_summary,saved_out,quiz_state]).then(quiz_view,quiz_state,[quiz_question,quiz_options,quiz_answer])
        quiz_btn.click(check_quiz,[quiz_options,quiz_answer,quiz_state,sentence_index],quiz_out)
        refresh_vocab_btn.click(refresh_vocab,outputs=[vocab_cards,vocab_choice,learning_summary]); vocab_choice.change(parse_vocab_id,vocab_choice,gr.State())
        review_btn.click(lambda c,q:review_selected(parse_vocab_id(c),q),[vocab_choice,quality],review_out).then(lambda:learning_stats(),outputs=learning_summary)
        check_btn.click(check_speaking,[sentence_text,audio,sentence_index],[speaking_out,recognized]).then(lambda:stats()+"  ·  "+learning_stats(),outputs=dashboard).then(lambda:stats()+"  ·  "+learning_stats(),outputs=progress)
        refresh.click(lambda:stats()+"  ·  "+learning_stats(),outputs=progress)
    ui.launch(server_name='0.0.0.0',server_port=int(os.getenv('PORT','7860')))

if __name__=='__main__': main()
