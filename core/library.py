import html, json, re
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

REPO_RAW = "https://raw.githubusercontent.com/mr2along/english/feature/english-lab-v21/Transcription/playlist_transcripts.json"


def video_id(value):
    value=(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value): return value
    try:
        p=urlparse(value); host=(p.hostname or "").lower()
        if host in {"youtu.be","www.youtu.be"}:
            x=p.path.strip("/").split("/")[0]
            return x if re.fullmatch(r"[A-Za-z0-9_-]{11}",x) else None
        x=parse_qs(p.query).get("v",[None])[0]
        if x and re.fullmatch(r"[A-Za-z0-9_-]{11}",x): return x
        parts=[x for x in p.path.split("/") if x]
        if len(parts)>1 and parts[0] in {"embed","shorts","live"} and re.fullmatch(r"[A-Za-z0-9_-]{11}",parts[1]): return parts[1]
    except Exception: pass
    return None


def clean(value):
    value=html.unescape(str(value or ""))
    return re.sub(r"\s+"," ",re.sub(r"<[^>]*>","",value)).strip()


def segments(raw):
    out=[]
    for item in raw or []:
        if not isinstance(item,dict): continue
        text=clean(item.get("text") or item.get("utf8"))
        try: start=float(item.get("start",0) or 0); duration=float(item.get("duration",0) or 0)
        except (TypeError,ValueError): continue
        if text: out.append({"index":len(out)+1,"start":start,"duration":duration,"text":text})
    for i in range(len(out)-1):
        if not out[i]["duration"]: out[i]["duration"]=max(0,out[i+1]["start"]-out[i]["start"])
    return out


def validate(data):
    if not isinstance(data,dict) or not isinstance(data.get("videos"),list): raise ValueError("Invalid transcript library")
    videos=[]
    for v in data["videos"]:
        if isinstance(v,dict) and v.get("video_id"):
            x=dict(v); x["title"]=clean(x.get("title") or x["video_id"]); x["transcript"]=segments(x.get("transcript")); videos.append(x)
    data["videos"]=videos
    return data


def load(base_dir):
    local=Path(base_dir)/"Transcription"/"playlist_transcripts.json"
    if local.exists():
        try: return validate(json.loads(local.read_text(encoding="utf-8-sig"))),"local",None
        except Exception as e: local_error=str(e)
    try:
        req=Request(REPO_RAW,headers={"User-Agent":"EnglishLearningLab/2.1"})
        with urlopen(req,timeout=15) as r: data=json.loads(r.read().decode("utf-8-sig"))
        return validate(data),"github",None
    except Exception as e: return {"videos":[]},"error",locals().get("local_error","")+" "+str(e)


def find(videos, value):
    vid=video_id(value)
    return next((v for v in videos if v.get("video_id")==vid),None)
