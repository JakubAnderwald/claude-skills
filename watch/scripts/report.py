#!/usr/bin/env python3
"""Write a structured report.md to the working directory.

Deterministic sections (frontmatter, pacing numbers, transcript) are filled
by this script. Narrative sections (TL;DR, entities, concepts, etc.) are
emitted as `<!-- pending Claude fill: <hint> -->` markers so Claude (the
orchestrator) knows exactly what to write after answering the user.

The report captures, per watch:
  - Entities (people, companies, tools mentioned)
  - Concepts (frameworks, mental models, named patterns)
  - A TL;DR + key moments + hook breakdown, all timestamped

The report is written in **the language the video is spoken in**, not English:
the detected language goes in the frontmatter and every pending marker carries
it, so Claude writes each section in that language.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from languages import describe, name_for, normalize, same_language  # noqa: E402


def _pending(hint: str, in_lang: str = "") -> str:
    return f"<!-- pending Claude fill{in_lang}: {hint} -->"


def _fmt_time(seconds: float) -> str:
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _yaml_list(items: list[str]) -> str:
    if not items:
        return "[]"
    return "[" + ", ".join(items) + "]"


def write_report(
    out_path: Path,
    source: str,
    title: str,
    duration_seconds: float,
    intent: str,
    transcript_segments: list[dict],
    transcript_source: str | None,
    all_frames: list[dict],
    hero_frames: list[dict],
    pacing: dict,
    hook: dict,
    watched_at: _dt.datetime | None = None,
    language: str | None = None,
    language_source: str | None = None,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    watched_at = watched_at or _dt.datetime.now().astimezone()

    lang_code = normalize(language)
    lang_name = name_for(lang_code)
    # Every pending marker repeats the target language — a marker read in
    # isolation still says what language to answer in.
    in_lang = f" (in {lang_name})" if lang_name else " (in the video's spoken language)"
    write_in = lang_name or "the language spoken in the video"

    hero_names = [Path(f["path"]).name for f in hero_frames]
    lines: list[str] = []

    lines.append("---")
    lines.append(f"source: {source}")
    lines.append(f"title: {title}")
    lines.append(f"duration: {_fmt_time(duration_seconds)}")
    lines.append(f"watched_at: {watched_at.isoformat()}")
    lines.append(f"intent: {intent or '(none)'}")
    lines.append(f"language: {describe(lang_code)}")
    if language_source:
        lines.append(f"language_detected_by: {language_source}")
    lines.append(f"hero_frames: {_yaml_list(hero_names)}")
    lines.append(f"transcript_source: {transcript_source or 'none'}")
    lines.append("---")
    lines.append("")

    not_english = "" if same_language(lang_code, "en") else ", not in English"
    lines.append(
        f"<!-- REPORT LANGUAGE: {write_in}. Write every narrative section below "
        f"— and the section headings — in {write_in}{not_english}. Leave "
        "timestamps, metric numbers, frame paths and the transcript verbatim. "
        "Keep this comment; it is invisible when rendered, and do not echo it "
        "when printing the report in chat. -->"
    )
    lines.append("")

    lines.append(f"# {title}")
    lines.append("")

    lines.append("## TL;DR")
    lines.append("")
    lines.append(_pending(
        f"3-5 bullets through the lens of: '{intent or 'general summary'}'",
        in_lang,
    ))
    lines.append("")

    lines.append("## Key moments")
    lines.append("")
    lines.append(_pending(
        "5-10 bullets in `- **[MM:SS] <label>** — <description>` format. "
        "Cite hero_frames or other frames by filename when useful.",
        in_lang,
    ))
    lines.append("")

    lines.append("## Hook microscope (0-10s)")
    lines.append("")
    if not hook.get("ran"):
        reason = hook.get("skipped_reason", "n/a")
        lines.append(f"_Skipped: {reason}._")
    else:
        lines.append(f"- Frames: {len(hook.get('frames', []))} at 2 fps")
        words = hook.get("words", [])
        if words:
            lines.append(f"- Word-level transcript ({len(words)} words):")
            lines.append("")
            lines.append("```")
            for w in words:
                lines.append(f"  [{w['start']:6.2f}s] {w['word']}")
            lines.append("```")
        lines.append("")
        lines.append(_pending(
            "Frame-by-frame interpretation: what visual change happens at each "
            "0.5s tick, aligned to what's being said. Identify the hook pattern "
            "(question, contrarian claim, in-medias-res, demo-first, etc.).",
            in_lang,
        ))
    lines.append("")

    lines.append("## Editorial profile")
    lines.append("")
    if pacing.get("shot_count", 0) > 0:
        lines.append(f"- Shots: {pacing['shot_count']}")
        lines.append(f"- Cuts/min: {pacing['cuts_per_minute']}")
        lines.append(f"- Mean shot length: {pacing['mean_shot_length']}s")
        lines.append(f"- Median shot length: {pacing['median_shot_length']}s")
        lines.append("- Talking-head ratio: n/a (opencv not installed)")
    else:
        lines.append("_No scene-change data — likely a static/screen-recorded source._")
    lines.append("")
    lines.append(_pending(
        "One-line style fingerprint: e.g. 'Tight Fireship-style cuts, B-roll-heavy, "
        "no on-screen text.' Inferred from pacing numbers + hero frames.",
        in_lang,
    ))
    lines.append("")

    lines.append("## Quotable moments")
    lines.append("")
    lines.append(_pending(
        "Top 3-5 quotable lines pulled from the transcript, each with [MM:SS]. "
        "Prefer punchy, standalone-comprehensible lines. Quote them verbatim in "
        "the spoken language — never translate a quote.",
        "",
    ))
    lines.append("")

    lines.append("## Entities mentioned")
    lines.append("")
    lines.append("- People: " + _pending("comma-separated; keep names as spoken"))
    lines.append("- Companies: " + _pending("comma-separated; keep names as spoken"))
    lines.append("- Tools / products: " + _pending("comma-separated; keep names as spoken"))
    lines.append("- Places: " + _pending("comma-separated, or omit if none", in_lang))
    lines.append("")

    lines.append("## Concepts surfaced")
    lines.append("")
    lines.append(_pending(
        "List of concept: one-line gist. Frameworks, mental models, named patterns.",
        in_lang,
    ))
    lines.append("")

    lines.append("## Transcript")
    lines.append("")
    if transcript_segments:
        lines.append(
            f"_Source: {transcript_source or 'unknown'}. "
            f"Language: {describe(lang_code)}._"
        )
        lines.append("")
        lines.append("```")
        for seg in transcript_segments:
            t = _fmt_time(seg.get("start", 0))
            lines.append(f"[{t}] {seg.get('text', '').strip()}")
        lines.append("```")
    else:
        lines.append("_No transcript available._")
    lines.append("")

    lines.append("## All frames")
    lines.append("")
    lines.append(f"_Total: {len(all_frames)}. Hero frames flagged with star._")
    lines.append("")
    hero_paths = {f["path"] for f in hero_frames}
    for f in all_frames:
        marker = "* " if f["path"] in hero_paths else "  "
        lines.append(f"{marker}`{f['path']}` (t={_fmt_time(f['timestamp_seconds'])})")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: report.py <kwargs.json> [<out.md>]", file=sys.stderr)
        raise SystemExit(2)
    payload = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("report.md")
    write_report(out_path=out, **payload)
    print(str(out.resolve()))
