from typing import Dict, Any

SYSTEM_PROMPT = "You are an English teacher. Explain clearly, correct mistakes, and use the lesson context."


def build_prompt(task: str, text: str, context: str = "") -> str:
    return f"{SYSTEM_PROMPT}\nTask: {task}\nLesson sentence: {text}\nContext: {context}".strip()


def grammar_request(text: str) -> Dict[str, Any]:
    return {"task": "grammar", "prompt": build_prompt("Explain the grammar and give one simple example.", text)}


def vocabulary_request(word: str, sentence: str = "") -> Dict[str, Any]:
    return {"task": "vocabulary", "prompt": build_prompt("Explain meaning, pronunciation, part of speech, and examples.", sentence or word)}
