import html
import json
import os
import re
from urllib.parse import parse_qs, urlparse

import gradio as gr

APP_TITLE = "English Lab"
DEFAULT_URL = "https://www.youtube.com/watch?v=vxtvWovNKKE"


def get_video_id(value: str):
    value = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    p = urlparse(value)
    host = (p.hostname or "").lower()
    if host == "youtu.be":
        x = p.path.strip("/").split("/")[0]
        return x if re.fullmatch(r"[A-Za-z0-9_-]{11}", x) else None
    x = parse_qs(p.query).get("v", [None])[0]
    if x and re.fullmatch(r"[A-Za-z0-9_-]{11}", x):
        return x
    parts = [x for x in p.path.split("/") if x]
    if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live"}:
        return parts[1] if re.fullmatch(r"[A-Za-z0-9_-]{11}", parts[1]) else None
    return None


def player_html(vid):
    v = html.escape(vid, quote=True)
    src = f"https://www.youtube.com/embed/{v}?enablejsapi=1&playsinline=1&rel=0"
    return f'''<div class="yt-wrap" data-video-id="{v}">
<div class="yt-status">YouTube video: <b>{v}</b></div>
<div class="yt-frame"><iframe id="englishlab-youtube" src="{src}" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe></div>
<div class="yt-links"><a href="https://www.youtube.com/watch?v={v}" target="_blank" rel="noopener">↗ Mở video trực tiếp trên YouTube</a> · <a href="https://www.youtube.com/embed/{v}" target="_blank" rel="noopener">Mở URL embed</a></div>
</div>'''


def load_video(url):
    vid = get_video_id(url)
    if not vid:
        return "❌ URL/Video ID YouTube không hợp lệ.", ""
    return f"✅ Đã tạo player cho Video ID: `{vid}`", player_html(vid)


CSS = r'''
.gradio-container{max-width:1400px!important}
.yt-wrap{font-family:system-ui,sans-serif;background:#fff;border:1px solid #e3e7ee;border-radius:16px;overflow:hidden}
.yt-status{padding:10px 14px;font-size:13px;color:#526071;border-bottom:1px solid #e8ebf0}
.yt-frame{width:100%;aspect-ratio:16/9;background:#000}
.yt-frame iframe{width:100%;height:100%;display:block;border:0}
.yt-links{padding:10px 14px;font-size:12px;color:#64748b}
.yt-links a{color:#2563eb;text-decoration:none}
.transcript-panel{font-family:system-ui,sans-serif;border:1px solid #e3e7ee;border-radius:16px;background:#fff;overflow:hidden}
.transcript-head{padding:12px 14px;border-bottom:1px solid #e8ebf0;font-weight:700}
.transcript-list{max-height:520px;overflow:auto;padding:8px}
.tline{display:flex;gap:10px;width:100%;border:0;background:#f8fafc;border-radius:9px;padding:10px;margin:4px 0;text-align:left;cursor:pointer;font-size:14px;line-height:1.45}
.tline:hover,.tline.active{background:#eaf1ff}
.tstamp{min-width:58px;color:#2563eb;font:600 12px ui-monospace,monospace}
.ttext{flex:1;color:#172033}
'''

