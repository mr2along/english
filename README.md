# 🇬🇧 English Learning Lab

A professional YouTube-based English listening, shadowing, pronunciation, grammar, vocabulary and progress-learning app designed for Hugging Face Spaces.

## V2.4 — Local AI + Learning System

AI Teacher runs **locally inside the Hugging Face Space** with `Qwen/Qwen3-4B` and Transformers. It does not call OpenAI, DeepSeek, Qwen API, or Hugging Face Inference Providers.

Qwen's official model card supports direct Transformers loading and recommends a current Transformers release.

### New in V2.4

- Persistent vocabulary extracted from AI Teacher results.
- Spaced repetition scheduler based on an SM-2-inspired algorithm.
- Daily due-word queue.
- Vocabulary mastery tracking.
- Interactive multiple-choice quiz generated from the current sentence.
- Quiz accuracy statistics.
- SQLite persistence so learning history survives Space restarts when persistent storage is available.

### Recommended deployment: ZeroGPU

For practical response speed, configure the Space hardware as **ZeroGPU**. Hugging Face documents ZeroGPU as dynamically allocated GPU infrastructure; eligible free personal accounts can host up to 2 ZeroGPU Spaces and the current Free quota is 5 minutes of GPU time per 24 hours.

In the Space:

1. Open **Settings**.
2. Open **Hardware**.
3. Select **ZeroGPU** if it is available for the account.
4. Restart/rebuild the Space.

The app uses `spaces.GPU` for local model inference. ZeroGPU is currently Gradio-only.

### CPU fallback

CPU Basic remains supported, but Qwen3-4B generation is substantially slower. Hugging Face lists CPU Basic as 2 vCPU / 16 GB RAM.

### Local model configuration

```text
HF_LOCAL_MODEL=Qwen/Qwen3-4B
HF_LOCAL_MAX_NEW_TOKENS=700
HF_LOCAL_MAX_INPUT_TOKENS=1024
WHISPER_MODEL=small
PORT=7860
```

No API key is required for the local AI Teacher when the public model can be downloaded anonymously.

## Main features

- YouTube playlist/video library
- Sentence-level transcript
- Show/hide/focus transcript modes
- Sentence navigation and timestamps
- Local Qwen3-4B AI Teacher
- Vietnamese translation
- Grammar explanation
- Vocabulary and collocations
- Sentence patterns
- Pronunciation tips
- AI-generated mini quiz
- Persistent vocabulary database
- Spaced repetition / due review queue
- Vocabulary mastery tracking
- Interactive quiz and accuracy tracking
- Microphone practice with Whisper
- Pronunciation/text similarity scoring
- SQLite learning progress
- Responsive mobile-first UI

## Run

```bash
pip install -r requirements.txt
python app_v24.py
```

## Project structure

```text
english/
├── app.py
├── app_v23.py
├── app_v24.py
├── ai/
│   └── teacher.py
├── learning/
│   └── progress.py
├── speech/
│   └── scoring.py
└── requirements.txt
```
