import os
import re
import time
import traceback
from urllib.parse import urlparse, parse_qs

import gradio as gr
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import WebshareProxyConfig

# Webshare credentials: move these to HF Secrets after testing.
WEBSHARE_USERNAME = os.getenv("WEBSHARE_USERNAME", "uvhnvfjd")
WEBSHARE_PASSWORD = os.getenv("WEBSHARE_PASSWORD", "ze82v8cwwxpa")


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


def make_api():
    print("[TRANSCRIPT] Creating YouTubeTranscriptApi client...", flush=True)
    return YouTubeTranscriptApi(
        proxy_config=WebshareProxyConfig(
            proxy_username=WEBSHARE_USERNAME,
            proxy_password=WEBSHARE_PASSWORD,
        )
    )


def get_transcript(url: str):
    started = time.time()
    logs = []

    def log(message):
        elapsed = time.time() - started
        line = f"[{elapsed:6.2f}s] {message}"
        logs.append(line)
        print(f"[TRANSCRIPT] {line}", flush=True)
        return "\n".join(logs)

    video_id = extract_video_id(url)
    if not video_id:
        log("❌ YouTube URL/Video ID không hợp lệ")
        return "❌ Link YouTube không hợp lệ.", "", "\n".join(logs)

    log(f"▶ Bắt đầu tải transcript — video_id={video_id}")
    log("🔧 Khởi tạo YouTubeTranscriptApi + Webshare proxy")

    try:
        api = make_api()

        log("🌐 Gọi YouTube API: list(video_id)...")
        transcript_list = api.list(video_id)
        log("✅ Nhận danh sách transcript từ YouTube")

        selected = None
        available = []
        for t in transcript_list:
            available.append(f"{t.language_code}{' (translated)' if getattr(t, 'is_translatable', False) else ''}")

        if available:
            log("📋 Transcript khả dụng: " + ", ".join(available))
        else:
            log("⚠️ YouTube trả về danh sách transcript rỗng")

        # Prefer an English transcript.
        log("🔎 Tìm English transcript trực tiếp...")
        for t in transcript_list:
            if t.language_code in {"en", "en-US", "en-GB"}:
                selected = t
                log(f"✅ Đã chọn English transcript: {t.language_code}")
                break

        # Otherwise find a translatable transcript and translate it.
        if selected is None:
            log("ℹ️ Không có English transcript trực tiếp — tìm transcript có thể dịch...")
            for t in transcript_list:
                try:
                    if t.is_translatable:
                        log(f"🔄 Đang dịch {t.language_code} → en...")
                        selected = t.translate("en")
                        log("✅ Đã tạo English transcript bằng translation")
                        break
                except Exception as exc:
                    log(f"⚠️ Không dịch được {getattr(t, 'language_code', '?')}: {exc}")

        if selected is None:
            log("❌ Không tìm thấy English transcript khả dụng")
            return "❌ Video không có English transcript khả dụng.", "", "\n".join(logs)

        log("📥 Đang fetch các segment transcript...")
        data = selected.fetch()
        log(f"✅ Fetch hoàn tất: {len(data)} segment")

        lines = []
        for index, item in enumerate(data, 1):
            text = re.sub(r"\s+", " ", item.text).strip()
            if text:
                lines.append(text)
            if index == 1 or index % 50 == 0 or index == len(data):
                log(f"📝 Xử lý segment {index}/{len(data)}")

        transcript = " ".join(lines)
        if not transcript:
            log("❌ Transcript rỗng sau khi xử lý")
            return "❌ Transcript rỗng.", "", "\n".join(logs)

        log(f"🎉 Hoàn tất: {len(lines)} câu/segment, {len(transcript):,} ký tự")
        log(f"⏱ Tổng thời gian: {time.time() - started:.2f}s")
        return "✅ Đã lấy English transcript qua YouTubeTranscript API + Webshare", transcript, "\n".join(logs)

    except Exception as exc:
        msg = str(exc)
        log(f"❌ LỖI: {type(exc).__name__}: {msg}")
        print("[TRANSCRIPT] Full traceback:", flush=True)
        traceback.print_exc()
        if "RequestBlocked" in msg or "IpBlocked" in msg or "blocked" in msg.lower():
            msg = "YouTube vẫn chặn proxy/IP Webshare. Hãy thử proxy residential/ISP hoặc proxy khác.\n\n" + msg
        return f"❌ Không lấy được transcript cho {video_id}.\n\n{msg}", "", "\n".join(logs)


with gr.Blocks(title="English Lab — YouTube Transcript") as demo:
    gr.Markdown("# 🎧 English Lab — YouTube Transcript")
    gr.Markdown("**youtube-transcript-api + Webshare Proxy** — không dùng Tactiq, Playwright, yt-dlp hoặc Invidious.")

    with gr.Row():
        url = gr.Textbox(
            label="YouTube URL hoặc Video ID",
            placeholder="https://www.youtube.com/watch?v=vxtvWovNKKE",
            scale=5,
        )
        button = gr.Button("🚀 Lấy English Transcript", variant="primary", scale=2)

    status = gr.Markdown("Sẵn sàng.")
    output = gr.Textbox(label="English Transcript", lines=24, show_copy_button=True)
    progress_log = gr.Textbox(
        label="🔎 Log tiến trình tải transcript",
        lines=14,
        max_lines=30,
        show_copy_button=True,
        interactive=False,
    )

    button.click(get_transcript, inputs=url, outputs=[status, output, progress_log])
    url.submit(get_transcript, inputs=url, outputs=[status, output, progress_log])


if __name__ == "__main__":
    print("[STARTUP] English Lab starting on 0.0.0.0:7860", flush=True)
    demo.launch(server_name="0.0.0.0", server_port=7860, ssr_mode=False)
