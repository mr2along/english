"""English Learning Lab V2.3 entrypoint.

Keeps the V2.2 app.py stable while exposing the new AI Teacher tab.
Run with: python app_v23.py
"""
import os
import gradio as gr

from app import (
    APP_NAME, DEFAULT_PLAYLIST, cards, load_library, load_lesson,
    select_sentence, translate, check_speaking, stats,
)
from ai.teacher import AITeacher


def teacher_markdown(sentence):
    return AITeacher().analyze(sentence).markdown()


def main():
    library_state = gr.State([])
    sentence_state = gr.State([])

    css = """
    .gradio-container{max-width:1200px!important}
    .hero{padding:24px;border-radius:20px;margin-bottom:16px}
    .player{position:relative;padding-top:56.25%;overflow:hidden;border-radius:18px;background:#000}
    .player iframe{position:absolute;inset:0;width:100%;height:100%;border:0}
    .sentence{width:100%;display:flex;gap:12px;text-align:left;border:1px solid #ddd;border-radius:14px;padding:12px;margin:7px 0;background:transparent}
    .transcript{max-height:510px;overflow:auto}
    .hidden,.empty{padding:42px;text-align:center;border:1px dashed #999;border-radius:16px}
    """
    js = """function englishLabSelect(i){const el=document.querySelector('#sentence_index input');if(!el)return;el.value=i;el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}"""

    with gr.Blocks(title=f"{APP_NAME} V2.3", css=css, js=js, theme=gr.themes.Soft()) as ui:
        gr.HTML('<div class="hero"><h1>🇬🇧 English Learning Lab V2.3</h1><p>Listen · Shadow · AI Teacher · Progress</p></div>')
        dashboard = gr.Markdown(stats())

        with gr.Tab("🎧 Lesson"):
            with gr.Row():
                playlist_url = gr.Textbox(label="YouTube Playlist", value=DEFAULT_PLAYLIST, scale=8)
                load_btn = gr.Button("📥 Import", variant="primary", scale=2)
            library_status = gr.Markdown()
            video_choice = gr.Dropdown(label="Video Library", choices=[])
            video_title = gr.Markdown()
            video_html = gr.HTML()
            transcript_status = gr.Markdown()
            with gr.Row():
                show = gr.Checkbox(label="👁 Show transcript", value=True)
                focus = gr.Checkbox(label="🎯 Focus current sentence", value=False)
            transcript_html = gr.HTML()
            sentence_index = gr.Number(value=0, visible=False, elem_id="sentence_index")
            with gr.Row():
                sentence_text = gr.Textbox(label="Current sentence", lines=3, interactive=False, scale=7)
                sentence_info = gr.Markdown(scale=2)
            sentence_time = gr.Textbox(label="Timestamp", interactive=False)
            with gr.Row():
                prev_btn = gr.Button("◀ Previous")
                next_btn = gr.Button("Next ▶")
                translate_btn = gr.Button("🇻🇳 Translate")
            translate_out = gr.Markdown()

        with gr.Tab("🤖 AI Teacher"):
            gr.Markdown("### Phân tích câu đang học bằng AI\nGrammar · Vocabulary · Collocations · Pattern · Pronunciation · Examples · Quiz")
            teacher_btn = gr.Button("🧑‍🏫 Analyze this sentence", variant="primary")
            teacher_out = gr.Markdown()

        with gr.Tab("🎤 Speaking"):
            audio = gr.Audio(sources=["microphone"], type="filepath", label="🎙 Record your voice")
            check_btn = gr.Button("🎯 Analyze pronunciation", variant="primary")
            speaking_out = gr.Markdown()
            recognized = gr.Textbox(label="Speech recognition", interactive=False)

        with gr.Tab("📊 Progress"):
            progress = gr.Markdown(stats())
            refresh = gr.Button("🔄 Refresh")

        load_btn.click(load_library, playlist_url, [video_choice, library_state, library_status, dashboard]).then(lambda: stats(), outputs=progress)
        video_choice.change(load_lesson, [video_choice, library_state], [video_html, sentence_state, transcript_status, video_title]).then(lambda s: cards(s, True), sentence_state, transcript_html)
        show.change(lambda s,v,f: cards(s,v,None if not f else 0), [sentence_state,show,focus], transcript_html)
        focus.change(lambda s,v,f: cards(s,v,None if not f else 0), [sentence_state,show,focus], transcript_html)
        sentence_index.change(select_sentence, [sentence_index,sentence_state], [sentence_text,sentence_info,sentence_time,sentence_index])
        prev_btn.click(lambda i,s:max(0,int(i or 0)-1), [sentence_index,sentence_state], sentence_index)
        next_btn.click(lambda i,s:min(len(s)-1,int(i or 0)+1) if s else 0, [sentence_index,sentence_state], sentence_index)
        translate_btn.click(translate, sentence_text, translate_out)
        teacher_btn.click(teacher_markdown, sentence_text, teacher_out)
        check_btn.click(check_speaking, [sentence_text,audio,sentence_index], [speaking_out,recognized]).then(lambda:stats(), outputs=dashboard).then(lambda:stats(), outputs=progress)
        refresh.click(stats, outputs=progress)

    ui.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))


if __name__ == "__main__":
    main()
