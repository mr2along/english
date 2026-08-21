"""V2.2 speech scoring: word alignment, completeness, fluency and timing."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Iterable, Sequence


WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")


@dataclass
class SpokenWord:
    text: str
    start: float
    end: float


def normalize_words(text: str) -> list[str]:
    return WORD_RE.findall((text or "").lower())


def _ratio(a: Sequence[str], b: Sequence[str]) -> float:
    return difflib.SequenceMatcher(None, list(a), list(b)).ratio()


def align_words(target: str, spoken: Iterable[SpokenWord]):
    target_words = normalize_words(target)
    spoken_words = [normalize_words(w.text)[0] for w in spoken if normalize_words(w.text)]
    matcher = difflib.SequenceMatcher(None, target_words, spoken_words)
    result = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                result.append({"target": target_words[i], "spoken": spoken_words[j], "status": "correct"})
        elif tag == "replace":
            span = max(i2 - i1, j2 - j1)
            for k in range(span):
                result.append({
                    "target": target_words[i1 + k] if i1 + k < i2 else "",
                    "spoken": spoken_words[j1 + k] if j1 + k < j2 else "",
                    "status": "review",
                })
        elif tag == "delete":
            for i in range(i1, i2):
                result.append({"target": target_words[i], "spoken": "", "status": "missing"})
        elif tag == "insert":
            for j in range(j1, j2):
                result.append({"target": "", "spoken": spoken_words[j], "status": "extra"})
    return result


def score_speech(target: str, spoken_text: str, spoken_words: Iterable[SpokenWord], duration: float | None = None):
    target_tokens = normalize_words(target)
    spoken_tokens = normalize_words(spoken_text)
    similarity = _ratio(target_tokens, spoken_tokens) * 100
    completeness = (min(len(spoken_tokens), len(target_tokens)) / len(target_tokens) * 100) if target_tokens else 0
    alignment = align_words(target, spoken_words)
    missing = [x["target"] for x in alignment if x["status"] == "missing"]
    review = [x["target"] for x in alignment if x["status"] == "review" and x["target"]]
    extra = [x["spoken"] for x in alignment if x["status"] == "extra"]
    fluency = 0.0
    wpm = 0.0
    if duration and duration > 0:
        wpm = len(spoken_tokens) / duration * 60
        # A broad learner-friendly range; this is a fluency proxy, not an accent score.
        fluency = max(0.0, 100.0 - abs(wpm - 120.0) * 0.65)
    else:
        fluency = similarity
    overall = round(similarity * 0.45 + completeness * 0.30 + fluency * 0.25)
    return {
        "overall": min(100, max(0, overall)),
        "similarity": round(similarity),
        "completeness": round(completeness),
        "fluency": round(fluency),
        "wpm": round(wpm),
        "missing": missing[:20],
        "review": review[:20],
        "extra": extra[:20],
        "alignment": alignment,
    }
