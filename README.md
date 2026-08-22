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

A professional YouTube-based English listening, shadowing, pronunciation, grammar, vocabulary and progress-learning app designed for Hugging Face Spaces.

## V2.1

- YouTube playlist/video library
- Sentence-level transcript
- Show/hide/focus transcript modes
- Sentence navigation and timestamps
- Translation and AI grammar explanation
- Microphone practice with Whisper
- Pronunciation/text similarity scoring
- SQLite learning progress
- Responsive mobile-first UI
- Tactiq + Playwright Async transcript extraction

## Runtime

The Space uses a Docker runtime because Playwright requires a real Chromium browser binary. The Docker image installs Chromium during build and exposes Gradio on port 7860.

No yt-dlp, youtube-transcript-api, pytube, or Invidious is used for transcript extraction.

## Local run

```bash
pip install -r requirements.txt
playwright install chromium
python app.py
```
