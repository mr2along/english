---
title: English Learning Lab
emoji: 🎧
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: "5.44.1"
python_version: "3.10"
app_file: app.py
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

## Run

```bash
pip install -r requirements.txt
python app.py
```

The app uses Playwright Async to access the Tactiq YouTube transcript page. No yt-dlp is required.
