"""Tests for report-language detection and original-language caption picking."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from download import _pick_subtitle, source_language, sub_lang_patterns  # noqa: E402
from languages import describe, name_for, normalize, same_language  # noqa: E402
from report import write_report  # noqa: E402
from watch import resolve_report_language  # noqa: E402
from whisper_local import detected_language  # noqa: E402


class TestLanguageNames(unittest.TestCase):

    def test_names_and_normalisation(self):
        self.assertEqual(name_for("pl"), "Polish")
        self.assertEqual(name_for("en-orig"), "English")
        self.assertEqual(name_for("pt-BR"), "Brazilian Portuguese")
        self.assertIsNone(name_for("zz"))
        self.assertEqual(normalize("PL"), "pl")
        self.assertIsNone(normalize("auto"))
        self.assertIsNone(normalize(None))
        self.assertEqual(describe("ja"), "Japanese (ja)")
        self.assertEqual(describe(None), "unknown")
        self.assertTrue(same_language("pt", "pt-BR"))
        self.assertFalse(same_language("pl", "en"))


class TestSourceLanguage(unittest.TestCase):

    def test_prefers_metadata_then_orig_track(self):
        self.assertEqual(source_language({"language": "pl"}), "pl")
        self.assertEqual(
            source_language({"automatic_captions": {"en": [], "pl-orig": []}}), "pl"
        )
        self.assertEqual(source_language({"subtitles": {"de": []}}), "de")
        self.assertIsNone(source_language({"subtitles": {"de": [], "fr": []}}))
        self.assertIsNone(source_language(None))

    def test_sub_langs_target_the_spoken_language(self):
        # A Polish video must not request `en` — that pulls a machine translation.
        self.assertEqual(sub_lang_patterns("pl"), ["pl.*"])
        self.assertEqual(sub_lang_patterns("pt-BR"), ["pt.*"])
        self.assertEqual(sub_lang_patterns(None), ["en.*", ".*-orig"])


class TestSubtitlePicking(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="watch-subs-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, *names):
        for name in names:
            (self.tmp / name).write_text("", encoding="utf-8")

    def test_human_captions_beat_auto_in_same_language(self):
        self._touch("video.pl.vtt", "video.pl-orig.vtt", "video.en.vtt")
        path, lang = _pick_subtitle(self.tmp, "pl", manual_langs={"pl"})
        self.assertEqual(path.name, "video.pl.vtt")
        self.assertEqual(lang, "pl")

    def test_auto_only_prefers_original_asr_track(self):
        self._touch("video.pl.vtt", "video.pl-orig.vtt")
        path, _ = _pick_subtitle(self.tmp, "pl", manual_langs=set())
        self.assertEqual(path.name, "video.pl-orig.vtt")

    def test_english_is_last_resort_on_a_foreign_video(self):
        self._touch("video.en.vtt", "video.de-orig.vtt")
        path, lang = _pick_subtitle(self.tmp, "pl", manual_langs=set())
        self.assertEqual(path.name, "video.de-orig.vtt")
        self.assertEqual(lang, "de")

    def test_no_captions(self):
        self.assertEqual(_pick_subtitle(self.tmp, "pl"), (None, None))


class TestDetectedLanguage(unittest.TestCase):

    def test_reads_whisper_result_language(self):
        self.assertEqual(
            detected_language({"result": {"language": "pl"}, "params": {"language": "auto"}}),
            "pl",
        )
        # Older builds only echo the request back in params.
        self.assertEqual(detected_language({"params": {"language": "de"}}), "de")
        self.assertIsNone(detected_language({"params": {"language": "auto"}}))
        self.assertIsNone(detected_language({}))


class TestResolveReportLanguage(unittest.TestCase):

    def test_precedence(self):
        self.assertEqual(
            resolve_report_language("en", "pl", "pl", "pl", "pl", "pl"),
            ("en", "--report-lang"),
        )
        self.assertEqual(
            resolve_report_language("auto", "pl", "en", "en", None, "auto"),
            ("pl", "whisper (full audio)"),
        )
        self.assertEqual(
            resolve_report_language("auto", None, "ja", "en", None, "auto"),
            ("ja", "source metadata"),
        )
        self.assertEqual(
            resolve_report_language("auto", None, None, "de", "de", "auto"),
            ("de", "caption track"),
        )
        self.assertEqual(
            resolve_report_language("auto", None, None, None, "it", "auto"),
            ("it", "whisper (hook, 10s)"),
        )
        self.assertEqual(
            resolve_report_language("auto", None, None, None, None, "auto"),
            (None, None),
        )


class TestReportLanguageMarkers(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="watch-report-lang-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, language):
        out = write_report(
            out_path=self.tmp / "report.md",
            source="video.mp4",
            title="Test",
            duration_seconds=60.0,
            intent="general summary",
            transcript_segments=[{"start": 0.0, "end": 1.0, "text": "Dzień dobry."}],
            transcript_source="whisper (local large-v3-q5_0)",
            all_frames=[{"index": 0, "timestamp_seconds": 0.0, "path": "/tmp/f1.jpg"}],
            hero_frames=[],
            pacing={"shot_count": 0},
            hook={"frames": [], "words": [], "ran": False, "skipped_reason": "n/a"},
            language=language,
            language_source="whisper (full audio)",
        )
        return out.read_text(encoding="utf-8")

    def test_markers_and_frontmatter_name_the_language(self):
        text = self._write("pl")
        self.assertIn("language: Polish (pl)", text)
        self.assertIn("language_detected_by: whisper (full audio)", text)
        self.assertIn("REPORT LANGUAGE: Polish.", text)
        self.assertIn("<!-- pending Claude fill (in Polish):", text)
        self.assertIn("Language: Polish (pl)._", text)
        # Quotes must be reproduced, not translated.
        self.assertIn("never translate a quote", text)

    def test_unknown_language_falls_back_to_the_transcript(self):
        text = self._write(None)
        self.assertIn("language: unknown", text)
        self.assertIn("<!-- pending Claude fill (in the video's spoken language):", text)
        self.assertIn("the language spoken in the video", text)


if __name__ == "__main__":
    unittest.main()
