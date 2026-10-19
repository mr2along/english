from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.file_cleanup import remove_stale_files
from core.learning_engine import make_practice_items
from core.library import segments as library_segments
from core.practice import make_quiz
from core.progress import ProgressStore
from core.qwen_mapper import map_segments_detailed
from core.transcript import normalize, parse_manual, render_transcript_html
from core.whisperx_runner import make_payload, to_srt
from core.youtube_download import download_youtube_video
from core.youtube_transcript import fetch_youtube_transcript, transcribe_youtube_audio
from core.ai_tutor import explain, vocabulary_request


class TranscriptTests(unittest.TestCase):
    def test_single_video_whisperx_json_can_overlay_selected_lesson(self):
        payload = {
            "videos": [
                {
                    "video_id": "source00001",
                    "segments": [{"start": 12.0, "text": "A sentence."}],
                }
            ]
        }

        result = parse_manual(json.dumps(payload), video_id="target00001")

        self.assertEqual([segment["text"] for segment in result], ["A sentence."])
        self.assertGreater(result[0]["duration"], 0)

    def test_multi_video_json_requires_a_matching_lesson(self):
        payload = {
            "videos": [
                {"video_id": "source00001", "segments": [{"start": 0, "text": "one"}]},
                {"video_id": "target00001", "segments": [{"start": 1, "text": "two"}]},
            ]
        }

        result = parse_manual(json.dumps(payload), video_id="target00001")

        self.assertEqual([segment["text"] for segment in result], ["two"])
        with self.assertRaisesRegex(ValueError, "nhiều bài"):
            parse_manual(json.dumps(payload), video_id="other000001")

    def test_timestamp_only_final_caption_gets_playable_duration(self):
        result = parse_manual("[00:00:12] final words here")

        self.assertEqual(len(result), 1)
        self.assertGreater(result[0]["duration"], 0)

    def test_hidden_transcript_keeps_sentence_controls_in_dom(self):
        rendered = render_transcript_html(
            [{"start": 3, "duration": 2, "text": "Hidden text."}], visible=False
        )

        self.assertIn('class="lines transcript-hidden"', rendered)
        self.assertIn('class="line" data-index="0"', rendered)
        self.assertIn("Hidden text.", rendered)

    def test_srt_and_library_segments_keep_positive_ends(self):
        srt = "1\n00:00:02,000 --> 00:00:02,000\nLast line\n"
        parsed = parse_manual(srt)
        loaded = library_segments([{"start": 2, "text": "Last line"}])

        self.assertGreater(parsed[0]["duration"], 0)
        self.assertGreater(loaded[0]["duration"], 0)

    def test_normalize_keeps_word_timing_and_infers_sentence_end(self):
        result = normalize(
            [
                {
                    "start": 4,
                    "text": "A short sentence.",
                    "words": [{"word": "sentence.", "start": 4.5, "end": 5.1}],
                }
            ]
        )

        self.assertEqual(result[0]["words"][0]["word"], "sentence.")
        self.assertAlmostEqual(result[0]["duration"], 1.1)


