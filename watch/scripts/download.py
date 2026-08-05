#!/usr/bin/env python3
"""Download a video via yt-dlp, or resolve a local file path.

Also fetches subtitles (manual first, then auto-generated) in VTT format so
transcribe.py can parse them without needing Whisper.

Subtitles are pulled **in the video's original language**, not in English. A
metadata probe runs first to learn what that language is: YouTube exposes 100+
auto-*translated* caption tracks per video, so blindly asking for `en` hands
back an English translation of a Polish video — and the whole report then comes
out in the wrong language. When the probe can't tell, English stays the guess.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from languages import base_code, normalize  # noqa: E402


VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".wmv"}

# yt-dlp treats each --sub-langs entry as a regex. `.*-orig` matches whatever
# YouTube tags as the original-language auto-caption without us knowing the code.
ORIG_PATTERN = ".*-orig"


def is_url(source: str) -> bool:
    if source.startswith("-"):
        return False
    parsed = urlparse(source)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def resolve_local(path: str) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"File not found: {p}")
    if p.suffix.lower() not in VIDEO_EXTS:
        print(
            f"[watch] warning: {p.suffix} is not a known video extension, proceeding anyway",
            file=sys.stderr,
        )
    return {
        "video_path": str(p),
        "subtitle_path": None,
        "subtitle_lang": None,
        "source_language": None,
        "info": {"title": p.name, "url": str(p)},
        "downloaded": False,
    }


def probe_info(url: str) -> dict | None:
    """Metadata-only yt-dlp pass (no download) to learn the video's language."""
    cmd = ["yt-dlp", "-J", "--no-playlist", "--no-warnings", "--", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[watch] language probe failed ({exc}) — assuming English captions", file=sys.stderr)
        return None
    if result.returncode != 0 or not result.stdout.strip():
        print("[watch] language probe returned nothing — assuming English captions", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print("[watch] language probe JSON unreadable — assuming English captions", file=sys.stderr)
        return None


def source_language(info: dict | None) -> str | None:
    """The language the video was *recorded* in, per yt-dlp metadata."""
    if not info:
        return None
    lang = normalize(info.get("language"))
    if lang:
        return lang
    # YouTube marks the original auto-caption track `<lang>-orig`; every other
    # entry in automatic_captions is a machine translation of it.
    for key in info.get("automatic_captions") or {}:
        if key.endswith("-orig"):
            return normalize(key)
    manual = [k for k in (info.get("subtitles") or {}) if k != "live_chat"]
    if len(manual) == 1:
        return normalize(manual[0])
    return None


def sub_lang_patterns(lang: str | None) -> list[str]:
    """--sub-langs entries that fetch the original language, not a translation."""
    base = base_code(lang)
    if not base:
        # Unknown original: take English plus whatever is tagged as original.
        return ["en.*", ORIG_PATTERN]
    return [f"{base}.*"]


def _lang_of(vtt: Path) -> str | None:
    """`video.pl-orig.vtt` → `pl-orig`. yt-dlp names subs `<stem>.<lang>.<ext>`."""
    parts = vtt.name.split(".")
    return parts[-2] if len(parts) >= 3 else None


def _pick_subtitle(
    out_dir: Path,
    prefer_lang: str | None = None,
    manual_langs: set[str] | None = None,
) -> tuple[Path | None, str | None]:
    """Pick the caption file closest to the video's own language.

    Best to worst: human-written captions in the spoken language, then the
    original-language ASR track (`<lang>-orig`), then YouTube's translation of
    it back into the same language, then anything else — English last, since an
    English track on a non-English video is a machine translation.
    """
    candidates = sorted(out_dir.glob("video*.vtt"))
    if not candidates:
        return None, None

    want = base_code(prefer_lang)
    manual = manual_langs or set()

    def rank(vtt: Path) -> tuple[int, str]:
        tag = _lang_of(vtt) or ""
        base = base_code(tag)
        is_manual = tag in manual
        is_orig = tag.endswith("-orig")
        if want and base == want:
            tier = 0 if is_manual else (1 if is_orig else 2)
        elif is_orig:
            tier = 3
        elif is_manual:
            tier = 4
        elif base == "en":
            tier = 5
        else:
            tier = 6
        return (tier, vtt.name)

    best = min(candidates, key=rank)
    return best, normalize(_lang_of(best))


def _pick_video(out_dir: Path) -> Path | None:
    for ext in (".mp4", ".mkv", ".webm", ".mov"):
        for candidate in out_dir.glob(f"video*{ext}"):
            return candidate
    for candidate in out_dir.glob("video.*"):
        if candidate.suffix.lower() in VIDEO_EXTS:
            return candidate
    return None


def download_url(url: str, out_dir: Path, probe: bool = True) -> dict:
    if shutil.which("yt-dlp") is None:
        raise SystemExit("yt-dlp is not installed. Install with: brew install yt-dlp")

    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(out_dir / "video.%(ext)s")

    print("[watch] probing source language…", file=sys.stderr)
    probed = probe_info(url) if probe else None
    original_lang = source_language(probed)
    sub_langs = sub_lang_patterns(original_lang)
    if original_lang:
        print(f"[watch] source language: {original_lang} — requesting captions in it", file=sys.stderr)

    cmd = [
        "yt-dlp",
        "-N", "8",
        "-f", "bv*[height<=720]+ba/b[height<=720]/bv+ba/b",
        "--merge-output-format", "mp4",
        "--write-info-json",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", ",".join(sub_langs),
        "--sub-format", "vtt",
        "--convert-subs", "vtt",
        "--no-playlist",
        "--ignore-errors",
        "-o", output_template,
        "--",
        url,
    ]

    # yt-dlp may exit non-zero if a subtitle variant fails (e.g. 429) even when
    # the video itself downloaded fine. Treat "video file present" as success.
    result = subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr)
    video = _pick_video(out_dir)
    if video is None:
        raise SystemExit(
            f"yt-dlp did not produce a video file in {out_dir} (exit {result.returncode})"
        )

    manual_langs = set((probed or {}).get("subtitles") or {})
    subtitle, subtitle_lang = _pick_subtitle(
        out_dir, prefer_lang=original_lang, manual_langs=manual_langs,
    )
    info_path = out_dir / "video.info.json"
    info: dict = {}
    if info_path.exists():
        try:
            raw = json.loads(info_path.read_text(encoding="utf-8"))
            info = {
                "title": raw.get("title"),
                "uploader": raw.get("uploader") or raw.get("channel"),
                "duration": raw.get("duration"),
                "url": raw.get("webpage_url") or url,
                "language": normalize(raw.get("language")) or original_lang,
            }
        except Exception as exc:
            print(f"[watch] info.json parse failed: {exc}", file=sys.stderr)
            info = {"url": url}

    if not original_lang:
        original_lang = info.get("language")

    return {
        "video_path": str(video),
        "subtitle_path": str(subtitle) if subtitle else None,
        "subtitle_lang": subtitle_lang,
        "source_language": original_lang,
        "info": info or {"url": url},
        "downloaded": True,
    }


def download(source: str, out_dir: Path, probe: bool = True) -> dict:
    if is_url(source):
        return download_url(source, out_dir, probe=probe)
    return resolve_local(source)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: download.py <url-or-path> <out-dir>", file=sys.stderr)
        raise SystemExit(2)
    result = download(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps(result, indent=2))
