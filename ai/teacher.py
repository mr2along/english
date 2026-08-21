"""Local AI Teacher powered by Qwen3-4B.

The model runs inside the Hugging Face Space with Transformers.
No OpenAI, DeepSeek, Qwen API, Inference Providers, or API key is used.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
except Exception:
    torch = None
    AutoModelForCausalLM = None
    AutoTokenizer = None

try:
    import spaces
except Exception:
    class _SpacesFallback:
        @staticmethod
        def GPU(*args, **kwargs):
            def deco(fn):
                return fn
            return deco
    spaces = _SpacesFallback()

MODEL_NAME = os.getenv("HF_LOCAL_MODEL", "Qwen/Qwen3-4B")
MAX_NEW_TOKENS = int(os.getenv("HF_LOCAL_MAX_NEW_TOKENS", "700"))
MAX_INPUT_TOKENS = int(os.getenv("HF_LOCAL_MAX_INPUT_TOKENS", "1024"))

_tokenizer = None
_model = None


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
            "## 🇬🇧 AI Teacher — Qwen3-4B Local",
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


def _load_model():
    """Load Qwen once, using low-memory loading and the best available device."""
    global _tokenizer, _model
    if _tokenizer is not None and _model is not None:
        return _tokenizer, _model
    if AutoTokenizer is None or AutoModelForCausalLM is None or torch is None:
        raise RuntimeError("transformers/torch are not installed")

    _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, use_fast=True)

    if torch.cuda.is_available():
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        _model = AutoModelForCausalLM.from_pretrained(
            MODEL_NAME,
            torch_dtype=dtype,
            device_map="auto",
            low_cpu_mem_usage=True,
        )
    else:
        # CPU Basic has 16 GB RAM; BF16 keeps the 4B model substantially smaller
        # than FP32. Generation is slower, but remains possible without an API.
        _model = AutoModelForCausalLM.from_pretrained(
            MODEL_NAME,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
        )
        _model.to("cpu")

    _model.eval()
    return _tokenizer, _model


def _extract_json(text: str) -> Dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match:
            return json.loads(match.group(0))
        raise


class AITeacher:
    """AI teacher using Qwen3-4B entirely inside the Space."""

    @property
    def available(self) -> bool:
        return AutoTokenizer is not None and AutoModelForCausalLM is not None and torch is not None

    def _fallback(self, sentence: str, reason: str = "") -> TeacherResult:
        words = re.findall(r"[A-Za-z][A-Za-z'’-]*", sentence)
        vocab = [{"word": w, "meaning": "Tra cứu nghĩa theo ngữ cảnh", "type": "word", "example": sentence} for w in words[:8]]
        msg = "Qwen3-4B local chưa khả dụng."
        if reason:
            msg += f" {reason}"
        return TeacherResult(
            translation=msg,
            grammar={"structure": "Xem câu mẫu", "tense": "AI analysis unavailable", "subject": "—", "main_verb": "—", "explanation": "Kiểm tra transformers, torch và tài nguyên Space."},
            vocabulary=vocab,
            pattern=sentence,
        )

    @spaces.GPU(duration=180)
    def analyze(self, sentence: str) -> TeacherResult:
        sentence = (sentence or "").strip()
        if not sentence:
            return TeacherResult(translation="Chưa chọn câu.")
        if not self.available:
            return self._fallback(sentence, "Thiếu PyTorch/Transformers.")

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
        prompt = f"""Analyze this English sentence for a Vietnamese learner. Return ONLY valid JSON matching this shape:\n{json.dumps(schema, ensure_ascii=False)}\n\nSentence: {sentence}\nRules: be accurate; explain grammar simply; preserve natural meaning; include pronunciation advice when useful; quiz must test this sentence."""
        try:
            tokenizer, model = _load_model()
            messages = [
                {"role": "system", "content": "You are a precise English teacher for Vietnamese learners. Return JSON only. Do not include reasoning or markdown."},
                {"role": "user", "content": prompt},
            ]
            text = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            inputs = tokenizer(
                [text],
                return_tensors="pt",
                truncation=True,
                max_length=MAX_INPUT_TOKENS,
            )
            device = next(model.parameters()).device
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.inference_mode():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=MAX_NEW_TOKENS,
                    do_sample=False,
                    repetition_penalty=1.05,
                    use_cache=True,
                )
            generated = outputs[0][inputs["input_ids"].shape[-1]:]
            raw = tokenizer.decode(generated, skip_special_tokens=True).strip()
            data = _extract_json(raw)
            return TeacherResult(
                translation=str(data.get("translation", "")), grammar=data.get("grammar") or {},
                vocabulary=data.get("vocabulary") or [], collocations=data.get("collocations") or [],
                pattern=str(data.get("pattern", "")), pronunciation=data.get("pronunciation") or [],
                examples=data.get("examples") or [], quiz=data.get("quiz") or {}, raw=raw,
            )
        except Exception as exc:
            fallback = self._fallback(sentence, f"Lỗi local Qwen: {type(exc).__name__}.")
            fallback.raw = f"Local Qwen error: {exc}"
            return fallback
