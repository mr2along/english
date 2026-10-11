#!/usr/bin/env python3
"""Transcribe one local audio/video file with WhisperX and export JSON + SRT."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.whisperx_runner import YOUTUBE_ID_RE, make_payload, transcribe_file, write_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run WhisperX speech recognition and word-level alignment on a local file."
    )
    parser.add_argument("audio", type=Path, help="Path to a local audio or video file")
    parser.add_argument("--video-id", help="Optional 11-character YouTube video ID")
    parser.add_argument("--title", help="Optional lesson title")
    parser.add_argument("--model", default="small", help="Whisper model (default: small)")
    parser.add_argument("--language", default="auto", help="Language code or auto (default: auto)")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument(
        "--compute-type",
        choices=["default", "float16", "float32", "int8"],
        default="int8",
    )
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "Transcription" / "whisperx_outputs")
    parser.add_argument("--json", dest="json_path", type=Path, help="Explicit JSON output path")
    parser.add_argument("--srt", dest="srt_path", type=Path, help="Explicit SRT output path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.video_id and not YOUTUBE_ID_RE.fullmatch(args.video_id.strip()):
        raise SystemExit("--video-id must be exactly 11 valid YouTube ID characters")
    language = None if args.language.lower() == "auto" else args.language
    result = transcribe_file(
        args.audio,
        model_name=args.model,
        language=language,
        device=args.device,
        compute_type=args.compute_type,
        batch_size=args.batch_size,
    )
    payload = make_payload(
        result,
        source_name=args.audio.name,
        video_id=args.video_id,
        title=args.title,
    )

    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", args.audio.stem).strip("_") or "audio"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.json_path or args.output_dir / f"whisperx_{safe_stem}_{stamp}.json"
    srt_path = args.srt_path or json_path.with_suffix(".srt")
    json_file, srt_file = write_outputs(payload, json_path, srt_path)
    video = payload["videos"][0]
    print(
        f"WhisperX completed: {video['sentence_count']} segments, "
        f"{video['word_count']} aligned words, language={result['language']}"
    )
    print(f"JSON: {json_file}")
    print(f"SRT : {srt_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
