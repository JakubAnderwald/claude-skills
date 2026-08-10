"""Tests for report.md emission."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from report import is_form_intent, write_report  # noqa: E402

CONTENT_SECTIONS = (
    "## TL;DR",
    "## Setup & premise",
    "## How it unfolds",
    "## Findings",
    "## Conclusions & caveats",
    "## Notable quotes",
    "## Entities mentioned",
    "## Concepts surfaced",
    "## Transcript",
)
FORM_SECTIONS = ("## Hook microscope", "## Editorial profile")

PACING = {
    "shot_count": 6,
    "cuts_per_minute": 2.88,
    "mean_shot_length": 20.83,
    "median_shot_length": 18.5,
    "shots": [],
}


class TestReport(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="watch-report-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name="report.md", **overrides):
        kwargs = dict(
            out_path=self.tmp / name,
            source="https://youtu.be/test",
            title="Test Video",
            duration_seconds=125.0,
            intent="summarise the test results",
            transcript_segments=[
                {"start": 0.0, "end": 2.0, "text": "Hello world."},
                {"start": 2.0, "end": 5.0, "text": "Second segment."},
            ],
            transcript_source="captions",
            all_frames=[
                {"index": 0, "timestamp_seconds": 0.0, "path": "/tmp/f1.jpg"},
                {"index": 1, "timestamp_seconds": 5.0, "path": "/tmp/f2.jpg"},
                {"index": 2, "timestamp_seconds": 120.0, "path": "/tmp/f3.jpg"},
            ],
            hero_frames=[
                {"index": 0, "timestamp_seconds": 0.0, "path": "/tmp/f1.jpg"},
                {"index": 1, "timestamp_seconds": 5.0, "path": "/tmp/f2.jpg"},
            ],
            pacing=PACING,
            hook={"frames": [], "words": [], "ran": False, "skipped_reason": "video <30s"},
        )
        kwargs.update(overrides)
        return write_report(**kwargs).read_text(encoding="utf-8")

    def test_writes_all_required_sections(self):
        text = self._write()
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("source: https://youtu.be/test", text)
        self.assertIn("intent: summarise the test results", text)
        self.assertIn("hero_frames:", text)
        for header in ("# Test Video",) + CONTENT_SECTIONS:
            self.assertIn(header, text, f"missing: {header}")
        self.assertIn("<!-- pending Claude fill", text)
        self.assertIn("Hello world.", text)

    def test_content_intent_demotes_craft_to_an_appendix(self):
        text = self._write()
        self.assertIn("form_analysis: off", text)
        self.assertIn("## Production notes", text)
        self.assertIn("Cuts/min: 2.88", text)
        self.assertIn("Mean shot length: 20.83", text)
        for header in FORM_SECTIONS:
            self.assertNotIn(header, text, f"craft section leaked: {header}")

    def test_findings_is_the_load_bearing_section(self):
        text = self._write()
        findings = text.split("## Findings", 1)[1].split("\n##", 1)[0]
        self.assertIn("MARKDOWN", findings)
        self.assertIn("TABLES", findings)
        # Ordered so Findings lands before the conclusions that lean on it.
        self.assertLess(text.index("## Setup & premise"), text.index("## How it unfolds"))
        self.assertLess(text.index("## How it unfolds"), text.index("## Findings"))
        self.assertLess(text.index("## Findings"), text.index("## Conclusions & caveats"))

    def test_form_intent_restores_craft_sections(self):
        text = self._write(name="form.md", intent="what's the hook pattern?")
        self.assertIn("form_analysis: on", text)
        self.assertNotIn("## Production notes", text)
        for header in FORM_SECTIONS + CONTENT_SECTIONS:
            self.assertIn(header, text, f"missing: {header}")

    def test_explicit_flag_overrides_intent_inference(self):
        forced_on = self._write(name="on.md", intent="summarise results", form_analysis=True)
        self.assertIn("form_analysis: on", forced_on)
        self.assertIn("## Editorial profile", forced_on)

        forced_off = self._write(name="off.md", intent="hook breakdown", form_analysis=False)
        self.assertIn("form_analysis: off", forced_off)
        self.assertNotIn("## Editorial profile", forced_off)

    def test_coverage_gap_warns_when_frames_stop_early(self):
        short = [{"index": 0, "timestamp_seconds": 10.0, "path": "/tmp/f1.jpg"}]
        text = self._write(name="gap.md", all_frames=short, hero_frames=short)
        self.assertIn("Coverage gap", text)
        self.assertIn("--start 00:10", text)
        # Frames reaching the end of the video must not warn.
        self.assertNotIn("Coverage gap", self._write(name="ok.md"))

    def test_is_form_intent_matches_across_languages(self):
        for intent in ("what's the hook?", "analyse the editing", "oceń montaż",
                       "jakie tempo cięć", "thumbnail strategy"):
            self.assertTrue(is_form_intent(intent), intent)
        for intent in ("", None, "podsumuj wyniki testów", "summarise the findings",
                       "what did they measure?", "general summary"):
            self.assertFalse(is_form_intent(intent), intent)


if __name__ == "__main__":
    unittest.main()
