import html, json, re
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

FINAL_RAW = "https://raw.githubusercontent.com/mr2along/english/feature/english-lab-v21/Transcription/final_transcripts.json"
FINAL_RAW_ROOT = "https://raw.githubusercontent.com/mr2along/english/feature/english-lab-v21/final_transcripts.json"
LEGACY_RAW = "https://raw.githubusercontent.com/mr2along/english/feature/english-lab-v21/Transcription/playlist_transcripts.json"

def video_id(value):
    value=(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value): return value
    try:
        p=urlparse(value); host=(p.hostname or "").lower()
        if host in {"youtu.be","www.youtu.be"}:
            x=p.path.strip("/").split("/")[0]; return x if re.fullmatch(r"[A-Za-z0-9_-]{11}",x) else None
        x=parse_qs(p.query).get("v",[None])[0]
        if x and re.fullmatch(r"[A-Za-z0-9_-]{11}",x): return x
        parts=[x for x in p.path.split("/") if x]
        if len(parts)>1 and parts[0] in {"embed","shorts","live"} and re.fullmatch(r"[A-Za-z0-9_-]{11}",parts[1]): return parts[1]
    except Exception: pass
    return None

def clean(value):
    value=html.unescape(str(value or "")); return re.sub(r"\s+"," ",re.sub(r"<[^>]*>","",value)).strip()

def segments(raw):
    out=[]
    for item in raw or []:
        if not isinstance(item,dict): continue
        text=clean(item.get("text") or item.get("utf8") or item.get("content"))
        try: start=float(item.get("start",item.get("start_time",0)) or 0)
        except (TypeError,ValueError): continue
        try:
            if item.get("end") is not None or item.get("end_time") is not None:
                end=float(item.get("end",item.get("end_time")) or start); duration=max(0,end-start)
            else: duration=float(item.get("duration",0) or 0)
        except (TypeError,ValueError): duration=0.0
        if text:
            x={"index":len(out)+1,"start":start,"duration":duration,"text":text}
            words=item.get("words")
            if isinstance(words,list):
                ww=[]
                for w in words:
                    if not isinstance(w,dict) or not w.get("word"): continue
                    try: ws=float(w.get("start",0) or 0); we=float(w.get("end",ws) or ws)
                    except (TypeError,ValueError): continue
                    ww.append({"word":clean(w.get("word")),"start":ws,"end":we})
                if ww: x["words"]=ww
            out.append(x)
    for i in range(len(out)-1):
        if not out[i]["duration"]: out[i]["duration"]=max(0,out[i+1]["start"]-out[i]["start"])
    return out

def validate(data):
    if not isinstance(data,dict) or not isinstance(data.get("videos"),list) or not data.get("videos"): raise ValueError("Transcript library is empty or invalid")
    videos=[]
    for v in data["videos"]:
        if not isinstance(v,dict) or not v.get("video_id"): continue
        x=dict(v); x["video_id"]=str(x["video_id"]); x["title"]=clean(x.get("title") or x["video_id"])
        source=x.get("segments") if isinstance(x.get("segments"),list) else x.get("transcript")
        x["transcript"]=segments(source); x["transcript_source"]=x.get("transcript_source") or "final_transcript"; x["alignment"]=x.get("alignment") or "final_alignment"; x["raw_transcript"]=list(x["transcript"]); videos.append(x)
    if not videos: raise ValueError("Transcript library contains no valid videos")
    data["videos"]=videos; return data

def _read_local(path): return validate(json.loads(path.read_text(encoding="utf-8-sig")))
def _read_remote(url):
    req=Request(url,headers={"User-Agent":"EnglishLearningLab/3.0"})
    with urlopen(req,timeout=20) as r: return validate(json.loads(r.read().decode("utf-8-sig")))

def load(base_dir):
    base=Path(base_dir); errors=[]
    for p in [base/"final_transcripts.json",base/"Transcription"/"final_transcripts.json"]:
        if p.exists() and p.stat().st_size>10:
            try: return _read_local(p),"final_transcript",None
            except Exception as e: errors.append(f"{p}: {e}")
    for u in [FINAL_RAW_ROOT,FINAL_RAW]:
        try: return _read_remote(u),"final_transcript_github",None
        except Exception as e: errors.append(f"{u}: {e}")
    legacy_local=base/"Transcription"/"playlist_transcripts.json"
    if legacy_local.exists() and legacy_local.stat().st_size>10:
        try: return _read_local(legacy_local),"legacy",None
        except Exception as e: errors.append(f"legacy local: {e}")
    try: return _read_remote(LEGACY_RAW),"legacy_github",None
    except Exception as e: errors.append(f"legacy remote: {e}")
    return {"videos":[]},"error"," | ".join(errors)

def find(videos,value):
    vid=video_id(value); return next((v for v in videos if v.get("video_id")==vid),None)
