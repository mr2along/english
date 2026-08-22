import json
import os
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from urllib.parse import parse_qs, urlparse

import gradio as gr
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig

WEBSHARE_USERNAME = os.getenv("WEBSHARE_USERNAME", "").strip()
WEBSHARE_PASSWORD = os.getenv("WEBSHARE_PASSWORD", "").strip()
TRANSCRIPT_LIST_TIMEOUT = int(os.getenv("TRANSCRIPT_LIST_TIMEOUT", "45"))
TRANSCRIPT_FETCH_TIMEOUT = int(os.getenv("TRANSCRIPT_FETCH_TIMEOUT", "90"))
PROXY_TEST_TIMEOUT = int(os.getenv("PROXY_TEST_TIMEOUT", "15"))


def extract_video_id(value: str):
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


def make_proxy_url():
    if not (WEBSHARE_USERNAME and WEBSHARE_PASSWORD):
        return None
    return f"http://{WEBSHARE_USERNAME}:{WEBSHARE_PASSWORD}@p.webshare.io:80/"


def test_proxy():
    proxy_url = make_proxy_url()
    if not proxy_url:
        return False, "credentials not configured"
    proxies = {"http": proxy_url, "https": proxy_url}
    try:
        response = requests.get("https://ipv4.webshare.io/", proxies=proxies, timeout=PROXY_TEST_TIMEOUT)
        response.raise_for_status()
        return True, response.text.strip()[:200]
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def make_api():
    print("[TRANSCRIPT] Creating YouTubeTranscriptApi client...", flush=True)
    if WEBSHARE_USERNAME and WEBSHARE_PASSWORD:
        print("[TRANSCRIPT] Webshare credentials: configured", flush=True)
        return YouTubeTranscriptApi(
            proxy_config=WebshareProxyConfig(
                proxy_username=WEBSHARE_USERNAME,
                proxy_password=WEBSHARE_PASSWORD,
            )
        )
    print("[TRANSCRIPT] Webshare credentials: NOT configured; using direct connection", flush=True)
    return YouTubeTranscriptApi()


