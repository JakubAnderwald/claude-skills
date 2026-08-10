#!/usr/bin/env python3
"""Write a structured report.md to the working directory.

Deterministic sections (frontmatter, pacing numbers, transcript) are filled
by this script. Narrative sections are emitted as
`<!-- pending Claude fill: <hint> -->` markers so Claude (the orchestrator)
knows exactly what to write after answering the user.

**The report is about what the video says, not how it was cut.** The default
spine is content-first:

    TL;DR → Setup & premise → How it unfolds → Findings (tables) →
    Conclusions & caveats → Notable quotes → Entities → Concepts

`Findings` is the load-bearing section: every concrete number, price, name,
measurement or result the video puts on screen or says out loud, tabulated.

Production craft (hook breakdown, cuts/min, shot length) is an appendix of raw
numbers with **no narrative fill** — unless the user actually asked about form,
in which case `form_analysis` promotes it back to full sections with their own
pending markers. Pass `form_analysis=None` to infer it from the intent string.

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

# Substrings that mean "the user is asking about the craft, not the content".
# Matched case-folded against the intent string, so stems are deliberate
# ("edit" catches editing/editorial, "montaż" catches montażu).
FORM_INTENT_KEYWORDS = (
    # English
    "hook", "edit", "pacing", "cut", "montage", "shot length", "b-roll",
    "broll", "thumbnail", "retention", "style", "cinematograph", "framing",
    "transition", "color grade", "grading", "lighting", "sound design",
    "camera work", "storytell", "structure of the video", "how it's made",
    "how it is made", "production value",
    # Polish
    "montaż", "montazu", "tempo", "cięci", "cieci", "ujęci", "ujeci",
    "forma", "formy", "formę", "kadr", "chwyt", "styl", "narracj",
    "miniatur", "realizacj",
)


def is_form_intent(intent: str | None) -> bool:
    """True when the user's stated reason for watching is about craft/form."""
    if not intent:
        return False
    haystack = intent.casefold()
    return any(kw in haystack for kw in FORM_INTENT_KEYWORDS)


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


