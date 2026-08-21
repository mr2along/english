"""English Learning Lab V2.5 - guided mobile learning session.

Flow: Listen -> Recall -> Reveal -> Shadow -> AI Teacher -> Quiz -> Next.
Reuses the V2.4 persistence and local Qwen3-4B teacher without external AI APIs.
"""
import os
import gradio as gr

from app import (
    APP_NAME, DEFAULT_PLAYLIST, cards, load_library, load_lesson,
    select_sentence, translate, check_speaking, stats,
)
from ai.teacher import AITeacher
from learning.progress import save_teacher_result, learning_stats, save_quiz


def analyze_teacher(sentence, idx):
    if not sentence:
        return "⚠️ Chưa có câu để phân tích.", {}, learning_stats()
    result = AITeacher().analyze(sentence)
    save_teacher_result(None, int(idx or 0), result)
    return result.markdown(), result.quiz or {}, learning_stats()


def quiz_options(q):
    if not q or not q.get("question"):
        return "Chưa có quiz. Hãy chạy AI Teacher.", gr.update(choices=[]), ""
    options = q.get("options") or []
    return f"### 📝 {q['question']}", gr.update(choices=[f"{chr(65+i)}. {x}" for i, x in enumerate(options[:4])]), q.get("answer", "A")


def grade_quiz(choice, answer, q):
    if not choice or not answer or not q:
        return "⚠️ Chọn một đáp án."
    letter = choice.split(".", 1)[0].strip().upper()
    ok = letter == answer.strip().upper()
    return ("## ✅ Correct!" if ok else f"## ❌ Chưa đúng — đáp án **{answer}**") + f"\n\n{q.get('explanation', '')}"


def next_index(idx, sentences):
    if not sentences:
        return 0
    return min(len(sentences) - 1, int(idx or 0) + 1)


def prev_index(idx, sentences):
    if not sentences:
        return 0
    return max(0, int(idx or 0) - 1)


def session_status(idx, sentences):
    if not sentences:
        return "Chưa có bài học."
    i = max(0, min(int(idx or 0), len(sentences)-1))
    return f"### Câu {i+1} / {len(sentences)}  ·  {round((i+1)/len(sentences)*100)}%"


CSS = """
.gradio-container{max-width:1180px!important}
.hero{padding:22px;border-radius:22px;margin-bottom:14px;background:linear-gradient(135deg,#0f172a,#334155);color:white}
.hero h1{margin:0;font-size:30px}.hero p{margin:5px 0 0;opacity:.82}
.step{border:1px solid #e2e8f0;border-radius:18px;padding:18px;margin:8px 0}
.sentence-main{font-size:26px;line-height:1.45;font-weight:600;padding:22px;border-radius:18px;border:1px solid #cbd5e1;min-height:100px}
.progressbar{height:8px;border-radius:8px;background:#e2e8f0}
@media(max-width:700px){.gradio-container{padding:8px!important}.hero h1{font-size:24px}.sentence-main{font-size:21px}.step{padding:12px}}
"""

JS = """
function setSentence(i){const el=document.querySelector('#sentence_index input');if(!el)return;el.value=i;el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));window.scrollTo({top:0,behavior:'smooth'});}
"""


