#!/usr/bin/env python3
"""Hook microscope: dense frames + word-level transcript over [0, 10s].

The first 10 seconds is where every retention curve gets decided. Treating
them like any other 10 seconds wastes the highest-leverage analysis budget.
This module re-runs frame extraction at 2 fps over the hook range and asks
local whisper.cpp for word-level timestamps so the reporter can align each
frame to the exact word being spoken.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from frames import extract  # noqa: E402
from whisper_local import (  # noqa: E402
    DEFAULT_LANG,
    WhisperLocalError,
    extract_audio_wav,
    resolve_model,
    transcribe_audio_local,
)


HOOK_DURATION_SECONDS = 10.0
HOOK_FPS = 2.0


def analyse_hook(
    video_path: str,
    out_dir: Path,
    model_path: str | None = None,
    full_video_duration: float = 0.0,
    lang: str = DEFAULT_LANG,
    transcribe_words: bool = True,
) -> dict:
    """Run hook microscope. Returns {frames, words, segments, ran}."""
    if full_video_duration > 0 and full_video_duration < 30.0:
        return {"frames": [], "words": [], "segments": [], "ran": False,
                "skipped_reason": "video <30s"}

    out_dir.mkdir(parents=True, exist_ok=True)
    hook_frames_dir = out_dir / "hook_frames"
    hook_frames = extract(
        video_path, hook_frames_dir,
        fps=HOOK_FPS, resolution=512, max_frames=25,
        start_seconds=0.0, end_seconds=HOOK_DURATION_SECONDS,
    )

    words: list[dict] = []
    segments: list[dict] = []
    if transcribe_words:
        try:
            model = resolve_model(model_path)
            hook_audio = extract_audio_wav(
                video_path, out_dir / "hook_audio.wav",
                duration=HOOK_DURATION_SECONDS,
            )
            segments, words = transcribe_audio_local(
                hook_audio, model, word_timestamps=True, lang=lang,
            )
        except WhisperLocalError as exc:
            print(f"[hook] local whisper unavailable — no word timings: {exc}",
                  file=sys.stderr)

    return {
        "frames": hook_frames,
        "words": words,
        "segments": segments,
        "ran": True,
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: hook.py <video-path> <out-dir>", file=sys.stderr)
        raise SystemExit(2)
    result = analyse_hook(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps(result, indent=2, default=str))
