"""Local-only media downloader for desktop Chrome and Android Chrome."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.library import video_id as parse_video_id  # noqa: E402
from core.youtube_download import download_youtube_audio, download_youtube_video  # noqa: E402


HOST = "127.0.0.1"
PORT = 8765
MAX_REQUEST_BYTES = 8192
JOB_RETENTION_SECONDS = 60 * 60
DEFAULT_DOWNLOAD_DIRECTORY = (
    Path.home() / "storage" / "downloads" / "English Lab Videos"
    if "com.termux" in os.environ.get("PREFIX", "")
    else Path.home() / "Downloads" / "English Lab Videos"
)
DOWNLOAD_DIRECTORY = Path(
    os.environ.get("ENGLISH_LAB_DOWNLOAD_DIR", str(DEFAULT_DOWNLOAD_DIRECTORY))
).expanduser()
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
DOWNLOAD_LOCK = threading.Lock()


DOWNLOAD_PAGE = r"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>English Lab · Tải audio/video</title>
  <style>
    *{box-sizing:border-box}body{margin:0;padding:16px;background:#f1f5f9;color:#0f172a;font:16px/1.55 system-ui,sans-serif}
    main{max-width:620px;margin:4vh auto;padding:22px;border:1px solid #dbe4f0;border-radius:18px;background:#fff;box-shadow:0 8px 28px #0f172a12}
    h1{margin:0 0 8px;font-size:24px}p{color:#475569}.field{display:block;margin:18px 0 7px;font-weight:650}
    input,select,button{width:100%;min-height:48px;border:1px solid #cbd5e1;border-radius:10px;padding:10px 12px;font:inherit}
    button{margin-top:16px;border:0;background:#2563eb;color:white;font-weight:700;cursor:pointer}button:disabled{opacity:.65;cursor:wait}
    .status{margin-top:18px;padding:14px;border-radius:12px;background:#eff6ff;overflow-wrap:anywhere}
    .bar{height:8px;margin-top:12px;border-radius:99px;background:#dbeafe;overflow:hidden}.fill{width:0;height:100%;background:#2563eb;transition:width .25s}
    .note{font-size:14px}code{overflow-wrap:anywhere}
  </style>
</head>
<body>
  <main>
    <h1>⬇️ Tải media cho English Lab</h1>
    <p>Nhập link YouTube để tải audio riêng hoặc video đầy đủ về thiết bị này. Công cụ không ghi âm tab đang phát.</p>
    <form id="download-form">
      <label class="field" for="video-url">Link YouTube</label>
      <input id="video-url" type="url" inputmode="url" autocomplete="url" placeholder="https://www.youtube.com/watch?v=…" required>
      <label class="field" for="media-type">Tệp muốn tải</label>
      <select id="media-type">
        <option value="audio">Chỉ audio · tệp nhỏ hơn để đưa vào WhisperX</option>
        <option value="video">Video đầy đủ · giữ cả hình và tiếng</option>
      </select>
      <button id="start" type="submit">⬇️ Tải audio về thiết bị</button>
    </form>
    <div id="status" class="status" role="status" aria-live="polite">Tệp sẽ được lưu trong Downloads/English Lab Videos.</div>
    <div class="bar"><div id="fill" class="fill"></div></div>
    <p id="next" class="note" hidden>Mở English Lab Space → tab <b>WhisperX · video/audio</b> → chọn tệp trong <code>Downloads/English Lab Videos</code> → chạy WhisperX. Audio/video được tải từ đầu video nên timestamp tính từ mốc 00:00.</p>
    <p class="note">Chỉ tải nội dung bạn sở hữu hoặc được phép tải. Giới hạn mỗi tệp: 2 giờ / 512 MB.</p>
  </main>
  <script>
    const statusBox=document.querySelector('#status');
    const fill=document.querySelector('#fill');
    const next=document.querySelector('#next');
    const form=document.querySelector('#download-form');
    const urlInput=document.querySelector('#video-url');
    const mediaInput=document.querySelector('#media-type');
    const startButton=document.querySelector('#start');
    const query=new URLSearchParams(location.search);
    urlInput.value=query.get('url')||'';
    if(['audio','video'].includes(query.get('type')))mediaInput.value=query.get('type');
    const showError=message=>{statusBox.textContent='❌ '+message;fill.style.background='#dc2626'};
    const updateButton=()=>{startButton.textContent='⬇️ Tải '+(mediaInput.value==='audio'?'audio':'video')+' về thiết bị'};
    mediaInput.addEventListener('change',updateButton);
    async function readJob(jobId){
      const response=await fetch('/api/jobs/'+encodeURIComponent(jobId));
      const job=await response.json();
      if(!response.ok)throw new Error(job.error||'Không đọc được trạng thái tải.');
      statusBox.textContent=job.message||'Đang tải video…';
      fill.style.width=Math.max(0,Math.min(100,Number(job.progress||0)*100))+'%';
      if(job.state==='completed'){
        statusBox.textContent='✅ Đã lưu '+(job.media_type==='audio'?'audio':'video')+': '+job.file_name;
        next.hidden=false;
        return;
      }
      if(job.state==='failed')throw new Error(job.error||'Tải video thất bại.');
      await new Promise(resolve=>window.setTimeout(resolve,1000));
      return readJob(jobId);
    }
    async function start(event){
      event.preventDefault();
      startButton.disabled=true;
      next.hidden=true;
      fill.style.background='#2563eb';
      statusBox.textContent='Đang yêu cầu tải…';
      try{
        const response=await fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:urlInput.value.trim(),media_type:mediaInput.value})});
        const result=await response.json();
        if(!response.ok)throw new Error(result.error||'Không bắt đầu được lượt tải.');
        await readJob(result.job_id);
      }catch(error){showError(error.message||'Không tải được tệp.')}
      finally{startButton.disabled=false;updateButton()}
    }
    form.addEventListener('submit',start);
    updateButton();
    if(urlInput.value)form.requestSubmit();
  </script>
</body>
</html>"""


