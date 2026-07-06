#!/usr/bin/env python3
"""Local Whisper transcription via whisper.cpp (large-v3-q5_0).

Replaces the cloud Groq/OpenAI backend. Everything runs offline: no API key,
nothing leaves the machine. Emits the same `{start, end, text}` segment shape
the rest of the pipeline expects, and — for the hook microscope — word-level
`{word, start, end}` timings via whisper.cpp's `--max-len 1 --split-on-word`
mode (the granular 0-10s timing the reporter aligns frames to).

Model resolution order (first existing wins):
  1. explicit path passed by the caller (`--whisper-model`)
  2. $WATCH_WHISPER_MODEL
  3. ~/code/whisper-transcribe/ggml-large-v3-q5_0.bin
  4. ~/.config/watch/models/ggml-large-v3-q5_0.bin
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_FILENAME = "ggml-large-v3-q5_0.bin"
MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-q5_0.bin"
)

# First existing path wins. $WATCH_WHISPER_MODEL overrides these.
_MODEL_CANDIDATES = [
    Path.home() / "code" / "whisper-transcribe" / MODEL_FILENAME,
    Path.home() / ".config" / "watch" / "models" / MODEL_FILENAME,
]

_BINARY_CANDIDATES = ("whisper-cli", "whisper-cpp", "main")

DEFAULT_LANG = os.environ.get("WATCH_WHISPER_LANG", "auto")


class WhisperLocalError(RuntimeError):
    """whisper.cpp binary or model is missing, or a run failed."""


def find_binary() -> str:
    for name in _BINARY_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    raise WhisperLocalError(
        "whisper.cpp not found (looked for whisper-cli / whisper-cpp / main). "
        "Install it with: brew install whisper-cpp"
    )


def model_candidates() -> list[Path]:
    """Ordered list of where the model is looked for (for setup/preflight)."""
    env = os.environ.get("WATCH_WHISPER_MODEL")
    cands = [Path(env).expanduser()] if env else []
    return cands + list(_MODEL_CANDIDATES)


def resolve_model(explicit: str | None = None) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise WhisperLocalError(f"whisper model not found at {p}")
        return p
    for cand in model_candidates():
        if cand.exists():
            return cand
    raise WhisperLocalError(
        f"whisper model '{MODEL_FILENAME}' not found. Download it (~1.1 GB):\n"
        f"  curl -L -C - --retry 15 -o ~/code/whisper-transcribe/{MODEL_FILENAME} \\\n"
        f"    {MODEL_URL}\n"
        "or set $WATCH_WHISPER_MODEL to an existing ggml model file."
    )


def extract_audio_wav(
    video_path: str, out_path: Path, duration: float | None = None
) -> Path:
    """Extract 16 kHz mono PCM WAV — the format whisper.cpp expects."""
    if shutil.which("ffmpeg") is None:
        raise WhisperLocalError("ffmpeg is not installed. Install with: brew install ffmpeg")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(Path(video_path).resolve()),
    ]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out_path.resolve())]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise WhisperLocalError(f"ffmpeg audio extraction failed: {result.stderr.strip()}")
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise WhisperLocalError("ffmpeg produced no audio — video may have no audio track")
    return out_path


def _run_whisper(
    model: Path, audio_wav: Path, out_base: Path,
    lang: str, word_level: bool,
) -> dict:
    """Run whisper.cpp, return the parsed JSON. `out_base` has no extension."""
    binary = find_binary()
    cmd = [
        binary,
        "-m", str(model),
        "-f", str(audio_wav),
        "-l", lang,
        "-oj",                       # write <out_base>.json
        "-of", str(out_base),
    ]
    if word_level:
        # One word per JSON entry → word-level offsets for the hook microscope.
        cmd += ["-ml", "1", "-sow"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    json_path = Path(str(out_base) + ".json")
    if result.returncode != 0 or not json_path.exists():
        tail = (result.stderr or result.stdout or "").strip()[-400:]
        raise WhisperLocalError(
            f"whisper.cpp failed (exit {result.returncode}): {tail}"
        )
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WhisperLocalError(f"could not parse whisper.cpp JSON at {json_path}: {exc}")


def _rows(data: dict) -> list[tuple[str, float, float]]:
    """Yield (text, start_s, end_s) from whisper.cpp JSON transcription entries."""
    out: list[tuple[str, float, float]] = []
    for entry in data.get("transcription") or []:
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        off = entry.get("offsets") or {}
        start = float(off.get("from") or 0) / 1000.0
        end = float(off.get("to") or 0) / 1000.0
        out.append((text, start, end))
    return out


def transcribe_audio_local(
    audio_wav: Path, model: Path,
    word_timestamps: bool = False, lang: str = DEFAULT_LANG,
) -> tuple[list[dict], list[dict]]:
    """Return (segments, words). `words` is empty unless word_timestamps=True.

    Runs whisper.cpp once for clean segments; when words are requested, a second
    pass in --max-len 1 --split-on-word mode yields word-level timings.
    """
    seg_data = _run_whisper(
        model, audio_wav, audio_wav.with_name(audio_wav.stem + "_seg"),
        lang=lang, word_level=False,
    )
    segments = [
        {"start": round(s, 2), "end": round(e, 2), "text": t}
        for t, s, e in _rows(seg_data)
    ]

    words: list[dict] = []
    if word_timestamps:
        word_data = _run_whisper(
            model, audio_wav, audio_wav.with_name(audio_wav.stem + "_words"),
            lang=lang, word_level=True,
        )
        words = [
            {"word": t, "start": round(s, 3), "end": round(e, 3)}
            for t, s, e in _rows(word_data)
        ]
    return segments, words


def transcribe_video_local(
    video_path: str, audio_out: Path, model: Path, lang: str = DEFAULT_LANG,
) -> list[dict]:
    """Extract audio → transcribe → return segments."""
    wav = audio_out if audio_out.suffix == ".wav" else audio_out.with_suffix(".wav")
    extract_audio_wav(video_path, wav)
    segments, _ = transcribe_audio_local(wav, model, word_timestamps=False, lang=lang)
    return segments


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: whisper_local.py <video-or-wav> [--words] [--model PATH]", file=sys.stderr)
        raise SystemExit(2)
    src = sys.argv[1]
    want_words = "--words" in sys.argv
    model_override = None
    if "--model" in sys.argv:
        model_override = sys.argv[sys.argv.index("--model") + 1]
    mdl = resolve_model(model_override)
    src_path = Path(src)
    if src_path.suffix.lower() == ".wav":
        segs, words = transcribe_audio_local(src_path, mdl, word_timestamps=want_words)
    else:
        segs = transcribe_video_local(src, Path("audio.wav"), mdl)
        words = []
    print(json.dumps({"model": str(mdl), "segments": segs, "words": words}, indent=2))
