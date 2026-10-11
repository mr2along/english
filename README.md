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

Learning progress is stored in the visitor's browser using a stable, app-specific Gradio BrowserState key. It is private to that browser and is not shared between Space visitors. Clearing browser storage removes it; it is not backed up to the Space server or synchronized across devices. Set `ENGLISH_LAB_BROWSER_STATE_SECRET` in the environment to override the default state-protection key.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

The Space runtime installs Gradio only; the app does not download YouTube captions or audio. `core/qwen_mapper.py` is an optional local sentence-mapping utility. Install `requirements-ml.txt` before loading its Qwen model. The transcript generation/alignment pipeline is not included in this repository; the Space serves the checked-in transcript library.

## Deploy

`.github/workflows/deploy-hf.yml` deploys pushes to `feature/english-lab-v21` to `Mrlongpro/autosubs` through Hugging Face Trusted Publisher OIDC. It needs a matching Trusted Publisher resource configured for `spaces/Mrlongpro/autosubs`; no long-lived Hugging Face token is stored in GitHub Actions.
