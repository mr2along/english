# 🇬🇧 English Learning Lab

A professional YouTube-based English listening, shadowing, pronunciation, grammar, vocabulary and progress-learning app designed for Hugging Face Spaces.

## V2.3 — Local AI Teacher

AI Teacher runs **locally inside the Hugging Face Space** with `Qwen/Qwen3-4B` and Transformers. It does not call OpenAI, DeepSeek, Qwen API, or Hugging Face Inference Providers.

Qwen's official model card supports direct Transformers loading and recommends a current Transformers release. urlQwen3-4B model cardhttps://huggingface.co/Qwen/Qwen3-4B

### Recommended free deployment: ZeroGPU

For practical response speed, configure the Space hardware as **ZeroGPU**. Hugging Face documents ZeroGPU as free GPU access for eligible personal accounts; free accounts in good standing can host up to 2 ZeroGPU Spaces. The current free quota is 5 minutes of GPU usage per 24-hour period, subject to the Space queue. urlHugging Face ZeroGPU documentationhttps://huggingface.co/docs/hub/spaces-zerogpu

In the Space:

1. Open **Settings**.
2. Open **Hardware**.
3. Select **ZeroGPU**.
4. Restart/rebuild the Space.

The code uses `spaces.GPU` around the AI generation function so GPU time is requested only when the AI Teacher is used.

### CPU fallback

CPU Basic is still supported, but Qwen3-4B generation is substantially slower. Hugging Face lists CPU Basic at 2 vCPU and 16 GB RAM. urlSpaces hardware documentationhttps://huggingface.co/docs/hub/spaces-overview

### Local model configuration

```text
HF_LOCAL_MODEL=Qwen/Qwen3-4B
HF_LOCAL_MAX_NEW_TOKENS=700
HF_LOCAL_MAX_INPUT_TOKENS=1024
WHISPER_MODEL=small
PORT=7860
```

No `HF_TOKEN` is required for the AI Teacher itself when the public model can be downloaded anonymously.

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
- Microphone practice with Whisper
- Pronunciation/text similarity scoring
- SQLite learning progress
- Responsive mobile-first UI

## Run

```bash
pip install -r requirements.txt
python app_v23.py
```
