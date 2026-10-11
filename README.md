---
title: English Learning Lab
emoji: 🎧
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# English Learning Lab

English listening and shadowing practice built with Gradio. The app uses the precomputed transcript library in `Transcription/final_transcripts.json` and embeds YouTube videos for playback.

## Learning functions

- Browse and search the 165 lesson library, open a lesson by its video URL or ID, and move between lessons.
- Select timestamped transcript sentences, navigate between them, set playback speed, and repeat a sentence 1, 2, 3, 5, or unlimited times.
- Prepare a sentence-by-sentence listening and shadowing session, play the selected sentence, and mark practiced sentences.
- Compare typed or browser speech-to-text against a sample sentence. The score measures word content and order; it does not assess audio quality or pronunciation acoustics.
- Generate grammar and vocabulary prompts from the selected sentence. These are prompts to copy into an AI assistant; the Space does not call an AI model.
- Create changing fill-in-the-blank or listen-and-type quizzes and check answers.
- Schedule individual sentences for spaced review and load sentences that are due.
- Preview imported TXT, SRT, WebVTT, or JSON transcripts. Previewing does not overwrite the published lesson library.
- Run optional WhisperX recognition and forced alignment on an uploaded audio/video file; download the resulting JSON and SRT. JSON keeps word-level timestamps for later addition to the lesson library.

Learning progress is stored in the visitor's browser using a stable, app-specific Gradio BrowserState key. It is private to that browser and is not shared between Space visitors. Clearing browser storage removes it; it is not backed up to the Space server or synchronized across devices. Set `ENGLISH_LAB_BROWSER_STATE_SECRET` in the environment to override the default state-protection key.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

The Space Docker image installs Gradio, CPU-only PyTorch, WhisperX, and FFmpeg so the WhisperX tab works after deployment. WhisperX model weights are downloaded only on the first transcription request; the default model is `small` with `int8` computation for CPU use. The default Space hardware is CPU, so processing may take a while for long files. The app does not download YouTube captions or audio.

### Run WhisperX locally

Install the optional dependency set in the same environment as the app:

```bash
pip install -r requirements.txt
pip install -r requirements-whisperx.txt
python app.py
```

The WhisperX tab accepts one local audio/video file, detects language automatically or uses the selected language, aligns recognized words, and provides JSON/SRT downloads. The default model is `small`; larger models need more memory and take longer, especially on CPU. FFmpeg must be installed and available on `PATH`. For GPU use, install a PyTorch build compatible with the machine's CUDA setup before installing WhisperX.

The same processor can run from the command line:

```bash
python Transcription/run_whisperx.py path/to/audio.mp3 --video-id dQw4w9WgXcQ --title "Lesson title"
```

Without `--video-id`, the result is still a standalone transcript, but it cannot be matched to a YouTube lesson in the library. JSON and SRT files are written under `Transcription/whisperx_outputs/` by default. Uploading a transcript file in English Lab only previews it; it does not overwrite the published transcript library. `core/qwen_mapper.py` remains an optional local sentence-mapping utility; install `requirements-ml.txt` before loading its Qwen model.

## Deploy

`.github/workflows/deploy-hf.yml` deploys pushes to `feature/english-lab-v21` to `Mrlongpro/autosubs` through Hugging Face Trusted Publisher OIDC. It needs a matching Trusted Publisher resource configured for `spaces/Mrlongpro/autosubs`; no long-lived Hugging Face token is stored in GitHub Actions.