class LearningFlowTests(unittest.TestCase):
    def test_practice_items_keep_source_sentence_indexes(self):
        items = make_practice_items(
            [
                {"start": 0, "duration": 1, "text": "First."},
                {"start": 1, "duration": 1, "text": ""},
                {"start": 2, "duration": 1, "text": "Third."},
            ]
        )

        self.assertEqual([item["index"] for item in items], [0, 2])

    def test_quiz_hides_a_word_span_and_records_answer(self):
        with patch("core.practice.random.randint", return_value=1):
            question = make_quiz(
                [{"start": 0, "text": "one two three four five six"}], index=0
            )

        self.assertEqual(question["type"], "fill_blank")
        self.assertEqual(question["answer"], "two")
        self.assertIn("____", question["question"])

    def test_spaced_review_uses_due_dates_and_marks_completion(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        store = ProgressStore(data=None)
        store.mark_sentence("lesson00001", 0, sentence_count=1)
        card = store.schedule_review("lesson00001", 0, score=5, now=now)

        self.assertTrue(store.lesson("lesson00001")["completed"])
        self.assertEqual(card["interval_days"], 1)
        self.assertFalse(store.due_reviews("lesson00001", now=now))
        self.assertEqual(
            len(store.due_reviews("lesson00001", now=now + timedelta(days=1))), 1
        )

    def test_caption_mapping_falls_back_when_ai_model_is_unavailable(self):
        raw = [
            {"start": 0, "duration": 0.5, "text": "Hello there."},
            {"start": 0.6, "duration": 0.5, "text": "How are you?"},
        ]
        with patch("core.qwen_mapper._qwen_boundaries", side_effect=RuntimeError("offline")):
            result, summary = map_segments_detailed(raw, batch_size=8)

        self.assertEqual(summary, {"ai_batches": 0, "fallback_batches": 1})
        self.assertEqual(len(result), 2)


class AITutorTests(unittest.TestCase):
    def test_grammar_fragment_does_not_claim_a_tense_or_call_the_model(self):
        with patch("core.ai_tutor._load_tutor_model") as load_model:
            result = explain("grammar", "Okay. The truth.")

        self.assertIn("không thấy động từ hữu hạn", result)
        self.assertIn("chưa thể xác định thì", result)
        load_model.assert_not_called()

    def test_participial_fragment_does_not_get_mistaken_for_a_finite_clause(self):
        with patch("core.ai_tutor._load_tutor_model") as load_model:
            result = explain("grammar", "Having been told the truth.")

        self.assertIn("mảnh câu", result)
        load_model.assert_not_called()

    def test_vocabulary_prompt_does_not_ask_small_model_to_invent_ipa(self):
        prompt = vocabulary_request("", sentence="Okay. The truth.")["prompt"]

        self.assertIn("Do not provide IPA", prompt)
        self.assertIn("do not guess pronunciation", prompt)

    def test_known_vocabulary_uses_verified_entries_instead_of_small_model_guessing(self):
        with patch("core.ai_tutor._load_tutor_model") as load_model:
            result = explain("vocabulary", "Okay. The truth.")

        self.assertIn("interjection", result)
        self.assertIn("sự thật", result)
        self.assertNotIn("thiên nhiên", result)
        load_model.assert_not_called()


class MediaFlowTests(unittest.TestCase):
    def test_caption_connection_error_gives_proxy_setup_guidance(self):
        class NetworkError(Exception):
            def __str__(self):
                return "HTTPSConnectionPool: Max retries exceeded (SSLEOFError)"

        with patch("core.youtube_transcript._api", side_effect=NetworkError()):
            with self.assertRaisesRegex(RuntimeError, "YOUTUBE_TRANSCRIPT_PROXY_USERNAME"):
                fetch_youtube_transcript("dQw4w9WgXcQ")

    def test_video_download_connection_error_gives_audio_proxy_guidance(self):
        class NetworkError(Exception):
            pass

        class FakeYoutubeDL:
            def __init__(self, _options):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, download=True):
                raise NetworkError("HTTPSConnectionPool: Max retries exceeded (SSLEOFError)")

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.dict(sys.modules, {"yt_dlp": SimpleNamespace(YoutubeDL=FakeYoutubeDL)}),
                patch("core.youtube_download.DOWNLOAD_CACHE_DIR", Path(directory) / "downloads"),
            ):
                with self.assertRaisesRegex(RuntimeError, "YOUTUBE_AUDIO_PROXY"):
                    download_youtube_video("dQw4w9WgXcQ")

    def test_youtube_download_returns_one_short_lived_video_file(self):
        video_id = "dQw4w9WgXcQ"

        class FakeYoutubeDL:
            def __init__(self, options):
                self.options = options
                self.path = Path(
                    options["outtmpl"].replace("%(id)s.%(ext)s", f"{video_id}.mp4")
                )

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, download=True):
                info = {"id": video_id, "title": "Sample lesson", "duration": 12, "ext": "mp4"}
                rejection = self.options["match_filter"](info)
                if rejection:
                    raise RuntimeError(rejection)
                self.path.write_bytes(b"video bytes")
                return info

            def prepare_filename(self, _info):
                return str(self.path)

        fake_module = SimpleNamespace(YoutubeDL=FakeYoutubeDL)
        with tempfile.TemporaryDirectory() as temporary_dir:
            destination = Path(temporary_dir) / "downloads"
            with (
                patch.dict(sys.modules, {"yt_dlp": fake_module}),
                patch("core.youtube_download.DOWNLOAD_CACHE_DIR", destination),
                patch("core.youtube_download._schedule_cleanup"),
            ):
                result = download_youtube_video(
                    f"https://www.youtube.com/watch?v={video_id}"
                )

            output = Path(result["path"])
            self.assertEqual(result["video_id"], video_id)
            self.assertEqual(result["title"], "Sample lesson")
            self.assertEqual(output.read_bytes(), b"video bytes")
            self.assertEqual(output.suffix, ".mp4")

    def test_youtube_whisperx_rejects_video_with_unknown_duration(self):
        class FakeYoutubeDL:
            def __init__(self, options):
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, download=True):
                error = self.options["match_filter"](
                    {"id": "dQw4w9WgXcQ", "duration": None}
                )
                if error:
                    raise RuntimeError(error)
                raise AssertionError("unknown duration should be rejected")

        with (
            patch.dict(sys.modules, {"yt_dlp": SimpleNamespace(YoutubeDL=FakeYoutubeDL)}),
            patch("core.whisperx_runner.transcribe_file") as transcribe,
        ):
            with self.assertRaisesRegex(RuntimeError, "Không xác định được thời lượng"):
                transcribe_youtube_audio("dQw4w9WgXcQ")

        transcribe.assert_not_called()

    def test_whisperx_payload_exports_valid_srt(self):
        payload = make_payload(
            {
                "language": "en",
                "model": "small",
                "segments": [{"start": 1.25, "end": 2.5, "text": "Hello world."}],
            },
            source_name="lesson.wav",
        )

        srt = to_srt(payload)

        self.assertIn("00:00:01,250 --> 00:00:02,500", srt)
        self.assertIn("Hello world.", srt)

    def test_stale_generated_files_are_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            stale = Path(directory) / "stale.json"
            current = Path(directory) / "current.json"
            stale.write_text("old", encoding="utf-8")
            current.write_text("new", encoding="utf-8")
            stale.touch()
            now = stale.stat().st_mtime + 60
            os.utime(current, (now - 1, now - 1))
            with patch("core.file_cleanup.time.time", return_value=now):
                remove_stale_files(directory, max_age_seconds=30)

            self.assertFalse(stale.exists())
            self.assertTrue(current.exists())


if __name__ == "__main__":
    unittest.main()
