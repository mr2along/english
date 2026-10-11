#!/usr/bin/env python3
"""English Learning Lab Gradio application."""

from __future__ import annotations

import html
import hashlib
import json
import os
import random
import re
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from importlib.util import find_spec
from pathlib import Path
from typing import Any
from urllib.parse import quote

import gradio as gr

from core.ai_tutor import explain, grammar_request, vocabulary_request
from core.learning_engine import make_practice_items
from core.library import load, video_id
from core.practice import make_quiz
from core.progress import ProgressStore
from core.transcript import format_time, parse_manual, to_json
from core.whisperx_runner import (
    SUPPORTED_AUDIO_SUFFIXES,
    YOUTUBE_ID_RE,
    make_payload,
    transcribe_file,
    write_outputs,
)


BASE = Path(__file__).resolve().parent
LIB, SOURCE, ERROR = load(BASE)
VIDEOS = LIB.get("videos", [])
MAP = {video.get("video_id"): video for video in VIDEOS if video.get("video_id")}
TOTAL = sum(len(video.get("transcript", [])) for video in VIDEOS)
DEFAULT = VIDEOS[0]["video_id"] if VIDEOS else ""
EMPTY_PROGRESS = {"lessons": {}, "words": {}, "reviews": {}}


def choices() -> list[tuple[str, str]]:
    return [
        (f"{index + 1:03d} · {video.get('title', video['video_id'])}", video["video_id"])
        for index, video in enumerate(VIDEOS)
    ]


def yt(vid: str | None) -> str:
    valid_id = video_id(vid or "")
    if not valid_id or valid_id not in MAP:
        return '<div class="empty">Chưa chọn video.</div>'
    safe_id = html.escape(valid_id, quote=True)
    url_id = quote(valid_id, safe="")
    return (
        '<div class="video">'
        f'<iframe id="ytplayer" title="YouTube video player for {safe_id}" '
        f'src="https://www.youtube.com/embed/{url_id}?enablejsapi=1&amp;playsinline=1&amp;rel=0" '
        'loading="lazy" referrerpolicy="strict-origin-when-cross-origin" '
        'allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>'
        '</div>'
        f'<div class="video-link">🎬 {safe_id} · '
        f'<a target="_blank" rel="noopener noreferrer" '
        f'href="https://www.youtube.com/watch?v={url_id}">Mở YouTube</a></div>'
    )


def transcript_html(segments: list[dict[str, Any]]) -> str:
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
    return (
        '<div class="panel"><div class="panel-title"><span>📝 Transcript</span>'
        f'<span class="count">{len(segments):,} câu</span></div>'
        f'<div class="lines">{"".join(rows)}</div></div>'
    )


def _store(progress_data: Any = None) -> ProgressStore:
    return ProgressStore(data=progress_data or EMPTY_PROGRESS)


def progress_stat(progress_data: Any = None) -> str:
    store = _store(progress_data)
    practiced_lessons = {
        str(video_id).split(":import:", 1)[0]
        for video_id, item in store.data["lessons"].items()
        if isinstance(item, dict)
        and (bool(item.get("sentences")) or bool(item.get("completed")))
    }
    due = store.due_count()
    return (
        '<div class="stat"><div class="num">'
        f"{len(practiced_lessons):,}</div><div class=\"label\">📈 Bài đã luyện · {due:,} câu đến hạn</div></div>"
    )


def lesson_status(
    vid: str | None, progress_data: Any = None, transcript_override: Any = None
) -> str:
    video = MAP.get(vid)
    if not video:
        return "Chưa chọn bài học."
    segments = effective_segments(vid, transcript_override)
    lesson = _store(progress_data).lesson(progress_scope(vid, transcript_override))
    done = sum(
        1
        for key, value in lesson.get("sentences", {}).items()
        if value and str(key).isdigit() and int(key) < len(segments)
    )
    percent = round(done / len(segments) * 100) if segments else 0
    title = html.escape(str(video.get("title", vid)))
    source = html.escape(
        "session_import" if transcript_override else video.get("transcript_source", "final_transcript")
    )
    alignment = html.escape(
        "user_imported" if transcript_override else video.get("alignment", "final_alignment")
    )
    raw_count = len(segments) if transcript_override else len(video.get("raw_transcript", segments))
    return (
        f"### 🎯 {video.get('position', '')} · {title}\n"
        f"`{vid}` · {video.get('language', 'en')} · **{len(segments):,} câu** · **{percent}% đã luyện**\n\n"
        f"📦 Source: `{source}` · 🔗 Alignment: `{alignment}` · Raw: {raw_count:,}"
    )


def effective_segments(vid: str | None, transcript_override: Any = None):
    if (
        isinstance(transcript_override, dict)
        and transcript_override.get("video_id") == vid
        and isinstance(transcript_override.get("segments"), list)
    ):
        return transcript_override["segments"]
    return MAP.get(vid, {}).get("transcript", [])


