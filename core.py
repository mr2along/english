"""English Learning Lab shared core: YouTube, transcript and speaking services.
AI is local only; hardware selection is automatic.
"""
from __future__ import annotations
import os, re, sqlite3, html
from pathlib import Path
import gradio as gr
import yt_dlp
try:
    from youtube_transcript_api import YouTubeTranscriptApi
except Exception: YouTubeTranscriptApi = None
try:
    from faster_whisper import WhisperModel
except Exception: WhisperModel = None
try:
    import torch
except Exception: torch = None
from speech.scoring import SpokenWord, score_speech
from ai.teacher import AITeacher, hardware_info

APP_NAME = "English Learning Lab"
DEFAULT_PLAYLIST = "https://youtube.com/playlist?list=PLRDC-DZ_uWhpbeuja5CFDhkVVKElpRje7&si=pnXRrHKug8I319jg"
DB_PATH = Path(os.getenv("ENGLISH_DB", "english_lab.db"))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
_whisper = None
_current_video = None


def db():
    conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row; conn.execute("PRAGMA journal_mode=WAL"); return conn

def init_db():
    with db() as c:
        c.executescript("""CREATE TABLE IF NOT EXISTS videos(video_id TEXT PRIMARY KEY,title TEXT NOT NULL,url TEXT NOT NULL,thumbnail TEXT,duration INTEGER DEFAULT 0,status TEXT DEFAULT 'new',last_sentence INTEGER DEFAULT 0,updated_at TEXT DEFAULT CURRENT_TIMESTAMP); CREATE TABLE IF NOT EXISTS sentences(video_id TEXT NOT NULL,sentence_index INTEGER NOT NULL,text TEXT NOT NULL,start REAL NOT NULL,end_time REAL NOT NULL,PRIMARY KEY(video_id,sentence_index)); CREATE TABLE IF NOT EXISTS practice(id INTEGER PRIMARY KEY AUTOINCREMENT,video_id TEXT,sentence_index INTEGER,score REAL,similarity REAL,completeness REAL,fluency REAL,wpm REAL,recognized TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);""")
init_db()

def clean(text): return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()
def stamp(seconds): n=max(0,int(seconds or 0)); return f"{n//60:02d}:{n%60:02d}"

def runtime_status():
    info=hardware_info(); return f"**Hardware:** `{info['mode']}` · **GPU:** {info['gpu']} · **VRAM:** {info['vram_gb']} GB · **RAM:** {info['ram_gb']} GB · **AI:** `{info.get('model','auto')}` · **Whisper:** `{WHISPER_MODEL}`"

