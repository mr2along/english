"""Actionable messages for YouTube network failures in hosted runtimes."""

from __future__ import annotations


def connection_help(error: Exception, operation: str) -> str | None:
    details = str(error).casefold()
    network_markers = (
        "ssleoferror", "sslerror", "tls", "max retries exceeded", "connectionerror",
        "connection reset", "connection aborted", "remote end closed", "timed out", "timeout",
    )
    if not any(marker in details for marker in network_markers):
        return None

    if operation == "captions":
        return (
            "Space không kết nối được tới YouTube để lấy phụ đề (lỗi SSL/mạng). "
            "Nếu video công khai mà lỗi vẫn lặp lại, hãy cấu hình proxy residential trong "
            "Secrets của Space bằng cả YOUTUBE_TRANSCRIPT_PROXY_USERNAME và "
            "YOUTUBE_TRANSCRIPT_PROXY_PASSWORD. Có thể dùng Import transcript để nạp SRT/VTT/JSON."
        )

    media = "audio" if operation == "audio" else "video"
    return (
        f"Space không kết nối được tới YouTube để tải {media} (lỗi SSL/mạng). "
        "Hãy thử lại hoặc cấu hình YOUTUBE_AUDIO_PROXY bằng URL proxy đầy đủ trong Secrets của Space."
    )
