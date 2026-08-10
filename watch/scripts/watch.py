#!/usr/bin/env python3
"""/watch entry point: download video, extract frames, parse transcript.

Prints a markdown report to stdout listing frame paths + transcript. Claude
then Reads each frame path to see the video.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from download import download, is_url  # noqa: E402
from frames import (  # noqa: E402
    MAX_FPS, auto_fps, auto_fps_focus, extract, extract_scene_change,
    format_time, get_metadata, parse_time, select_hero_frames,
)
from hook import analyse_hook  # noqa: E402
from languages import describe, name_for, normalize, same_language  # noqa: E402
from pacing import compute_pacing  # noqa: E402
from report import is_form_intent, write_report  # noqa: E402
from transcribe import filter_range, format_transcript, parse_vtt  # noqa: E402
from whisper_local import (  # noqa: E402
    DEFAULT_LANG, WhisperLocalError, resolve_model, transcribe_video_local,
)


def resolve_report_language(
    override: str | None,
    whisper_lang: str | None,
    metadata_lang: str | None,
    caption_lang: str | None,
    hook_lang: str | None,
    requested_lang: str | None,
) -> tuple[str | None, str | None]:
    """Decide what language the report gets written in, and say who decided.

    Most-trusted first: an explicit override, then whisper listening to the
    whole audio track, then the uploader's own metadata, then the caption track
    that shipped, then whisper on the 10s hook (short clips misdetect on music
    or silence), then a language the caller pinned via --lang.
    """
    for value, source in (
        (override, "--report-lang"),
        (whisper_lang, "whisper (full audio)"),
        (metadata_lang, "source metadata"),
        (caption_lang, "caption track"),
        (hook_lang, "whisper (hook, 10s)"),
        (requested_lang, "--lang"),
    ):
        code = normalize(value)
        if code:
            return code, source
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="watch",
        description="Download a video, extract auto-scaled frames, and surface the transcript.",
    )
    ap.add_argument("source", help="Video URL or local file path")
    ap.add_argument("--max-frames", type=int, default=80, help="Cap on frame count (default 80, hard max 100)")
    ap.add_argument("--resolution", type=int, default=512, help="Frame width in pixels (default 512)")
    ap.add_argument("--fps", type=float, default=None, help="Override auto-fps")
    ap.add_argument("--start", type=str, default=None, help="Range start (SS, MM:SS, or HH:MM:SS)")
    ap.add_argument("--end", type=str, default=None, help="Range end (SS, MM:SS, or HH:MM:SS)")
    ap.add_argument("--out-dir", type=str, default=None, help="Working directory (default: tmp)")
    ap.add_argument(
        "--no-whisper",
        action="store_true",
        help="Disable local Whisper. Report frames-only if no captions, and skip hook word timings.",
    )
    ap.add_argument(
        "--whisper-model",
        type=str,
        default=None,
        help="Path to a ggml whisper.cpp model. Default: large-v3-q5_0 "
             "(via $WATCH_WHISPER_MODEL or ~/code/whisper-transcribe/).",
    )
    ap.add_argument(
        "--lang",
        type=str,
        default=DEFAULT_LANG,
        help="Spoken language for whisper.cpp ('auto' to detect; default from $WATCH_WHISPER_LANG or 'auto').",
    )
    ap.add_argument(
        "--intent",
        type=str,
        default="",
        help="Why the user wants to watch this video. Aims the report's TL;DR and "
             "Conclusions, and decides whether the craft sections appear "
             "(see --form-analysis).",
    )
    ap.add_argument(
        "--report-lang",
        type=str,
        default="auto",
        help="Language the report should be written in. Default 'auto' = the language "
             "the video is spoken in (detected). Pass a code (e.g. 'en', 'pl') to override.",
    )
    ap.add_argument(
        "--no-probe",
        action="store_true",
        help="Skip the yt-dlp metadata probe that detects the source language "
             "(captions then fall back to English).",
    )
    ap.add_argument(
        "--no-scene-change",
        action="store_true",
        help="Force uniform frame sampling (skip scene-change detection).",
    )
    ap.add_argument(
        "--no-hook-microscope",
        action="store_true",
        help="Skip the dense 0-10s hook re-pass.",
    )
    form = ap.add_mutually_exclusive_group()
    form.add_argument(
        "--form-analysis",
        dest="form_analysis",
        action="store_true",
        default=None,
        help="Promote the hook breakdown and editorial profile to full report "
             "sections. Default: inferred from --intent (on only when the user "
             "asked about craft — hook, editing, pacing, montaż, tempo...).",
    )
    form.add_argument(
        "--no-form-analysis",
        dest="form_analysis",
        action="store_false",
        help="Force craft metrics down to a raw-numbers appendix even when the "
             "intent mentions form.",
    )
    args = ap.parse_args()

    max_frames = min(args.max_frames, 100)

    if args.out_dir:
        work = Path(args.out_dir).expanduser().resolve()
    else:
        work = Path(tempfile.mkdtemp(prefix="watch-"))
    work.mkdir(parents=True, exist_ok=True)
    print(f"[watch] working dir: {work}", file=sys.stderr)

    print(
        "[watch] downloading via yt-dlp…" if is_url(args.source) else "[watch] using local file…",
        file=sys.stderr,
    )
    dl = download(args.source, work / "download", probe=not args.no_probe)
    video_path = dl["video_path"]

    meta = get_metadata(video_path)
    full_duration = meta["duration_seconds"]

    start_sec = parse_time(args.start)
    end_sec = parse_time(args.end)

    if start_sec is not None and start_sec < 0:
        raise SystemExit("--start must be non-negative")
    if end_sec is not None and start_sec is not None and end_sec <= start_sec:
        raise SystemExit("--end must be greater than --start")
    if full_duration > 0 and start_sec is not None and start_sec >= full_duration:
        raise SystemExit(f"--start {start_sec:.1f}s is past end of video ({full_duration:.1f}s)")

    effective_start = start_sec if start_sec is not None else 0.0
    effective_end = end_sec if end_sec is not None else full_duration
    effective_duration = max(0.0, effective_end - effective_start)
    focused = start_sec is not None or end_sec is not None

    if focused:
        fps, target = auto_fps_focus(effective_duration, max_frames=max_frames)
    else:
        fps, target = auto_fps(effective_duration, max_frames=max_frames)
    if args.fps is not None:
        fps = min(args.fps, MAX_FPS)
        target = max(1, int(round(fps * effective_duration)))

    scope = (
        f"{format_time(effective_start)}-{format_time(effective_end)} ({effective_duration:.1f}s)"
        if focused else f"full {effective_duration:.1f}s"
    )
    print(f"[watch] extracting ~{target} frames at {fps:.3f} fps over {scope}…", file=sys.stderr)

    use_scene = (not args.no_scene_change) and not focused and args.fps is None
    if use_scene:
        print("[watch] extracting scene-change frames (one per shot)…", file=sys.stderr)
        frames = extract_scene_change(
            video_path,
            work / "frames",
            scene_threshold=0.3,
            resolution=args.resolution,
            max_frames=max_frames,
            uniform_fallback_min=10,
            start_seconds=start_sec,
            end_seconds=end_sec,
        )
        sampling_mode = (
            "scene-change" if frames and frames[0].get("source") == "scene-change"
            else "uniform-fallback"
        )
    else:
        frames = extract(
            video_path,
            work / "frames",
            fps=fps,
            resolution=args.resolution,
            max_frames=max_frames,
            start_seconds=start_sec,
            end_seconds=end_sec,
        )
        sampling_mode = "uniform"

    # Pacing: derive scene-change timestamps from frame metadata.
    if sampling_mode == "scene-change":
        scene_times = [f["timestamp_seconds"] for f in frames]
    else:
        scene_times = []
    pacing = compute_pacing(
        scene_times=scene_times,
        video_duration=effective_duration,
        motion_scores=None,
    )

    # Hook microscope: dense pass over [0, 10s] when not in focused mode.
    if (not args.no_hook_microscope) and (not focused) and full_duration >= 30.0:
        print("[watch] running hook microscope on first 10s…", file=sys.stderr)
        hook_result = analyse_hook(
            video_path, work,
            model_path=args.whisper_model,
            full_video_duration=full_duration,
            lang=args.lang,
            transcribe_words=not args.no_whisper,
        )
    else:
        hook_result = {"frames": [], "words": [], "segments": [], "ran": False,
                       "skipped_reason": "focused mode or short video or --no-hook-microscope"}

    transcript_segments: list[dict] = []
    transcript_text: str | None = None
    transcript_source: str | None = None
    whisper_lang: str | None = None
    if dl.get("subtitle_path"):
        try:
            all_segments = parse_vtt(dl["subtitle_path"])
            transcript_segments = filter_range(all_segments, start_sec, end_sec) if focused else all_segments
            transcript_text = format_transcript(transcript_segments)
            transcript_source = "captions"
        except Exception as exc:
            print(f"[watch] subtitle parse failed: {exc}", file=sys.stderr)

    if not transcript_segments and not args.no_whisper:
        try:
            model = resolve_model(args.whisper_model)
            all_segments, whisper_lang = transcribe_video_local(
                video_path, work / "audio.wav", model, lang=args.lang,
            )
            transcript_segments = filter_range(all_segments, start_sec, end_sec) if focused else all_segments
            transcript_text = format_transcript(transcript_segments)
            transcript_source = "whisper (local large-v3-q5_0)"
        except WhisperLocalError as exc:
            setup_py = SCRIPT_DIR / "setup.py"
            print(
                f"[watch] no captions and local Whisper unavailable: {exc}\n"
                f"[watch] run `python3 {setup_py}` to set up whisper.cpp + the model",
                file=sys.stderr,
            )

    info = dl.get("info") or {}

    report_lang, lang_source = resolve_report_language(
        override=args.report_lang,
        whisper_lang=whisper_lang,
        metadata_lang=dl.get("source_language"),
        caption_lang=dl.get("subtitle_lang") if transcript_source == "captions" else None,
        hook_lang=hook_result.get("language"),
        requested_lang=args.lang,
    )

    # Build report.md (the structured artifact).
    hero_frames = select_hero_frames(frames, pacing=pacing)
    report_path = write_report(
        out_path=work / "report.md",
        source=args.source,
        title=info.get("title") or Path(args.source).stem,
        duration_seconds=full_duration,
        intent=args.intent,
        transcript_segments=transcript_segments,
        transcript_source=transcript_source,
        all_frames=frames,
        hero_frames=hero_frames,
        pacing=pacing,
        hook=hook_result,
        language=report_lang,
        language_source=lang_source,
        form_analysis=args.form_analysis,
    )

    print()
    print("# watch: video report")
    print()
    print(f"- **Source:** {args.source}")
    if info.get("title"):
        print(f"- **Title:** {info['title']}")
    if info.get("uploader"):
        print(f"- **Uploader:** {info['uploader']}")
    print(f"- **Duration:** {format_time(full_duration)} ({full_duration:.1f}s)")
    if focused:
        print(
            f"- **Focus range:** {format_time(effective_start)} → {format_time(effective_end)} "
            f"({effective_duration:.1f}s)"
        )
    if meta.get("width") and meta.get("height"):
        print(f"- **Resolution:** {meta['width']}x{meta['height']} ({meta.get('codec') or 'unknown codec'})")
    mode = "focused" if focused else "full"
    print(f"- **Frames:** {len(frames)} @ {fps:.3f} fps, {mode} mode (budget {target}, max {max_frames})")
    print(f"- **Frame size:** {args.resolution}px wide")
    if transcript_segments:
        in_range = " in range" if focused else ""
        print(
            f"- **Transcript:** {len(transcript_segments)} segments{in_range} "
            f"(via {transcript_source or 'captions'})"
        )
    else:
        print("- **Transcript:** none available")
    lang_note = f" — via {lang_source}" if lang_source else ""
    print(f"- **Spoken language:** {describe(report_lang)}{lang_note}")
    form_on = args.form_analysis if args.form_analysis is not None else is_form_intent(args.intent)
    how = "explicit flag" if args.form_analysis is not None else "inferred from --intent"
    print(
        f"- **Report focus:** {'content + form' if form_on else 'content'} "
        f"({how}) — {'hook + editorial sections included' if form_on else 'craft metrics are a raw appendix, write no commentary on them'}"
    )

    print()
    write_in = name_for(report_lang) or "the language spoken in the video"
    not_english = "" if same_language(report_lang, "en") else ", not English"
    print(
        f"> **Write the report in {write_in}.** Every narrative section of "
        f"`report.md` — and its headings — goes in {write_in}{not_english}. "
        "Quotes stay verbatim. Answer the user in chat in whatever language "
        "*they* wrote to you in."
    )

    if not focused and full_duration > 600:
        mins = int(full_duration // 60)
        print()
        print(
            f"> **Warning:** This is a {mins}-minute video. Frame coverage is sparse at this length — "
            "accuracy degrades noticeably on anything over 10 minutes. For better results, "
            "re-run with `--start HH:MM:SS --end HH:MM:SS` to zoom into a specific section."
        )

    print()
    print("## Frames")
    print()
    print(f"Frames live at: `{work / 'frames'}`")
    print()
    print(
        "**Read each frame path below with the Read tool to view the image.** "
        "Frames are in chronological order; `t=MM:SS` is the absolute timestamp in the source video."
    )
    print()
    for frame in frames:
        print(f"- `{frame['path']}` (t={format_time(frame['timestamp_seconds'])})")

    print()
    print("## Transcript")
    print()
    if transcript_text:
        label = transcript_source or "captions"
        if focused:
            print(f"_Source: {label}. Filtered to {format_time(effective_start)} → {format_time(effective_end)}:_")
        else:
            print(f"_Source: {label}._")
        print()
        print("```")
        print(transcript_text)
        print("```")
    elif focused and dl.get("subtitle_path"):
        print(f"_No transcript lines fell inside {format_time(effective_start)} → {format_time(effective_end)}._")
    else:
        setup_py = SCRIPT_DIR / "setup.py"
        print(
            "_No transcript available — proceed with frames only. "
            "Captions were missing and the Whisper fallback was unavailable "
            "(no API key set, or `--no-whisper` was used). "
            f"Run `python3 {setup_py}` to enable Whisper, then re-run._"
        )

    print()
    print("---")
    print(f"_Report: `{report_path}`_")
    print(f"_Work dir: `{work}` — delete when done._")
    print(
        "_Next: fill every `<!-- pending Claude fill … -->` marker in the report "
        f"(in {write_in}), then **print the finished report in chat** — the user "
        "reads it there, not by opening the file._"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
