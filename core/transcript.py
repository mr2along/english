import json, re

def format_time(seconds):
    s=max(0,int(float(seconds or 0))); h,s=divmod(s,3600); m,s=divmod(s,60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def to_json(segments): return json.dumps(segments or [],ensure_ascii=False,indent=2)

def parse_manual(raw):
    raw=raw or ""
    if not raw.strip(): return []
    if raw.lstrip().startswith(("{","[")):
        data=json.loads(raw); data=data.get("transcript") or data.get("segments") or [] if isinstance(data,dict) else data
        return normalize(data)
    out=[]
    for line in raw.splitlines():
        line=line.strip()
        m=re.match(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\]?\s*(.*)$",line)
        if not m: continue
        p=m.group(1).replace(",",".").split(":")
        start=float(p[-1])+float(p[-2])*60+(float(p[-3])*3600 if len(p)==3 else 0)
        if m.group(2).strip(): out.append({"index":len(out)+1,"start":start,"duration":0,"text":m.group(2).strip()})
    for i in range(len(out)-1): out[i]["duration"]=out[i+1]["start"]-out[i]["start"]
    return out

def normalize(raw):
    out=[]
    for x in raw or []:
        if isinstance(x,dict) and str(x.get("text") or "").strip():
            out.append({"index":len(out)+1,"start":float(x.get("start",0) or 0),"duration":float(x.get("duration",0) or 0),"text":str(x.get("text")).strip()})
    for i in range(len(out)-1):
        if not out[i]["duration"]: out[i]["duration"]=max(0,out[i+1]["start"]-out[i]["start"])
    return out

def active_index(segments,current_time):
    t=float(current_time or 0)
    for i,s in enumerate(segments):
        if s["start"] <= t < s["start"]+max(s.get("duration",0),0.25): return i
    return max(0,len(segments)-1) if segments and t>=segments[-1]["start"] else -1
