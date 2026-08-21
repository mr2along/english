---
title: English Learning Lab
emoji: 📜
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: 5.50.0
app_file: app.py
pinned: false
python_version: 3.11
---

# 🇬🇧 English Learning Lab — V2.7

Professional YouTube-based English listening, shadowing, pronunciation, grammar, vocabulary, quiz and progress-learning app for Vietnamese learners.

## Learning flow

**YouTube → transcript → Listen → Hide/Reveal → Translate → Shadowing → Qwen3-4B AI Teacher → Quiz → Progress**

## Runtime

- Gradio SSR is disabled in `app.py` for Hugging Face Space compatibility.
- Python 3.11 is explicitly declared for the Space.
- Local Qwen3-4B and Faster-Whisper are used for AI and speech scoring.

## AI architecture

- Qwen/Qwen3-4B runs locally with Transformers/PyTorch inside the Space.
- No OpenAI API, DeepSeek API or Qwen API is required.
- Faster-Whisper is used locally for speech recognition/scoring.

## Features

- YouTube playlist import and video library.
- Sentence-level transcript navigation.
- Hide/reveal transcript for listening recall.
- Vietnamese translation.
- Microphone shadowing and speech-to-text scoring.
- Local Qwen3-4B grammar, vocabulary, collocations, pronunciation tips, examples and quiz generation.
- SQLite learning progress.
- Mobile-first Gradio UI.

## Environment

```text
HF_LOCAL_MODEL=Qwen/Qwen3-4B
HF_LOCAL_MAX_NEW_TOKENS=500
HF_LOCAL_MAX_INPUT_TOKENS=1024
WHISPER_MODEL=small
PORT=7860
```

## Local run

```bash
pip install -r requirements.txt
python app.py
```

## Project structure

```text
english/
├── app.py
├── core.py
├── ai/
├── learning/
├── speech/
├── requirements.txt
└── README.md
```
