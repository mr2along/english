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
- Prepare a sentence-by-sentence listening and shadowing session. The app selects the next unmarked sentence and advances after it is marked.
- Compare typed text or a microphone/upload recording against the sample. WhisperX can transcribe the recording; the score measures word content and order, not acoustic pronunciation quality.
- Generate Vietnamese grammar and vocabulary explanations with Qwen. The model is loaded on the first request; a copyable prompt remains available if model loading fails.
- Create changing fill-in-the-blank or listen-and-type quizzes and check answers.
- Schedule individual sentences for spaced review and load sentences that are due.
- Import TXT, SRT, WebVTT, or JSON into the current session. Practice, quiz, AI Tutor, and review use the imported transcript; the published library is unchanged, and imported-transcript progress is kept separate.
- Fetch a public YouTube caption track by URL or video ID, including auto-generated captions when available. Qwen groups caption fragments into sentences while retaining their timestamps. The fetched lesson is temporary to the current session; it can be practiced, quizzed, reviewed, and exported without modifying the published library.
- Download a single public YouTube video you own or are authorized to download. Downloads exclude livestreams, are limited to two hours and 512 MB, and are offered through a temporary link that expires after about five minutes.
- Use the optional local helper in `browser-extension/` to download audio only or the full video when the Space cannot reach YouTube. Desktop Chrome can use the extension; Android Chrome can use the Termux helper, then upload the saved file to WhisperX.
- Run WhisperX directly on a YouTube URL when a caption track is unavailable. The app downloads audio only to a temporary directory, aligns recognized words, then deletes the audio. Online WhisperX is limited to public, non-live videos up to two hours and 512 MB.
- Run WhisperX recognition and forced alignment on an uploaded audio/video file, download JSON/SRT, or load the result directly into the current lesson session. JSON keeps word-level timestamps.
- View and download the active lesson transcript as JSON, then restore the published transcript at any time.

Learning progress is stored in the visitor's browser using a stable, app-specific Gradio BrowserState key. It is private to that browser and is not shared between Space visitors. Clearing browser storage removes it; it is not backed up to the Space server or synchronized across devices. Set `ENGLISH_LAB_BROWSER_STATE_SECRET` in the environment to override the default state-protection key.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-whisperx.txt
pip install -r requirements-ml.txt
python app.py
```

The Space Docker image installs Gradio, YouTube caption/audio clients, CPU-only PyTorch, WhisperX, Qwen dependencies, and FFmpeg. WhisperX and Qwen model weights are downloaded on their first use. WhisperX defaults to `small` with `int8` computation for CPU use; the default Space hardware is CPU, so processing long files and the first AI request may take a while. Caption mode fetches captions only; online WhisperX mode downloads audio temporarily and deletes it after transcription. Video downloads are kept in a temporary cache: the regular download link expires after five minutes, and a video loaded into the WhisperX tab remains available for up to 60 minutes.

YouTube may block requests from cloud-hosted Space IP addresses. If caption mode reports that YouTube blocked the Space, configure a residential proxy in the Space secrets as `YOUTUBE_TRANSCRIPT_PROXY_USERNAME` and `YOUTUBE_TRANSCRIPT_PROXY_PASSWORD`. WhisperX URL mode accepts an optional complete proxy URL in `YOUTUBE_AUDIO_PROXY`. Online mode requires a public, non-live video; use the WhisperX tab with an uploaded file when a URL cannot be fetched by the Space.

### Audio and AI runtime

The extra dependency files enable microphone transcription and Qwen AI Tutor in the same environment as the app:

```bash
pip install -r requirements-whisperx.txt
pip install -r requirements-ml.txt
```

The WhisperX tab accepts a local source video or audio file. Its YouTube download button uses the Space server and places the full video in the WhisperX file field. If YouTube blocks the Space, the local helper can download audio only or a full video to a desktop or Android device; [Android setup](browser-extension/README.md#android-chrome). WhisperX extracts audio from video, detects language automatically or uses the selected language, aligns recognized words, and provides JSON/SRT downloads. Files and YouTube downloads are limited to 512 MB and two hours. The default model is `small`; larger models need more memory and take longer, especially on CPU. FFmpeg and `ffprobe` must be installed and available on `PATH`. For GPU use, install a PyTorch build compatible with the machine's CUDA setup before installing WhisperX. `requirements-ml.txt` installs the shared Qwen runtime used by AI Tutor and caption sentence grouping. Model inference is queued so only one WhisperX/Qwen job uses the app's memory at a time.

The same processor can run from the command line:

```bash
python Transcription/run_whisperx.py path/to/audio.mp3 --video-id dQw4w9WgXcQ --title "Lesson title"
```

Without `--video-id`, the result is still a standalone transcript, but it cannot be matched to a YouTube lesson in the library. JSON and SRT files are written under `Transcription/whisperx_outputs/` by default. In the app, a transcript can be loaded into the current session or downloaded as JSON; neither action overwrites the published transcript library. `core/qwen_mapper.py` maps caption fragments into sentences for the online caption workflow.

## Deploy

`.github/workflows/deploy-hf.yml` deploys pushes to `feature/english-lab-v21` to `Mrlongpro/autosubs` through Hugging Face Trusted Publisher OIDC. It needs a matching Trusted Publisher resource configured for `spaces/Mrlongpro/autosubs`; no long-lived Hugging Face token is stored in GitHub Actions. The local browser extension is kept in GitHub and excluded from the Space image.

The deployment workflow compiles the Python modules and runs the regression checks in `tests/` before uploading. Run the checks locally with `python -m unittest discover -s tests -v`.
