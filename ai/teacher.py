"""Hugging Face AI Teacher for sentence-level English learning.

Uses Hugging Face Inference Providers directly through huggingface_hub.
No OpenAI package or OpenAI API key is required.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

try:
    from huggingface_hub import InferenceClient
except Exception:
    InferenceClient = None


@dataclass
class TeacherResult:
    translation: str = ""
    grammar: Dict[str, Any] = field(default_factory=dict)
    vocabulary: List[Dict[str, Any]] = field(default_factory=list)
    collocations: List[str] = field(default_factory=list)
    pattern: str = ""
    pronunciation: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    quiz: Dict[str, Any] = field(default_factory=dict)
    raw: str = ""

    def markdown(self) -> str:
        g = self.grammar or {}
        lines = [
            "## 🇬🇧 AI Teacher",
            "",
            f"### 🇻🇳 Nghĩa tự nhiên\n{self.translation or 'Chưa có.'}",
            "",
            "### 📚 Grammar",
            f"**Structure:** {g.get('structure', '—')}",
            f"\n**Tense:** {g.get('tense', '—')}",
            f"\n**Subject:** {g.get('subject', '—')}",
            f"\n**Main verb:** {g.get('main_verb', '—')}",
            f"\n**Explanation:** {g.get('explanation', '—')}",
            "",
            "### 🧠 Vocabulary",
        ]
        if self.vocabulary:
            lines += ["| Word | Meaning | Type | Example |", "|---|---|---|---|"]
            for v in self.vocabulary[:12]:
                lines.append(f"| {v.get('word','')} | {v.get('meaning','')} | {v.get('type','')} | {v.get('example','')} |")
        else:
            lines.append("Không có mục nổi bật.")
        if self.collocations:
            lines += ["", "### 🔗 Collocations / Phrasal verbs"] + [f"- {x}" for x in self.collocations]
        if self.pattern:
            lines += ["", f"### 💡 Sentence pattern\n`{self.pattern}`"]
        if self.pronunciation:
            lines += ["", "### 🗣️ Pronunciation tips"] + [f"- {x}" for x in self.pronunciation]
        if self.examples:
            lines += ["", "### ✍️ Similar examples"] + [f"- {x}" for x in self.examples]
        if self.quiz:
            lines += ["", "### 📝 Mini quiz", f"**{self.quiz.get('question','')}**"]
            for i, option in enumerate(self.quiz.get('options', [])[:4]):
                lines.append(f"- **{chr(65+i)}.** {option}")
            if self.quiz.get('answer'):
                lines.append(f"\n<details><summary>Đáp án</summary>{self.quiz['answer']} — {self.quiz.get('explanation','')}</details>")
        return "\n".join(lines)


class AITeacher:
    """AI teacher backed by Hugging Face Inference Providers."""

    def __init__(self, token: str | None = None, model: str | None = None, provider: str | None = None):
        self.token = token if token is not None else os.getenv("HF_TOKEN", "")
        self.model = model or os.getenv("HF_AI_MODEL", "Qwen/Qwen3-4B-Instruct-2507")
        self.provider = provider or os.getenv("HF_AI_PROVIDER", "auto")

    @property
    def available(self) -> bool:
        return bool(self.token and InferenceClient is not None)

    def _fallback(self, sentence: str, reason: str = "") -> TeacherResult:
        words = re.findall(r"[A-Za-z][A-Za-z'’-]*", sentence)
        vocab = [{"word": w, "meaning": "Tra cứu nghĩa theo ngữ cảnh", "type": "word", "example": sentence} for w in words[:8]]
        msg = "Hugging Face AI chưa khả dụng."
        if reason:
            msg += f" {reason}"
        msg += " Bạn vẫn có thể luyện nghe và shadowing."
        return TeacherResult(
            translation=msg,
            grammar={"structure": "Xem câu mẫu", "tense": "AI analysis unavailable", "subject": "—", "main_verb": "—", "explanation": "Hãy kiểm tra HF_TOKEN, model và Inference Providers."},
            vocabulary=vocab,
            pattern=sentence,
        )

    def analyze(self, sentence: str) -> TeacherResult:
        sentence = (sentence or "").strip()
        if not sentence:
            return TeacherResult(translation="Chưa chọn câu.")
        if not self.available:
            return self._fallback(sentence, "Cần Secret HF_TOKEN có quyền Inference Providers.")

        schema = {
            "translation": "natural Vietnamese translation",
            "grammar": {"structure": "string", "tense": "string", "subject": "string", "main_verb": "string", "explanation": "string"},
            "vocabulary": [{"word": "string", "meaning": "string", "type": "string", "example": "string"}],
            "collocations": ["string"],
            "pattern": "string",
            "pronunciation": ["string"],
            "examples": ["string"],
            "quiz": {"question": "string", "options": ["string"], "answer": "A", "explanation": "string"},
        }
        prompt = f"""Analyze this English sentence for a Vietnamese learner. Return ONLY valid JSON matching this shape:\n{json.dumps(schema, ensure_ascii=False)}\n\nSentence: {sentence}\nRules: be accurate; explain grammar simply; preserve natural meaning; include IPA or connected-speech advice when useful; quiz must test the sentence, not trivia."""
        try:
            client = InferenceClient(token=self.token, provider=self.provider)
            response = client.chat.completions.create(
                model=self.model,
                temperature=0.15,
                max_tokens=1800,
                messages=[
                    {"role": "system", "content": "You are a precise English teacher for Vietnamese learners. Return JSON only."},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = response.choices[0].message.content or "{}"
            # Some reasoning models may wrap JSON in markdown fences.
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I | re.S)
            data = json.loads(raw)
            return TeacherResult(
                translation=str(data.get("translation", "")), grammar=data.get("grammar") or {},
                vocabulary=data.get("vocabulary") or [], collocations=data.get("collocations") or [],
                pattern=str(data.get("pattern", "")), pronunciation=data.get("pronunciation") or [],
                examples=data.get("examples") or [], quiz=data.get("quiz") or {}, raw=raw,
            )
        except Exception as exc:
            fallback = self._fallback(sentence, f"Lỗi HF AI: {type(exc).__name__}.")
            fallback.raw = f"HF AI error: {exc}"
            return fallback
