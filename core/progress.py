"""Per-learner progress helpers.

Progress is passed in from Gradio BrowserState, so a public Space does not
mix one visitor's learning history with another visitor's history.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from core.learning_engine import ReviewItem, next_review


def _empty_progress() -> dict[str, Any]:
    return {"lessons": {}, "words": {}, "reviews": {}}


class ProgressStore:
    """Small progress store backed by a JSON-compatible browser-state object.

    ``path`` remains optional for local scripts that need a durable JSON file.
    The web app passes ``data`` and leaves ``path`` unset.
    """

    def __init__(self, path: str | Path | None = None, data: Any = None):
        self.path = Path(path) if path is not None else None
        self.data = self._normalize(data if data is not None else self._load())

    @staticmethod
    def _normalize(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            data = {}
        normalized = _empty_progress()
        for key in normalized:
            value = data.get(key)
            if isinstance(value, dict):
                normalized[key] = value
        return normalized

    def _load(self) -> dict[str, Any]:
        if self.path is None:
            return _empty_progress()
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_progress()

    def save(self) -> dict[str, Any]:
        """Persist to disk only when an explicit path was supplied."""
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as tmp:
                json.dump(self.data, tmp, ensure_ascii=False, indent=2)
                temp_path = Path(tmp.name)
            os.replace(temp_path, self.path)
        return self.data

    def lesson(self, video_id: str) -> dict[str, Any]:
        data = self.data["lessons"].setdefault(video_id, {})
        if not isinstance(data, dict):
            data = {}
            self.data["lessons"][video_id] = data
        try:
            data["views"] = max(0, int(data.get("views", 0)))
        except (TypeError, ValueError):
            data["views"] = 0
        data["completed"] = bool(data.get("completed", False))
        if not isinstance(data.get("sentences"), dict):
            data["sentences"] = {}
        return data

    def mark_view(self, video_id: str) -> dict[str, Any]:
        self.lesson(video_id)["views"] += 1
        return self.save()

    def mark_sentence(
        self, video_id: str, index: int, sentence_count: int | None = None
    ) -> dict[str, Any]:
        lesson = self.lesson(video_id)
        lesson["sentences"][str(index)] = True
        if sentence_count is not None and sentence_count > 0:
            completed_count = sum(
                1
                for key, value in lesson["sentences"].items()
                if value and str(key).isdigit() and int(key) < sentence_count
            )
            lesson["completed"] = completed_count >= sentence_count
        return self.save()

    @staticmethod
    def _review_key(video_id: str, sentence_index: int) -> str:
        return f"{video_id}:{sentence_index}"

    def schedule_review(
        self,
        video_id: str,
        sentence_index: int,
        score: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Apply SM-2 scheduling and save one sentence's next due date."""
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        key = self._review_key(video_id, sentence_index)
        previous = self.data["reviews"].get(key, {})
        if not isinstance(previous, dict):
            previous = {}
        try:
            item = ReviewItem(
                video_id=video_id,
                segment_index=sentence_index,
                text="",
                interval=max(0, int(previous.get("interval_days", 0))),
                ease=float(previous.get("ease", 2.5)),
                repetitions=max(0, int(previous.get("repetitions", 0))),
            )
            item = next_review(item, score)
        except (TypeError, ValueError):
            item = next_review(
                ReviewItem(video_id, sentence_index, ""), score
            )

        due_at = now.astimezone(timezone.utc) + timedelta(days=item.interval)
        self.data["reviews"][key] = {
            "video_id": video_id,
            "segment_index": sentence_index,
            "score": max(0, min(5, int(score))),
            "interval_days": item.interval,
            "ease": round(item.ease, 3),
            "repetitions": item.repetitions,
            "last_reviewed_at": now.astimezone(timezone.utc).isoformat(),
            "due_at": due_at.isoformat(),
        }
        self.save()
        return self.data["reviews"][key]

    def due_reviews(
        self, video_id: str | None = None, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        due = []
        for item in self.data["reviews"].values():
            if not isinstance(item, dict):
                continue
            if video_id and item.get("video_id") != video_id:
                continue
            try:
                due_at = datetime.fromisoformat(str(item["due_at"]))
                if due_at.tzinfo is None:
                    due_at = due_at.replace(tzinfo=timezone.utc)
            except (KeyError, TypeError, ValueError):
                continue
            if due_at <= now:
                due.append(item)
        return sorted(due, key=lambda item: str(item.get("due_at", "")))

    def due_count(self) -> int:
        return len(self.due_reviews())
