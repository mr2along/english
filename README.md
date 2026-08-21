# 🇬🇧 English Learning Lab

A professional YouTube-based English listening, shadowing, pronunciation, grammar, vocabulary and progress-learning app designed for Hugging Face Spaces.

## V2.5 — Guided Learning Session

AI Teacher runs locally inside the Hugging Face Space with `Qwen/Qwen3-4B` and Transformers. The learning flow is designed for mobile use:

**Listen → Recall/Reveal → Translate → Shadowing → AI Teacher → Quiz → Next sentence**

No OpenAI, DeepSeek, Qwen API, or Hugging Face Inference Provider is required for the local AI Teacher.

### V2.5 features

- Mobile-first guided learning session.
- Sentence-by-sentence progress indicator.
- Hide/reveal transcript for listening recall.
- Vietnamese translation.
- Microphone shadowing and speech-to-text scoring.
- Local Qwen3-4B grammar/vocabulary/quiz teacher.
- Persistent vocabulary and spaced repetition from V2.4.
- SQLite learning progress.
- YouTube playlist/video library.

### Recommended deployment: ZeroGPU

For practical response speed, configure the Space hardware as **ZeroGPU** when available. Hugging Face documents ZeroGPU as dynamically allocated GPU infrastructure and currently lists a 48 GB `large` configuration; Free personal accounts in good standing can host up to 2 ZeroGPU Spaces with 5 minutes of daily GPU quota. urlHugging Face ZeroGPU documentationhttps://huggingface.co/docs/hub/spaces-zerogpu

ZeroGPU is currently compatible with Gradio Spaces. urlHugging Face Gradio Spaces documentationhttps://huggingface.co/docs/hub/spaces-sdks-gradio

### Local model configuration

```text
HF_LOCAL_MODEL=Qwen/Qwen3-4B
HF_LOCAL_MAX_NEW_TOKENS=700
HF_LOCAL_MAX_INPUT_TOKENS=1024
WHISPER_MODEL=small
PORT=7860
```

No API key is required for the local AI Teacher when the public model can be downloaded anonymously.

## Run

```bash
pip install -r requirements.txt
python app_v25.py
```

## Project structure

```text
english/
├── app.py
├── app_v23.py
├── app_v24.py
├── app_v25.py
├── ai/
│   └── teacher.py
├── learning/
│   └── progress.py
├── speech/
│   └── scoring.py
└── requirements.txt
```
