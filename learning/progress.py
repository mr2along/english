"""Local SQLite learning system for vocabulary, reviews and quiz results."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

DB_PATH = Path(__import__("os").getenv("ENGLISH_DB", "english_lab.db"))


def _db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_learning_db():
    with _db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS vocabulary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT,
            sentence_index INTEGER,
            word TEXT NOT NULL,
            meaning TEXT DEFAULT '',
            word_type TEXT DEFAULT '',
            example TEXT DEFAULT '',
            ease REAL DEFAULT 2.5,
            interval_days INTEGER DEFAULT 0,
            repetitions INTEGER DEFAULT 0,
            due_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_reviewed TEXT,
            UNIQUE(video_id, sentence_index, word)
        );
        CREATE TABLE IF NOT EXISTS quiz_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT,
            sentence_index INTEGER,
            question TEXT,
            selected TEXT,
            answer TEXT,
            correct INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)


init_learning_db()


def save_teacher_result(video_id: str | None, sentence_index: int, result: Any) -> int:
    """Persist vocabulary returned by the local AI teacher."""
    rows = result.vocabulary if result else []
    saved = 0
    with _db() as c:
        for item in rows:
            word = str(item.get("word", "")).strip().lower()
            if not word:
                continue
            c.execute("""INSERT INTO vocabulary(video_id,sentence_index,word,meaning,word_type,example)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(video_id,sentence_index,word) DO UPDATE SET
                meaning=excluded.meaning, word_type=excluded.word_type, example=excluded.example""",
                (video_id, int(sentence_index), word, str(item.get("meaning", "")),
                 str(item.get("type", "")), str(item.get("example", ""))))
            saved += 1
    return saved


def due_words(limit: int = 20) -> List[Dict[str, Any]]:
    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    with _db() as c:
        rows = c.execute("""SELECT * FROM vocabulary
            WHERE due_at <= ? ORDER BY due_at ASC, repetitions ASC LIMIT ?""", (now, limit)).fetchall()
    return [dict(r) for r in rows]


def all_words(limit: int = 100) -> List[Dict[str, Any]]:
    with _db() as c:
        rows = c.execute("SELECT * FROM vocabulary ORDER BY word ASC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def review_word(vocab_id: int, quality: int) -> Dict[str, Any]:
    """SM-2 inspired scheduling. quality: 0..5."""
    quality = max(0, min(5, int(quality)))
    with _db() as c:
        row = c.execute("SELECT * FROM vocabulary WHERE id=?", (vocab_id,)).fetchone()
        if not row:
            return {}
        ease = float(row["ease"])
        reps = int(row["repetitions"])
        interval = int(row["interval_days"])
        if quality < 3:
            reps = 0
            interval = 1
        else:
            reps += 1
            if reps == 1:
                interval = 1
            elif reps == 2:
                interval = 3
            else:
                interval = max(1, round(interval * ease))
            ease = max(1.3, ease + (0.1 - (5-quality) * (0.08 + (5-quality) * 0.02)))
        due = datetime.utcnow() + timedelta(days=interval)
        c.execute("""UPDATE vocabulary SET ease=?,interval_days=?,repetitions=?,due_at=?,last_reviewed=? WHERE id=?""",
                  (ease, interval, reps, due.isoformat(sep=" ", timespec="seconds"),
                   datetime.utcnow().isoformat(sep=" ", timespec="seconds"), vocab_id))
        return dict(c.execute("SELECT * FROM vocabulary WHERE id=?", (vocab_id,)).fetchone())


def save_quiz(video_id: str | None, sentence_index: int, question: str, selected: str, answer: str) -> bool:
    correct = int(str(selected).strip().lower() == str(answer).strip().lower())
    with _db() as c:
        c.execute("INSERT INTO quiz_results(video_id,sentence_index,question,selected,answer,correct) VALUES(?,?,?,?,?,?)",
                  (video_id, sentence_index, question, selected, answer, correct))
    return bool(correct)


def learning_stats() -> str:
    with _db() as c:
        total = c.execute("SELECT COUNT(*) n FROM vocabulary").fetchone()["n"]
        due = c.execute("SELECT COUNT(*) n FROM vocabulary WHERE due_at <= CURRENT_TIMESTAMP").fetchone()["n"]
        mastered = c.execute("SELECT COUNT(*) n FROM vocabulary WHERE repetitions >= 4").fetchone()["n"]
        quizzes = c.execute("SELECT COUNT(*) n FROM quiz_results").fetchone()["n"]
        correct = c.execute("SELECT COALESCE(SUM(correct),0) n FROM quiz_results").fetchone()["n"]
    accuracy = (correct / quizzes * 100) if quizzes else 0
    return f"**{total}** từ  ·  **{due}** từ cần ôn  ·  **{mastered}** từ mastered  ·  **{quizzes}** quiz  ·  **{accuracy:.0f}%** quiz accuracy"