def _pacing_lines(pacing: dict) -> list[str]:
    """Raw editorial metrics as bullets — no interpretation."""
    if pacing.get("shot_count", 0) <= 0:
        return ["_No scene-change data — likely a static/screen-recorded source._"]
    return [
        f"- Shots: {pacing['shot_count']}",
        f"- Cuts/min: {pacing['cuts_per_minute']}",
        f"- Mean shot length: {pacing['mean_shot_length']}s",
        f"- Median shot length: {pacing['median_shot_length']}s",
        "- Talking-head ratio: n/a (opencv not installed)",
    ]


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
    form_analysis: bool | None = None,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    watched_at = watched_at or _dt.datetime.now().astimezone()
    if form_analysis is None:
        form_analysis = is_form_intent(intent)

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
    lines.append(f"form_analysis: {'on' if form_analysis else 'off'}")
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
        "3-5 bullets that ANSWER this, not describe the video: "
        f"'{intent or 'general summary'}'. Lead with the single most concrete "
        "finding, numbers included. No sentence may be true of a video the "
        "viewer has not watched ('the host explains several devices' is filler; "
        "'the 300 zl unit matched the 5000 zl one to 0.01' is the answer).",
        in_lang,
    ))
    lines.append("")

    lines.append("## Setup & premise")
    lines.append("")
    lines.append(_pending(
        "What the video sets out to establish, and the concrete parameters it "
        "runs under — stated as facts, not narration. Whatever applies: the "
        "question being answered, who/what takes part (with the numbers that "
        "characterise them), equipment or products with prices and specs, the "
        "dose/sample/dataset, definitions and thresholds used as pass-fail "
        "criteria, sponsors or sourcing. Use small tables wherever there are "
        "3+ comparable items. Timestamp each claim [MM:SS]. Mark any figure you "
        "derived yourself rather than took from the video.",
        in_lang,
    ))
    lines.append("")

    lines.append("## How it unfolds")
    lines.append("")
    lines.append(_pending(
        "The process or argument in order, as a numbered list — the steps of a "
        "test, the stages of a build, the beats of an argument. Each item: what "
        "happened and why it matters to the result, with [MM:SS]. Include "
        "control steps, validation checks and anything the video does to make "
        "its result trustworthy. Close with a short paragraph on what the "
        "method does NOT control for (sample size, missing repeats, "
        "uncontrolled variables) — flag it even when the video does not.",
        in_lang,
    ))
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    lines.append(_pending(
        "THE LOAD-BEARING SECTION — write it before the others and give it the "
        "most room. Every concrete result the video produces, in MARKDOWN "
        "TABLES. Group by the unit the video itself groups by (per person, per "
        "product, per run, per version) and give each group its own table plus "
        "one or two lines of what that group's numbers show. Rows = the varying "
        "dimension (time, trial, model); columns = what was measured. Bold the "
        "decisive cell in each table. Add a final cross-cutting table comparing "
        "the groups on the one metric that matters most. Read the numbers off "
        "the FRAMES, not off the captions — auto-captions mangle decimals. If a "
        "figure only ever appears in narration, mark it as such. Skip the "
        "section entirely only if the video produces no measurable output at "
        "all, and say so in one line.",
        in_lang,
    ))
    lines.append("")

    lines.append("## Conclusions & caveats")
    lines.append("")
    lines.append(_pending(
        f"What the findings mean for: '{intent or 'general summary'}'. Answer "
        "the question in the user's terms, in bold, in the first sentence — "
        "give the number or the verdict, not a hedge. Then: what generalises "
        "and what does not; where the video's own conclusion overreaches its "
        "data; the practical takeaway a viewer would act on. End with a short "
        "numbered list of caveats — conditions that would change the result, "
        "measurement error, sample limits — including ones the video never "
        "raises. Keep the video's own closing verdict, attributed, with [MM:SS].",
        in_lang,
    ))
    lines.append("")

    lines.append("## Notable quotes")
    lines.append("")
    lines.append(_pending(
        "Top 3-5 lines from the transcript, each with [MM:SS]. Prefer lines "
        "that carry a claim, a number or a verdict over lines that are merely "
        "punchy. Quote them verbatim in the spoken language — never translate "
        "a quote, and never clean up the transcript's wording.",
        "",
    ))
    lines.append("")

    if form_analysis:
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
                "Frame-by-frame interpretation: what visual change happens at "
                "each 0.5s tick, aligned to what's being said. Identify the "
                "hook pattern (question, contrarian claim, in-medias-res, "
                "demo-first, etc.).",
                in_lang,
            ))
        lines.append("")

        lines.append("## Editorial profile")
        lines.append("")
        lines.extend(_pacing_lines(pacing))
        lines.append("")
        lines.append(_pending(
            "One-line style fingerprint: e.g. 'Tight Fireship-style cuts, "
            "B-roll-heavy, no on-screen text.' Inferred from pacing numbers "
            "+ hero frames.",
            in_lang,
        ))
        lines.append("")

    lines.append("## Entities mentioned")
    lines.append("")
    lines.append("- People: " + _pending("comma-separated; keep names as spoken"))
    lines.append("- Companies: " + _pending("comma-separated; keep names as spoken"))
    lines.append("- Tools / products: " + _pending(
        "comma-separated; keep names as spoken. Attach the model number, "
        "version or price when the video gives one"))
    lines.append("- Places: " + _pending("comma-separated, or omit if none", in_lang))
    lines.append("")

    lines.append("## Concepts surfaced")
    lines.append("")
    lines.append(_pending(
        "`**Term** — one-line gist` per bullet. Frameworks, mental models, "
        "named patterns, domain mechanisms and any jargon the video defines or "
        "leans on. Explain the mechanism, not the vibe: a reader who skipped "
        "the video should be able to use the term correctly afterwards.",
        in_lang,
    ))
    lines.append("")

    if not form_analysis:
        # Craft data stays available as raw numbers, but nothing here asks for
        # narrative — the report is about the content unless the user asked
        # about the form (`--form-analysis`, or a form-shaped --intent).
        lines.append("## Production notes")
        lines.append("")
        lines.append(
            "_Raw craft metrics, kept for reference. Do not write commentary "
            "on them — re-run with `--form-analysis` if the user wants the "
            "hook breakdown and editorial read._"
        )
        lines.append("")
        lines.extend(_pacing_lines(pacing))
        if hook.get("ran"):
            n_words = len(hook.get("words", []))
            plural = "" if n_words == 1 else "s"
            lines.append(
                f"- Hook microscope: {len(hook.get('frames', []))} frames at "
                f"2 fps, {n_words} word-level timing{plural} "
                "(see `hook_audio_words.json`)"
            )
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
    last_t = max((f["timestamp_seconds"] for f in all_frames), default=0.0)
    if all_frames and duration_seconds > 0 and last_t < 0.85 * duration_seconds:
        lines.append("")
        lines.append(
            f"> **Coverage gap:** the frame budget ran out at "
            f"{_fmt_time(last_t)} of {_fmt_time(duration_seconds)} — everything "
            f"after that point is unseen. Re-run with "
            f"`--start {_fmt_time(last_t)}` before writing Findings."
        )
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
