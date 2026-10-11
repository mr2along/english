"""Optional WhisperX transcription and word-alignment helpers.

WhisperX is imported lazily so the regular English Lab runtime does not need
to install PyTorch or download speech models.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SUPPORTED_AUDIO_SUFFIXES = {
    ".aac", ".flac", ".m4a", ".mka", ".mkv", ".mov", ".mp3", ".mp4",
    ".mpeg", ".mpg", ".oga", ".ogg", ".opus", ".wav", ".webm", ".wma",
}
YOUTUBE_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}\Z")


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def transcribe_file(
    audio_path: str | Path,
    *,
    model_name: str = "small",
    language: str | None = None,
    device: str = "auto",
    compute_type: str = "default",
    batch_size: int = 4,
    align_words: bool = True,
) -> dict[str, Any]:
    """Transcribe one local audio/video file and optionally align its words."""
    path = Path(audio_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("Không tìm thấy tệp audio/video đã tải lên.")
    if path.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
        raise ValueError("Định dạng tệp chưa được hỗ trợ.")
    if path.stat().st_size == 0:
        raise ValueError("Tệp audio/video đang rỗng.")
    if not 1 <= int(batch_size) <= 32:
        raise ValueError("Batch size cần nằm trong khoảng 1–32.")

    try:
        import torch
        import whisperx
    except ImportError as error:
        raise RuntimeError(
            "WhisperX chưa được cài trong môi trường này. Cài bằng "
            "`pip install -r requirements-whisperx.txt` rồi khởi động lại app."
        ) from error

    requested_device = (device or "auto").lower()
    if requested_device == "auto":
        requested_device = "cuda" if torch.cuda.is_available() else "cpu"
    if requested_device not in {"cpu", "cuda"}:
        raise ValueError("Device chỉ nhận auto, cpu hoặc cuda.")
    if requested_device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Đã chọn CUDA nhưng PyTorch không tìm thấy GPU khả dụng.")

    model = None
    align_model = None
    try:
        audio = whisperx.load_audio(str(path))
        model = whisperx.load_model(
            model_name,
            requested_device,
            compute_type=compute_type,
            language=language,
        )
        recognized = model.transcribe(audio, batch_size=int(batch_size))
        raw_segments = recognized.get("segments") or []
        if not raw_segments:
            raise RuntimeError("WhisperX không tìm thấy lời thoại trong tệp này.")

        detected_language = str(recognized.get("language") or language or "")
        if not detected_language:
            raise RuntimeError("WhisperX không xác định được ngôn ngữ để căn chỉnh.")

        # Release the ASR model before loading the language-specific aligner.
        del model
        model = None
        if requested_device == "cuda":
            torch.cuda.empty_cache()

        if align_words:
            align_model, align_metadata = whisperx.load_align_model(
                language_code=detected_language,
                device=requested_device,
            )
            if align_model is None or align_metadata is None:
                raise RuntimeError(
                    f"Không tìm thấy mô hình căn chỉnh cho ngôn ngữ `{detected_language}`."
                )
            aligned = whisperx.align(
                raw_segments,
                align_model,
                align_metadata,
                audio,
                requested_device,
                return_char_alignments=False,
            )
            aligned_segments = aligned.get("segments") or []
        else:
            aligned_segments = raw_segments
        segments: list[dict[str, Any]] = []
        for raw in aligned_segments:
            text = re.sub(r"\s+", " ", str(raw.get("text") or "")).strip()
            start = _number(raw.get("start"))
            end = _number(raw.get("end"))
            if not text or start is None or end is None or start < 0 or end < start:
                continue

            words: list[dict[str, Any]] = []
            for word in raw.get("words") or []:
                if not isinstance(word, dict):
                    continue
                token = re.sub(r"\s+", " ", str(word.get("word") or "")).strip()
                word_start = _number(word.get("start"))
                word_end = _number(word.get("end"))
                if (
                    token
                    and word_start is not None
                    and word_end is not None
                    and 0 <= word_start <= word_end
                ):
                    words.append({"word": token, "start": word_start, "end": word_end})

            segments.append(
                {
                    "id": len(segments),
                    "start": start,
                    "end": end,
                    "text": text,
                    "words": words,
                }
            )

        if not segments:
            raise RuntimeError("WhisperX không trả về câu có timestamp hợp lệ.")
        return {
            "language": detected_language,
            "device": requested_device,
            "model": model_name,
            "segments": segments,
        }
    finally:
        if model is not None:
            del model
        if align_model is not None:
            del align_model
        try:
            import gc

            gc.collect()
            if requested_device == "cuda":
                torch.cuda.empty_cache()
        except Exception:
            pass


def make_payload(
    result: dict[str, Any],
    *,
    source_name: str,
    video_id: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Wrap aligned segments in the project's transcript-library JSON shape."""
    normalized_id = (video_id or "").strip() or None
    if normalized_id and not YOUTUBE_ID_RE.fullmatch(normalized_id):
        raise ValueError("YouTube Video ID phải có đúng 11 ký tự hợp lệ.")

    segments = result.get("segments") or []
    return {
        "schema_version": "english_lab_whisperx_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_videos": 1,
        "videos": [
            {
                "video_id": normalized_id,
                "title": (title or "").strip() or Path(source_name).stem,
                "transcript_source": "whisperx_local",
                "alignment": "whisperx_forced_alignment",
                "language": result.get("language"),
                "model": result.get("model"),
                "sentence_count": len(segments),
                "word_count": sum(len(segment.get("words") or []) for segment in segments),
                "segments": segments,
            }
        ],
    }


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{millis:03}"


def to_srt(payload: dict[str, Any]) -> str:
    videos = payload.get("videos") or []
    segments = videos[0].get("segments", []) if videos else []
    blocks = []
    for index, segment in enumerate(segments, start=1):
        start = _number(segment.get("start"))
        end = _number(segment.get("end"))
        text = str(segment.get("text") or "").strip()
        if start is None or end is None or not text:
            continue
        blocks.append(
            f"{index}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_path = handle.name
            handle.write(content)
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def write_outputs(
    payload: dict[str, Any], json_path: str | Path, srt_path: str | Path
) -> tuple[Path, Path]:
    json_file = Path(json_path)
    srt_file = Path(srt_path)
    _atomic_write(json_file, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    _atomic_write(srt_file, to_srt(payload))
    return json_file, srt_file
