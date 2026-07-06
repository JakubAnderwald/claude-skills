#!/usr/bin/env python3
"""Setup / preflight for /watch (local whisper.cpp edition).

Modes:
  setup.py --check      Silent preflight. Exit 0 if ready, 2/3/4 on failure.
  setup.py --json       Machine-readable status for Claude to parse.
  setup.py              Installer. Brew-installs deps, downloads the ggml model.

/watch transcribes locally with whisper.cpp + the large-v3-q5_0 model — no API
key, nothing leaves the machine. "Ready" means: ffmpeg/ffprobe/yt-dlp + a
whisper.cpp binary + the ggml model are all present.

Design:
- Silent on success: --check exits 0 with no output when ready, so /watch
  doesn't spam a status line on every turn.
- Idempotent: re-running the installer is safe.
- Never sudo. On macOS, auto-install via brew. Elsewhere, print exact commands.
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from whisper_local import (  # noqa: E402
    MODEL_FILENAME, MODEL_URL, _BINARY_CANDIDATES, model_candidates,
)


REQUIRED_BINARIES = ["ffmpeg", "ffprobe", "yt-dlp"]
WHISPER_BIN_LABEL = "whisper-cli"  # representative; whisper-cpp / main also accepted
CONFIG_DIR = Path.home() / ".config" / "watch"
MARKER_FILE = CONFIG_DIR / ".setup_complete"
# Where the installer downloads the model when it isn't found anywhere.
MODEL_INSTALL_PATH = CONFIG_DIR / "models" / MODEL_FILENAME


def _which(name: str) -> str | None:
    return shutil.which(name)


def _has_whisper_bin() -> bool:
    return any(_which(b) for b in _BINARY_CANDIDATES)


def _missing_binaries() -> list[str]:
    missing = [b for b in REQUIRED_BINARIES if not _which(b)]
    if not _has_whisper_bin():
        missing.append(WHISPER_BIN_LABEL)
    return missing


def _find_model() -> Path | None:
    for cand in model_candidates():
        if cand.exists():
            return cand
    return None


def is_first_run() -> bool:
    return not MARKER_FILE.exists()


def _mark_complete() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        MARKER_FILE.write_text("ok\n", encoding="utf-8")
    except OSError:
        pass


def _status() -> dict:
    """Structured preflight snapshot."""
    missing = _missing_binaries()
    model = _find_model()
    has_model = model is not None

    if not missing and has_model:
        status = "ready"
    elif missing and not has_model:
        status = "needs_install_and_model"
    elif missing:
        status = "needs_install"
    else:
        status = "needs_model"

    return {
        "status": status,
        "first_run": is_first_run(),
        "missing_binaries": missing,
        "transcription": "local whisper.cpp (large-v3-q5_0)",
        "has_model": has_model,
        "model_path": str(model) if model else None,
        "model_search_paths": [str(p) for p in model_candidates()],
        "platform": platform.system(),
    }


def _brew_pkg(missing: list[str]) -> list[str]:
    pkgs: list[str] = []
    for bin_name in missing:
        if bin_name in ("ffmpeg", "ffprobe"):
            pkg = "ffmpeg"
        elif bin_name == "yt-dlp":
            pkg = "yt-dlp"
        elif bin_name == WHISPER_BIN_LABEL:
            pkg = "whisper-cpp"
        else:
            pkg = bin_name
        if pkg not in pkgs:
            pkgs.append(pkg)
    return pkgs


def _install_macos(missing: list[str]) -> tuple[bool, str]:
    if _which("brew") is None:
        return False, (
            "Homebrew is not installed. Install it from https://brew.sh, then re-run setup. "
            "Or install manually: `brew install " + " ".join(_brew_pkg(missing)) + "`"
        )
    pkgs = _brew_pkg(missing)
    if not pkgs:
        return True, "nothing to install"
    cmd = ["brew", "install", *pkgs]
    print(f"[setup] running: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        return False, f"brew install failed with exit code {result.returncode}"
    return True, f"installed via brew: {', '.join(pkgs)}"


def _install_hint(system: str, missing: list[str]) -> str:
    pkgs = _brew_pkg(missing)
    hints = []
    if "ffmpeg" in pkgs:
        if system == "Windows":
            hints.append("ffmpeg: `winget install Gyan.FFmpeg`")
        else:
            hints.append("ffmpeg: `sudo apt install ffmpeg` (or dnf/pacman equivalent)")
    if "yt-dlp" in pkgs:
        hints.append("yt-dlp: `pipx install yt-dlp` (or `pip install --user yt-dlp`)")
    if "whisper-cpp" in pkgs:
        hints.append(
            "whisper.cpp: build from https://github.com/ggml-org/whisper.cpp "
            "(provides the `whisper-cli` binary)"
        )
    return "\n  ".join(hints) if hints else "nothing to install"


def _download_model(dest: Path) -> tuple[bool, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[setup] downloading {MODEL_FILENAME} (~1.1 GB) → {dest}", file=sys.stderr)
    if _which("curl"):
        cmd = [
            "curl", "-L", "-C", "-", "--retry", "15", "--retry-all-errors",
            "--speed-limit", "150000", "--speed-time", "30",
            "-o", str(dest), MODEL_URL,
        ]
        result = subprocess.run(cmd)
        ok = result.returncode == 0 and dest.exists() and dest.stat().st_size > 0
        return ok, ("downloaded" if ok else f"curl failed (exit {result.returncode})")
    try:
        import urllib.request
        urllib.request.urlretrieve(MODEL_URL, dest)
        return True, "downloaded"
    except Exception as exc:  # noqa: BLE001
        return False, f"download failed: {exc}"


def cmd_check() -> int:
    """Silent-on-success preflight.

    Exit 0 with no output when ready. On failure, print one actionable line to
    stderr and return: 2 → binaries missing, 3 → model missing, 4 → both.
    """
    s = _status()
    if s["status"] == "ready":
        return 0

    parts = []
    if s["missing_binaries"]:
        parts.append(f"missing binaries: {', '.join(s['missing_binaries'])}")
    if not s["has_model"]:
        parts.append(f"whisper model {MODEL_FILENAME} not found")
    installer = Path(__file__).resolve()
    sys.stderr.write(
        f"[watch] setup incomplete ({'; '.join(parts)}). "
        f"Run: python3 {installer}\n"
    )
    sys.stderr.flush()

    if s["missing_binaries"] and not s["has_model"]:
        return 4
    if s["missing_binaries"]:
        return 2
    return 3


def cmd_json() -> int:
    json.dump(_status(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_install() -> int:
    missing = _missing_binaries()
    system = platform.system()
    if missing:
        if system == "Darwin":
            ok, msg = _install_macos(missing)
            print(f"[setup] {msg}", file=sys.stderr)
            if not ok:
                return 2
            missing = _missing_binaries()
            if missing:
                print(f"[setup] still missing after install: {', '.join(missing)}", file=sys.stderr)
                return 2
        else:
            print(f"[setup] dependencies missing on {system} — please install:", file=sys.stderr)
            print("  " + _install_hint(system, missing), file=sys.stderr)
            return 2

    model = _find_model()
    if model is None:
        ok, msg = _download_model(MODEL_INSTALL_PATH)
        print(f"[setup] {msg}", file=sys.stderr)
        if not ok:
            print(
                f"[setup] download the model manually:\n"
                f"  curl -L -C - --retry 15 -o {MODEL_INSTALL_PATH} \\\n    {MODEL_URL}",
                file=sys.stderr,
            )
            return 3
        model = MODEL_INSTALL_PATH

    _mark_complete()
    print(f"[setup] ready. local whisper.cpp + model at {model}")
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--check":
            return cmd_check()
        if arg == "--json":
            return cmd_json()
    return cmd_install()


if __name__ == "__main__":
    raise SystemExit(main())
