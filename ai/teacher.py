"""Structured AI Teacher for sentence-level English learning.

Works with OpenAI-compatible chat APIs and is deliberately provider-neutral.
The service requests JSON, validates it, and falls back to a useful local
response when the provider is unavailable.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


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
                lines.append(
                    f"| {v.get('word','')} | {v.get('meaning','')} | "
                    f"{v.get('type','')} | {v.get('example','')} |"
                )
        else:
            lines.append("Không có mục nổi bật.")

        if self.collocations:
            lines += ["", "### 🔗 Collocations / Phrasal verbs"]
            lines += [f"- {x}" for x in self.collocations]
        if self.pattern:
            lines += ["", f"### 💡 Sentence pattern\n`{self.pattern}`"]
        if self.pronunciation:
            lines += ["", "### 🗣️ Pronunciation tips"]
            lines += [f"- {x}" for x in self.pronunciation]
        if self.examples:
            lines += ["", "### ✍️ Similar examples"]
            lines += [f"- {x}" for x in self.examples]
        if self.quiz:
            lines += ["", "### 📝 Mini quiz"]
            lines.append(f"**{self.quiz.get('question','')}**")
            for i, option in enumerate(self.quiz.get('options', [])[:4]):
                letter = chr(65 + i)
                lines.append(f"- **{letter}.** {option}")
            if self.quiz.get('answer'):
                lines.append(f"\n<details><summary>Đáp án</summary>{self.quiz['answer']} — {self.quiz.get('explanation','')}</details>")
        return "\n".join(lines)


class AITeacher:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None):
        self.api_key = api_key if api_key is not None else os.getenv("AI_API_KEY", "")
        self.base_url = base_url or os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
        self.model = model or os.getenv("AI_MODEL", "gpt-4o-mini")

    @property
    def available(self) -> bool:
        return bool(self.api_key and OpenAI is not None)

    def _fallback(self, sentence: str) -> TeacherResult:
        words = re.findall(r"[A-Za-z][A-Za-z'’-]*", sentence)
        vocab = [{"word": w, "meaning": "Tra cứu nghĩa theo ngữ cảnh", "type": "word", "example": sentence} for w in words[:8]]
        return TeacherResult(
            translation="AI chưa được cấu hình. Hãy thêm AI_API_KEY để nhận bản dịch và phân tích đầy đủ.",
            grammar={"structure": "Xem câu mẫu", "tense": "AI analysis unavailable", "subject": "—", "main_verb": "—", "explanation": "Có thể vẫn luyện nghe và shadowing khi AI không khả dụng."},
            vocabulary=vocab,
            pattern=sentence,
        )

    def analyze(self, sentence: str) -> TeacherResult:
        sentence = (sentence or "").strip()
        if not sentence:
            return TeacherResult(translation="Chưa chọn câu.")
        if not self.available:
            return self._fallback(sentence)

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
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            response = client.chat.completions.create(
                model=self.model,
                temperature=0.15,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "You are a precise English teacher for Vietnamese learners."},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            return TeacherResult(
                translation=str(data.get("translation", "")),
                grammar=data.get("grammar") or {},
                vocabulary=data.get("vocabulary") or [],
                collocations=data.get("collocations") or [],
                pattern=str(data.get("pattern", "")),
                pronunciation=data.get("pronunciation") or [],
                examples=data.get("examples") or [],
                quiz=data.get("quiz") or {},
                raw=raw,
            )
        except Exception as exc:
            fallback = self._fallback(sentence)
            fallback.raw = f"AI error: {exc}"
            return fallback
