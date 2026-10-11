from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class ReviewItem:
    video_id: str
    segment_index: int
    text: str
    due: float = 0.0
    interval: int = 0
    ease: float = 2.5
    repetitions: int = 0


def make_practice_items(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = []
    for index, segment in enumerate(segments or []):
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        try:
            start = max(0.0, float(segment.get("start", 0) or 0))
            duration = max(0.0, float(segment.get("duration", 0) or 0))
        except (TypeError, ValueError):
            continue
        items.append(
            {
                "index": index,
                "text": text,
                "start": start,
                "duration": duration,
                "end": start + duration,
            }
        )
    return items


def build_quiz(segment: Dict[str, Any], distractors: List[str] | None = None) -> Dict[str, Any]:
    text = str((segment or {}).get("text", "")).strip()
    words = text.split()
    if not words:
        return {"type": "unavailable", "question": "Câu này chưa có nội dung.", "answer": "", "choices": [], "text": ""}
    answer = words[0]
    options = list(dict.fromkeys([answer] + [str(value) for value in (distractors or []) if value and str(value) != answer]))[:4]
    if len(options) > 1:
        return {
            "type": "multiple_choice",
            "question": "Từ nào bắt đầu câu này?",
            "answer": answer,
            "choices": options,
            "text": text,
        }
    return {
        "type": "fill_blank",
        "question": "____ " + " ".join(words[1:]),
        "answer": answer,
        "choices": [],
        "text": text,
    }


def next_review(item: ReviewItem, quality: int) -> ReviewItem:
    try:
        quality = max(0, min(5, int(quality)))
    except (TypeError, ValueError):
        quality = 0
    if quality < 3:
        item.repetitions = 0
        item.interval = 1
    else:
        item.repetitions += 1
        if item.repetitions == 1: item.interval = 1
        elif item.repetitions == 2: item.interval = 6
        else: item.interval = max(1, round(item.interval * item.ease))
        item.ease = max(1.3, item.ease + (0.1 - (5-quality)*(0.08 + (5-quality)*0.02)))
    return item
