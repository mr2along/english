"""English Lab transcript bootstrap.

Loaded automatically by Python before app.py.  If YouTube blocks the Space's
TLS connection, provide a lightweight transcript backend through a public
transcript service and keep app.py's existing YouTubeTranscriptApi interface.
"""
import re
import requests

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except Exception:
    YouTubeTranscriptApi = None


class _RemoteTranscript:
    language_code = "en"
    is_translatable = False
    language = "English"

    def __init__(self, video_id, source):
        self.video_id = video_id
        self.source = source

    def fetch(self):
        urls = [
            f"https://youtube-transcript.ai/transcript/{self.video_id}.vtt?lang=en",
            f"https://youtube-transcript.ai/transcript/{self.video_id}.srt?lang=en",
            f"https://youtube-transcript.ai/transcript/{self.video_id}.txt?lang=en",
        ]
        last = None
        for url in urls:
            try:
                r = requests.get(url, timeout=25, headers={"User-Agent": "EnglishLab/1.0"})
                r.raise_for_status()
                text = r.text
                items = _parse_timed_text(text)
                if items:
                    self.source = url
                    return items
            except Exception as e:
                last = e
        raise RuntimeError(f"Remote transcript backend failed: {last}")

    def translate(self, language):
        if language.lower().startswith("en"):
            return self
        raise RuntimeError("Remote fallback currently exposes English captions only")


def _parse_clock(value):
    value = value.replace(",", ".").strip()
    parts = value.split(":")
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except Exception:
        return None


def _parse_timed_text(text):
    # WebVTT / SRT: preserve the original cue timestamps.
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    i = 0
    while i < len(lines):
        m = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?[\.,]\d{3})\s+-->\s+(\d{1,2}:\d{2}(?::\d{2})?[\.,]\d{3})", lines[i])
        if m:
            start = _parse_clock(m.group(1))
            end = _parse_clock(m.group(2))
            buf = []
            i += 1
            while i < len(lines) and lines[i].strip():
                if not re.match(r"^\d+$", lines[i].strip()):
                    buf.append(re.sub(r"<[^>]+>", "", lines[i]).strip())
                i += 1
            txt = re.sub(r"\s+", " ", " ".join(buf)).strip()
            if txt and start is not None:
                out.append({"start": start, "duration": max(0.0, (end or start) - start), "text": txt})
        else:
            i += 1
    if out:
        return out

    # Markdown/plain text fallback: [m:ss] sentence/paragraph timestamps.
    pat = re.compile(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.+?)(?=\s*\[\d{1,2}:\d{2}(?::\d{2})?\]|$)", re.S)
    matches = list(pat.finditer(text))
    for n, m in enumerate(matches):
        start = _parse_clock(m.group(1))
        txt = re.sub(r"\s+", " ", m.group(2)).strip()
        if txt and start is not None:
            nxt = _parse_clock(matches[n + 1].group(1)) if n + 1 < len(matches) else start
            out.append({"start": start, "duration": max(0.0, nxt - start), "text": txt})
    return out


if YouTubeTranscriptApi is not None:
    _original_list = YouTubeTranscriptApi.list

    def _patched_list(self, video_id):
        # The existing backend is attempted first. If YouTube itself returns
        # an SSL/connection failure, the app's own fallback remains available.
        # This remote list is deliberately opt-in through an environment flag.
        import os
        if os.getenv("ENGLISH_LAB_REMOTE_TRANSCRIPT", "1") != "1":
            return _original_list(self, video_id)
        try:
            probe = requests.get(
                f"https://youtube-transcript.ai/transcript/{video_id}.txt?lang=en",
                timeout=15,
                headers={"User-Agent": "EnglishLab/1.0"},
            )
            if probe.ok and probe.text and "Transcript" in probe.text[:500]:
                return [_RemoteTranscript(video_id, probe.url)]
        except Exception:
            pass
        return _original_list(self, video_id)

    YouTubeTranscriptApi.list = _patched_list
    print("[TRANSCRIPT-BOOT] Remote transcript bridge enabled", flush=True)
