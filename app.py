import os
import re
import sqlite3
import difflib
import html
from pathlib import Path
from typing import Any

import gradio as gr
import yt_dlp

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except Exception:
    YouTubeTranscriptApi = None

try:
    from faster_whisper import WhisperModel
except Exception:
    WhisperModel = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

APP_NAME = "English Learning Lab"
DEFAULT_PLAYLIST = "https://youtube.com/playlist?list=PLRDC-DZ_uWhpbeuja5CFDhkVVKElpRje7&si=pnXRrHKug8I319jg"
DB_PATH = Path(os.getenv("ENGLISH_DB", "english_lab.db"))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
AI_KEY = os.getenv("AI_API_KEY", "")
AI_BASE = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")

_whisper = None


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                thumbnail TEXT,
                duration INTEGER DEFAULT 0,
                status TEXT DEFAULT 'new',
                last_sentence INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sentences (
                video_id TEXT NOT NULL,
                sentence_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                start REAL NOT NULL,
                end_time REAL NOT NULL,
                PRIMARY KEY(video_id, sentence_index)
            );
            CREATE TABLE IF NOT EXISTS practice (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT,
                sentence_index INTEGER,
                score REAL,
                recognized TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS vocabulary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT,
                word TEXT,
                meaning TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(video_id, word)
            );
            """
        )


init_db()


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\n", " ")).strip()


def video_id(url: str):
    if not url:
        return None
    for p in [r"[?&]v=([\w-]{11})", r"youtu\.be/([\w-]{11})", r"shorts/([\w-]{11})"]:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def stamp(seconds: float) -> str:
    n = max(0, int(seconds))
    return f"{n//60:02d}:{n%60:02d}"


def playlist(url: str):
    opts = {"quiet": True, "extract_flat": True, "skip_download": True, "ignoreerrors": True}
    out = []
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
        for e in (info or {}).get("entries", [])[:150]:
            if not e or not e.get("id"):
                continue
            vid = e["id"]
            item = {
                "id": vid,
                "title": e.get("title") or vid,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                "duration": e.get("duration") or 0,
            }
            out.append(item)
            with db() as c:
                c.execute(
                    """INSERT INTO videos(video_id,title,url,thumbnail,duration)
                       VALUES(?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET title=excluded.title,url=excluded.url,thumbnail=excluded.thumbnail,duration=excluded.duration,updated_at=CURRENT_TIMESTAMP""",
                    (vid, item["title"], item["url"], item["thumbnail"], item["duration"]),
                )
        return out, f"✅ {len(out)} video được tải vào thư viện."
    except Exception as e:
        return [], f"❌ Playlist error: {e}"


def transcript_for(vid: str):
    if not vid or YouTubeTranscriptApi is None:
        return [], "Transcript engine chưa sẵn sàng."
    try:
        api = YouTubeTranscriptApi()
        raw = None
        for langs in (["en", "en-US", "en-GB"],):
            try:
                raw = api.fetch(vid, languages=langs)
                break
            except Exception:
                pass
        if raw is None:
            try:
                for t in api.list(vid):
                    if str(getattr(t, "language_code", "")).startswith("en"):
                        raw = t.fetch()
                        break
            except Exception:
                pass
        if raw is None:
            return [], "❌ Video không có English transcript khả dụng."
        pieces = []
        for x in raw:
            text = clean(getattr(x, "text", ""))
            if not text:
                continue
            start = float(getattr(x, "start", 0))
            dur = float(getattr(x, "duration", 0))
            pieces.append((text, start, start + dur))
        result, buf, start, end = [], [], None, None
        for text, s, e in pieces:
            start = s if start is None else start
            end = e
            buf.append(text)
            joined = clean(" ".join(buf))
            if re.search(r"[.!?…]$", joined) or len(joined) >= 180:
                result.append({"index": len(result), "text": joined, "start": start, "end": end})
                buf, start, end = [], None, None
        if buf:
            result.append({"index": len(result), "text": clean(" ".join(buf)), "start": start or 0, "end": end or 0})
        with db() as c:
            c.execute("DELETE FROM sentences WHERE video_id=?", (vid,))
            c.executemany(
                "INSERT INTO sentences(video_id,sentence_index,text,start,end_time) VALUES(?,?,?,?,?)",
                [(vid, s["index"], s["text"], s["start"], s["end"]) for s in result],
            )
            c.execute("UPDATE videos SET status='in-progress', updated_at=CURRENT_TIMESTAMP WHERE video_id=?", (vid,))
        return result, f"✅ {len(result)} câu transcript."
    except Exception as e:
        return [], f"❌ Transcript error: {e}"


def cards(sentences, visible=True, focus=None):
    if not sentences:
        return '<div class="empty">Chưa có transcript.</div>'
    if not visible:
        return '<div class="hidden">🔒 Transcript đang ẩn<br><small>Hãy nghe và tự nhớ câu.</small></div>'
    rows = sentences if focus is None else [sentences[focus]] if 0 <= focus < len(sentences) else []
    parts = ['<div class="transcript">']
    for s in rows:
        parts.append(
            f'<button class="sentence" onclick="englishLabSelect({s["index"]})">'
            f'<span class="num">{s["index"]+1}</span>'
            f'<span><small>{stamp(s["start"])}</small><br>{html.escape(s["text"])}</span></button>'
        )
    parts.append('</div>')
    return ''.join(parts)


def select_sentence(idx, sentences):
    if not sentences:
        return "", "", "", 0
    i = max(0, min(int(idx or 0), len(sentences) - 1))
    s = sentences[i]
    with db() as c:
        c.execute("UPDATE videos SET last_sentence=?, updated_at=CURRENT_TIMESTAMP WHERE video_id=?", (i, CURRENT_VIDEO.get("id") if CURRENT_VIDEO else ""))
    return s["text"], f"Câu {i+1} / {len(sentences)}", stamp(s["start"]), i


CURRENT_VIDEO = None


def load_library(url):
    global CURRENT_VIDEO
    items, status = playlist(url)
    choices = [f"{i+1:03d} | {x['title']}" for i, x in enumerate(items)]
    return gr.update(choices=choices, value=choices[0] if choices else None), items, status


def load_lesson(choice, items):
    global CURRENT_VIDEO
    if not choice or not items:
        return "", [], "❌ Chưa chọn video.", "", ""
    i = int(choice.split("|")[0]) - 1
    CURRENT_VIDEO = items[i]
    sentences, status = transcript_for(CURRENT_VIDEO["id"])
    embed = f'''<div class="player"><iframe id="ytplayer" src="https://www.youtube.com/embed/{CURRENT_VIDEO['id']}?enablejsapi=1&rel=0" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div>'''
    return embed, sentences, status, CURRENT_VIDEO["title"], CURRENT_VIDEO["url"]


def ai(prompt):
    if not AI_KEY or OpenAI is None:
        return "⚠️ Chưa cấu hình AI_API_KEY trong Hugging Face Secrets."
    try:
        client = OpenAI(api_key=AI_KEY, base_url=AI_BASE)
        r = client.chat.completions.create(model=AI_MODEL, temperature=0.2, messages=[
            {"role": "system", "content": "Bạn là giáo viên tiếng Anh chuyên dạy người Việt. Trả lời rõ ràng, thực hành được."},
            {"role": "user", "content": prompt},
        ])
        return r.choices[0].message.content
    except Exception as e:
        return f"❌ AI error: {e}"


def explain(sentence):
    return ai(f'''Phân tích câu tiếng Anh này cho người Việt: "{sentence}".\n\nCho: nghĩa tự nhiên; cấu trúc; chủ ngữ/động từ; thì; từ vựng; collocation/phrasal verb; điểm phát âm; mẫu câu tương tự; một mini quiz.''')


def translate(sentence):
    return ai(f'Dịch câu sau sang tiếng Việt tự nhiên, sau đó giải thích 2 từ/cụm từ quan trọng: {sentence}')


def get_whisper():
    global _whisper
    if WhisperModel is None:
        return None
    if _whisper is None:
        _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper


def words(s):
    return re.findall(r"[a-z]+(?:'[a-z]+)?", (s or "").lower())


def check_speaking(target, audio, idx, items):
    if not target:
        return "❌ Chưa chọn câu.", ""
    if not audio:
        return "❌ Hãy ghi âm trước.", ""
    model = get_whisper()
    if model is None:
        return "❌ faster-whisper chưa cài đặt.", ""
    try:
        segs, _ = model.transcribe(audio, language="en", beam_size=5)
        spoken = clean(" ".join(s.text for s in segs))
        score = round(difflib.SequenceMatcher(None, words(target), words(spoken)).ratio() * 100)
        label = "🟢 Excellent" if score >= 90 else "🟡 Good" if score >= 75 else "🟠 Practice more" if score >= 60 else "🔴 Repeat"
        with db() as c:
            vid = CURRENT_VIDEO["id"] if CURRENT_VIDEO else None
            c.execute("INSERT INTO practice(video_id,sentence_index,score,recognized) VALUES(?,?,?,?)", (vid, idx, score, spoken))
        return f'''### 🎤 Speaking result\n**Score: {score}/100 — {label}**\n\n**Target:** {target}\n\n**You said:** {spoken}\n\n**Next:** nghe mẫu 2 lần → shadowing → đọc lại.\n\n> Lưu ý: điểm hiện tại là điểm tương đồng nhận dạng lời nói, chưa phải đánh giá âm vị chuyên sâu.''', spoken
    except Exception as e:
        return f"❌ Speech error: {e}", ""


def stats():
    with db() as c:
        videos = c.execute("SELECT COUNT(*) n FROM videos").fetchone()["n"]
        done = c.execute("SELECT COUNT(*) n FROM videos WHERE status='done'").fetchone()["n"]
        sentences = c.execute("SELECT COUNT(*) n FROM sentences").fetchone()["n"]
        sessions = c.execute("SELECT COUNT(*) n FROM practice").fetchone()["n"]
        avg = c.execute("SELECT COALESCE(AVG(score),0) n FROM practice").fetchone()["n"]
    return f"**{videos}** videos  ·  **{sentences}** sentences  ·  **{sessions}** practice sessions  ·  **{avg:.0f}** avg speaking score"


CSS = '''
:root { --radius: 16px; }
.gradio-container { max-width: 1200px !important; }
.hero { padding: 24px; border-radius: 20px; background: linear-gradient(135deg,#111827,#334155); color: white; margin-bottom: 16px; }
.hero h1 { margin: 0 0 6px; font-size: 32px; }
.hero p { margin: 0; opacity: .82; }
.player { position: relative; padding-top: 56.25%; overflow: hidden; border-radius: 18px; background: #000; }
.player iframe { position:absolute; inset:0; width:100%; height:100%; border:0; }
.transcript { max-height: 510px; overflow:auto; padding: 4px; }
.sentence { width:100%; display:flex; gap:12px; text-align:left; border:1px solid #e5e7eb; border-radius:14px; padding:12px; margin:7px 0; background:transparent; cursor:pointer; }
.sentence:hover { border-color:#94a3b8; transform:translateY(-1px); }
.num { min-width:30px; font-weight:700; }
.sentence small { opacity:.55; }
.hidden,.empty { padding:42px 18px; text-align:center; border:1px dashed #94a3b8; border-radius:16px; }
.metric { padding:14px; border-radius:14px; background:rgba(148,163,184,.12); }
'''

JS = '''
function englishLabSelect(i) {
  const el = document.querySelector('#sentence_index input');
  if (!el) return;
  el.value = i;
  el.dispatchEvent(new Event('input',{bubbles:true}));
  el.dispatchEvent(new Event('change',{bubbles:true}));
}
'''

with gr.Blocks(title=APP_NAME, css=CSS, js=JS, theme=gr.themes.Soft()) as app:
    library_state = gr.State([])
    sentence_state = gr.State([])

    gr.HTML('''<div class="hero"><h1>🇬🇧 English Learning Lab</h1><p>Listen · Shadow · Speak · Grammar · Vocabulary · Progress</p></div>''')
    dashboard = gr.Markdown(stats())

    with gr.Tab("🎧 Listening"):
        with gr.Row():
            playlist_url = gr.Textbox(label="YouTube Playlist", value=DEFAULT_PLAYLIST, scale=8)
            load_btn = gr.Button("📥 Import", variant="primary", scale=2)
        library_status = gr.Markdown()
        video_choice = gr.Dropdown(label="Video Library", choices=[])
        video_title = gr.Markdown()
        video_html = gr.HTML()
        video_url = gr.Textbox(visible=False)
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
            grammar_btn = gr.Button("📚 Grammar", variant="primary")
        translate_out = gr.Markdown()
        grammar_out = gr.Markdown()

    with gr.Tab("🎤 Speaking"):
        gr.Markdown("### Shadowing\nNghe câu → ẩn transcript → đọc → ghi âm → kiểm tra.")
        audio = gr.Audio(sources=["microphone"], type="filepath", label="Record your voice")
        check_btn = gr.Button("🎯 Check pronunciation", variant="primary")
        speaking_out = gr.Markdown()
        recognized = gr.Textbox(label="Speech recognition", interactive=False)

    with gr.Tab("📊 Progress"):
        progress = gr.Markdown(stats())
        refresh = gr.Button("🔄 Refresh")
        gr.Markdown("### Learning roadmap\n**V2.1** Listening engine → **V2.2** speaking → **V2.3** AI teacher → **V2.4** vocabulary/quiz → **V2.5** PWA/mobile optimization.")

    load_btn.click(load_library, playlist_url, [video_choice, library_state, library_status]).then(lambda: stats(), outputs=dashboard).then(lambda: stats(), outputs=progress)
    video_choice.change(load_lesson, [video_choice, library_state], [video_html, sentence_state, transcript_status, video_title, video_url]).then(lambda s: cards(s, True), sentence_state, transcript_html)
    show.change(lambda s,v,f: cards(s,v, None if not f else 0), [sentence_state, show, focus], transcript_html)
    focus.change(lambda s,v,f: cards(s,v, None if not f else 0), [sentence_state, show, focus], transcript_html)
    sentence_index.change(select_sentence, [sentence_index, sentence_state], [sentence_text, sentence_info, sentence_time, sentence_index])
    prev_btn.click(lambda i,s: max(0, int(i or 0)-1), [sentence_index,sentence_state], sentence_index)
    next_btn.click(lambda i,s: min(len(s)-1, int(i or 0)+1) if s else 0, [sentence_index,sentence_state], sentence_index)
    translate_btn.click(translate, sentence_text, translate_out)
    grammar_btn.click(explain, sentence_text, grammar_out)
    check_btn.click(check_speaking, [sentence_text,audio,sentence_index,library_state], [speaking_out,recognized]).then(lambda: stats(), outputs=dashboard).then(lambda: stats(), outputs=progress)
    refresh.click(stats, outputs=progress)

if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
