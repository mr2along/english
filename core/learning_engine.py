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
    return [{"index": i + 1, "text": s.get("text", ""), "start": float(s.get("start", 0)), "duration": float(s.get("duration", 0))} for i, s in enumerate(segments) if s.get("text")]


def build_quiz(segment: Dict[str, Any], distractors: List[str] | None = None) -> Dict[str, Any]:
    text = str(segment.get("text", "")).strip()
    words = text.split()
    answer = words[0] if words else ""
    choices = [answer] + [x for x in (distractors or []) if x and x != answer][:3]
    return {"question": "Từ nào bắt đầu câu này?", "answer": answer, "choices": choices, "text": text}


def next_review(item: ReviewItem, quality: int) -> ReviewItem:
    quality = max(0, min(5, int(quality)))
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
