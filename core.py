"""English Learning Lab shared core."""
from __future__ import annotations
import os,re,sqlite3,json,traceback
from pathlib import Path
from urllib.parse import urlparse,parse_qs
import requests
import gradio as gr
import yt_dlp
try:
 from youtube_transcript_api import YouTubeTranscriptApi
except Exception: YouTubeTranscriptApi=None
try:
 from faster_whisper import WhisperModel
except Exception: WhisperModel=None
try: import torch
except Exception: torch=None
from speech.scoring import SpokenWord,score_speech
from ai.teacher import AITeacher,hardware_info
APP_NAME="English Learning Lab"; DEFAULT_PLAYLIST="https://youtube.com/playlist?list=PLRDC-DZ_uWhpbeuja5CFDhkVVKElpRje7"; DB_PATH=Path(os.getenv("ENGLISH_DB","english_lab.db")); WHISPER_MODEL=os.getenv("WHISPER_MODEL","small"); _whisper=None; _current_video=None
# Public instances are only a fallback. Operators can supply their own rotating
# proxy/API nodes with INVIDIOUS_INSTANCES (comma-separated HTTPS base URLs).
DEFAULT_INVIDIOUS_INSTANCES=(
 "https://inv.nadeko.net",
 "https://invidious.nerdvpn.de",
 "https://yt.chocolatemoo53.com",
)

def db():
 c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; c.execute("PRAGMA journal_mode=WAL"); return c

def init_db():
 with db() as c:c.executescript("CREATE TABLE IF NOT EXISTS videos(video_id TEXT PRIMARY KEY,title TEXT NOT NULL,url TEXT NOT NULL,thumbnail TEXT,duration INTEGER DEFAULT 0,status TEXT DEFAULT 'new',last_sentence INTEGER DEFAULT 0,updated_at TEXT DEFAULT CURRENT_TIMESTAMP); CREATE TABLE IF NOT EXISTS sentences(video_id TEXT NOT NULL,sentence_index INTEGER NOT NULL,text TEXT NOT NULL,start REAL NOT NULL,end_time REAL NOT NULL,PRIMARY KEY(video_id,sentence_index)); CREATE TABLE IF NOT EXISTS practice(id INTEGER PRIMARY KEY AUTOINCREMENT,video_id TEXT,sentence_index INTEGER,score REAL,similarity REAL,completeness REAL,fluency REAL,wpm REAL,recognized TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);")
init_db()
def clean(x):return re.sub(r"\s+"," ",(x or "").replace("\n"," ")).strip()
def stamp(s):n=max(0,int(s or 0));return f"{n//60:02d}:{n%60:02d}"
def runtime_status():
 i=hardware_info();return f"**Hardware:** `{i['mode']}` · **GPU:** {i['gpu']} · **VRAM:** {i['vram_gb']} GB · **RAM:** {i['ram_gb']} GB · **AI:** `{i.get('model','auto')}` · **Whisper:** `{WHISPER_MODEL}`"
def _youtube_opts(impersonate=True):
 o={"quiet":True,"extract_flat":True,"skip_download":True,"ignoreerrors":False,"retries":5,"fragment_retries":5,"socket_timeout":30,"source_address":"0.0.0.0","http_headers":{"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36","Accept-Language":"en-US,en;q=0.9"},"noplaylist":False}
 if impersonate:o["impersonate"]="chrome"
 if os.getenv("YT_DLP_NO_CHECK_CERTIFICATE","0").lower() in {"1","true","yes"}:o["nocheckcertificate"]=True
 return o

def _playlist_id(url):
 try:return parse_qs(urlparse(url).query).get("list",[None])[0]
 except Exception:return None

def _proxy_instances():
 raw=os.getenv("INVIDIOUS_INSTANCES","").strip()
 values=[x.strip().rstrip("/") for x in raw.split(",") if x.strip()] if raw else list(DEFAULT_INVIDIOUS_INSTANCES)
 # Prefer a user-supplied/private proxy, then public fallback nodes.
 return list(dict.fromkeys(values))

