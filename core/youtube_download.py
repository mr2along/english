"""Bounded download of public YouTube videos for the current app session."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from core.library import video_id as parse_video_id
from core.youtube_errors import connection_help
from core.whisperx_runner import MAX_MEDIA_DURATION_SECONDS, MAX_MEDIA_FILE_BYTES


DOWNLOAD_TTL_SECONDS = 5 * 60
DOWNLOAD_CACHE_DIR = Path(tempfile.gettempdir()) / "english-lab-youtube-downloads"
VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi", ".flv"}
AUDIO_SUFFIXES = {".m4a", ".mp3", ".opus", ".ogg", ".aac", ".wav"}


def _cleanup_downloads(now: float | None = None) -> None:
    now = now or time.time()
    DOWNLOAD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for path in DOWNLOAD_CACHE_DIR.iterdir():
        try:
            if path.is_file() and now - path.stat().st_mtime > DOWNLOAD_TTL_SECONDS:
                path.unlink()
        except OSError:
            continue


def _schedule_cleanup(path: Path) -> None:
    def remove_file():
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    cleanup = threading.Timer(DOWNLOAD_TTL_SECONDS, remove_file)
    cleanup.daemon = True
    cleanup.start()


def download_youtube_video(value: str, progress_callback: Callable | None = None) -> dict:
    """Download one public, non-live YouTube video to a short-lived local file."""
    video_id = parse_video_id(value or "")
    if not video_id:
        raise ValueError("Dán URL YouTube hợp lệ hoặc Video ID 11 ký tự.")

    try:
        from yt_dlp import YoutubeDL
    except ImportError as error:
        raise RuntimeError("Thiếu yt-dlp. Hãy cài dependencies của English Lab rồi thử lại.") from error

    _cleanup_downloads()

    def report_download(status: dict):
        if not progress_callback:
            return
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            downloaded = status.get("downloaded_bytes") or 0
            fraction = min(1.0, downloaded / total) if total else 0.0
            progress_callback(fraction, "Đang tải video YouTube")
        elif status.get("status") == "finished":
            progress_callback(1.0, "Đã tải video · đang chuẩn bị file tải xuống")

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
            return "Video dài hơn giới hạn 2 giờ cho mỗi lần tải."
        size = info.get("filesize") or info.get("filesize_approx")
        try:
            if size is not None and int(size) > MAX_MEDIA_FILE_BYTES:
                return "Video vượt giới hạn dung lượng 512 MB."
        except (TypeError, ValueError, OverflowError):
            pass
        return None

    with tempfile.TemporaryDirectory(prefix="english-lab-video-") as temporary_dir:
        options = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": str(Path(temporary_dir) / "%(id)s.%(ext)s"),
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
                    raise RuntimeError("Không thể tải video đơn lẻ từ URL này.")
                if str(info.get("id") or "") != video_id:
                    raise RuntimeError("YouTube trả về video không khớp với URL đã nhập.")
                expected_path = Path(downloader.prepare_filename(info))

            candidates = [
                path
                for path in Path(temporary_dir).glob(f"{video_id}.*")
                if path.is_file()
                and path.suffix.lower() in VIDEO_SUFFIXES
                and not path.name.endswith((".part", ".ytdl"))
            ]
            if expected_path.is_file() and expected_path.suffix.lower() in VIDEO_SUFFIXES:
                video_path = expected_path
            elif candidates:
                video_path = max(candidates, key=lambda item: item.stat().st_size)
            else:
                raise RuntimeError("yt-dlp không tạo được file video có thể tải xuống.")

            size = video_path.stat().st_size
            if size <= 0:
                raise RuntimeError("File video tải về đang rỗng.")
            if size > MAX_MEDIA_FILE_BYTES:
                raise RuntimeError("Video vượt giới hạn dung lượng 512 MB.")
            if video_path.suffix.lower() in AUDIO_SUFFIXES:
                raise RuntimeError("YouTube chỉ trả về audio, không tìm thấy luồng video.")

            title = str(info.get("title") or f"YouTube {video_id}").strip()
            safe_title = re.sub(r"[^\w .()-]+", "_", title, flags=re.UNICODE).strip(" .")
            safe_title = (safe_title or "youtube_video")[:80]
            DOWNLOAD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            result_path = DOWNLOAD_CACHE_DIR / (
                f"{safe_title} [{video_id}] {uuid.uuid4().hex[:8]}{video_path.suffix.lower()}"
            )
            shutil.move(str(video_path), result_path)
            duration = float(info.get("duration") or 0)
        except Exception as error:
            if isinstance(error, (RuntimeError, ValueError)):
                raise
            help_message = connection_help(error, "video")
            if help_message:
                raise RuntimeError(help_message) from error
            raise RuntimeError(f"Không tải được video YouTube: {error}") from error

    _schedule_cleanup(result_path)
    if progress_callback:
        progress_callback(1.0, "Hoàn tất")
    return {
        "video_id": video_id,
        "title": title,
        "path": str(result_path),
        "duration": duration,
        "size_bytes": size,
    }
