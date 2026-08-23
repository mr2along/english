"""Qwen-assisted transcript sentence segmentation and timestamp synchronization."""
import json
import os
import re
from typing import Dict, List

_MODEL = None
_TOKENIZER = None


def _load_model():
    global _MODEL, _TOKENIZER
    if _MODEL is not None:
        return _TOKENIZER, _MODEL
    from transformers import AutoModelForCausalLM, AutoTokenizer
    model_id = os.getenv("QWEN_MODEL", "Qwen/Qwen3-0.6B")
    _TOKENIZER = AutoTokenizer.from_pretrained(model_id)
    _MODEL = AutoModelForCausalLM.from_pretrained(
        model_id,
        dtype="auto",
        device_map="auto",
    )
    return _TOKENIZER, _MODEL


def _fallback(raw: List[Dict]) -> List[Dict]:
    out, buf = [], []
    for item in raw:
        buf.append(item)
        text = " ".join(x["text"] for x in buf).strip()
        pause = (item["start"] - buf[-2]["start"]) if len(buf) > 1 else 0
        end_punct = bool(re.search(r"[.!?][\"']?$", text))
        if end_punct or len(text.split()) >= 18 or pause >= 1.1:
            out.append(_make(buf)); buf = []
    if buf: out.append(_make(buf))
    return out


def _make(parts: List[Dict]) -> Dict:
    start = float(parts[0]["start"])
    last = parts[-1]
    end = float(last["start"]) + float(last.get("duration", 0) or 0)
    if end <= start and len(parts) > 1:
        end = float(parts[-1]["start"])
    return {"start": round(start, 3), "end": round(max(end, start + 0.05), 3), "text": " ".join(x["text"] for x in parts).strip()}


def _qwen_boundaries(raw: List[Dict]) -> List[int]:
    tokenizer, model = _load_model()
    numbered = "\n".join(f'{i}: {x["text"]}' for i, x in enumerate(raw))
    prompt = (
        "Split these transcript fragments into natural spoken English sentences. "
        "Return ONLY a JSON array of integer fragment indexes where a sentence ENDS. "
        "Do not rewrite words, do not add punctuation, and do not change order. "
        "Every fragment must belong to exactly one sentence.\n\n" + numbered
    )
    messages = [{"role": "user", "content": prompt}]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    inputs = tokenizer([text], return_tensors="pt").to(model.device)
    out = model.generate(**inputs, max_new_tokens=min(512, max(64, len(raw) * 4)), do_sample=False)
    generated = out[0][inputs.input_ids.shape[1]:]
    answer = tokenizer.decode(generated, skip_special_tokens=True)
    match = re.search(r"\[[\s\d,]+\]", answer)
    if not match:
        raise ValueError("Qwen did not return a JSON boundary list")
    values = json.loads(match.group(0))
    if not isinstance(values, list) or not all(isinstance(x, int) for x in values):
        raise ValueError("Invalid Qwen boundary list")
    return sorted(set(x for x in values if 0 <= x < len(raw)))


def map_segments(raw: List[Dict]) -> List[Dict]:
    if not raw:
        return []
    try:
        boundaries = _qwen_boundaries(raw)
        out, start = [], 0
        for end_idx in boundaries:
            if end_idx < start:
                continue
            out.append(_make(raw[start:end_idx + 1])); start = end_idx + 1
        if start < len(raw):
            out.append(_make(raw[start:]))
        if not out:
            raise ValueError("empty mapping")
        return out
    except Exception:
        return _fallback(raw)


def map_video(video: Dict) -> Dict:
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
