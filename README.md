---
title: English Learning Lab
emoji: 📜
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: 5.50.0
app_file: app.py
pinned: false
---

# 🇬🇧 English Learning Lab — V2.6

Professional YouTube-based English listening, shadowing, pronunciation, grammar, vocabulary, quiz and progress-learning app for Vietnamese learners.

## Learning flow

**YouTube → transcript → Listen → Hide/Reveal → Translate → Shadowing → Qwen3-4B AI Teacher → Quiz → Spaced Repetition → Progress**

## AI architecture

- Qwen/Qwen3-4B runs locally with Transformers/PyTorch inside the Space.
- No OpenAI API.
- No DeepSeek API.
- No Qwen API.
- No Hugging Face Inference Providers.
- No AI API key is required for the local teacher when the public model can be downloaded.
- Faster-Whisper is used locally for speech recognition/scoring.

## Features

- YouTube playlist import and video library.
- Sentence-level transcript navigation.
- Hide/reveal transcript for listening recall.
- Vietnamese translation.
- Microphone shadowing and speech-to-text scoring.
- Local Qwen3-4B grammar, vocabulary, collocations, pronunciation tips, examples and quiz generation.
- SQLite learning progress.
- Vocabulary review and spaced repetition.
- Quiz history and learning statistics.
- Mobile-first Gradio UI.

## Hugging Face ZeroGPU

Select **ZeroGPU** hardware for the Space when available. ZeroGPU is dynamically allocated and is compatible with Gradio Spaces. Free accounts in good standing can host up to 2 ZeroGPU Spaces; the current documented Free quota is 5 minutes of GPU usage per 24 hours. See the official documentation for current limits:

https://huggingface.co/docs/hub/spaces-zerogpu

The Qwen analysis function uses `@spaces.GPU`, and the model is prepared at process startup for efficient ZeroGPU execution.

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
├── app.py                 # single production entrypoint
├── core.py                # YouTube, transcript, speech and app helpers
├── ai/
│   └── teacher.py         # local Qwen3-4B AI Teacher
├── learning/
│   └── progress.py        # SQLite, vocabulary, SRS and quiz progress
├── speech/
│   └── scoring.py         # shadowing/scoring engine
├── requirements.txt
└── README.md
```

## Deployment

Configure the Space as a Gradio Space and set `app.py` as the application file. Hugging Face Spaces rebuilds and restarts after commits to the Space repository.
