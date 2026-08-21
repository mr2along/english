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

## Run

```bash
pip install -r requirements.txt
python app.py
```

Optional environment variables:

- `AI_API_KEY`
- `AI_BASE_URL`
- `AI_MODEL`
- `WHISPER_MODEL`

The default lesson playlist is configurable in the UI.