def progress_scope(vid: str | None, transcript_override: Any = None) -> str | None:
    """Keep practice progress for imported session transcripts separate."""
    if not vid:
        return None
    if (
        isinstance(transcript_override, dict)
        and transcript_override.get("video_id") == vid
        and isinstance(transcript_override.get("segments"), list)
    ):
        canonical = json.dumps(
            transcript_override["segments"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
        return f"{vid}:import:{fingerprint}"
    return vid


def select(vid: str | None, progress_data: Any = None, transcript_override: Any = None):
    if vid not in MAP:
        return (
            "❌ Không tìm thấy bài học.",
            yt(None),
            transcript_html([]),
            "[]",
            None,
            "",
            progress_data or EMPTY_PROGRESS,
            0,
            "",
            None,
        )
    store = _store(progress_data)
    video = MAP[vid]
    active_override = (
        transcript_override
        if isinstance(transcript_override, dict) and transcript_override.get("video_id") == vid
        else None
    )
    segments = effective_segments(vid, active_override)
    return (
        lesson_status(vid, store.data, active_override),
        yt(vid),
        transcript_html(segments),
        to_json(segments),
        vid,
        f"https://www.youtube.com/watch?v={vid}",
        store.data,
        0,
        sentence_for(vid, 0, active_override),
        active_override,
    )


def open_url(value: str | None, progress_data: Any = None, transcript_override: Any = None):
    vid = video_id(value or "")
    if vid in MAP:
        return select(vid, progress_data, transcript_override)
    return (
        "❌ URL/Video ID không có trong thư viện bài học.",
        yt(None),
        transcript_html([]),
        "[]",
        None,
        value or "",
        progress_data or EMPTY_PROGRESS,
        0,
        "",
        None,
    )


def search(query: str | None, current: str | None):
    query = (query or "").strip().casefold()
    matches = [
        item
        for item in choices()
        if not query or query in f"{item[0]} {item[1]}".casefold()
    ]
    values = {value for _, value in matches}
    selected = current if current in values else (matches[0][1] if len(matches) == 1 else None)
    return gr.update(choices=matches, value=selected)


def move(vid: str | None, direction: int):
    ids = list(MAP)
    if not ids:
        return None
    try:
        index = ids.index(vid)
    except ValueError:
        index = 0
    return ids[(index + direction) % len(ids)]


def sentence_for(vid: str | None, index: Any, transcript_override: Any = None) -> str:
    segments = effective_segments(vid, transcript_override)
    if not segments:
        return ""
    try:
        number = int(float(index))
    except (TypeError, ValueError, OverflowError):
        number = 0
    number = max(0, min(number, len(segments) - 1))
    return str(segments[number].get("text", ""))


def mark_sentence(
    vid: str | None,
    index: Any,
    progress_data: Any = None,
    transcript_override: Any = None,
):
    if vid not in MAP:
        return "Chưa chọn bài.", "Chưa chọn bài học.", progress_data or EMPTY_PROGRESS
    segments = effective_segments(vid, transcript_override)
    try:
        number = int(float(index))
    except (TypeError, ValueError, OverflowError):
        number = -1
    if not segments:
        return "Bài này chưa có transcript.", lesson_status(vid, progress_data, transcript_override), progress_data or EMPTY_PROGRESS
    if number < 0 or number >= len(segments):
        return (
            f"❌ Số câu phải nằm trong khoảng 0–{len(segments) - 1}.",
            lesson_status(vid, progress_data, transcript_override),
            progress_data or EMPTY_PROGRESS,
        )
    store = _store(progress_data)
    store.mark_sentence(progress_scope(vid, transcript_override), number, len(segments))
    return f"✅ Đã đánh dấu câu {number + 1}.", lesson_status(vid, store.data, transcript_override), store.data


def practice(vid: str | None, progress_data: Any = None, transcript_override: Any = None):
    video = MAP.get(vid)
    if not video:
        return "Chưa chọn bài.", 0, ""
    items = make_practice_items(effective_segments(vid, transcript_override))
    if not items:
        return "Bài này chưa có câu để luyện.", 0, ""
    lesson = _store(progress_data).lesson(progress_scope(vid, transcript_override))
    completed_indices = {
        str(item["index"])
        for item in items
        if lesson["sentences"].get(str(item["index"]))
    }
    completed = len(completed_indices)
    next_item = next(
        (item for item in items if str(item["index"]) not in completed_indices),
        items[0],
    )
    all_done = completed == len(items)
    next_message = (
        "Đã luyện hết bài; bắt đầu lại từ câu đầu."
        if all_done
        else f"Câu tiếp theo chưa luyện: {next_item['index'] + 1}."
    )
    message = (
        f"### 🎧 Listening / Shadowing\n**{len(items):,} câu luyện tập · "
        f"{completed:,} câu đã đánh dấu**\n\n"
        f"{next_message} "
        "Nghe câu, shadowing rồi bấm **Đánh dấu câu đã luyện** để chuyển tiếp."
    )
    index = next_item["index"]
    return message, index, sentence_for(vid, index, transcript_override)


def grammar(vid: str | None, index: Any, transcript_override: Any = None) -> str:
    text = sentence_for(vid, index, transcript_override)
    if not text:
        return "Chưa có câu để phân tích."
    try:
        return "### 📖 AI Tutor · Grammar\n\n" + explain("grammar", text)
    except Exception as error:
        prompt = grammar_request(text)["prompt"]
        return (
            "### AI Tutor chưa sẵn sàng\n"
            f"{html.escape(str(error))}\n\nPrompt dự phòng để sao chép:\n\n{html.escape(prompt)}"
        )


def vocab(vid: str | None, index: Any, transcript_override: Any = None) -> str:
    text = sentence_for(vid, index, transcript_override)
    if not text:
        return "Chưa có câu để phân tích."
    try:
        return "### 📚 AI Tutor · Vocabulary\n\n" + explain("vocabulary", text)
    except Exception as error:
        prompt = vocabulary_request("", sentence=text)["prompt"]
        return (
            "### AI Tutor chưa sẵn sàng\n"
            f"{html.escape(str(error))}\n\nPrompt dự phòng để sao chép:\n\n{html.escape(prompt)}"
        )


def quiz(vid: str | None, history: Any = None, transcript_override: Any = None):
    segments = effective_segments(vid, transcript_override)
    if not segments:
        return "Bài này chưa có transcript để tạo quiz.", "", "", "", 0, "", []
    candidates = [
        index for index, segment in enumerate(segments)
        if len(str(segment.get("text", "")).split()) >= 2
    ]
    if not candidates:
        return "Không có câu đủ nội dung để tạo quiz.", "", "", "", 0, "", []
    history_indices = []
    for value in history or []:
        if str(value).isdigit():
            index_value = int(value)
            if index_value not in history_indices:
                history_indices.append(index_value)
    seen = set(history_indices)
    available = [index for index in candidates if index not in seen]
    if not available:
        available = candidates
        history_indices = []
        seen.clear()
    index = random.choice(available)
    question = make_quiz(segments, index)
    history_indices.append(index)
    next_history = history_indices[-100:]
    if question["type"] == "fill_blank":
        prompt = (
            "### 🧠 Điền từ còn thiếu\n\n"
            f"**{html.escape(question['question'])}**\n\n"
            "Nhập từ hoặc cụm từ còn thiếu. Có thể bấm **▶ Nghe câu quiz** trước."
        )
    else:
        prompt = (
            "### 🧠 Nghe và gõ lại câu\n\n"
            "Bấm **▶ Nghe câu quiz**, rồi nhập lại câu bạn nghe."
        )
    return (
        prompt,
        question["answer"],
        "",
        "",
        index,
        sentence_for(vid, index, transcript_override),
        next_history,
    )


def _tokens(text: Any) -> list[str]:
    return re.findall(r"[\w]+(?:['’][\w]+)?", str(text or "").casefold(), flags=re.UNICODE)


def check_quiz(answer: Any, expected: Any) -> str:
    if not expected:
        return "Hãy bấm **Tạo Quiz** trước."
    if _tokens(answer) == _tokens(expected):
        return "✅ Chính xác!"
    return f"❌ Chưa đúng. Đáp án: **{html.escape(str(expected))}**"


def sr(
    vid: str | None,
    index: Any,
    score: Any,
    progress_data: Any = None,
    transcript_override: Any = None,
):
    if vid not in MAP:
        return "Chưa chọn bài.", progress_data or EMPTY_PROGRESS
    segments = effective_segments(vid, transcript_override)
    try:
        number = int(float(index))
        rating = max(0, min(5, int(float(score))))
    except (TypeError, ValueError, OverflowError):
        return "Chọn số câu và mức nhớ hợp lệ trước khi lập lịch.", progress_data or EMPTY_PROGRESS
    if number < 0 or number >= len(segments):
        return f"Số câu phải nằm trong khoảng 0–{len(segments) - 1}.", progress_data or EMPTY_PROGRESS
    store = _store(progress_data)
    card = store.schedule_review(progress_scope(vid, transcript_override), number, rating)
    due_at = datetime.fromisoformat(card["due_at"]).astimezone(timezone.utc)
    return (
        f"✅ Đã lập lịch cho câu {number + 1}. Mức nhớ **{rating}/5** · "
        f"lặp lại sau **{card['interval_days']} ngày** · đến hạn **{due_at:%d/%m/%Y %H:%M UTC}**.",
        store.data,
    )


def due_reviews(vid: str | None, progress_data: Any = None, transcript_override: Any = None):
    if vid not in MAP:
        return "Chưa chọn bài học.", gr.update(choices=[], value=None)
    store = _store(progress_data)
    scope = progress_scope(vid, transcript_override)
    due = store.due_reviews(scope)
    total = sum(
        isinstance(item, dict) and item.get("video_id") == scope
        for item in store.data["reviews"].values()
    )
    choices_for_due = []
    for item in due:
        index = item.get("segment_index")
        if not isinstance(index, int) or vid not in MAP:
            continue
        segments = effective_segments(vid, transcript_override)
        if not 0 <= index < len(segments):
            continue
        text = str(segments[index].get("text", "")).strip()
        label = f"Câu {index + 1}: {text[:90]}{'…' if len(text) > 90 else ''}"
        choices_for_due.append((label, str(index)))
    message = f"**{len(due):,} câu đến hạn / {total:,} câu đã lập lịch** trong bài này."
    if not due:
        message += " Chưa có câu đến hạn; câu mới sẽ đến hạn sau ít nhất một ngày."
    return message, gr.update(choices=choices_for_due, value=None)


def use_due_sentence(value: Any, vid: str | None, transcript_override: Any = None):
    try:
        index = int(value)
    except (TypeError, ValueError):
        return 0, ""
    return index, sentence_for(vid, index, transcript_override)


def _edit_distance(left: list[str], right: list[str]) -> int:
    if len(left) > len(right):
        left, right = right, left
    previous = list(range(len(left) + 1))
    for row, right_token in enumerate(right, 1):
        current = [row]
        for column, left_token in enumerate(left, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_token != right_token),
                )
            )
        previous = current
    return previous[-1]