def _proxy_playlist(url):
 plid=_playlist_id(url)
 if not plid:raise RuntimeError("Không tìm thấy playlist ID trong URL")
 errors=[]
 headers={"User-Agent":"EnglishLearningLab/2.7","Accept":"application/json"}
 for base in _proxy_instances():
  try:
   r=requests.get(f"{base}/api/v1/playlists/{plid}",params={"page":1},headers=headers,timeout=(8,20),allow_redirects=True)
   r.raise_for_status(); data=r.json()
   videos=data.get("videos") or []
   if not videos:raise RuntimeError("proxy trả về playlist nhưng không có video")
   return [{"id":str(v.get("videoId")),"title":v.get("title") or str(v.get("videoId")),"url":f"https://www.youtube.com/watch?v={v.get('videoId')}","thumbnail":((v.get("videoThumbnails") or [{}])[-1].get("url") or f"https://i.ytimg.com/vi/{v.get('videoId')}/hqdefault.jpg"),"duration":v.get("lengthSeconds") or 0} for v in videos if re.fullmatch(r"[A-Za-z0-9_-]{11}",str(v.get("videoId") or ""))]
  except Exception as e:errors.append(f"{base}: {type(e).__name__}: {e}")
 raise RuntimeError("Proxy playlist thất bại: " + " | ".join(errors))

def _extract_playlist(url):
 errors=[]
 # Direct YouTube remains the fastest path when the Space network allows it.
 for imp in (True,False):
  try:
   with yt_dlp.YoutubeDL(_youtube_opts(imp)) as y:return y.extract_info(url,download=False)
  except Exception as e:errors.append(f"{'curl_cffi' if imp else 'urllib'}: {type(e).__name__}: {e}")
 # The documented Invidious API provides /api/v1/playlists/:plid and is used
 # only after direct YouTube access fails. This changes the network node rather
 # than disabling TLS verification.
 try:return {"entries":_proxy_playlist(url),"_proxy":True}
 except Exception as e:errors.append(str(e))
 raise RuntimeError("; ".join(errors))

