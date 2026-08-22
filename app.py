import json
import os
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from urllib.parse import parse_qs, urlparse, quote

import gradio as gr
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig

USER=os.getenv("WEBSHARE_USERNAME","").strip(); PASSWORD=os.getenv("WEBSHARE_PASSWORD","").strip(); HOST=os.getenv("WEBSHARE_PROXY_HOST","p.webshare.io").strip(); PORT=os.getenv("WEBSHARE_PROXY_PORT","80").strip()
LIST_TIMEOUT=int(os.getenv("TRANSCRIPT_LIST_TIMEOUT","45")); FETCH_TIMEOUT=int(os.getenv("TRANSCRIPT_FETCH_TIMEOUT","90")); TEST_TIMEOUT=int(os.getenv("PROXY_TEST_TIMEOUT","15")); HTTP_TIMEOUT=int(os.getenv("YOUTUBE_HTTP_TIMEOUT","20"))


def video_id(value):
    value=(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}",value): return value
    p=urlparse(value); host=(p.hostname or "").lower()
    if host=="youtu.be":
        x=p.path.strip("/").split("/")[0]; return x if re.fullmatch(r"[A-Za-z0-9_-]{11}",x) else None
    if "youtube.com" in host or "youtube-nocookie.com" in host:
        x=parse_qs(p.query).get("v",[None])[0]
        if x and re.fullmatch(r"[A-Za-z0-9_-]{11}",x): return x
        parts=[x for x in p.path.split("/") if x]
        if len(parts)>=2 and parts[0] in {"shorts","embed","live"}: return parts[1] if re.fullmatch(r"[A-Za-z0-9_-]{11}",parts[1]) else None
    return None


def proxy_url():
    if not all([USER,PASSWORD,HOST,PORT]): return None
    return f"http://{quote(USER,safe='')}:{quote(PASSWORD,safe='')}@{HOST}:{PORT}/"


def proxy_dict():
    p=proxy_url()
    return {"http":p,"https":p} if p else None


def diagnostic():
    p=proxy_url()
    if not p: return ["❌ Webshare configuration missing"]
    proxies={"http":p,"https":p}; out=[f"Endpoint: {HOST}:{PORT}"]
    tests=[("webshare-ip","https://ipv4.webshare.io/"),("google","https://www.google.com/generate_204"),("youtube-home","https://www.youtube.com/"),("youtube-video","https://www.youtube.com/watch?v=vxtvWovNKKE")]
    for name,url in tests:
        t=time.time()
        try:
            r=requests.get(url,proxies=proxies,timeout=TEST_TIMEOUT,allow_redirects=True,headers={"User-Agent":"Mozilla/5.0"})
            out.append(f"[DIAG] {name}: OK status={r.status_code} elapsed={time.time()-t:.2f}s final={r.url}")
        except Exception as e:
            out.append(f"[DIAG] {name}: FAIL {type(e).__name__}: {e} elapsed={time.time()-t:.2f}s")
    return out


def make_api():
    p=proxy_url(); print("[TRANSCRIPT] Creating YouTubeTranscriptApi client...",flush=True)
    if p:
        print(f"[TRANSCRIPT] Webshare endpoint: {HOST}:{PORT}",flush=True); return YouTubeTranscriptApi(proxy_config=GenericProxyConfig(http_url=p,https_url=p))
    print("[TRANSCRIPT] Webshare credentials: NOT configured; using direct connection",flush=True); return YouTubeTranscriptApi()


def call_timeout(fn,timeout):
    ex=ThreadPoolExecutor(max_workers=1); f=ex.submit(fn)
    try: return f.result(timeout=timeout)
    except FutureTimeoutError: f.cancel(); raise TimeoutError(f"operation timed out after {timeout}s")
    finally: ex.shutdown(wait=False,cancel_futures=True)


def _extract_caption_tracks(html):
    """Extract caption track metadata from YouTube page HTML when transcript-api cannot reach it."""
    # YouTube embeds ytInitialPlayerResponse as JSON; capture a balanced-ish JSON object by looking for the captions key.
    marker='"captionTracks":'
    pos=html.find(marker)
    if pos < 0: return []
    start=html.find('[',pos+len(marker))
    if start < 0: return []
    depth=0; in_str=False; esc=False
    for i in range(start,len(html)):
        ch=html[i]
        if in_str:
            if esc: esc=False
            elif ch=='\\': esc=True
            elif ch=='"': in_str=False
            continue
        if ch=='"': in_str=True
        elif ch=='[': depth+=1
        elif ch==']':
            depth-=1
            if depth==0:
                try: return json.loads(html[start:i+1])
                except Exception: return []
    return []