def main():
    with gr.Blocks(title=f"{APP_NAME} V2.5", css=CSS, js=JS, theme=gr.themes.Soft()) as ui:
        library = gr.State([])
        sentences = gr.State([])
        quiz_state = gr.State({})
        gr.HTML('<div class="hero"><h1>🇬🇧 English Learning Lab</h1><p>Guided Learning Session · Listening → Shadowing → AI Teacher → Quiz</p></div>')
        dashboard = gr.Markdown(stats() + "  ·  " + learning_stats())

        with gr.Tab("📚 Library"):
            with gr.Row():
                playlist = gr.Textbox(label="YouTube Playlist", value=DEFAULT_PLAYLIST, scale=8)
                import_btn = gr.Button("📥 Import", variant="primary", scale=2)
            status = gr.Markdown()
            video = gr.Dropdown(label="Chọn video", choices=[])
            title = gr.Markdown()
            player = gr.HTML()
            transcript_status = gr.Markdown()
            import_btn.click(load_library, playlist, [video, library, status, dashboard])
            video.change(load_lesson, [video, library], [player, sentences, transcript_status, title])

        with gr.Tab("🎯 Learning Session"):
            gr.Markdown("## 6 bước luyện một câu")
            session_progress = gr.Markdown("Chưa có bài học.")
            sentence_index = gr.Number(value=0, visible=False, elem_id="sentence_index")
            current_sentence = gr.Markdown("<div class='sentence-main'>Chọn video để bắt đầu.</div>")
            timestamp = gr.Markdown()

            with gr.Row():
                prev_btn = gr.Button("◀ Câu trước")
                listen_btn = gr.Button("🔊 Nghe câu")
                next_btn = gr.Button("Câu tiếp ▶", variant="primary")

            with gr.Group(elem_classes="step"):
                gr.Markdown("### 1️⃣ Listen — Nghe trước")
                gr.Markdown("Nghe câu trong video và cố gắng hiểu mà không nhìn transcript.")
                hide_transcript = gr.Checkbox(label="🔒 Tôi muốn ẩn transcript", value=True)
                reveal = gr.Button("👁 Hiện câu")
                transcript_reveal = gr.Markdown("Transcript đang ẩn.")

            with gr.Group(elem_classes="step"):
                gr.Markdown("### 2️⃣ Translate & Grammar")
                translate_btn = gr.Button("🇻🇳 Dịch câu")
                translation = gr.Markdown()

            with gr.Group(elem_classes="step"):
                gr.Markdown("### 3️⃣ Shadowing — Đọc theo")
                audio = gr.Audio(sources=["microphone"], type="filepath", label="🎙 Đọc câu")
                speak_btn = gr.Button("🎯 Chấm phát âm", variant="primary")
                speaking = gr.Markdown()
                recognized = gr.Textbox(label="AI nhận được", interactive=False)

            with gr.Group(elem_classes="step"):
                gr.Markdown("### 4️⃣ AI Teacher")
                teacher_btn = gr.Button("🧑‍🏫 Phân tích câu", variant="primary")
                teacher = gr.Markdown()
                teacher_progress = gr.Markdown()

            with gr.Group(elem_classes="step"):
                gr.Markdown("### 5️⃣ Quick Quiz")
                quiz_question = gr.Markdown("Quiz sẽ xuất hiện sau AI Teacher.")
                quiz_choice = gr.Radio(label="Chọn đáp án", choices=[])
                quiz_answer = gr.State("")
                quiz_btn = gr.Button("✅ Kiểm tra")
                quiz_result = gr.Markdown()

            with gr.Row():
                complete = gr.Button("☑️ Hoàn thành câu & sang câu tiếp", variant="primary")
                restart = gr.Button("↺ Về đầu bài")

        with gr.Tab("📊 Progress"):
            progress = gr.Markdown(stats() + "  ·  " + learning_stats())
            refresh = gr.Button("🔄 Refresh")

        def current(i, ss):
            text, info, stamp, idx = select_sentence(i, ss)
            return f"<div class='sentence-main'>{text or 'Chưa có câu.'}</div>", f"⏱️ {stamp}", session_status(idx, ss), idx

        def reveal_sentence(show, text):
            return text if show else "🔒 Transcript đang ẩn. Hãy nghe và tự nhớ câu trước."

        sentence_index.change(current, [sentence_index, sentences], [current_sentence, timestamp, session_progress, sentence_index])
        next_btn.click(next_index, [sentence_index, sentences], sentence_index)
        prev_btn.click(prev_index, [sentence_index, sentences], sentence_index)
        restart.click(lambda: 0, outputs=sentence_index)
        reveal.click(lambda s, t: reveal_sentence(s, t), [hide_transcript, current_sentence], transcript_reveal)
        hide_transcript.change(lambda hidden: "🔒 Transcript đang ẩn." if hidden else "👁 Transcript đã bật.", hide_transcript, transcript_reveal)
        translate_btn.click(translate, current_sentence, translation)
        speak_btn.click(check_speaking, [current_sentence, audio, sentence_index], [speaking, recognized])
        teacher_btn.click(analyze_teacher, [current_sentence, sentence_index], [teacher, quiz_state, teacher_progress]).then(quiz_options, quiz_state, [quiz_question, quiz_choice, quiz_answer])
        quiz_btn.click(grade_quiz, [quiz_choice, quiz_answer, quiz_state], quiz_result)
        complete.click(next_index, [sentence_index, sentences], sentence_index).then(lambda: stats() + "  ·  " + learning_stats(), outputs=dashboard)
        refresh.click(lambda: stats() + "  ·  " + learning_stats(), outputs=progress)

    ui.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))


if __name__ == "__main__":
    main()
