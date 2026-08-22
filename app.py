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
LIST_TIMEOUT=int(os.getenv("TRANSCRIPT_LIST_TIMEOUT","45")); FETCH_TIMEOUT=int(os.getenv("TRANSCRIPT_FETCH_TIMEOUT","90")); TEST_TIMEOUT=int(os.getenv("PROXY_TEST_TIMEOUT","15"))

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

def diagnostic():
    p=proxy_url()
    if not p: return ["❌ Webshare configuration missing"]
    proxies={"http":p,"https":p}; out=[f"Endpoint: {HOST}:{PORT}"]
    tests=[("webshare-ip","https://ipv4.webshare.io/"),("google","https://www.google.com/generate_204"),("youtube-home","https://www.youtube.com/"),("youtube-video","https://www.youtube.com/watch?v=vxtvWovNKKE")]
    for name,url in tests:
        t=time.time()
        try:
            r=requests.get(url,proxies=proxies,timeout=TEST_TIMEOUT,allow_redirects=True)
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
        api=make_api(); log(f"🌐 Gọi YouTube API: list(video_id)... (timeout {LIST_TIMEOUT}s)"); yield state("🌐 Đang gọi YouTube API list()...")
        tl=call_timeout(lambda:api.list(vid),LIST_TIMEOUT); log("✅ Nhận danh sách transcript"); yield state("🔎 Đang chọn English transcript...")
        available=[f"{t.language_code}{' (translated)' if getattr(t,'is_translatable',False) else ''}" for t in tl]; log("📋 Transcript khả dụng: "+(", ".join(available) if available else "rỗng"))
        selected=next((t for t in tl if t.language_code in {"en","en-US","en-GB"}),None)
        if selected: log(f"✅ Đã chọn English transcript: {selected.language_code}")
        if selected is None:
            for t in tl:
                if getattr(t,"is_translatable",False):
                    try: selected=t.translate("en"); log(f"🔄 Đã dịch {t.language_code} → en"); break
                    except Exception as e: log(f"⚠️ Dịch thất bại: {e}")
        if selected is None: raise RuntimeError("Video không có English transcript khả dụng.")
        log(f"📥 Fetch timestamp + text... (timeout {FETCH_TIMEOUT}s)"); yield state("📥 Đang tải timestamp + text...")
        data=call_timeout(selected.fetch,FETCH_TIMEOUT); log(f"✅ Fetch hoàn tất: {len(data)} segment")
        lines=[]
        for i,item in enumerate(data,1):
            text=re.sub(r"\s+"," ",item.text).strip()
            if text: lines.append({"index":i,"start":float(getattr(item,"start",0.0)),"duration":float(getattr(item,"duration",0.0)),"text":text})
            if i==1 or i%50==0 or i==len(data): log(f"📝 Xử lý segment {i}/{len(data)}")
        if not lines: raise RuntimeError("Transcript rỗng.")
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
