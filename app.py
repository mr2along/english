import html
import json
import os
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from urllib.parse import parse_qs, quote, urlparse

import gradio as gr
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig

USER = os.getenv("WEBSHARE_USERNAME", "").strip()
PASSWORD = os.getenv("WEBSHARE_PASSWORD", "").strip()
HOST = os.getenv("WEBSHARE_PROXY_HOST", "p.webshare.io").strip()
PORT = os.getenv("WEBSHARE_PROXY_PORT", "80").strip()
LIST_TIMEOUT = int(os.getenv("TRANSCRIPT_LIST_TIMEOUT", "45"))
FETCH_TIMEOUT = int(os.getenv("TRANSCRIPT_FETCH_TIMEOUT", "90"))
TEST_TIMEOUT = int(os.getenv("PROXY_TEST_TIMEOUT", "15"))
HTTP_TIMEOUT = int(os.getenv("YOUTUBE_HTTP_TIMEOUT", "20"))


def video_id(value):
    value = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    p = urlparse(value)
    host = (p.hostname or "").lower()
    if host == "youtu.be":
        x = p.path.strip("/").split("/")[0]
        return x if re.fullmatch(r"[A-Za-z0-9_-]{11}", x) else None
    if "youtube.com" in host or "youtube-nocookie.com" in host:
        x = parse_qs(p.query).get("v", [None])[0]
        if x and re.fullmatch(r"[A-Za-z0-9_-]{11}", x):
            return x
        parts = [x for x in p.path.split("/") if x]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            return parts[1] if re.fullmatch(r"[A-Za-z0-9_-]{11}", parts[1]) else None
    return None


def proxy_url():
    if not all([USER, PASSWORD, HOST, PORT]):
        return None
    return f"http://{quote(USER, safe='')}:{quote(PASSWORD, safe='')}@{HOST}:{PORT}/"


def proxy_dict():
    p = proxy_url()
    return {"http": p, "https": p} if p else None