def pron_score(target: str | None, spoken: str | None) -> str:
    expected = _tokens(target)
    actual = _tokens(spoken)
    if not expected:
        return "Chưa có câu mẫu."
    if len(expected) > 1000 or len(actual) > 1000:
        return "Mỗi ô chỉ hỗ trợ tối đa 1.000 từ."
    errors = _edit_distance(expected, actual)
    score = max(0, round((1 - errors / len(expected)) * 100))
    missing = list((Counter(expected) - Counter(actual)).elements())[:10]
    extra = list((Counter(actual) - Counter(expected)).elements())[:10]
    details = []
    if missing:
        details.append("Thiếu: `" + ", ".join(html.escape(word) for word in missing) + "`")
    if extra:
        details.append("Thừa: `" + ", ".join(html.escape(word) for word in extra) + "`")
    if not missing and not extra and errors:
        details.append("Kiểm tra lại thứ tự từ trong câu.")
    if not errors:
        details.append("🎉 Câu chữ khớp hoàn toàn.")
    return (
        f"### 🎤 Độ khớp văn bản\n# {score}%\n\n"
        f"{errors} lỗi từ theo thứ tự · {len(expected)} từ mẫu / {len(actual)} từ đọc\n\n"
        + "\n\n".join(details)
    )


def speech_to_text_ui(audio_file: str | None, model_name: str, language: str):
    if not audio_file:
        return gr.update(), "❌ Hãy ghi âm hoặc tải audio trước."
    try:
        result = transcribe_file(
            audio_file,
            model_name=model_name,
            language=None if language == "auto" else language,
            device="auto",
            compute_type="int8",
            batch_size=2,
            align_words=False,
        )
        spoken = " ".join(
            str(segment.get("text") or "").strip()
            for segment in result.get("segments", [])
            if str(segment.get("text") or "").strip()
        ).strip()
        if not spoken:
            return "", "❌ Không nhận được lời thoại từ audio này."
        return spoken, f"✅ Đã chép lời · `{result['language']}` · model `{result['model']}`."
    except Exception as error:
        return gr.update(), f"❌ {html.escape(str(error))}"