def playlist(url):
    try:
        opts={"quiet":True,"extract_flat":True,"skip_download":True,"ignoreerrors":True}; out=[]
        with yt_dlp.YoutubeDL(opts) as y: info=y.extract_info(url,download=False)
        for e in (info or {}).get("entries",[])[:150]:
            if not e or not e.get("id"): continue
            vid=e["id"]; item={"id":vid,"title":e.get("title") or vid,"url":f"https://www.youtube.com/watch?v={vid}","thumbnail":f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg","duration":e.get("duration") or 0}; out.append(item)
            with db() as c: c.execute("INSERT INTO videos(video_id,title,url,thumbnail,duration) VALUES(?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET title=excluded.title,url=excluded.url,thumbnail=excluded.thumbnail,duration=excluded.duration,updated_at=CURRENT_TIMESTAMP",(vid,item["title"],item["url"],item["thumbnail"],item["duration"]))
        return out,f"✅ {len(out)} video được đưa vào thư viện."
    except Exception as e: return [],f"❌ Playlist error: {e}"

def transcript_for(vid):
    if not vid or YouTubeTranscriptApi is None:return [],"❌ Transcript engine chưa sẵn sàng."
    try:
        api=YouTubeTranscriptApi(); raw=None
        try: raw=api.fetch(vid,languages=["en","en-US","en-GB"])
        except Exception:
            try:
                for t in api.list(vid):
                    if str(getattr(t,"language_code","")).startswith("en"): raw=t.fetch(); break
            except Exception: pass
        if raw is None:return [],"❌ Video không có English transcript khả dụng."
        pieces=[]
        for x in raw:
            text=clean(getattr(x,"text",""));
            if text:
                s=float(getattr(x,"start",0)); pieces.append((text,s,s+float(getattr(x,"duration",0))))
        result=[]; buf=[]; start=end=None
        for text,s,e in pieces:
            start=s if start is None else start; end=e; buf.append(text); joined=clean(" ".join(buf))
            if re.search(r"[.!?…]$",joined) or len(joined)>=180:
                result.append({"index":len(result),"text":joined,"start":start,"end":end}); buf=[]; start=end=None
        if buf: result.append({"index":len(result),"text":clean(" ".join(buf)),"start":start or 0,"end":end or 0})
        with db() as c:
            c.execute("DELETE FROM sentences WHERE video_id=?",(vid,)); c.executemany("INSERT INTO sentences(video_id,sentence_index,text,start,end_time) VALUES(?,?,?,?,?)",[(vid,x["index"],x["text"],x["start"],x["end"]) for x in result]); c.execute("UPDATE videos SET status='in-progress',updated_at=CURRENT_TIMESTAMP WHERE video_id=?",(vid,))
        return result,f"✅ {len(result)} câu transcript."
    except Exception as e:return [],f"❌ Transcript error: {e}"

def load_library(url):
    items,status=playlist(url); choices=[f"{i+1:03d} | {x['title']}" for i,x in enumerate(items)]; return gr.update(choices=choices,value=choices[0] if choices else None),items,status,stats()

def load_lesson(choice,items):
    global _current_video
    if not choice or not items:return "",[],"❌ Chưa chọn video.",""
    i=int(choice.split("|")[0])-1; _current_video=items[i]; sentences,status=transcript_for(_current_video["id"]); embed=f'<div class="player"><iframe src="https://www.youtube.com/embed/{_current_video["id"]}?enablejsapi=1&rel=0" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div>'; return embed,sentences,status,f"### {_current_video['title']}"

def select_sentence(idx,sentences):
    if not sentences:return "","","",0
    i=max(0,min(int(idx or 0),len(sentences)-1)); s=sentences[i]
    if _current_video:
        with db() as c:c.execute("UPDATE videos SET last_sentence=?,updated_at=CURRENT_TIMESTAMP WHERE video_id=?",(i,_current_video["id"]))
    return s["text"],f"**Câu {i+1} / {len(sentences)}**",stamp(s["start"]),i

def translate(sentence):
    if not sentence:return "⚠️ Chưa có câu."
    return f"### 🇻🇳 Nghĩa tự nhiên\n{AITeacher().analyze(sentence).translation or 'Chưa có.'}"

def explain(sentence):
    if not sentence:return "⚠️ Chưa có câu."
    return AITeacher().analyze(sentence).markdown()

def _whisper_config():
    gpu=bool(torch is not None and torch.cuda.is_available())
    if gpu:return "cuda", "float16"
    # CPU Basic currently provides 2 vCPU / 16 GB RAM; int8 is the safest default.
    return "cpu", os.getenv("WHISPER_CPU_COMPUTE", "int8")

def get_whisper():
    global _whisper
    if WhisperModel is None:return None
    if _whisper is None:
        device,compute=_whisper_config()
        model_name=os.getenv("WHISPER_MODEL", "small" if device=="cuda" else "base")
        try:_whisper=WhisperModel(model_name,device=device,compute_type=compute)
        except Exception:
            _whisper=WhisperModel("tiny",device="cpu",compute_type="int8")
    return _whisper

def check_speaking(target,audio,idx):
    if not target:return "❌ Chưa chọn câu.",""
    if not audio:return "❌ Hãy ghi âm trước.",""
    model=get_whisper()
    if model is None:return "❌ faster-whisper chưa cài đặt.",""
    try:
        segments,_=model.transcribe(audio,language="en",beam_size=5,word_timestamps=True); segs=list(segments); spoken=clean(" ".join(s.text for s in segs)); words=[]
        for seg in segs:
            for w in (getattr(seg,"words",None) or []):words.append(SpokenWord(clean(w.word),float(w.start or 0),float(w.end or 0)))
        duration=(max(0,words[-1].end-words[0].start) if words else (max(0,float(segs[-1].end)-float(segs[0].start)) if segs else 0)); result=score_speech(target,spoken,words,duration)
        with db() as c:c.execute("INSERT INTO practice(video_id,sentence_index,score,similarity,completeness,fluency,wpm,recognized) VALUES(?,?,?,?,?,?,?,?)",(_current_video["id"] if _current_video else None,int(idx or 0),result["overall"],result["similarity"],result["completeness"],result["fluency"],result["wpm"],spoken))
        return f"### 🎤 Pronunciation / Shadowing\n\n**Overall: {result['overall']}/100**\n\n| Metric | Score |\n|---|---:|\n| Recognition similarity | {result['similarity']}/100 |\n| Completeness | {result['completeness']}/100 |\n| Fluency proxy | {result['fluency']}/100 |\n| Speaking speed | {result['wpm']} WPM |\n\n**Target:** {target}\n\n**You said:** {spoken}\n\n**Missing:** {', '.join(result['missing']) or 'Không phát hiện.'}\n\n**Review:** {', '.join(result['review']) or 'Không có.'}\n\n**Extra:** {', '.join(result['extra']) or 'Không có.'}",spoken
    except Exception as e:return f"❌ Speech error: {e}",""

def stats():
    with db() as c:
        v=c.execute("SELECT COUNT(*) n FROM videos").fetchone()["n"]; s=c.execute("SELECT COUNT(*) n FROM sentences").fetchone()["n"]; p=c.execute("SELECT COUNT(*) n FROM practice").fetchone()["n"]; a=c.execute("SELECT COALESCE(AVG(score),0) n FROM practice").fetchone()["n"]
    return f"**{v}** videos · **{s}** sentences · **{p}** practice sessions · **{a:.0f}** avg speaking score"
