"""Fetch YouTube captions or temporarily transcribe audio from a public video."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from core.library import video_id as parse_video_id
from core.youtube_errors import connection_help
from core.whisperx_runner import MAX_MEDIA_DURATION_SECONDS, MAX_MEDIA_FILE_BYTES


def _api():
    from youtube_transcript_api import YouTubeTranscriptApi

    username = os.getenv("YOUTUBE_TRANSCRIPT_PROXY_USERNAME", "").strip()
    password = os.getenv("YOUTUBE_TRANSCRIPT_PROXY_PASSWORD", "").strip()
    if bool(username) != bool(password):
        raise RuntimeError(
            "Cấu hình proxy YouTube chưa đủ: cần cả YOUTUBE_TRANSCRIPT_PROXY_USERNAME "
            "và YOUTUBE_TRANSCRIPT_PROXY_PASSWORD."
        )
    if username and password:
        from youtube_transcript_api.proxies import WebshareProxyConfig

        return YouTubeTranscriptApi(
            proxy_config=WebshareProxyConfig(
                proxy_username=username,
                proxy_password=password,
            )
        )
    return YouTubeTranscriptApi()


def _title(video_id: str) -> str:
    query = urlencode(
        {
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "format": "json",
        }
    )
    request = Request(
        f"https://www.youtube.com/oembed?{query}",
        headers={"User-Agent": "EnglishLearningLab/1.0"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        title = str(data.get("title") or "").strip()
        return title or f"YouTube · {video_id}"
    except Exception:
        return f"YouTube · {video_id}"


def fetch_youtube_transcript(value: str, language: str = "en") -> dict:
    """Fetch a manual or auto-generated YouTube caption track and its timing."""
    video_id = parse_video_id(value)
    if not video_id:
        raise ValueError("Dán URL YouTube hợp lệ hoặc Video ID 11 ký tự.")

    try:
        transcript_list = _api().list(video_id)
        if language == "auto":
            available = list(transcript_list)
            if not available:
                raise LookupError("Video không có track phụ đề khả dụng.")
            track = next(
                (item for item in available if item.language_code == "en"),
                available[0],
            )
        else:
            track = transcript_list.find_transcript([language])
        fetched = track.fetch()
        segments = fetched.to_raw_data()
    except Exception as error:
        error_name = type(error).__name__
        if error_name in {"RequestBlocked", "IpBlocked"}:
            raise RuntimeError(
                "YouTube đang chặn IP máy chủ Space nên chưa lấy được caption. "
                "Có thể cấu hình proxy residential bằng hai biến môi trường "
                "YOUTUBE_TRANSCRIPT_PROXY_USERNAME và YOUTUBE_TRANSCRIPT_PROXY_PASSWORD."
            ) from error
        if error_name in {"TranscriptsDisabled", "NoTranscriptFound", "VideoUnavailable"}:
            raise RuntimeError(
                "Video không có phụ đề ở ngôn ngữ đã chọn, phụ đề bị tắt, "
                "hoặc video không công khai. Hãy chọn chế độ WhisperX để chép lời trực tiếp từ audio."
            ) from error
        if isinstance(error, LookupError):
            raise RuntimeError(str(error)) from error
        if isinstance(error, ValueError):
            raise
        help_message = connection_help(error, "captions")
        if help_message:
            raise RuntimeError(help_message) from error
        raise RuntimeError(f"Không lấy được caption YouTube: {error}") from error

    if not segments:
        raise RuntimeError("YouTube trả về track phụ đề rỗng.")
    return {
        "video_id": video_id,
        "title": _title(video_id),
        "language": getattr(fetched, "language", language),
        "language_code": getattr(fetched, "language_code", language),
        "is_generated": bool(getattr(fetched, "is_generated", False)),
        "segments": segments,
    }


def transcribe_youtube_audio(
    value: str,
    model_name: str = "small",
    language: str = "auto",
    progress_callback=None,
) -> dict:
    """Temporarily fetch audio for one public video and transcribe it with WhisperX."""
    video_id = parse_video_id(value)
    if not video_id:
        raise ValueError("Dán URL YouTube hợp lệ hoặc Video ID 11 ký tự.")

    try:
        from yt_dlp import YoutubeDL
    except ImportError as error:
        raise RuntimeError("Thiếu yt-dlp. Hãy cài dependencies của English Lab rồi thử lại.") from error

    from core.whisperx_runner import transcribe_file

    def report_download(status: dict):
        if not progress_callback:
            return
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            downloaded = status.get("downloaded_bytes") or 0
            fraction = min(1.0, downloaded / total) if total else 0.0
            progress_callback(fraction, "Đang tải audio tạm thời từ YouTube")
        elif status.get("status") == "finished":
            progress_callback(1.0, "Đã tải audio · đang nhận dạng bằng WhisperX")

    def limit_video(info: dict, *, incomplete: bool = False):
        if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
            return "Không hỗ trợ livestream hoặc buổi phát trực tiếp sắp diễn ra."
        try:
            duration = float(info.get("duration"))
        except (TypeError, ValueError):
            return "Không xác định được thời lượng video nên đã dừng để bảo vệ tài nguyên Space."
        if duration <= 0:
            return "Video không có thời lượng hợp lệ."
        if duration > MAX_MEDIA_DURATION_SECONDS:
            return "Video dài hơn giới hạn 2 giờ cho chép lời online."
        return None

    with tempfile.TemporaryDirectory(prefix="english-lab-youtube-") as temporary_dir:
        output_template = str(Path(temporary_dir) / "%(id)s.%(ext)s")
        options = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
            "retries": 2,
            "fragment_retries": 2,
            "max_filesize": MAX_MEDIA_FILE_BYTES,
            "match_filter": limit_video,
            "progress_hooks": [report_download],
        }
        audio_proxy = os.getenv("YOUTUBE_AUDIO_PROXY", "").strip()
        if audio_proxy:
            options["proxy"] = audio_proxy
        try:
            with YoutubeDL(options) as downloader:
                info = downloader.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}", download=True
                )
                if not isinstance(info, dict) or info.get("entries"):
                    raise RuntimeError("Không thể đọc thông tin video đơn lẻ từ YouTube.")
                audio_path = Path(downloader.prepare_filename(info))
            if not audio_path.is_file():
                candidates = [
                    path for path in Path(temporary_dir).glob(f"{video_id}.*")
                    if path.is_file() and not path.name.endswith((".part", ".ytdl"))
                ]
                audio_path = candidates[0] if candidates else audio_path
            if not audio_path.is_file() or audio_path.stat().st_size == 0:
                raise RuntimeError("yt-dlp không tạo được tệp audio.")
            if audio_path.stat().st_size > MAX_MEDIA_FILE_BYTES:
                raise RuntimeError("Audio vượt giới hạn kích thước 512 MB.")
            if progress_callback:
                progress_callback(0.0, "Đang chép lời bằng WhisperX")
            result = transcribe_file(
                audio_path,
                model_name=model_name,
                language=None if language == "auto" else language,
                device="auto",
                compute_type="int8",
                batch_size=2,
                align_words=True,
            )
        except Exception as error:
            if isinstance(error, (RuntimeError, ValueError)):
                raise
            help_message = connection_help(error, "audio")
            if help_message:
                raise RuntimeError(help_message) from error
            raise RuntimeError(f"Không tải/chép lời được video YouTube: {error}") from error

    result.update(
        {
            "video_id": video_id,
            "title": _title(video_id),
            "source": "youtube_whisperx",
        }
    )
    return result
