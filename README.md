# 🇬🇧 English Learning Lab

A professional YouTube-based English listening, shadowing, pronunciation, grammar, vocabulary and progress-learning app designed for Hugging Face Spaces.

## V2.3 — Local AI Teacher

AI Teacher now runs **locally inside the Hugging Face Space** with `Qwen/Qwen3-4B` and Transformers. It does not call OpenAI, DeepSeek, Qwen API, or Hugging Face Inference Providers.

Qwen's official model card documents direct Transformers loading with `AutoTokenizer` and `AutoModelForCausalLM`; current Qwen3 requires a recent Transformers release. urlQwen3-4B model cardhttps://huggingface.co/Qwen/Qwen3-4B

The model is downloaded/cached on first startup and kept in memory for subsequent requests.

### Space requirements

- **GPU Space:** strongly recommended for practical AI response speed.
- **CPU-only Space:** supported, but Qwen3-4B generation may be slow.
- **Disk:** enough cache/storage for model weights.

No `HF_TOKEN` is required for the AI Teacher itself when the public model can be downloaded anonymously.

### Optional environment variables

```text
HF_LOCAL_MODEL=Qwen/Qwen3-4B
HF_LOCAL_MAX_NEW_TOKENS=1400
WHISPER_MODEL=small
PORT=7860
```

## Main features

- YouTube playlist/video library
- Sentence-level transcript
- Show/hide/focus transcript modes
- Sentence navigation and timestamps
- Local Qwen AI Teacher
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