def _prune_jobs(now: float | None = None) -> None:
    current = now or time.time()
    with JOBS_LOCK:
        expired = [
            job_id
            for job_id, job in JOBS.items()
            if current - job.get("updated_at", current) > JOB_RETENTION_SECONDS
        ]
        for job_id in expired:
            JOBS.pop(job_id, None)


def _update_job(job_id: str, **updates) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is not None:
            job.update(updates, updated_at=time.time())


def _run_download(job_id: str, value: str, media_type: str) -> None:
    downloader = download_youtube_audio if media_type == "audio" else download_youtube_video
    _update_job(
        job_id,
        state="downloading",
        message=f"Đang tải {media_type} về thiết bị…",
        progress=0.0,
    )
    try:
        result = downloader(
            value,
            progress_callback=lambda fraction, description: _update_job(
                job_id,
                message=description,
                progress=float(fraction),
            ),
        )
        DOWNLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
        source = Path(result["path"])
        destination = DOWNLOAD_DIRECTORY / source.name
        if destination.exists():
            destination = DOWNLOAD_DIRECTORY / (
                f"{source.stem}-{uuid.uuid4().hex[:6]}{source.suffix}"
            )
        shutil.copy2(source, destination)
        _update_job(
            job_id,
            state="completed",
            progress=1.0,
            message=f"Tải {media_type} hoàn tất.",
            media_type=media_type,
            file_name=destination.name,
        )
    except Exception as error:
        _update_job(
            job_id,
            state="failed",
            message="Không tải được video.",
            error=str(error),
        )


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "EnglishLabVideoHelper/1.0"

    def log_message(self, format_string: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {format_string % args}")

    def _json(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        _prune_jobs()
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"ok": True, "service": "english-lab-video-helper"})
            return
        if parsed.path in {"/", "/download"}:
            query = parse_qs(parsed.query)
            value = query.get("url", [""])[0]
            if value and not parse_video_id(value):
                self._json(400, {"error": "URL YouTube không hợp lệ."})
                return
            body = DOWNLOAD_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.removeprefix("/api/jobs/")
            if not re.fullmatch(r"[a-f0-9]{32}", job_id):
                self._json(404, {"error": "Không tìm thấy lượt tải này."})
                return
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                payload = dict(job) if job else None
            if payload is None:
                self._json(404, {"error": "Lượt tải đã hết hạn. Hãy bấm tiện ích để thử lại."})
            else:
                self._json(200, payload)
            return
        self._json(404, {"error": "Không tìm thấy đường dẫn."})

    def do_POST(self) -> None:
        _prune_jobs()
        if urlparse(self.path).path != "/api/download":
            self._json(404, {"error": "Không tìm thấy đường dẫn."})
            return
        origin = self.headers.get("Origin")
        if origin != f"http://{HOST}:{PORT}":
            self._json(403, {"error": "Yêu cầu phải xuất phát từ bộ trợ giúp trên máy này."})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "Yêu cầu không hợp lệ."})
            return
        if not 1 <= content_length <= MAX_REQUEST_BYTES:
            self._json(413, {"error": "Dữ liệu yêu cầu quá lớn hoặc đang trống."})
            return
        try:
            request = json.loads(self.rfile.read(content_length))
            value = str(request.get("url") or "").strip()
            media_type = str(request.get("media_type") or "video").strip().lower()
        except (json.JSONDecodeError, AttributeError, UnicodeDecodeError):
            self._json(400, {"error": "Không đọc được URL video."})
            return
        video_id = parse_video_id(value)
        if not video_id:
            self._json(400, {"error": "Dán URL YouTube hợp lệ rồi thử lại."})
            return
        if media_type not in {"audio", "video"}:
            self._json(400, {"error": "Hãy chọn tải audio hoặc video."})
            return
        if not DOWNLOAD_LOCK.acquire(blocking=False):
            self._json(409, {"error": "Một video khác đang được tải. Hãy đợi video đó hoàn tất."})
            return
        job_id = uuid.uuid4().hex
        with JOBS_LOCK:
            JOBS[job_id] = {
                "state": "queued",
                "message": f"Đang chuẩn bị tải {media_type}…",
                "progress": 0.0,
                "media_type": media_type,
                "updated_at": time.time(),
            }

        def run_with_lock():
            try:
                _run_download(job_id, value, media_type)
            finally:
                DOWNLOAD_LOCK.release()

        threading.Thread(target=run_with_lock, daemon=True).start()
        self._json(202, {"job_id": job_id})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), RequestHandler)
    print(f"English Lab video helper is running at http://{HOST}:{PORT}")
    print(f"Downloaded files will be saved in: {DOWNLOAD_DIRECTORY}")
    print("Keep this window open while using the browser extension. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping English Lab video helper…")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
