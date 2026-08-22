import os
import re
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
    return YouTubeTranscriptApi(
        proxy_config=WebshareProxyConfig(
            proxy_username=WEBSHARE_USERNAME,
            proxy_password=WEBSHARE_PASSWORD,
        )
    )


def get_transcript(url: str):
    video_id = extract_video_id(url)
    if not video_id:
        return "❌ Link YouTube không hợp lệ.", ""

    try:
        api = make_api()
        transcript_list = api.list(video_id)

        # Prefer an English transcript. If English is unavailable, use a
        # translatable transcript and translate it to English when possible.
        selected = None
        for t in transcript_list:
            if t.language_code in {"en", "en-US", "en-GB"}:
                selected = t
                break

        if selected is None:
            for t in transcript_list:
                try:
                    if t.is_translatable:
                        selected = t.translate("en")
                        break
                except Exception:
                    continue

        if selected is None:
            return "❌ Video không có English transcript khả dụng.", ""

        data = selected.fetch()
        lines = []
        for item in data:
            text = re.sub(r"\s+", " ", item.text).strip()
            if text:
                lines.append(text)

        transcript = " ".join(lines)
        if not transcript:
            return "❌ Transcript rỗng.", ""

        return "✅ Đã lấy English transcript qua YouTubeTranscript API + Webshare", transcript

    except Exception as exc:
        msg = str(exc)
        if "RequestBlocked" in msg or "IpBlocked" in msg or "blocked" in msg.lower():
            msg = "YouTube vẫn chặn proxy/IP Webshare. Hãy thử proxy residential/ISP hoặc proxy khác.\n\n" + msg
        return f"❌ Không lấy được transcript cho {video_id}.\n\n{msg}", ""


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

    button.click(get_transcript, inputs=url, outputs=[status, output])
    url.submit(get_transcript, inputs=url, outputs=[status, output])


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, ssr_mode=False)