# All YouTube transcript retrieval is deliberately performed in the user's browser.
# No YouTube transcript request is made by the HF/Python server.
JS = r'''() => {
  const state = {videoId:null, tracks:[], segments:[], timer:null};
  const $ = (id) => document.getElementById(id);
  const status = (text) => { const el=$('client-status'); if(el) el.textContent=text; };
  const esc = (s) => String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const time = (s) => { s=Math.max(0,Math.floor(Number(s)||0)); const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),x=s%60; return h?`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(x).padStart(2,'0')}`:`${String(m).padStart(2,'0')}:${String(x).padStart(2,'0')}`; };
  const getId = (value) => {
    value=(value||'').trim();
    if(/^[A-Za-z0-9_-]{11}$/.test(value)) return value;
    try { const u=new URL(value); if(u.hostname==='youtu.be') return u.pathname.split('/').filter(Boolean)[0]||null; const q=u.searchParams.get('v'); if(q&&/^[A-Za-z0-9_-]{11}$/.test(q)) return q; const p=u.pathname.split('/').filter(Boolean); if(p.length>=2&&['embed','shorts','live'].includes(p[0])) return p[1]; } catch(e) {}
    return null;
  };
  const parseXml = (xml) => {
    const doc=new DOMParser().parseFromString(xml,'text/xml');
    return [...doc.querySelectorAll('text')].map((n,i)=>({index:i+1,start:Number(n.getAttribute('start')||0),duration:Number(n.getAttribute('dur')||0),text:(n.textContent||'').replace(/\s+/g,' ').trim()})).filter(x=>x.text);
  };
  const parseJson3 = (data) => {
    const events=data.events||[]; const out=[];
    for(const e of events){ const text=(e.segs||[]).map(s=>s.utf8||'').join('').replace(/\s+/g,' ').trim(); if(text&&e.tStartMs!=null) out.push({index:out.length+1,start:Number(e.tStartMs)/1000,duration:Number(e.dDurationMs||0)/1000,text}); }
    return out;
  };
  const render = () => {
    const box=$('client-transcript'); if(!box) return;
    if(!state.segments.length){ box.innerHTML='<div class="transcript-panel"><div class="transcript-head">📝 English transcript</div><div style="padding:18px;color:#64748b">Chưa có transcript.</div></div>'; return; }
    box.innerHTML='<div class="transcript-panel"><div class="transcript-head">📝 Transcript · '+state.segments.length+' câu</div><div class="transcript-list">'+state.segments.map((x,i)=>`<button class="tline" data-index="${i}"><span class="tstamp">${time(x.start)}</span><span class="ttext">${esc(x.text)}</span></button>`).join('')+'</div></div>';
    box.querySelectorAll('.tline').forEach(b=>b.addEventListener('click',()=>seek(state.segments[Number(b.dataset.index)].start)));
  };
  const frame = () => $('englishlab-youtube');
  const command = (func,args=[]) => { const f=frame(); if(f?.contentWindow) f.contentWindow.postMessage(JSON.stringify({event:'command',func,args}),'*'); };
  const seek = (seconds) => { command('seekTo',[Number(seconds)||0,true]); command('playVideo'); };
  const current = (cb) => { const f=frame(); if(!f?.contentWindow) return; const listener=(e)=>{if(e.source!==f.contentWindow||typeof e.data!=='string')return;try{const d=JSON.parse(e.data);if(typeof d?.info?.currentTime==='number'){window.removeEventListener('message',listener);cb(d.info.currentTime);}}catch(_){} }; window.addEventListener('message',listener); command('getCurrentTime'); setTimeout(()=>window.removeEventListener('message',listener),500); };
  const highlight = (t) => { const rows=[...document.querySelectorAll('.tline')]; let idx=-1; for(let i=0;i<state.segments.length;i++){const a=state.segments[i].start,b=i+1<state.segments.length?state.segments[i+1].start:Infinity;if(t>=a&&t<b){idx=i;break;}} rows.forEach((r,i)=>r.classList.toggle('active',i===idx)); if(idx>=0) rows[idx].scrollIntoView({block:'nearest',behavior:'smooth'}); };
  const fetchCaptions = async () => {
    const input=document.querySelector('textarea, input');
    const candidates=[...document.querySelectorAll('input')].map(x=>x.value).filter(Boolean);
    const url=candidates.find(x=>x.includes('youtube.com')||x.includes('youtu.be')) || '';
    const vid=getId(url); if(!vid){status('❌ Không tìm thấy YouTube URL/Video ID trong ô nhập.');return;}
    const lang=document.querySelector('select')?.value||'en'; state.videoId=vid; status('⏳ Đang lấy caption trực tiếp từ YouTube trên trình duyệt…');
    try {
      const body={context:{client:{hl:lang==='auto'?'en':lang,gl:'US',clientName:'WEB',clientVersion:'2.20260820.01.00'}} ,videoId:vid};
      const r=await fetch('https://www.youtube.com/youtubei/v1/player?prettyPrint=false',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(!r.ok) throw new Error('YouTube player request HTTP '+r.status);
      const data=await r.json(); const tracks=data?.captions?.playerCaptionsTracklistRenderer?.captionTracks||[]; state.tracks=tracks;
      if(!tracks.length) throw new Error('YouTube không trả về captionTracks cho video này. Có thể video không có phụ đề hoặc YouTube yêu cầu đăng nhập.');
      let track=tracks.find(t=>(t.languageCode||'').toLowerCase()===(lang||'en').toLowerCase()) || tracks.find(t=>(t.languageCode||'').toLowerCase().startsWith((lang||'en').toLowerCase())) || tracks[0];
      status('⏳ Đã tìm thấy caption '+(track.languageCode||'')+' · đang tải transcript…');
      const u=new URL(track.baseUrl); u.searchParams.set('fmt','json3');
      let cr=await fetch(u.toString(),{credentials:'omit'}); let segments=[];
      if(cr.ok){ const ct=cr.headers.get('content-type')||''; if(ct.includes('json')){segments=parseJson3(await cr.json());} else {segments=parseXml(await cr.text());} }
      if(!segments.length){ cr=await fetch(track.baseUrl,{credentials:'omit'}); if(cr.ok) segments=parseXml(await cr.text()); }
      if(!segments.length) throw new Error('Đã tìm thấy caption track nhưng không đọc được nội dung.');
      state.segments=segments; render(); status('✅ Lấy transcript trực tiếp thành công · '+segments.length+' câu · ngôn ngữ '+(track.languageCode||''));
    } catch(e) { status('❌ Browser transcript: '+e.message+' — nếu trình duyệt chặn CORS, hãy dùng Import SRT/VTT/JSON.'); }
  };
  window.englishLabSeek=seek; window.englishLabFetchTranscript=fetchCaptions;
  setInterval(()=>current(highlight),1200);
  setTimeout(()=>{ const b=$('client-fetch'); if(b)b.addEventListener('click',fetchCaptions); },300);
}'''