def _call_with_timeout(fn, timeout):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError:
        future.cancel()
        raise TimeoutError(f"operation timed out after {timeout}s")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def get_transcript(url: str):
    started = time.time()
    logs = []
    timestamp_payload = ""

    def line(message):
        elapsed = time.time() - started
        text = f"[{elapsed:6.2f}s] {message}"
        logs.append(text)
        print(f"[TRANSCRIPT] {text}", flush=True)

    def state(status, transcript=""):
        return status, transcript, "\n".join(logs), timestamp_payload

    video_id = extract_video_id(url)
    if not video_id:
        line("❌ YouTube URL/Video ID không hợp lệ")
        yield state("❌ Link YouTube không hợp lệ.")
        return

    line(f"▶ Bắt đầu tải transcript — video_id={video_id}")
    yield state("⏳ Đang chuẩn bị tải transcript...")

    line("🔧 Khởi tạo YouTubeTranscriptApi + Webshare proxy")
    yield state("⏳ Đã khởi tạo client; chuẩn bị kiểm tra proxy...")

    try:
        api = make_api()
        if WEBSHARE_USERNAME and WEBSHARE_PASSWORD:
            line("🔐 Proxy: Webshare")
            line(f"🌐 Kiểm tra Webshare connectivity... (timeout {PROXY_TEST_TIMEOUT}s)")
            yield state("🌐 Đang kiểm tra kết nối Webshare...")
            ok, detail = test_proxy()
            if not ok:
                line(f"❌ Webshare connectivity failed: {detail}")
                yield state("❌ Webshare proxy không kết nối được. Xem log để kiểm tra credential/network.")
                return
            line(f"✅ Webshare connectivity OK: {detail}")
        else:
            line("🔐 Proxy: direct — Webshare credentials chưa được nạp vào runtime")
            yield state("⚠️ Chưa thấy Webshare credentials trong runtime; đang dùng direct connection...")

        line(f"🌐 Gọi YouTube API: list(video_id)... (timeout {TRANSCRIPT_LIST_TIMEOUT}s)")
        yield state("🌐 Đang gọi YouTube API list() — nếu quá thời gian sẽ báo timeout...")

        transcript_list = _call_with_timeout(lambda: api.list(video_id), TRANSCRIPT_LIST_TIMEOUT)
        line("✅ Nhận danh sách transcript từ YouTube")
        yield state("🔎 Đã nhận danh sách transcript; đang phân tích ngôn ngữ...")

        selected = None
        available = []
        for t in transcript_list:
            available.append(
                f"{t.language_code}{' (translated)' if getattr(t, 'is_translatable', False) else ''}"
            )
        if available:
            line("📋 Transcript khả dụng: " + ", ".join(available))
        else:
            line("⚠️ YouTube trả về danh sách transcript rỗng")
        yield state("🔎 Đang chọn English transcript...")

        line("🔎 Tìm English transcript trực tiếp...")
        for t in transcript_list:
            if t.language_code in {"en", "en-US", "en-GB"}:
                selected = t
                line(f"✅ Đã chọn English transcript: {t.language_code}")
                break

        if selected is None:
            line("ℹ️ Không có English transcript trực tiếp — tìm transcript có thể dịch...")
            for t in transcript_list:
                try:
                    if t.is_translatable:
                        line(f"🔄 Đang dịch {t.language_code} → en...")
                        selected = t.translate("en")
                        line("✅ Đã tạo English transcript bằng translation")
                        break
                except Exception as exc:
                    line(f"⚠️ Không dịch được {getattr(t, 'language_code', '?')}: {exc}")

        if selected is None:
            line("❌ Không tìm thấy English transcript khả dụng")
            yield state("❌ Video không có English transcript khả dụng.")
            return

        line(f"📥 Đang fetch các segment transcript... (timeout {TRANSCRIPT_FETCH_TIMEOUT}s)")
        yield state("📥 Đang tải timestamp + text của từng segment...")
        data = _call_with_timeout(selected.fetch, TRANSCRIPT_FETCH_TIMEOUT)
        line(f"✅ Fetch hoàn tất: {len(data)} segment")
        yield state("🧩 Đang chuẩn hóa transcript và giữ timestamp...")

        lines = []
        for index, item in enumerate(data, 1):
            text = re.sub(r"\s+", " ", item.text).strip()
            if text:
                lines.append(
                    {
                        "index": index,
                        "start": float(getattr(item, "start", 0.0)),
                        "duration": float(getattr(item, "duration", 0.0)),
                        "text": text,
                    }
                )
            if index == 1 or index % 50 == 0 or index == len(data):
                line(f"📝 Xử lý segment {index}/{len(data)}")
                yield state(f"📝 Đang xử lý segment {index}/{len(data)}...")

        if not lines:
            line("❌ Transcript rỗng sau khi xử lý")
            yield state("❌ Transcript rỗng.")
            return

        timestamp_payload = json.dumps(lines, ensure_ascii=False)
        transcript = "\n".join(f"[{item['start']:.2f}s] {item['text']}" for item in lines)

        line(f"🎉 Hoàn tất: {len(lines)} câu/segment, {len(transcript):,} ký tự")
        line(f"⏱ Tổng thời gian: {time.time() - started:.2f}s")
        yield state(
            "✅ Transcript đã tải xong — timestamp đã được giữ lại để đồng bộ YouTube player.",
            transcript,
        )

    except Exception as exc:
        msg = str(exc)
        line(f"❌ LỖI: {type(exc).__name__}: {msg}")
        print("[TRANSCRIPT] Full traceback:", flush=True)
        traceback.print_exc()
        if "RequestBlocked" in msg or "IpBlocked" in msg or "blocked" in msg.lower():
            msg = "YouTube vẫn chặn proxy/IP Webshare. Kiểm tra Webshare proxy hoặc thử IP/proxy khác.\n\n" + msg
        yield state(f"❌ Không lấy được transcript cho {video_id}.\n\n{msg}")


with gr.Blocks(title="English Lab — YouTube Transcript") as demo:
    gr.Markdown("# 🎧 English Lab — YouTube Transcript")
    gr.Markdown("**youtube-transcript-api + Webshare Proxy** — kiểm tra proxy trước, log tiến trình trực tiếp, giữ timestamp để đồng bộ player.")

    with gr.Row():
        url = gr.Textbox(
            label="YouTube URL hoặc Video ID",
            placeholder="https://www.youtube.com/watch?v=vxtvWovNKKE",
            scale=5,
        )
        button = gr.Button("🚀 Lấy English Transcript", variant="primary", scale=2)

    status = gr.Markdown("Sẵn sàng.")
    output = gr.Textbox(label="English Transcript + timestamp", lines=24, show_copy_button=True)
    progress_log = gr.Textbox(
        label="🔎 Log tiến trình tải transcript (live)",
        lines=14,
        max_lines=30,
        show_copy_button=True,
        interactive=False,
    )
    timestamp_payload = gr.Textbox(label="Timestamp data (machine-readable)", visible=False)

    button.click(get_transcript, inputs=url, outputs=[status, output, progress_log, timestamp_payload])
    url.submit(get_transcript, inputs=url, outputs=[status, output, progress_log, timestamp_payload])


if __name__ == "__main__":
    print("[STARTUP] English Lab starting on 0.0.0.0:7860", flush=True)
    demo.launch(server_name="0.0.0.0", server_port=7860, ssr_mode=False)