def playlist(url):
 try:
  info=_extract_playlist(url);out=[];entries=info.get("entries") or []
  for e in entries[:150]:
   if not e:continue
   vid=e.get("id") or e.get("url")
   if not vid:continue
   vid=str(vid).split("?")[0].split("&")[0]
   if not re.fullmatch(r"[A-Za-z0-9_-]{11}",vid):continue
   title=e.get("title") or vid;item={"id":vid,"title":title,"url":f"https://www.youtube.com/watch?v={vid}","thumbnail":e.get("thumbnail") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg","duration":e.get("duration") or 0};out.append(item)
   with db() as c:c.execute("INSERT INTO videos(video_id,title,url,thumbnail,duration) VALUES(?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET title=excluded.title,url=excluded.url,thumbnail=excluded.thumbnail,duration=excluded.duration,updated_at=CURRENT_TIMESTAMP",(vid,title,item["url"],item["thumbnail"],item["duration"]))
  if not out:return [],"❌ Playlist đã được kết nối nhưng không tìm thấy video ID hợp lệ."
  source="proxy fallback" if info.get("_proxy") else "YouTube"
  return out,f"✅ {len(out)} video được đưa vào thư viện · nguồn: {source}."
 except Exception as e:return [],f"❌ Playlist error: {type(e).__name__}: {e}"

def transcript_for(vid):
 if not vid or YouTubeTranscriptApi is None:return [],"❌ Transcript engine chưa sẵn sàng."
 try:
  api=YouTubeTranscriptApi();raw=None
  try:raw=api.fetch(vid,languages=["en","en-US","en-GB"])
  except Exception:
   try:
    for t in api.list(vid):
     if str(getattr(t,"language_code","")).startswith("en"):raw=t.fetch();break
   except Exception:pass
  if raw is None:return [],"❌ Video không có English transcript khả dụng."
  pieces=[]
  for x in raw:
   text=clean(getattr(x,"text",""))
   if text:
    s=float(getattr(x,"start",0));pieces.append((text,s,s+float(getattr(x,"duration",0))))
  result=[];buf=[];start=end=None
  for text,s,e in pieces:
   start=s if start is None else start;end=e;buf.append(text);j=clean(" ".join(buf))
   if re.search(r"[.!?…]$",j) or len(j)>=180:result.append({"index":len(result),"text":j,"start":start,"end":end});buf=[];start=end=None
  if buf:result.append({"index":len(result),"text":clean(" ".join(buf)),"start":start or 0,"end":end or 0})
  with db() as c:
   c.execute("DELETE FROM sentences WHERE video_id=?",(vid,));c.executemany("INSERT INTO sentences(video_id,sentence_index,text,start,end_time) VALUES(?,?,?,?,?)",[(vid,x["index"],x["text"],x["start"],x["end"]) for x in result]);c.execute("UPDATE videos SET status='in-progress',updated_at=CURRENT_TIMESTAMP WHERE video_id=?",(vid,))
  return result,f"✅ {len(result)} câu transcript."
 except Exception as e:return [],f"❌ Transcript error: {type(e).__name__}: {e}"
def load_library(url):
 items,status=playlist(url);choices=[f"{i+1:03d} | {x['title']}" for i,x in enumerate(items)];return gr.update(choices=choices,value=choices[0] if choices else None),items,status,stats()
def load_lesson(choice,items):
 global _current_video
 if not choice or not items:return "",[],"❌ Chưa chọn video.",""
 i=int(choice.split("|")[0])-1;_current_video=items[i];sentences,status=transcript_for(_current_video["id"]);embed=f'<div class="player"><iframe src="https://www.youtube.com/embed/{_current_video["id"]}?enablejsapi=1&rel=0" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div>';return embed,sentences,status,f"### {_current_video['title']}"
def select_sentence(idx,sentences):
 if not sentences:return "","","",0
 i=max(0,min(int(idx or 0),len(sentences)-1));s=sentences[i]
 if _current_video:
  with db() as c:c.execute("UPDATE videos SET last_sentence=?,updated_at=CURRENT_TIMESTAMP WHERE video_id=?",(i,_current_video["id"]))
 return s["text"],f"**Câu {i+1} / {len(sentences)}**",stamp(s["start"]),i
def translate(sentence):
 if not sentence:return "⚠️ Chưa có câu."
 return f"### 🇻🇳 Nghĩa tự nhiên\n{AITeacher().analyze(sentence).translation or 'Chưa có.'}"
def explain(sentence):return "⚠️ Chưa có câu." if not sentence else AITeacher().analyze(sentence).markdown()
def _whisper_config():return ("cuda","float16") if torch is not None and torch.cuda.is_available() else ("cpu",os.getenv("WHISPER_CPU_COMPUTE","int8"))
def get_whisper():
 global _whisper
 if WhisperModel is None:return None
 if _whisper is None:
  d,c=_whisper_config();m=os.getenv("WHISPER_MODEL","small" if d=="cuda" else "base")
  try:_whisper=WhisperModel(m,device=d,compute_type=c)
  except Exception:_whisper=WhisperModel("tiny",device="cpu",compute_type="int8")
 return _whisper
def check_speaking(target,audio,idx):
 if not target:return "❌ Chưa chọn câu.",""
 if not audio:return "❌ Hãy ghi âm trước.",""
 model=get_whisper()
 if model is None:return "❌ faster-whisper chưa cài đặt.",""
 try:
  segs=list(model.transcribe(audio,language="en",beam_size=5,word_timestamps=True)[0]);spoken=clean(" ".join(s.text for s in segs));words=[]
  for s in segs:
   for w in getattr(s,"words",None) or []:words.append(SpokenWord(clean(w.word),float(w.start or 0),float(w.end or 0)))
  dur=max(0,words[-1].end-words[0].start) if words else 0;r=score_speech(target,spoken,words,dur)
  with db() as c:c.execute("INSERT INTO practice(video_id,sentence_index,score,similarity,completeness,fluency,wpm,recognized) VALUES(?,?,?,?,?,?,?,?)",(_current_video["id"] if _current_video else None,int(idx or 0),r["overall"],r["similarity"],r["completeness"],r["fluency"],r["wpm"],spoken))
  return f"### 🎤 Pronunciation / Shadowing\n\n**Overall: {r['overall']}/100**\n\n| Metric | Score |\n|---|---:|\n| Recognition similarity | {r['similarity']}/100 |\n| Completeness | {r['completeness']}/100 |\n| Fluency proxy | {r['fluency']}/100 |\n| Speaking speed | {r['wpm']} WPM |\n\n**Target:** {target}\n\n**You said:** {spoken}\n\n**Missing:** {', '.join(r['missing']) or 'Không phát hiện.'}",spoken
 except Exception as e:return f"❌ Speech error: {type(e).__name__}: {e}",""
def stats():
 with db() as c:v=c.execute("SELECT COUNT(*) n FROM videos").fetchone()["n"];s=c.execute("SELECT COUNT(*) n FROM sentences").fetchone()["n"];p=c.execute("SELECT COUNT(*) n FROM practice").fetchone()["n"];a=c.execute("SELECT COALESCE(AVG(score),0) n FROM practice").fetchone()["n"]
 return f"**{v}** videos · **{s}** sentences · **{p}** practice sessions · **{a:.0f}** avg speaking score"
