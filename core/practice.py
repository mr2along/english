import random

from core.learning_engine import ReviewItem, next_review


def make_quiz(segments, index=0):
    if not segments:
        return None
    try:
        index = int(index) % len(segments)
    except (TypeError, ValueError):
        index = 0
    target = segments[index]
    text = str(target.get("text", "")).strip()
    words = text.split()
    try:
        start = float(target.get("start", 0) or 0)
    except (TypeError, ValueError):
        start = 0.0
    if len(words) < 4:
        return {
            "type": "repeat",
            "answer": text,
            "sentence": text,
            "start": start,
            "index": index,
        }

    # Hide one contiguous span. Varying the position keeps the same sentence
    # useful for multiple attempts and avoids always exposing its opening.
    hidden_count = max(1, min(4, len(words) // 4))
    hidden_start = random.randint(0, len(words) - hidden_count)
    hidden_end = hidden_start + hidden_count
    answer = " ".join(words[hidden_start:hidden_end])
    question = " ".join(
        "____" if hidden_start <= i < hidden_end else word
        for i, word in enumerate(words)
    )
    return {
        "type": "fill_blank",
        "question": question,
        "answer": answer,
        "sentence": text,
        "start": start,
        "index": index,
    }

def spaced_repetition_box(score, interval=0, repetitions=0, ease=2.5):
    item = ReviewItem(
        video_id="",
        segment_index=0,
        text="",
        interval=max(0, int(interval)),
        repetitions=max(0, int(repetitions)),
        ease=float(ease),
    )
    item = next_review(item, score)
    return {
        "score": max(0, min(5, int(score))),
        "interval_days": item.interval,
        "repetitions": item.repetitions,
        "ease": round(item.ease, 3),
    }