def import_transcript(
    file: str | None,
    text: str | None,
    vid: str | None,
    progress_data: Any = None,
    transcript_override: Any = None,
):
    unchanged = (gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update())
    if vid not in MAP:
        return "❌ Hãy chọn bài học trong thư viện trước khi nạp transcript.", *unchanged
    raw = text or ""
    if file:
        try:
            raw = Path(file).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            return f"❌ Không đọc được file: {html.escape(str(error))}", *unchanged
    try:
        segments = parse_manual(raw, video_id=vid)
        if not segments:
            return "❌ Không tìm thấy câu có timestamp trong transcript.", *unchanged
        imported = {"video_id": vid, "segments": segments}
        message = (
            f"✅ Đã nạp {len(segments):,} câu vào phiên hiện tại. "
            "Bài luyện dùng transcript này trong phiên này; thư viện đã deploy không bị thay đổi."
        )
        return (
            message,
            to_json(segments),
            transcript_html(segments),
            imported,
            lesson_status(vid, progress_data, imported),
            sentence_for(vid, 0, imported),
            0,
        )
    except Exception as error:
        return f"❌ Parse lỗi: {html.escape(str(error))}", *unchanged


def import_transcript_text(
    text: str | None,
    vid: str | None,
    progress_data: Any = None,
    transcript_override: Any = None,
):
    return import_transcript(None, text, vid, progress_data, transcript_override)


def restore_library_transcript(vid: str | None, progress_data: Any = None):
    if vid not in MAP:
        return (
            "❌ Hãy chọn bài học trước.",
            gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(),
        )
    segments = MAP[vid].get("transcript", [])
    return (
        "✅ Đã khôi phục transcript trong thư viện.",
        to_json(segments),
        transcript_html(segments),
        None,
        lesson_status(vid, progress_data),
        sentence_for(vid, 0),
        0,
    )


def export_transcript(vid: str | None, transcript_override: Any = None) -> str:
    if vid not in MAP:
        raise ValueError("Hãy chọn bài học trước khi tải transcript.")
    segments = effective_segments(vid, transcript_override)
    output_dir = Path(tempfile.gettempdir()) / "english-lab-exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"transcript_{vid}_{uuid.uuid4().hex[:10]}.json"
    path.write_text(to_json(segments) + "\n", encoding="utf-8")
    return str(path)


def run_whisperx_ui(
    audio_file: str | None,
    vid: str | None,
    title: str | None,
    model_name: str,
    language: str,
    device: str,
    compute_type: str,
    batch_size: float,
):
    if not audio_file:
        return "❌ Hãy tải lên tệp audio/video trước.", "{}", None, None
    if vid and not YOUTUBE_ID_RE.fullmatch(vid.strip()):
        return "❌ YouTube Video ID phải có đúng 11 ký tự hợp lệ.", "{}", None, None
    try:
        source_name = Path(audio_file).name
        result = transcribe_file(
            audio_file,
            model_name=model_name,
            language=None if language == "auto" else language,
            device=device,
            compute_type=compute_type,
            batch_size=int(batch_size),
        )
        payload = make_payload(result, source_name=source_name, video_id=vid, title=title)
        output_dir = Path(tempfile.gettempdir()) / "english-lab-whisperx"
        output_dir.mkdir(parents=True, exist_ok=True)
        unique = uuid.uuid4().hex[:10]
        json_path = output_dir / f"transcript_{unique}.json"
        srt_path = output_dir / f"transcript_{unique}.srt"
        json_file, srt_file = write_outputs(payload, json_path, srt_path)
        lesson = payload["videos"][0]
        status = (
            f"✅ Hoàn tất: {lesson['sentence_count']:,} đoạn, "
            f"{lesson['word_count']:,} từ đã căn chỉnh · "
            f"ngôn ngữ `{result['language']}` · thiết bị `{result['device']}`."
        )
        return status, json.dumps(payload, ensure_ascii=False, indent=2), str(json_file), str(srt_file)
    except Exception as error:
        return f"❌ {html.escape(str(error))}", "{}", None, None


