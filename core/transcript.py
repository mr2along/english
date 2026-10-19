"""Transcript parsing and display helpers."""

from __future__ import annotations

import html
import json
import math
import re
from typing import Any


def format_time(seconds: Any) -> str:
    try:
        value = float(seconds or 0)
    except (TypeError, ValueError):
        value = 0.0
    if not math.isfinite(value):
        value = 0.0
    total = max(0, int(value))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def estimate_duration(text: Any) -> float:
    """Give a timestamp-only final sentence a short playable interval."""
    word_count = len(str(text or "").split())
    return round(max(1.0, min(30.0, word_count / 2.8)), 3)


def render_transcript_html(segments: list[dict[str, Any]], visible: bool = True) -> str:
    """Render transcript controls, retaining them in the DOM when text is hidden."""
    if not segments:
        return (
            '<div class="panel"><div class="panel-title">📝 Transcript</div>'
            '<div class="empty">Chưa có transcript.</div></div>'
        )
    rows = []
    for index, segment in enumerate(segments):
        try:
            start = max(0.0, float(segment.get("start", 0) or 0))
            duration = max(0.0, float(segment.get("duration", 0) or 0))
        except (TypeError, ValueError):
            start, duration = 0.0, 0.0
        end = start + duration
        sentence = html.escape(str(segment.get("text", "")), quote=False)
        rows.append(
            f'<button type="button" class="line" data-index="{index}" '
            f'data-start="{start:.3f}" data-end="{end:.3f}" '
            f'aria-label="Phát câu {index + 1}, bắt đầu lúc {format_time(start)}">'
            f'<span class="time">{format_time(start)}</span>'
            f'<span class="line-text">{sentence}</span></button>'
        )
    hidden_class = " transcript-hidden" if not visible else ""
    return (
        '<div class="panel"><div class="panel-title"><span>📝 Transcript</span>'
        f'<span class="count">{len(segments):,} câu</span></div>'
        f'<div class="lines{hidden_class}">{"".join(rows)}</div></div>'
    )


def to_json(segments: Any) -> str:
    return json.dumps(segments or [], ensure_ascii=False, indent=2)


_TIMESTAMP = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3})\s+-->\s+"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3})"
)


def _seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def _clean_caption(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _json_segments(data: Any, video_id: str | None = None) -> Any:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("videos"), list):
        videos = data["videos"]
        video = next(
            (item for item in videos if isinstance(item, dict) and item.get("video_id") == video_id),
            None,
        ) if video_id else None
        if video is None and len(videos) == 1:
            only_video = videos[0]
            if isinstance(only_video, dict):
                # Importing a one-video file overlays the currently selected lesson.
                # Its source ID can differ from the lesson ID in the UI.
                video = only_video
        if not isinstance(video, dict):
            return []
        return video.get("segments") or video.get("transcript") or []
    return data.get("transcript") or data.get("segments") or []


def parse_manual(raw: str, video_id: str | None = None) -> list[dict[str, Any]]:
    """Parse JSON, SRT, WebVTT, or ``[m:ss] text`` into normalized segments."""
    raw = raw or ""
    if not raw.strip():
        return []
    stripped = raw.lstrip()
    is_json = stripped.startswith("{") or (
        stripped.startswith("[") and stripped[1:].lstrip().startswith(("{", "["))
    )
    if is_json:
        data = json.loads(raw)
        source = _json_segments(data, video_id)
        if (
            not source
            and isinstance(data, dict)
            and isinstance(data.get("videos"), list)
            and len(data["videos"]) > 1
            and not any(
                isinstance(item, dict) and item.get("video_id") == video_id
                for item in data["videos"]
            )
        ):
            raise ValueError("JSON có nhiều bài; hãy chọn bài học tương ứng trước khi xem trước.")
        return normalize(source)

    out: list[dict[str, Any]] = []
    lines = raw.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines):
        cue = _TIMESTAMP.search(lines[i])
        if cue:
            start = _seconds(cue.group("start"))
            end = _seconds(cue.group("end"))
            i += 1
            text: list[str] = []
            while i < len(lines) and lines[i].strip():
                if _TIMESTAMP.search(lines[i]):
                    break
                text.append(lines[i].strip())
                i += 1
            caption = _clean_caption(" ".join(text))
            if caption and math.isfinite(start) and math.isfinite(end) and end >= start:
                out.append(
                    {
                        "index": len(out),
                        "start": start,
                        "duration": end - start,
                        "text": caption,
                    }
                )
            continue
        i += 1
    if out:
        return normalize(out)

    # Plain text format: [m:ss] caption.
    for line in lines:
        line = line.strip()
        match = re.match(
            r"^\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\]?\s*(.*)$",
            line,
        )
        if not match:
            continue
        start = _seconds(match.group(1))
        caption = _clean_caption(match.group(2))
        if caption and math.isfinite(start):
            out.append(
                {"index": len(out), "start": start, "duration": 0.0, "text": caption}
            )
    for index in range(len(out) - 1):
        out[index]["duration"] = max(0.0, out[index + 1]["start"] - out[index]["start"])
    return normalize(out)


def normalize(raw: Any) -> list[dict[str, Any]]:
    out = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        text = _clean_caption(str(item.get("text") or item.get("utf8") or ""))
        if not text:
            continue
        try:
            start = float(item.get("start", item.get("start_time", 0)) or 0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(start) or start < 0:
            continue
        try:
            duration = float(item.get("duration", 0) or 0)
            if item.get("end") is not None or item.get("end_time") is not None:
                end = float(item.get("end", item.get("end_time")) or start)
                duration = end - start
        except (TypeError, ValueError):
            duration = 0.0
        if not math.isfinite(duration) or duration < 0:
            duration = 0.0
        segment = {
            "index": len(out),
            "start": start,
            "duration": duration,
            "text": text,
        }
        words = item.get("words")
        if isinstance(words, list):
            aligned_words = []
            for word in words:
                if not isinstance(word, dict):
                    continue
                token = _clean_caption(str(word.get("word") or ""))
                try:
                    word_start = float(word.get("start"))
                    word_end = float(word.get("end", word_start))
                except (TypeError, ValueError):
                    continue
                if (
                    token
                    and math.isfinite(word_start)
                    and math.isfinite(word_end)
                    and 0 <= word_start <= word_end
                ):
                    aligned_words.append(
                        {"word": token, "start": word_start, "end": word_end}
                    )
            if aligned_words:
                segment["words"] = aligned_words
                if not segment["duration"]:
                    word_end = max(word["end"] for word in aligned_words)
                    if word_end > start:
                        segment["duration"] = word_end - start
        out.append(segment)
    for index in range(len(out) - 1):
        if not out[index]["duration"]:
            out[index]["duration"] = max(0.0, out[index + 1]["start"] - out[index]["start"])
    for segment in out:
        if not segment["duration"]:
            segment["duration"] = estimate_duration(segment["text"])
    return out


def active_index(segments: list[dict[str, Any]], current_time: float) -> int:
    try:
        timestamp = float(current_time or 0)
    except (TypeError, ValueError):
        timestamp = 0.0
    for index, item in enumerate(segments):
        start = float(item.get("start", 0) or 0)
        end = start + max(float(item.get("duration", 0) or 0), 0.25)
        if start <= timestamp < end:
            return index
    return max(0, len(segments) - 1) if segments and timestamp >= segments[-1]["start"] else -1