def _http_transcript_fallback(vid, log):
    """Fallback: fetch YouTube watch HTML and caption XML directly, preserving start/duration."""
    proxies=proxy_dict(); headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36","Accept-Language":"en-US,en;q=0.9"}
    watch=f"https://www.youtube.com/watch?v={vid}&hl=en"
    log("🛟 Fallback HTTP: tải YouTube watch HTML...")
    r=requests.get(watch,proxies=proxies,headers=headers,timeout=HTTP_TIMEOUT,allow_redirects=True)
    r.raise_for_status(); log(f"🛟 Fallback HTTP: watch HTML OK ({len(r.text):,} bytes)")
    tracks=_extract_caption_tracks(r.text)
    if not tracks: raise RuntimeError("Không tìm thấy captionTracks trong YouTube HTML.")
    english=next((x for x in tracks if (x.get("languageCode") or "").lower() in {"en","en-us","en-gb"}),None)
    selected=english or next((x for x in tracks if x.get("isTranslatable")),None)
    if selected is None: raise RuntimeError("Không tìm thấy English caption track.")
    base=selected.get("baseUrl")
    if not base: raise RuntimeError("Caption track không có baseUrl.")
    log(f"🛟 Fallback HTTP: caption track={selected.get('languageCode','unknown')}")
    # Prefer JSON3; XML is a robust fallback for classic caption tracks.
    sep='&' if '?' in base else '?'
    for fmt in ("json3", "srv3", "xml"):
        try:
            u=base+sep+"fmt="+fmt
            rr=requests.get(u,proxies=proxies,headers=headers,timeout=HTTP_TIMEOUT)
            rr.raise_for_status()
            if fmt=="json3":
                obj=rr.json(); events=[]
                for ev in obj.get("events",[]):
                    segs=ev.get("segs") or []
                    text="".join(s.get("utf8","") for s in segs).strip()
                    if text and ev.get("tStartMs") is not None:
                        events.append({"start":float(ev.get("tStartMs",0))/1000.0,"duration":float(ev.get("dDurationMs",0))/1000.0,"text":text})
                if events: return events
            elif fmt=="srv3":
                import xml.etree.ElementTree as ET
                root=ET.fromstring(rr.text); events=[]
                for tr in root.findall('.//text'):
                    text=''.join(tr.itertext()).strip();
                    if text: events.append({"start":float(tr.attrib.get('start','0')),"duration":float(tr.attrib.get('dur','0')),"text":text})
                if events: return events
            else:
                import xml.etree.ElementTree as ET, html as htmlmod
                root=ET.fromstring(rr.text); events=[]
                for tr in root.findall('.//text'):
                    text=htmlmod.unescape(''.join(tr.itertext())).strip()
                    if text: events.append({"start":float(tr.attrib.get('start','0')),"duration":float(tr.attrib.get('dur','0')),"text":text})
                if events: return events
        except Exception as e: log(f"⚠️ Fallback {fmt} thất bại: {type(e).__name__}: {e}")
    raise RuntimeError("Không tải được caption data từ track.")


def normalize_segments(data):
    lines=[]
    for i,item in enumerate(data,1):
        text=re.sub(r"\s+"," ",str(item.get("text",getattr(item,"text","")))).strip()
        if text:
            lines.append({"index":i,"start":float(item.get("start",getattr(item,"start",0.0))),"duration":float(item.get("duration",getattr(item,"duration",0.0))),"text":text})
    return lines