CSS = r"""
body{background:#f8fafc}
.gradio-container{max-width:1480px!important;padding:18px 22px 40px!important}
.hero{padding:28px 30px;border-radius:24px;border:1px solid #dbe4f0;background:linear-gradient(135deg,#eef6ff,#f5f3ff,#f8fafc);box-shadow:0 8px 30px rgba(15,23,42,.06);margin-bottom:14px}
.hero h1{margin:0;font-size:34px;line-height:1.2;overflow-wrap:anywhere}
.hero .sub{margin-top:7px;color:#64748b;font-size:14px;line-height:1.5}
.badge{display:inline-block;margin-top:13px;padding:5px 10px;border-radius:999px;background:#fff;border:1px solid #dbe4f0;color:#475569;font-size:12px;font-weight:700}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:12px 0}
.stat{min-width:0;padding:16px;border:1px solid #e2e8f0;border-radius:18px;background:#fff}
.num{font-size:24px;font-weight:800;overflow-wrap:anywhere}
.label{font-size:12px;color:#64748b;line-height:1.5}
.toolbar{padding:14px;border:1px solid #e2e8f0;border-radius:18px;background:#fff;margin:10px 0}
.video{aspect-ratio:16/9;background:#020617;border-radius:18px 18px 0 0;overflow:hidden;max-width:100%}
.video iframe{width:100%;height:100%;border:0}
.video-link{padding:10px 14px;border:1px solid #e2e8f0;background:#fff;color:#64748b;font-size:12px;overflow-wrap:anywhere}
.video-link a{color:#2563eb;font-weight:700}
.panel{min-width:0;border:1px solid #e2e8f0;border-radius:18px;background:#fff;overflow:hidden}
.panel-title{padding:14px 16px;border-bottom:1px solid #e2e8f0;font-weight:800;display:flex;justify-content:space-between;gap:8px}
.count{font-size:12px;color:#64748b;white-space:nowrap}
.lines{max-height:590px;overflow:auto;overscroll-behavior:contain;padding:8px}
.line{display:flex;align-items:flex-start;gap:12px;width:100%;border:0;background:transparent;padding:11px 12px;border-radius:12px;text-align:left;cursor:pointer;line-height:1.5;color:inherit}
.line:hover,.line.active{background:#e0ecff}
.line:focus-visible{outline:3px solid #2563eb;outline-offset:2px}
.line-text{min-width:0;overflow-wrap:anywhere;word-break:normal}
.time{flex:0 0 64px;color:#2563eb;font:700 12px ui-monospace,monospace;padding-top:2px}
.empty{padding:24px;color:#64748b;text-align:center}
.footer-note{text-align:center;color:#94a3b8;font-size:12px;margin-top:20px}
.repeat-bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0 0;padding:10px 12px;border:1px solid #e2e8f0;border-radius:14px;background:#fff}
.repeat-label{font-size:12px;color:#64748b;font-weight:700}
.repeat-choice button{min-width:48px;min-height:42px}
.repeat-choice.selected button{background:#2563eb!important;color:#fff!important;border-color:#2563eb!important}
.whisperx-id-row{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.whisperx-id-row>*{min-width:0}
.whisperx-control-row{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.whisperx-control-row>*{min-width:0}
@media(max-width:900px){.gradio-container{padding:12px!important}.hero{padding:22px}.hero h1{font-size:29px}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.lines{max-height:480px}}
@media(max-width:900px){.whisperx-control-row{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:600px){.gradio-container{padding:8px!important}.hero{padding:17px;border-radius:18px}.hero h1{font-size:24px}.hero .sub{font-size:13px}.stats{gap:8px}.stat{padding:12px;border-radius:14px}.num{font-size:20px}.line{gap:8px;padding:10px 8px}.time{flex-basis:54px;font-size:11px}.panel-title{padding:12px}.repeat-bar{gap:6px;padding:8px}.repeat-choice button{min-width:42px}.video{border-radius:12px 12px 0 0}.whisperx-control-row{grid-template-columns:minmax(0,1fr)}}
"""


JS = r'''() => {
let i=-1,n=[],repeatCount=1,repeatsLeft=0,active=false,player=null,frame=null,apiLoading=false;
const clear=()=>{active=false};
const ready=()=>{
 const el=document.getElementById('ytplayer');
 if(!el||el===frame||!window.YT?.Player)return;
 frame=el;player=null;
 try{player=new YT.Player(el,{events:{onReady:()=>{if(active){let s=segment();if(s){call('seekTo',s.start,true);call('playVideo')}}},onStateChange:e=>{if(e.data===0&&active)checkEnd(true)}}})}catch(e){player=null}
};
const loadApi=()=>{
 if(window.YT?.Player){ready();return}
 if(apiLoading)return;apiLoading=true;
 const previous=window.onYouTubeIframeAPIReady;
 window.onYouTubeIframeAPIReady=()=>{if(typeof previous==='function')previous();ready()};
 const s=document.createElement('script');s.src='https://www.youtube.com/iframe_api';document.head.appendChild(s);
};
const call=(name,...args)=>{try{if(player?.[name])return player[name](...args)}catch(e){}return undefined};
const syncSentence=k=>{let input=document.querySelector('#sentence-no input');if(!input)return;const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')?.set;if(setter)setter.call(input,String(k));else input.value=String(k);input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}))};
const wire=()=>{let next=[...document.querySelectorAll('.line')];if(n.length&&(next.length!==n.length||next[0]!==n[0])){clear();i=-1}n=next;n.forEach((b,k)=>{if(!b.dataset.wired){b.dataset.wired=1;b.onclick=()=>go(k)}});if(i>=0&&i<n.length){n[i].classList.add('active');n[i].setAttribute('aria-pressed','true')}ready()};
const segment=()=>{let b=n[i];return b?{start:+b.dataset.start,end:+b.dataset.end}:null};
const checkEnd=ended=>{if(!active||i<0||(!ended&&call('getPlayerState')!==1))return;let s=segment();if(!s||!(s.end>s.start))return;let t=call('getCurrentTime');if(!ended&&(typeof t!=='number'||t<s.end-0.02))return;if(repeatsLeft>0){repeatsLeft--;call('seekTo',s.start,true);call('playVideo')}else{active=false;call('seekTo',s.end,true);call('pauseVideo')}};
const go=k=>{if(!n.length)return;i=Math.max(0,Math.min(k,n.length-1));n.forEach(x=>{x.classList.remove('active');x.setAttribute('aria-pressed','false')});let b=n[i];b.classList.add('active');b.setAttribute('aria-pressed','true');b.scrollIntoView({behavior:'smooth',block:'center'});syncSentence(i);repeatsLeft=Math.max(0,repeatCount-1);active=true;call('seekTo',+b.dataset.start,true);call('playVideo')};
const repeat=()=>{if(i<0){go(0);return}go(i)};
wire();loadApi();new MutationObserver(()=>{wire();loadApi()}).observe(document.body,{subtree:true,childList:true});setInterval(()=>checkEnd(false),150);
window.EL={play:()=>call('playVideo'),playSentence:v=>{let k=parseInt(v,10);return go(Number.isFinite(k)?k:0)},pause:()=>call('pauseVideo'),back:()=>{clear();repeatsLeft=0;call('seekTo',0,true)},speed:r=>call('setPlaybackRate',+r||1),prevSentence:()=>go(i<0?n.length-1:i-1),nextSentence:()=>go(i<0?0:i+1),repeat,setRepeatCount:v=>{let selected=(v==='infinite'||v==='∞')?'∞':Math.max(1,parseInt(v,10)||1);repeatCount=selected==='∞'?999999:selected;if(active)repeatsLeft=Math.max(0,repeatCount-1);document.querySelectorAll('.repeat-choice').forEach((el,k)=>el.classList.toggle('selected',['1','2','3','5','∞'][k]===String(selected)))}};
window.EL.setRepeatCount(1);
}'''


