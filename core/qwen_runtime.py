"""Shared, lazily loaded Qwen runtime for the learning app."""

from __future__ import annotations

import os
import threading
from typing import Any


_TOKENIZER: Any = None
_MODEL: Any = None
_LOAD_LOCK = threading.Lock()


def load_qwen_model() -> tuple[Any, Any]:
    """Load one process-wide Qwen model and tokenizer on first use."""
    global _TOKENIZER, _MODEL
    if _MODEL is not None:
        return _TOKENIZER, _MODEL

    with _LOAD_LOCK:
        if _MODEL is not None:
            return _TOKENIZER, _MODEL

        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as error:
            raise RuntimeError(
                "Thiếu thư viện AI. Cài `requirements-ml.txt` rồi khởi động lại English Lab."
            ) from error

        model_id = os.getenv("QWEN_MODEL", "Qwen/Qwen3-0.6B")
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype="auto",
            device_map="auto",
        )
        model.eval()
        _TOKENIZER, _MODEL = tokenizer, model
        return _TOKENIZER, _MODEL