def get_transcript(url):
    started=time.time(); logs=[]; payload=""
    def log(msg):
        x=f"[{time.time()-started:6.2f}s] {msg}"; logs.append(x); print(f"[TRANSCRIPT] {x}",flush=True)
    def state(status,text=""): return status,text,"\n".join(logs),payload
    vid=video_id(url)
    if not vid: log("❌ YouTube URL/Video ID không hợp lệ"); yield state("❌ Link YouTube không hợp lệ."); return
    log(f"▶ Bắt đầu tải transcript — video_id={vid}"); yield state("⏳ Đang chuẩn bị...")
    try:
        p=proxy_url(); log("🔐 Proxy: Webshare" if p else "🔐 Proxy: direct")
        if p:
            log(f"🌐 Endpoint: {HOST}:{PORT}"); yield state("🌐 Đang kiểm tra Webshare → YouTube...")
            diag=diagnostic()
            for item in diag: log(item)
        try:
            api=make_api(); log(f"🌐 Gọi YouTube API: list(video_id)... (timeout {LIST_TIMEOUT}s)"); yield state("🌐 Đang gọi YouTube API list()...")
            tl=call_timeout(lambda:api.list(vid),LIST_TIMEOUT); log("✅ Nhận danh sách transcript"); yield state("🔎 Đang chọn English transcript...")
            available=[f"{t.language_code}{' (translated)' if getattr(t,'is_translatable',False) else ''}" for t in tl]; log("📋 Transcript khả dụng: "+(", ".join(available) if available else "rỗng"))
            selected=next((t for t in tl if t.language_code in {"en","en-US","en-GB"}),None)
            if selected is None:
                for t in tl:
                    if getattr(t,"is_translatable",False):
                        try: selected=t.translate("en"); log(f"🔄 Đã dịch {t.language_code} → en"); break
                        except Exception as e: log(f"⚠️ Dịch thất bại: {e}")
            if selected is None: raise RuntimeError("Video không có English transcript khả dụng.")
            log(f"📥 Fetch timestamp + text... (timeout {FETCH_TIMEOUT}s)"); yield state("📥 Đang tải timestamp + text...")
            data=call_timeout(selected.fetch,FETCH_TIMEOUT); lines=normalize_segments(data); log(f"✅ Fetch hoàn tất: {len(lines)} segment")
        except Exception as primary:
            log(f"⚠️ Backend youtube-transcript-api thất bại: {type(primary).__name__}: {primary}")
            log("🔁 Chuyển sang HTTP caption fallback..."); yield state("🔁 Đang thử transcript backend thứ hai...")
            lines=normalize_segments(_http_transcript_fallback(vid,log)); log(f"✅ Fallback hoàn tất: {len(lines)} segment")
        if not lines: raise RuntimeError("Transcript rỗng.")
        for i in range(1,len(lines)+1):
            if i==1 or i%50==0 or i==len(lines): log(f"📝 Xử lý segment {i}/{len(lines)}")
        payload=json.dumps(lines,ensure_ascii=False); transcript="\n".join(f"[{x['start']:.2f}s] {x['text']}" for x in lines)
        log(f"🎉 Hoàn tất: {len(lines)} segment, {len(transcript):,} ký tự"); log(f"⏱ Tổng thời gian: {time.time()-started:.2f}s")
        yield state("✅ Transcript đã tải xong — timestamp đã được giữ lại.",transcript)
    except Exception as e:
        log(f"❌ LỖI: {type(e).__name__}: {e}"); traceback.print_exc(); yield state(f"❌ Không lấy được transcript cho {vid}.\n\n{type(e).__name__}: {e}")


with gr.Blocks(title="English Lab — YouTube Transcript") as demo:
    gr.Markdown("# 🎧 English Lab — YouTube Transcript")
    gr.Markdown("**Webshare → YouTube diagnostic + transcript timestamp logging**")
    with gr.Row():
        url=gr.Textbox(label="YouTube URL hoặc Video ID",placeholder="https://www.youtube.com/watch?v=vxtvWovNKKE",scale=5); button=gr.Button("🚀 Lấy English Transcript",variant="primary")
    diag=gr.Button("🔬 Test Webshare → YouTube"); diag_out=gr.Textbox(label="Network diagnostic",lines=8,interactive=False)
    status=gr.Markdown("Sẵn sàng."); output=gr.Textbox(label="English Transcript + timestamp",lines=24,show_copy_button=True)
    progress_log=gr.Textbox(label="🔎 Log tiến trình tải transcript",lines=18,max_lines=40,interactive=False,show_copy_button=True); timestamp_payload=gr.Textbox(label="Timestamp data",visible=False)
    diag.click(lambda:"\n".join(diagnostic()),outputs=diag_out)
    button.click(get_transcript,inputs=url,outputs=[status,output,progress_log,timestamp_payload]); url.submit(get_transcript,inputs=url,outputs=[status,output,progress_log,timestamp_payload])

if __name__=="__main__":
    print("[STARTUP] English Lab starting on 0.0.0.0:7860",flush=True); demo.launch(server_name="0.0.0.0",server_port=7860,ssr_mode=False)