with gr.Blocks(title="English Learning Lab", css=CSS, js=JS, theme=gr.themes.Soft()) as demo:
    progress_state = gr.BrowserState(
        default_value=EMPTY_PROGRESS,
        storage_key="english-learning-lab-progress-v1",
        secret=os.getenv("ENGLISH_LAB_BROWSER_STATE_SECRET", "english-lab-progress-v1"),
    )
    transcript_override = gr.State(None)
    quiz_history = gr.State([])
    gr.HTML(
        f"<div class='hero'><h1>🎧 English Learning Lab</h1>"
        "<div class='sub'>Listening · Reading · Shadowing · Text Match · Grammar · Vocabulary · Quiz · Spaced Repetition</div>"
        f"<span class='badge'>English Lab · Final Transcript · {len(VIDEOS):,} lessons · {TOTAL:,} sentence segments</span></div>"
    )
    with gr.Row(elem_classes="stats"):
        gr.HTML(f"<div class='stat'><div class='num'>{len(VIDEOS):,}</div><div class='label'>📚 Bài học</div></div>")
        gr.HTML(f"<div class='stat'><div class='num'>{TOTAL:,}</div><div class='label'>📝 Sentence segments</div></div>")
        progress_stat_out = gr.HTML(progress_stat(EMPTY_PROGRESS))
        gr.HTML(
            f"<div class='stat'><div class='num'>{'FINAL' if SOURCE.startswith('final') else html.escape(SOURCE.upper())}</div>"
            "<div class='label'>📦 Library source</div></div>"
        )
    gr.Markdown(
        f"**📦 Library:** `{SOURCE}`" + (f" · ⚠️ {html.escape(ERROR)}" if ERROR else " · Dữ liệu sẵn sàng")
    )
    with gr.Row(elem_classes="toolbar"):
        search_box = gr.Textbox(label="🔎 Tìm bài học", placeholder="Tên bài hoặc Video ID", scale=2)
        lesson = gr.Dropdown(choices=choices(), value=DEFAULT, label="📚 Chọn bài học", scale=3)
        open_btn = gr.Button("▶ Học bài", variant="primary")
    with gr.Row():
        prev = gr.Button("← Bài trước")
        nxt = gr.Button("Bài tiếp →")
        show = gr.Checkbox(value=True, label="👁️ Hiện toàn bộ script")
    with gr.Row():
        url = gr.Textbox(
            label="YouTube URL / Video ID",
            value=f"https://www.youtube.com/watch?v={DEFAULT}" if DEFAULT else "",
        )
        url_btn = gr.Button("🎬 Mở video")
    status = gr.Markdown(lesson_status(DEFAULT, EMPTY_PROGRESS))
    with gr.Row():
        with gr.Column(scale=7):
            player = gr.HTML(yt(DEFAULT))
        with gr.Column(scale=5):
            trans = gr.HTML(transcript_html(MAP.get(DEFAULT, {}).get("transcript", [])))
    with gr.Row():
        prev_sentence = gr.Button("⏮ Câu trước")
        play = gr.Button("▶ Phát")
        repeat_sentence = gr.Button("🔁 Lặp câu")
        pause = gr.Button("⏸ Dừng")
        next_sentence = gr.Button("Câu kế tiếp ⏭")
        back = gr.Button("↺ Về đầu")
        speed = gr.Dropdown([0.5, 0.75, 1, 1.25, 1.5], value=1, label="⚡ Tốc độ", interactive=True)
    with gr.Row(elem_classes="repeat-bar"):
        gr.HTML('<span class="repeat-label">🔁 Số lần lặp:</span>')
        repeat_1 = gr.Button("1×", elem_classes="repeat-choice selected")
        repeat_2 = gr.Button("2×", elem_classes="repeat-choice")
        repeat_3 = gr.Button("3×", elem_classes="repeat-choice")
        repeat_5 = gr.Button("5×", elem_classes="repeat-choice")
        repeat_infinite = gr.Button("∞", elem_classes="repeat-choice")
        gr.Markdown(
            "Chọn câu trong transcript rồi bấm **🔁 Lặp câu**. Mỗi lần lặp giữ nguyên timestamp của câu.",
            elem_classes="repeat-label",
        )

    with gr.Tabs():
        with gr.Tab("🎧 Listening / Shadowing"):
            practice_out = gr.Markdown()
            practice_btn = gr.Button("🚀 Chuẩn bị luyện tập", variant="primary")
            sentence_no = gr.Number(
                value=0, precision=0, label="Số câu (bắt đầu từ 0)", elem_id="sentence-no"
            )
            practice_play = gr.Button("▶ Phát câu đang chọn")
            mark_btn = gr.Button("✅ Đánh dấu câu đã luyện")
            mark_out = gr.Markdown()
        with gr.Tab("🎤 Text Match"):
            target = gr.Textbox(label="Câu mẫu", value=sentence_for(DEFAULT, 0), lines=2)
            spoken = gr.Textbox(label="Câu bạn đọc / Speech-to-text", lines=2)
            speech_audio = gr.Audio(
                sources=["microphone", "upload"],
                type="filepath",
                label="Ghi âm hoặc tải audio câu bạn đọc",
            )
            with gr.Row(elem_classes="whisperx-control-row"):
                speech_model = gr.Dropdown(
                    ["tiny", "base", "small"], value="tiny", label="Model chép lời"
                )
                speech_language = gr.Dropdown(
                    ["auto", "en", "vi"], value="en", label="Ngôn ngữ audio"
                )
            speech_btn = gr.Button("🗣️ Chép audio vào ô câu đọc", variant="secondary")
            speech_status = gr.Markdown()
            pron_btn = gr.Button("🎯 Chấm độ khớp văn bản", variant="primary")
            pron_out = gr.Markdown()
            gr.Markdown(
                "Có thể nhập văn bản hoặc ghi âm để WhisperX chép lời. Điểm so sánh nội dung và thứ tự từ; "
                "không đo chất lượng âm thanh hay độ chính xác phát âm."
            )
        with gr.Tab("🧩 AI Tutor"):
            with gr.Row():
                grammar_btn = gr.Button("📖 Phân tích Grammar", variant="primary")
                vocab_btn = gr.Button("📚 Học Vocabulary", variant="primary")
            ai_out = gr.Markdown(
                "Chọn câu trong transcript rồi yêu cầu Qwen giải thích bằng tiếng Việt. "
                "Model được tải ở lần dùng đầu tiên."
            )
        with gr.Tab("🧠 Quiz"):
            quiz_btn = gr.Button("🎯 Tạo câu hỏi mới", variant="primary")
            quiz_out = gr.Markdown()
            quiz_play_btn = gr.Button("▶ Nghe câu quiz")
            quiz_answer = gr.Textbox(label="Câu trả lời", placeholder="Nhập đáp án…", interactive=True)
            quiz_check = gr.Button("✅ Kiểm tra đáp án")
            quiz_feedback = gr.Markdown()
            quiz_state = gr.State("")
        with gr.Tab("🔁 Spaced Repetition"):
            sr_score = gr.Slider(0, 5, value=3, step=1, label="Mức nhớ 0–5")
            sr_btn = gr.Button("📅 Lập lịch cho câu đang chọn", variant="primary")
            sr_out = gr.Markdown()
            due_refresh = gr.Button("🔄 Cập nhật câu đến hạn")
            due_summary = gr.Markdown()
            due_sentence = gr.Dropdown(choices=[], label="Câu cần ôn", interactive=True)
            use_due_btn = gr.Button("↪ Chọn câu này để luyện")
            due_play_btn = gr.Button("▶ Phát câu ôn")
        with gr.Tab("📦 Data"):
            parsed = gr.Code(
                to_json(MAP.get(DEFAULT, {}).get("transcript", [])),
                language="json",
                label="Transcript JSON của bài đang chọn",
                lines=12,
            )
            download_transcript = gr.DownloadButton("⬇ Tải transcript JSON")
            gr.Markdown(
                "File tải về dùng transcript đang hiển thị, kể cả transcript đã nạp trong phiên này."
            )
        with gr.Tab("🎙️ WhisperX"):
            if find_spec("whisperx"):
                gr.Markdown(
                    "Tải audio/video lên để nhận dạng lời thoại và căn timestamp đến từng từ. "
                    "Tệp được xử lý trên máy chủ đang chạy English Lab."
                )
            else:
                gr.Markdown(
                    "WhisperX chưa được cài trong runtime này. Chạy "
                    "`pip install -r requirements-whisperx.txt` rồi khởi động lại app. "
                    "Image Docker của repo đã được cấu hình cài WhisperX CPU khi deploy."
                )
            whisperx_audio = gr.File(
                label="Audio / video cần chép lời",
                file_types=sorted(SUPPORTED_AUDIO_SUFFIXES),
                type="filepath",
            )
            with gr.Row(elem_classes="whisperx-id-row"):
                whisperx_video_id = gr.Textbox(
                    label="YouTube Video ID (nếu muốn ghép vào thư viện)",
                    placeholder="Ví dụ: dQw4w9WgXcQ",
                    scale=1,
                )
                whisperx_title = gr.Textbox(label="Tên bài (không bắt buộc)", scale=2)
            with gr.Row(elem_classes="whisperx-control-row"):
                whisperx_model = gr.Dropdown(
                    ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"],
                    value="small",
                    label="Whisper model",
                )
                whisperx_language = gr.Dropdown(
                    ["auto", "en", "vi", "es", "fr", "de", "it", "ja", "ko", "zh", "pt", "ru"],
                    value="auto",
                    label="Ngôn ngữ",
                )
            with gr.Row(elem_classes="whisperx-control-row"):
                whisperx_device = gr.Dropdown(
                    ["auto", "cpu", "cuda"], value="auto", label="Thiết bị"
                )
                whisperx_compute = gr.Dropdown(
                    ["default", "int8", "float16", "float32"],
                    value="int8",
                    label="Compute type",
                )
                whisperx_batch = gr.Slider(
                    1, 16, value=4, step=1, label="Batch size"
                )
            whisperx_run = gr.Button("🎙️ Chạy WhisperX", variant="primary")
            whisperx_status = gr.Markdown()
            whisperx_json = gr.Code(
                language="json", label="Transcript JSON (timestamps câu và từ)", lines=16
            )
            whisperx_import = gr.Button(
                "📥 Dùng kết quả này cho bài đang chọn", variant="secondary"
            )
            with gr.Row():
                whisperx_json_file = gr.File(label="Tải JSON")
                whisperx_srt_file = gr.File(label="Tải phụ đề SRT")

    gr.Markdown("### 📥 Import transcript dự phòng")
    with gr.Row():
        file = gr.File(file_types=[".txt", ".srt", ".vtt", ".json"], type="filepath", label="TXT / SRT / VTT / JSON")
        text = gr.Textbox(label="Hoặc dán transcript", lines=4)
    imp = gr.Button("📥 Nạp transcript vào phiên này")
    reset_import = gr.Button("↩ Khôi phục transcript thư viện")
    imp_status = gr.Markdown()
    gr.HTML(
        "<div class='footer-note'>Tiến độ được lưu riêng trong trình duyệt này · "
        "Transcript có sẵn trong thư viện · Space không tải audio YouTube</div>"
    )

    search_box.change(search, [search_box, lesson], lesson)
    lesson_outputs = [
        status, player, trans, parsed, lesson, url, progress_state, sentence_no,
        target, transcript_override,
    ]
    lesson_change = lesson.change(
        select, [lesson, progress_state, transcript_override], lesson_outputs
    )
    lesson_change.then(
        due_reviews, [lesson, progress_state, transcript_override], [due_summary, due_sentence]
    )
    lesson_change.then(
        lambda: ("", "", "", "", []),
        None,
        [quiz_out, quiz_state, quiz_answer, quiz_feedback, quiz_history],
    )
    open_btn.click(select, [lesson, progress_state, transcript_override], lesson_outputs)
    url_btn.click(open_url, [url, progress_state, transcript_override], lesson_outputs)
    # Changing the dropdown triggers lesson.change, which loads the next lesson.
    prev.click(lambda value: move(value, -1), lesson, lesson)
    nxt.click(lambda value: move(value, 1), lesson, lesson)
    show.change(
        lambda visible, vid, override: transcript_html(effective_segments(vid, override))
        if visible else '<div class="panel"><div class="empty">Script đang ẩn.</div></div>',
        [show, lesson, transcript_override],
        trans,
    )
    practice_btn.click(
        practice,
        [lesson, progress_state, transcript_override],
        [practice_out, sentence_no, target],
    )
    practice_play.click(None, sentence_no, js="n => {window.EL?.playSentence(n); return []}")
    sentence_no.change(sentence_for, [lesson, sentence_no, transcript_override], target)
    mark_btn.click(
        mark_sentence,
        [lesson, sentence_no, progress_state, transcript_override],
        [mark_out, status, progress_state],
    ).then(
        practice,
        [lesson, progress_state, transcript_override],
        [practice_out, sentence_no, target],
    )
    grammar_btn.click(
        grammar,
        [lesson, sentence_no, transcript_override],
        ai_out,
        concurrency_id="ai-tutor",
        concurrency_limit=1,
        time_limit=1800,
    )
    vocab_btn.click(
        vocab,
        [lesson, sentence_no, transcript_override],
        ai_out,
        concurrency_id="ai-tutor",
        concurrency_limit=1,
        time_limit=1800,
    )
    quiz_btn.click(
        quiz,
        [lesson, quiz_history, transcript_override],
        [quiz_out, quiz_state, quiz_answer, quiz_feedback, sentence_no, target, quiz_history],
    )
    quiz_play_btn.click(None, sentence_no, js="n => {window.EL?.playSentence(n); return []}")
    quiz_check.click(check_quiz, [quiz_answer, quiz_state], quiz_feedback)
    sr_btn.click(
        sr,
        [lesson, sentence_no, sr_score, progress_state, transcript_override],
        [sr_out, progress_state],
    ).then(
        due_reviews,
        [lesson, progress_state, transcript_override],
        [due_summary, due_sentence],
    )
    due_refresh.click(
        due_reviews,
        [lesson, progress_state, transcript_override],
        [due_summary, due_sentence],
    )
    use_due_btn.click(
        use_due_sentence,
        [due_sentence, lesson, transcript_override],
        [sentence_no, target],
    )
    due_play_btn.click(None, sentence_no, js="n => {window.EL?.playSentence(n); return []}")
    pron_btn.click(pron_score, [target, spoken], pron_out)
    speech_btn.click(
        speech_to_text_ui,
        [speech_audio, speech_model, speech_language],
        [spoken, speech_status],
        concurrency_id="whisperx-job",
        concurrency_limit=1,
        time_limit=1800,
    )
    imp.click(
        import_transcript,
        [file, text, lesson, progress_state, transcript_override],
        [imp_status, parsed, trans, transcript_override, status, target, sentence_no],
    ).then(
        due_reviews,
        [lesson, progress_state, transcript_override],
        [due_summary, due_sentence],
    ).then(
        lambda: ("", "", "", "", []),
        None,
        [quiz_out, quiz_state, quiz_answer, quiz_feedback, quiz_history],
    )
    reset_import.click(
        restore_library_transcript,
        [lesson, progress_state],
        [imp_status, parsed, trans, transcript_override, status, target, sentence_no],
    ).then(
        due_reviews,
        [lesson, progress_state, transcript_override],
        [due_summary, due_sentence],
    ).then(
        lambda: ("", "", "", "", []),
        None,
        [quiz_out, quiz_state, quiz_answer, quiz_feedback, quiz_history],
    )
    whisperx_import.click(
        import_transcript_text,
        [whisperx_json, lesson, progress_state, transcript_override],
        [imp_status, parsed, trans, transcript_override, status, target, sentence_no],
    ).then(
        due_reviews,
        [lesson, progress_state, transcript_override],
        [due_summary, due_sentence],
    ).then(
        lambda: ("", "", "", "", []),
        None,
        [quiz_out, quiz_state, quiz_answer, quiz_feedback, quiz_history],
    )
    download_transcript.click(
        export_transcript, [lesson, transcript_override], download_transcript
    )
    whisperx_run.click(
        run_whisperx_ui,
        [
            whisperx_audio,
            whisperx_video_id,
            whisperx_title,
            whisperx_model,
            whisperx_language,
            whisperx_device,
            whisperx_compute,
            whisperx_batch,
        ],
        [whisperx_status, whisperx_json, whisperx_json_file, whisperx_srt_file],
        concurrency_id="whisperx-job",
        concurrency_limit=1,
        time_limit=3600,
    )
    progress_state.change(progress_stat, progress_state, progress_stat_out)
    demo.load(progress_stat, progress_state, progress_stat_out)
    demo.load(
        due_reviews,
        [lesson, progress_state, transcript_override],
        [due_summary, due_sentence],
    )

    play.click(None, js="() => {window.EL?.play(); return []}")
    repeat_sentence.click(None, js="() => {window.EL?.repeat(); return []}")
    repeat_1.click(None, js="() => {window.EL?.setRepeatCount(1); return []}")
    repeat_2.click(None, js="() => {window.EL?.setRepeatCount(2); return []}")
    repeat_3.click(None, js="() => {window.EL?.setRepeatCount(3); return []}")
    repeat_5.click(None, js="() => {window.EL?.setRepeatCount(5); return []}")
    repeat_infinite.click(None, js="() => {window.EL?.setRepeatCount('∞'); return []}")
    pause.click(None, js="() => {window.EL?.pause(); return []}")
    back.click(None, js="() => {window.EL?.back(); return []}")
    speed.change(None, js="r => {window.EL?.speed(r); return []}")
    prev_sentence.click(None, js="() => {window.EL?.prevSentence(); return []}")
    next_sentence.click(None, js="() => {window.EL?.nextSentence(); return []}")


demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))
