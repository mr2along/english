import json
import math
import os
import re
from typing import Callable, Dict, List

from core.qwen_runtime import load_qwen_model


def _load_model():
    return load_qwen_model()


def _fallback(raw: List[Dict]) -> List[Dict]:
    out, buf = [], []
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        try:
            start = float(item.get("start", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not 0 <= start < float("inf"):
            continue
        item = dict(item, start=start)
        buf.append(item)
        text = " ".join(x["text"] for x in buf).strip()
        previous = buf[-2] if len(buf) > 1 else None
        if previous:
            try:
                previous_end = float(previous["start"]) + max(
                    0.0, float(previous.get("duration", 0) or 0)
                )
            except (TypeError, ValueError):
                previous_end = float(previous["start"])
        else:
            previous_end = start
        pause = max(0.0, start - previous_end) if previous else 0.0
        if re.search(r"[.!?][\"']?$", text) or len(text.split()) >= 18 or pause >= 1.1:
            out.append(_make(buf)); buf = []
    if buf: out.append(_make(buf))
    return out


def _make(parts: List[Dict]) -> Dict:
    if not parts:
        return {"start": 0.0, "end": 0.05, "text": ""}
    try:
        start = max(0.0, float(parts[0].get("start", 0) or 0))
    except (TypeError, ValueError):
        start = 0.0
    last = parts[-1]
    try:
        last_start = max(start, float(last.get("start", start) or start))
        duration = max(0.0, float(last.get("duration", 0) or 0))
    except (TypeError, ValueError):
        last_start, duration = start, 0.0
    end = last_start + duration
    if end <= start and len(parts) > 1:
        try:
            end = float(parts[-1].get("start", start))
        except (TypeError, ValueError):
            end = start
    if not math.isfinite(end):
        end = start
    text = " ".join(str(item.get("text", "")).strip() for item in parts).strip()
    return {"start": round(start, 3), "end": round(max(end, start + 0.05), 3), "text": text}


def _qwen_boundaries(raw: List[Dict], language: str = "English") -> List[int]:
    if not raw:
        return []
    tokenizer, model = _load_model()
    numbered = "\n".join(f'{i}: {x["text"]}' for i, x in enumerate(raw))
    prompt = (f"Split these transcript fragments into natural spoken {language} sentences. "
              "Return ONLY a JSON array of integer fragment indexes where a sentence ENDS. "
              "Do not rewrite words, do not add punctuation, and do not change order. "
              "Every fragment must belong to exactly one sentence.\n\n" + numbered)
    messages = [{"role": "user", "content": prompt}]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    inputs = tokenizer([text], return_tensors="pt").to(model.device)
    out = model.generate(**inputs, max_new_tokens=min(512, max(64, len(raw) * 4)), do_sample=False)
    generated = out[0][inputs.input_ids.shape[1]:]
    answer = tokenizer.decode(generated, skip_special_tokens=True)
    match = re.search(r"\[[\s\d,]+\]", answer)
    if not match: raise ValueError("Qwen did not return a JSON boundary list")
    values = json.loads(match.group(0))
    if not isinstance(values, list) or not all(isinstance(x, int) for x in values): raise ValueError("Invalid Qwen boundary list")
    boundaries = sorted(set(x for x in values if 0 <= x < len(raw)))
    if not boundaries:
        raise ValueError("Qwen returned no sentence boundaries")
    return boundaries


def map_segments(raw: List[Dict]) -> List[Dict]:
    if not raw: return []
    try:
        boundaries = _qwen_boundaries(raw)
        out, start = [], 0
        for end_idx in boundaries:
            if end_idx < start: continue
            out.append(_make(raw[start:end_idx + 1])); start = end_idx + 1
        if start < len(raw): out.append(_make(raw[start:]))
        if not out: raise ValueError("empty mapping")
        return out
    except Exception:
        return _fallback(raw)


def map_segments_detailed(
    raw: List[Dict],
    language: str = "English",
    batch_size: int = 48,
    progress_callback: Callable[[float, str], None] | None = None,
) -> tuple[List[Dict], Dict[str, int]]:
    """Align caption fragments into sentences and report which batches used Qwen."""
    if not raw:
        return [], {"ai_batches": 0, "fallback_batches": 0}

    size = max(8, min(int(batch_size), 96))
    output: List[Dict] = []
    ai_batches = fallback_batches = 0
    for offset in range(0, len(raw), size):
        batch = raw[offset : offset + size]
        try:
            boundaries = _qwen_boundaries(batch, language=language)
            start = 0
            mapped = []
            for end_index in boundaries:
                if end_index < start:
                    continue
                mapped.append(_make(batch[start : end_index + 1]))
                start = end_index + 1
            if start < len(batch):
                mapped.append(_make(batch[start:]))
            if not mapped:
                raise ValueError("Qwen returned no sentences")
            output.extend(mapped)
            ai_batches += 1
        except Exception:
            output.extend(_fallback(batch))
            fallback_batches += 1
        if progress_callback:
            completed = min(1.0, (offset + len(batch)) / len(raw))
            progress_callback(completed, f"AI phân câu: {offset + len(batch):,}/{len(raw):,} caption")
    return output, {"ai_batches": ai_batches, "fallback_batches": fallback_batches}


def map_video(video: Dict) -> Dict:
    # final_transcripts.json is already sentence-aligned by the Colab pipeline.
    # Never run Qwen again in the production Space.
    source = str(video.get("transcript_source", ""))
    alignment = str(video.get("alignment", ""))
    if source.startswith("final_transcript") or alignment in {"existing_caption", "whisper_word_qwen_sentence"}:
        result = dict(video)
        result["raw_transcript"] = list(video.get("raw_transcript") or video.get("transcript") or [])
        result["transcript_mapping"] = {
            "engine": "precomputed",
            "model": video.get("qwen", {}).get("model") if isinstance(video.get("qwen"), dict) else None,
            "raw_segments": len(result["raw_transcript"]),
            "sentences": len(result.get("transcript", [])),
        }
        return result

    raw = list(video.get("transcript") or [])
    mapped = map_segments(raw)
    result = dict(video)
    result["raw_transcript"] = raw
    result["transcript"] = mapped
    result["transcript_mapping"] = {
        "engine": "qwen3",
        "model": os.getenv("QWEN_MODEL", "Qwen/Qwen3-0.6B"),
        "raw_segments": len(raw),
        "sentences": len(mapped),
    }
    return result