def diagnostic():
    p = proxy_url()
    if not p:
        return ["❌ Webshare configuration missing"]
    proxies = {"http": p, "https": p}
    out = [f"Endpoint: {HOST}:{PORT}"]
    tests = [
        ("webshare-ip", "https://ipv4.webshare.io/"),
        ("google", "https://www.google.com/generate_204"),
        ("youtube-home", "https://www.youtube.com/"),
        ("youtube-video", "https://www.youtube.com/watch?v=vxtvWovNKKE"),
    ]
    for name, url in tests:
        t = time.time()
        try:
            r = requests.get(url, proxies=proxies, timeout=TEST_TIMEOUT, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0"})
            out.append(f"[DIAG] {name}: OK status={r.status_code} elapsed={time.time()-t:.2f}s final={r.url}")
        except Exception as e:
            out.append(f"[DIAG] {name}: FAIL {type(e).__name__}: {e} elapsed={time.time()-t:.2f}s")
    return out


def make_api():
    print("[TRANSCRIPT] Creating YouTubeTranscriptApi client...", flush=True)
    if all([USER, PASSWORD, HOST, PORT]):
        print(f"[TRANSCRIPT] Webshare endpoint: {HOST}:{PORT}", flush=True)
        return YouTubeTranscriptApi(
            proxy_config=WebshareProxyConfig(
                proxy_username=USER,
                proxy_password=PASSWORD,
            )
        )
    print("[TRANSCRIPT] Webshare credentials: NOT configured; using direct connection", flush=True)
    return YouTubeTranscriptApi()


def call_timeout(fn, timeout):
    ex = ThreadPoolExecutor(max_workers=1)
    f = ex.submit(fn)
    try:
        return f.result(timeout=timeout)
    except FutureTimeoutError:
        f.cancel()
        raise TimeoutError(f"operation timed out after {timeout}s")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def _extract_caption_tracks(page):
    marker = '"captionTracks":'
    pos = page.find(marker)
    if pos < 0:
        return []
    start = page.find("[", pos + len(marker))
    if start < 0:
        return []
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(page)):
        ch = page[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(page[start:i + 1])
                except Exception:
                    return []
    return []


def _http_transcript_fallback(vid, log):
    proxies = proxy_dict()
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    watch = f"https://www.youtube.com/watch?v={vid}&hl=en"
    log("🛟 Fallback HTTP: tải YouTube watch HTML...")
    r = requests.get(watch, proxies=proxies, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    log(f"🛟 Fallback HTTP: watch HTML OK ({len(r.text):,} bytes)")
    tracks = _extract_caption_tracks(r.text)
    if not tracks:
        raise RuntimeError("Không tìm thấy captionTracks trong YouTube HTML.")
    selected = next((x for x in tracks if (x.get("languageCode") or "").lower() in {"en", "en-us", "en-gb"}), None)
    selected = selected or next((x for x in tracks if x.get("isTranslatable")), None)
    if selected is None:
        raise RuntimeError("Không tìm thấy English caption track.")
    base = selected.get("baseUrl")
    if not base:
        raise RuntimeError("Caption track không có baseUrl.")
    log(f"🛟 Fallback HTTP: caption track={selected.get('languageCode', 'unknown')}")
    sep = "&" if "?" in base else "?"
    for fmt in ("json3", "srv3", "xml"):
        try:
            rr = requests.get(base + sep + "fmt=" + fmt, proxies=proxies, headers=headers, timeout=HTTP_TIMEOUT)
            rr.raise_for_status()
            if fmt == "json3":
                events = []
                for ev in rr.json().get("events", []):
                    text = "".join(s.get("utf8", "") for s in (ev.get("segs") or [])).strip()
                    if text and ev.get("tStartMs") is not None:
                        events.append({"start": float(ev["tStartMs"]) / 1000, "duration": float(ev.get("dDurationMs", 0)) / 1000, "text": text})
                if events:
                    return events
            else:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(rr.text)
                events = []
                for tr in root.findall(".//text"):
                    text = html.unescape("".join(tr.itertext())).strip()
                    if text:
                        events.append({"start": float(tr.attrib.get("start", "0")), "duration": float(tr.attrib.get("dur", "0")), "text": text})
                if events:
                    return events
        except Exception as e:
            log(f"⚠️ Fallback {fmt} thất bại: {type(e).__name__}: {e}")
    raise RuntimeError("Không tải được caption data từ track.")


def normalize_segments(data):
    lines = []
    for i, item in enumerate(data, 1):
        if hasattr(item, "text"):
            text = item.text
            start = item.start
            duration = item.duration
        else:
            text = item.get("text", "")
            start = item.get("start", 0)
            duration = item.get("duration", 0)
        text = re.sub(r"\s+", " ", str(text)).strip()
        if text:
            lines.append({"index": i, "start": float(start), "duration": float(duration), "text": text})
    return lines


def build_player(vid, lines):
    data = html.escape(json.dumps(lines, ensure_ascii=False), quote=True)
    safe_vid = html.escape(vid, quote=True)
    return f'''<div id="english-lab-player" class="el-shell" data-video-id="{safe_vid}" data-lines="{data}">
<style>
.el-shell{{font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#172033}}
.el-grid{{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(300px,.8fr);gap:18px}}
.el-card{{background:rgba(255,255,255,.98);border:1px solid #e6eaf0;border-radius:18px;box-shadow:0 8px 30px rgba(20,35,60,.07);overflow:hidden}}
.el-video{{aspect-ratio:16/9;background:#080b10}}
.el-video iframe{{width:100%;height:100%;border:0;display:block}}
.el-head{{padding:14px 16px;border-bottom:1px solid #edf0f4;display:flex;align-items:center;justify-content:space-between;gap:10px}}
.el-title{{font-weight:750;font-size:16px}} .el-sub{{font-size:12px;color:#748096;margin-top:2px}}
.el-transcript{{height:calc(min(66vh,620px));overflow:auto;padding:10px}}
.el-line{{display:flex;width:100%;gap:10px;text-align:left;border:0;border-radius:12px;background:transparent;padding:10px 11px;margin:2px 0;cursor:pointer;color:#263247;line-height:1.45;font-size:14px}}
.el-line:hover{{background:#f5f7fb}} .el-line.active{{background:#eaf1ff;box-shadow:inset 3px 0 0 #2563eb}}
.el-time{{font:600 11px ui-monospace,SFMono-Regular,Menlo,monospace;color:#718096;min-width:45px;padding-top:2px}}
.el-text{{flex:1}} .el-num{{color:#a0a9b8;font-size:11px;margin-right:4px}}
.el-tools{{display:flex;gap:8px;flex-wrap:wrap;padding:12px 16px;border-top:1px solid #edf0f4}}
.el-btn{{border:1px solid #dce2ea;background:#fff;border-radius:10px;padding:8px 12px;font-weight:650;cursor:pointer}}
.el-btn.primary{{background:#2563eb;color:#fff;border-color:#2563eb}}
.el-tip{{padding:10px 16px;font-size:12px;color:#69768a;background:#f8fafc}}
@media(max-width:850px){{.el-grid{{grid-template-columns:1fr}}.el-transcript{{height:420px}}}}
</style>
<div class="el-grid">
  <section class="el-card">
    <div class="el-head"><div><div class="el-title">🎬 Video lesson</div><div class="el-sub">Click any sentence to jump to its exact timestamp</div></div><div id="el-count" class="el-sub"></div></div>
    <div class="el-video"><iframe id="el-youtube-frame" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div>
    <div class="el-tools"><button id="el-play" class="el-btn primary">▶ Phát câu hiện tại</button><button id="el-replay" class="el-btn">↺ Phát lại câu</button><button id="el-top" class="el-btn">↑ Về đầu</button></div>
    <div class="el-tip">💡 Mẹo: chọn một câu → nghe → đọc theo → chọn lại câu để luyện nhiều lần.</div>
  </section>
  <section class="el-card">
    <div class="el-head"><div><div class="el-title">📝 English transcript</div><div class="el-sub">Timestamp synchronized with video</div></div></div>
    <div id="el-lines" class="el-transcript"></div>
  </section>
</div>
<script>
(function(){{
 const root=document.getElementById('english-lab-player'); if(!root)return;
 const vid=root.dataset.videoId; let lines=[]; try{{lines=JSON.parse(root.dataset.lines||'[]')}}catch(e){{}}
 const frame=document.getElementById('el-youtube-frame');
 frame.src='https://www.youtube.com/embed/'+encodeURIComponent(vid)+'?enablejsapi=1&playsinline=1&rel=0&origin='+encodeURIComponent(location.origin);
 const list=document.getElementById('el-lines'), buttons=[]; let active=-1;
 const fmt=t=>{{t=Math.max(0,Number(t)||0);const m=Math.floor(t/60),s=Math.floor(t%60);return String(m).padStart(2,'0')+':'+String(s).padStart(2,'0')}};
 document.getElementById('el-count').textContent=lines.length+' sentences';
 function cmd(func,args){{try{{frame.contentWindow.postMessage(JSON.stringify({{event:'command',func,args:args||[]}}),'*')}}catch(e){{}}}}
 function seek(t){{cmd('seekTo',[Number(t)||0,true]);cmd('playVideo',[]);}}
 lines.forEach((x,i)=>{{const b=document.createElement('button');b.className='el-line';b.type='button';
  b.innerHTML='<span class="el-time">'+fmt(x.start)+'</span><span class="el-text"><span class="el-num">#'+(i+1)+'</span>'+String(x.text).replace(/[&<>]/g,m=>({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[m]))+'</span>';
  b.onclick=()=>seek(x.start);list.appendChild(b);buttons.push(b);
 }});
 function setActive(i){{if(i===active)return;active=i;buttons.forEach((b,j)=>b.classList.toggle('active',j===i));if(i>=0)buttons[i]?.scrollIntoView({{block:'nearest',behavior:'smooth'}})}}
 function current(t){{let i=-1;for(let j=0;j<lines.length;j++){{const a=+lines[j].start||0,b=j+1<lines.length?(+lines[j+1].start||a):Infinity;if(t>=a&&t<b){{i=j;break}}}}return i}}
 window.addEventListener('message',e=>{{if(typeof e.data!=='string')return;let d;try{{d=JSON.parse(e.data)}}catch(_){{return}};const t=d?.info?.currentTime??d?.infoDelivery?.currentTime;if(typeof t==='number')setActive(current(t))}});
 document.getElementById('el-play').onclick=()=>seek(lines[Math.max(active,0)]?.start||0);
 document.getElementById('el-replay').onclick=()=>{{if(active>=0)seek(lines[active].start)}};
 document.getElementById('el-top').onclick=()=>seek(0);
 setInterval(()=>cmd('getCurrentTime',[]),500);
}})();
</script></div>'''


def get_transcript(url):
    started=time.time(); logs=[]; payload=""; player=""
    def log(msg):
        x=f"[{time.time()-started:6.2f}s] {msg}"; logs.append(x); print(f"[TRANSCRIPT] {x}",flush=True)
    def state(status,text=""): return status,text,"\n".join(logs),payload,player
    vid=video_id(url)
    if not vid:
        log("❌ YouTube URL/Video ID không hợp lệ"); yield state("❌ Link YouTube không hợp lệ."); return
    log(f"▶ Bắt đầu tải transcript — video_id={vid}"); yield state("⏳ Đang chuẩn bị...")
    try:
        p=proxy_url(); log("🔐 Proxy: Webshare" if p else "🔐 Proxy: direct")
        if p:
            log(f"🌐 Endpoint: {HOST}:{PORT}"); yield state("🌐 Đang kiểm tra Webshare → YouTube...")
            for item in diagnostic(): log(item)
        try:
            api=make_api(); log(f"🌐 Gọi YouTube API: list(video_id)... (timeout {LIST_TIMEOUT}s)"); yield state("🌐 Đang gọi YouTube API...")
            tl=call_timeout(lambda:api.list(vid),LIST_TIMEOUT); log("✅ Nhận danh sách transcript"); yield state("🔎 Đang chọn English transcript...")
            available=[t.language_code for t in tl]; log("📋 Transcript khả dụng: "+(", ".join(available) if available else "rỗng"))
            selected=next((t for t in tl if t.language_code.lower() in {"en","en-us","en-gb"}),None)
            if selected is None:
                for t in tl:
                    if getattr(t,"is_translatable",False):
                        try: selected=t.translate("en"); log(f"🔄 Đã dịch {t.language_code} → en"); break
                        except Exception as e: log(f"⚠️ Dịch thất bại: {e}")
            if selected is None: raise RuntimeError("Video không có English transcript khả dụng.")
            log(f"📥 Fetch timestamp + text... (timeout {FETCH_TIMEOUT}s)"); yield state("📥 Đang tải timestamp + text...")
            data=call_timeout(selected.fetch,FETCH_TIMEOUT); lines=normalize_segments(data); log(f"✅ Fetch hoàn tất: {len(lines)} segment")
        except Exception as primary:
            log(f"⚠️ Backend youtube-transcript-api thất bại: {type(primary).__name__}: {primary}"); log("🔁 Chuyển sang HTTP caption fallback..."); yield state("🔁 Đang thử backend transcript dự phòng...")
            lines=normalize_segments(_http_transcript_fallback(vid,log)); log(f"✅ Fallback hoàn tất: {len(lines)} segment")
        if not lines: raise RuntimeError("Transcript rỗng.")
        for i in range(1,len(lines)+1):
            if i==1 or i%50==0 or i==len(lines): log(f"📝 Xử lý segment {i}/{len(lines)}")
        payload=json.dumps(lines,ensure_ascii=False); transcript="\n".join(f"[{x['start']:.2f}s] {x['text']}" for x in lines); player=build_player(vid,lines)
        log(f"🎬 Player + transcript UI: {len(lines)} câu"); log("🔗 Click câu → seekTo(timestamp) → playVideo"); log(f"🎉 Hoàn tất: {len(lines)} segment, {len(transcript):,} ký tự"); log(f"⏱ Tổng thời gian: {time.time()-started:.2f}s")
        yield state("✅ Bài học đã sẵn sàng.",transcript)
    except Exception as e:
        log(f"❌ LỖI: {type(e).__name__}: {e}"); traceback.print_exc(); yield state(f"❌ Không lấy được transcript cho {vid}.\n\n{type(e).__name__}: {e}")


CSS="""
:root{--el-blue:#2563eb;--el-bg:#f4f7fb}
body{background:var(--el-bg)!important}
.gradio-container{max-width:1180px!important;margin:auto!important;padding:18px!important}
#app-header{border-radius:20px;padding:24px 26px;background:linear-gradient(135deg,#0f172a,#1e3a8a);color:white;box-shadow:0 12px 35px rgba(15,23,42,.16);margin-bottom:16px}
#app-header h1{margin:0;font-size:30px}.header-sub{margin-top:7px;opacity:.82}
#load-row{background:white;border:1px solid #e5e9f0;border-radius:16px;padding:14px;box-shadow:0 5px 20px rgba(20,35,60,.06)}
#url-box textarea{border-radius:11px!important}.load-btn{border-radius:11px!important;font-weight:700!important}
.status-box{border-radius:12px!important}
#raw-output,#log-box{border-radius:14px!important}
footer{display:none!important}
@media(max-width:700px){.gradio-container{padding:10px!important}#app-header{padding:18px}.gradio-container h1{font-size:24px}}
"""

with gr.Blocks(title="English Lab", css=CSS, theme=gr.themes.Soft(primary_hue="blue", neutral_hue="slate"), fill_width=True) as demo:
    gr.HTML('''<div id="app-header"><h1>🎧 English Lab</h1><div class="header-sub">Luyện nghe · đọc · phát âm với video YouTube — transcript đồng bộ theo từng câu</div></div>''')
    with gr.Row(elem_id="load-row"):
        url=gr.Textbox(label="YouTube URL hoặc Video ID", placeholder="Dán link YouTube vào đây…", scale=5, elem_id="url-box")
        button=gr.Button("🚀 Tải bài học", variant="primary", scale=1, elem_classes=["load-btn"])
    status=gr.Markdown("### 👋 Sẵn sàng\nDán một video YouTube rồi bấm **Tải bài học**.", elem_classes=["status-box"])
    player_out=gr.HTML()
    with gr.Accordion("🔧 Developer / Network diagnostics", open=False):
        diag=gr.Button("🔬 Kiểm tra Webshare → YouTube")
        diag_out=gr.Textbox(label="Network diagnostic", lines=7, interactive=False, show_copy_button=True)
        progress_log=gr.Textbox(label="Log tiến trình tải transcript", lines=16, max_lines=40, interactive=False, show_copy_button=True, elem_id="log-box")
    with gr.Accordion("📄 Transcript dạng text / export", open=False):
        output=gr.Textbox(label="English Transcript + timestamp", lines=18, show_copy_button=True, elem_id="raw-output")
        timestamp_payload=gr.Textbox(label="Timestamp JSON", visible=False)
    diag.click(lambda:"\n".join(diagnostic()),outputs=diag_out)
    button.click(get_transcript,inputs=url,outputs=[status,output,progress_log,timestamp_payload,player_out])
    url.submit(get_transcript,inputs=url,outputs=[status,output,progress_log,timestamp_payload,player_out])

if __name__=="__main__":
    print("[STARTUP] English Lab starting on 0.0.0.0:7860",flush=True)
    demo.launch(server_name="0.0.0.0",server_port=7860,ssr_mode=False)