with gr.Blocks(title=APP_TITLE, css=CSS, js=JS, theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🎧 English Lab\nLuyện nghe · đọc · phát âm với video YouTube và transcript")
    with gr.Row():
        url = gr.Textbox(label="YouTube URL hoặc Video ID", value=DEFAULT_URL, scale=5)
        embed = gr.Button("🎬 Nhúng video", variant="primary", scale=1)
    with gr.Row():
        lang = gr.Dropdown(["en", "vi", "ja", "ko", "zh", "auto"], value="en", label="Ngôn ngữ transcript", scale=1, elem_id="client-lang")
        get_transcript = gr.Button("🚀 Lấy transcript trên trình duyệt", variant="primary", scale=2, elem_id="client-fetch")
    status = gr.Markdown("Sẵn sàng — transcript sẽ được request trực tiếp từ trình duyệt của bạn.", elem_id="client-status")
    player = gr.HTML(value=player_html("vxtvWovNKKE"), label="Video lesson")
    gr.HTML('<div id="client-transcript"><div class="transcript-panel"><div class="transcript-head">📝 English transcript</div><div style="padding:18px;color:#64748b">Bấm “Lấy transcript trên trình duyệt”.</div></div></div>')
    gr.Markdown("### 📄 Dự phòng\nNếu YouTube chặn request CORS trên trình duyệt, hãy import `.srt`, `.vtt`, `.txt` hoặc `.json` thủ công.")
    with gr.Row():
        file = gr.File(label="Transcript TXT / SRT / VTT / JSON", file_types=[".txt", ".srt", ".vtt", ".json"], type="filepath")
        text = gr.Textbox(label="Dán transcript", lines=6)
    imp = gr.Button("🚀 Import transcript thủ công")
    parsed = gr.Code(label="🔬 Parsed segments", language="json", lines=10)

    embed.click(load_video, url, [status, player])
    # Keep manual import as a server-side fallback; browser retrieval is the primary path.
    def manual_import(file_obj, text_value):
        raw=text_value or ""
        if file_obj:
            path=getattr(file_obj,'name',file_obj)
            with open(path,'r',encoding='utf-8-sig') as f: raw=f.read()
        rows=[]
        for line in raw.splitlines():
            m=re.match(r'^\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\]?\s*(.*)$',line.strip())
            if m:
                p=m.group(1).replace(',','.').split(':'); start=float(p[-1])+(float(p[-2])*60 if len(p)>=2 else 0)+(float(p[-3])*3600 if len(p)==3 else 0); rows.append({'start':start,'text':m.group(2).strip()})
        return json.dumps(rows,ensure_ascii=False,indent=2)
    imp.click(manual_import,[file,text],parsed)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))