---
name: watch
description: Watch a video (URL or local path) like an editor. Extracts scene-change frames, pacing metrics (cuts/min, shot length), and a dense 0-10s hook microscope; pulls transcript from captions or local whisper.cpp (large-v3-q5_0). Produces a structured `report.md` — a timestamped summary shaped by *why* the user watched it, written in the language the video is spoken in and printed straight into the chat.
argument-hint: "<video-url-or-path> [why you're watching it]"
allowed-tools: Bash, Read, AskUserQuestion
homepage: https://github.com/taoufik123-collab/claude-watch
repository: https://github.com/taoufik123-collab/claude-watch
author: taoufik
license: MIT
user-invocable: true
---

# /watch — Claude watches a video

You don't have a video input; this skill gives you one. A Python script downloads the video, extracts frames as JPEGs (one per detected shot via scene-change), gets a timestamped transcript (native captions first, then local whisper.cpp — `large-v3-q5_0` — as fallback), runs editorial pacing metrics, and microscopes the first 10 seconds at higher density. You then `Read` each frame path to see the images, combine them with the transcript to answer the user, and fill the structured `report.md`.

## What v2 does differently

- **Scene-change frame sampling** — one frame per detected shot instead of uniform ticks. Cuts the frame budget on long videos while capturing every transition.
- **Editorial pacing metrics** — cuts/min, mean shot length, motion (when available). Lets you reason about pacing the way an editor does.
- **Hook microscope** — first 10s auto-runs at 2 fps + word-level timings from local whisper.cpp. The single most leveraged 10 seconds of any video deserves dense treatment.
- **Structured `report.md`** — every watch emits a structured report at `<workdir>/report.md` with TL;DR, key moments, hook breakdown, editorial profile, quotable moments, entities, concepts, and transcript. Narrative sections are emitted as `<!-- pending Claude fill: ... -->` markers — you fill them in after answering the user.
- **Report in the video's own language** — a Polish video gets a Polish report, a Japanese video a Japanese one. The script detects the spoken language and captions are fetched in it (never a machine translation). See "Report language" below.
- **Report printed in chat** — the filled report goes into your reply, not just onto disk. A file path alone is not the deliverable.

Transcription runs entirely **on-device** via whisper.cpp with the `large-v3-q5_0` model — no API key, nothing leaves the machine. Dependencies: `ffmpeg` + `yt-dlp` + `whisper-cpp` + the ggml model.

## Step 0 — Setup preflight (runs every `/watch` invocation, silent on success)

**Python interpreter:** every `python3 ...` command in this skill is for macOS/Linux. On **Windows**, substitute `python` — the `python3` command on Windows is the Microsoft Store stub and will not run the script.

Before every `/watch` run, verify that dependencies and the local whisper model are in place:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py" --check
```

This is a <100ms lookup. On exit 0, the script emits **nothing** — proceed to Step 1 without comment. **Do NOT announce "setup is complete" to the user** — they don't need a status message on every turn. The only acceptable user-visible output from Step 0 is when remediation is required.

On non-zero exit, follow the table:

| Exit | Meaning | Action |
|------|---------|--------|
| `2` | Missing binaries (`ffmpeg` / `ffprobe` / `yt-dlp` / `whisper-cli`) | Run installer |
| `3` | Whisper model (`large-v3-q5_0`) not downloaded | Run installer (it downloads the model) |
| `4` | Both missing | Run installer |

The installer is idempotent — safe to re-run:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py"
```

On macOS with Homebrew, it auto-installs `ffmpeg`, `yt-dlp`, and `whisper-cpp`, then downloads the `large-v3-q5_0` ggml model (~1.1 GB) if it isn't already present. On Linux/Windows, it prints the exact install commands. It writes a `~/.config/watch/.setup_complete` marker once deps + model are in place so the next session knows this machine is set up.

**Model location:** the skill looks for `ggml-large-v3-q5_0.bin` via `$WATCH_WHISPER_MODEL`, then `~/code/whisper-transcribe/`, then `~/.config/watch/models/`. If it's missing, run the installer to download it, or point `$WATCH_WHISPER_MODEL` at an existing copy. If the user doesn't want local transcription set up, proceed with `--no-whisper` and tell them videos without native captions come back frames-only (and the hook microscope will have no word-level timings).

**Structured mode (optional):** `python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py" --json` emits `{status, first_run, missing_binaries, transcription, has_model, model_path, model_search_paths, platform}` where `status` is one of `ready | needs_install | needs_model | needs_install_and_model`. Use this when you need to branch on specifics (e.g. "is this the user's very first run?" → `first_run: true`).

Within a single session, you can skip Step 0 on follow-up `/watch` calls — once `--check` returned 0, nothing about the environment changes between turns.

## When to use

- User pastes a video URL (YouTube, Vimeo, X, TikTok, Twitch clip, most yt-dlp-supported sites) and asks about it.
- User points at a local video file (`.mp4`, `.mov`, `.mkv`, `.webm`, etc.) and asks about it.
- User types `/watch <url-or-path> [question]`.

## Recommended limits

- **Best accuracy: videos under 10 minutes.** Frame coverage scales inversely with duration.
- **Hard caps: 100 frames total and 2 fps.** Token cost grows with frame count, so the script targets a frame budget by duration (and never exceeds 2 fps even when the budget would imply more):
  - ≤30s → ~1-2 fps (up to 30 frames)
  - 30s-1min → ~40 frames
  - 1-3min → ~60 frames
  - 3-10min → ~80 frames
  - \>10min → 100 frames, sparsely spaced (warning printed)
- If the user hands you a long video, consider asking whether they want a specific section before burning tokens on a sparse scan.

## How to invoke

**Step 1 — parse the user input.** Separate the video source from any question the user asked. The question (or the user's prior stated interest) IS the intent — pass it to the script via `--intent`. Example: `/watch https://youtu.be/abc what's the hook pattern?` → source = `https://youtu.be/abc`, intent = `what's the hook pattern?`. If no question is given, use a brief inferred intent ("general summary") so the report's TL;DR has a lens. The intent shapes how the report's TL;DR and entity/concept sections get filled at Step 4 — same video with intent "pricing tactics" vs "editing style" produces different reports.

**Step 2 — run the watch script.** Pass the source verbatim. Do not shell-escape it yourself beyond normal quoting:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/watch.py" "<source>" --intent "<intent string>"
```

Pass `--intent` whenever you have any signal from the user about why they want this video — the question they asked, a stated goal, or a brief inferred summary. Empty `--intent` works but produces less-targeted report sections.

Optional flags:
- `--start T` / `--end T` — focus on a section. Accepts `SS`, `MM:SS`, or `HH:MM:SS`. When either is set, fps auto-scales denser (see "Focusing on a section" below).
- `--max-frames N` — lower the cap for tighter token budget (e.g. `--max-frames 40`)
- `--resolution W` — change frame width in px (default 512; bump to 1024 only if the user needs to read on-screen text)
- `--fps F` — override auto-fps (clamped to 2 fps max). Setting `--fps` disables scene-change sampling.
- `--out-dir DIR` — keep working files somewhere specific (default: an auto-generated tmp dir)
- `--whisper-model PATH` — use a specific ggml whisper.cpp model (default: `large-v3-q5_0`, resolved via `$WATCH_WHISPER_MODEL` or `~/code/whisper-transcribe/`)
- `--lang CODE` — spoken language for whisper.cpp (`auto` to detect; default `auto`). Set e.g. `--lang en` or `--lang pl` when known
- `--report-lang CODE` — language the report is written in. Default `auto` = the detected spoken language. Pass a code (`en`, `pl`, …) **only when the user explicitly asks for the report in a specific language**
- `--no-probe` — skip the metadata probe that detects the source language before downloading captions (captions then fall back to English)
- `--no-whisper` — disable local whisper entirely (frames-only if no captions; hook microscope loses word-level timings)
- `--no-scene-change` — force uniform frame sampling (debug only; usually leave on)
- `--no-hook-microscope` — skip the 0-10s dense pass (saves the local whisper passes)

### Focusing on a section (higher frame rate)

When the user asks about a specific moment — "what happens at the 2 minute mark?", "zoom into 0:45 to 1:00", "the first 10 seconds" — pass `--start` and/or `--end`. The script switches to focused-mode budgets, which are denser than full-video budgets (still capped at 2 fps):

- ≤5s → 2 fps (up to 10 frames)
- 5-15s → 2 fps (up to 30 frames)
- 15-30s → ~2 fps (up to 60 frames)
- 30-60s → ~1.3 fps (up to 80 frames)
- 60-180s → ~0.6 fps (100 frames, capped)

Focused mode is the right call for:
- Any moment/range the user names explicitly ("around 2:30", "the intro", "the last 30 seconds").
- Any video longer than ~10 minutes where the user's question is about a specific part — running focused on the relevant section is far more useful than a sparse scan of the whole thing.
- Re-runs after a full scan didn't have enough detail in some region.

Transcript is auto-filtered to the same range. Frame timestamps are absolute (real video timeline, not offset-from-start).

Examples:
```bash
# Last 10 seconds of a 1 minute video
python3 "${CLAUDE_SKILL_DIR}/scripts/watch.py" video.mp4 --start 50 --end 60

# Zoom into 2:15 → 2:45 at 3 fps (90 frames)
python3 "${CLAUDE_SKILL_DIR}/scripts/watch.py" "$URL" --start 2:15 --end 2:45 --fps 3

# From 1h12m to the end of the video
python3 "${CLAUDE_SKILL_DIR}/scripts/watch.py" "$URL" --start 1:12:00
```

**Step 3 — Read every frame path the script lists.** The Read tool renders JPEGs directly as images for you. Read all frames in a single message (parallel tool calls) so you see them together. The frames are in chronological order with a `t=MM:SS` timestamp so you can align them to the transcript.

**Step 4 — answer the user, then fill the report.** You now have three streams of evidence:
- **Frames** — what's on screen at each timestamp
- **Transcript** — what's said at each timestamp
- **`report.md`** — structured artifact at `<workdir>/report.md` with `<!-- pending Claude fill: ... -->` markers

First, answer the user's question in chat citing timestamps.

Then, **fill in the pending markers in `report.md` using the Edit tool** — every section written in the video's spoken language (see "Report language" below). Walk every `<!-- pending Claude fill: ... -->` in order:
- **TL;DR** — 3-5 bullets through the lens of the user's intent (read from the frontmatter)
- **Key moments** — 5-10 timestamped bullets
- **Hook microscope interpretation** — frame-by-frame: visual change × what's said; identify the hook pattern (question, contrarian claim, in-medias-res, demo-first, etc.)
- **Editorial profile fingerprint** — one-line style summary inferred from pacing numbers + hero frames
- **Quotable moments** — top 3-5 punchy, standalone lines from the transcript, **quoted verbatim** (never translated)
- **Entities mentioned** — people, companies, tools, places (kebab-case, lowercase), spelled as they're said in the video
- **Concepts surfaced** — frameworks, mental models, named patterns — short gist each

Do not skip the fill — the report is the durable artifact of the watch.

**Step 5 — print the report in chat.** The user reads the report in the console; a link alone doesn't count as delivering it. After the last marker is filled, output the report as normal markdown in your reply:

- Everything from the `# <title>` heading through **Concepts surfaced**, as written in the file.
- Skip the YAML frontmatter, the HTML comments, the **All frames** list, and the raw **Transcript** block — they're bulk, and they stay in the file. Replace them with one line noting the transcript and frame list are in the report file. If the user explicitly asks for the transcript, print that too.
- Add the metadata that isn't in the body but is worth seeing: duration, spoken language, transcript source.
- End with the path on its own line: `📄 Report: <workdir>/report.md`.

Print it as real markdown — not inside a code fence — so it renders.

**Step 6 — clean up.** The script prints a working directory at the end. If the user isn't going to ask follow-ups, delete it with `rm -rf <dir>`. If they might ask follow-ups (or want the report / frames), leave it in place and point them at `<workdir>/report.md`.

## Report language

**The report is written in the language the video is spoken in — not English.** A Polish video gets a Polish report; a Japanese video gets a Japanese one. This applies to the narrative sections *and* their headings (`## Kluczowe momenty` rather than `## Key moments`). English is just one possible answer, not the default.

What stays untouched regardless of language: the YAML frontmatter keys, timestamps, pacing numbers, frame filenames and paths, and the transcript block. Quotes are reproduced verbatim in the spoken language — never translate a quote.

The script resolves the language for you and prints it in its stdout header (`- **Spoken language:** Polish (pl) — via whisper (full audio)`). It also lands in the report frontmatter as `language:` and is repeated inside every pending marker (`<!-- pending Claude fill (in Polish): ... -->`). Detection order, most trusted first:

1. `--report-lang CODE` if you passed one
2. whisper.cpp's detection over the full audio track
3. the source's own metadata (yt-dlp `language`, or YouTube's `<lang>-orig` caption tag)
4. the language of the caption track that was actually downloaded
5. whisper.cpp's detection over the 10s hook (short clips misdetect on music or silence)
6. `--lang` if it was pinned to something other than `auto`

If detection comes back `unknown`, read the transcript and write the report in whatever language it's in.

Two things this does *not* change:

- **Your chat reply follows the user, not the video.** Someone writing to you in English about a Polish video gets an English answer in chat — and a Polish `report.md`. When you print the report in Step 5, it stays in the video's language; add a one-line note in the user's language if the mismatch needs flagging.
- **Explicit user requests win.** "Give me the report in English" → pass `--report-lang en` and write it in English.

## Transcription

The script gets a timestamped transcript in one of two ways:

1. **Native captions (free, preferred).** yt-dlp pulls manual or auto-generated subtitles from the source platform if available — **in the video's original language**. A metadata probe runs first to learn what that language is, because YouTube serves 100+ machine-*translated* caption tracks per video: asking for `en` on a Polish video hands back an English translation and drags the whole report into the wrong language. Preference order is human-written captions in the spoken language → the original-language ASR track (`<lang>-orig`) → anything else, with English last on non-English videos. `--no-probe` skips the probe (and falls back to English captions).
2. **Local whisper.cpp fallback.** If no captions came back (or the source is a local file), the script extracts audio (`ffmpeg -vn -ac 1 -ar 16000 -c:a pcm_s16le`, 16 kHz mono WAV) and transcribes it **on-device** with whisper.cpp using the **`large-v3-q5_0`** model — the full large-v3 model quantized to 5-bit (higher quality than the `turbo` distill on hard audio/proper nouns; ~1.1 GB). No API key; nothing leaves the machine. Multilingual — pass `--lang` when the language is known (default `auto`).

   For the **hook microscope**, the first 10 s is transcribed a second time in `--max-len 1 --split-on-word` mode to produce **word-level** start/end timings, so each frame can be aligned to the exact word being spoken.

   whisper.cpp transcribes in the spoken language and never translates, and with `--lang auto` it reports which language it heard — that detection is what the report is written in.

The model is resolved via `$WATCH_WHISPER_MODEL`, then `~/code/whisper-transcribe/`, then `~/.config/watch/models/`. Override the model per-run with `--whisper-model PATH`, or use `--no-whisper` to skip local transcription entirely (frames-only if no captions).

## Failure modes and handling

- **Setup preflight failed** → run `python3 "${CLAUDE_SKILL_DIR}/scripts/setup.py"` (on macOS: brew-installs ffmpeg/yt-dlp/whisper-cpp, then downloads the `large-v3-q5_0` model ~1.1 GB). On exit `3` only the model is missing — the installer fetches it.
- **No transcript available** → captions missing AND (`--no-whisper` set OR whisper.cpp/model unavailable OR the local run failed). Script prints a hint pointing to setup. Proceed frames-only and tell the user.
- **Long video warning printed** → acknowledge it in your answer. Offer to re-run focused on a specific section via `--start`/`--end` rather than a sparse full-video scan.
- **Download fails** → yt-dlp's error goes to stderr. If it's a login-required or region-locked video, tell the user plainly; do not keep retrying.
- **Local whisper fails** → the error is printed to stderr (likely: `whisper-cli` not installed, or the model file is missing/corrupt). The report will say transcript "none available". Re-run `setup.py` to repair deps/model, or pass `--whisper-model PATH` to point at a known-good ggml model.
- **Report has unfilled `<!-- pending Claude fill: ... -->` markers** → you skipped Step 4. Go back, read the report, and fill every marker via Edit.
- **Language came back `unknown`** → the probe failed and whisper had nothing to detect from (no transcript at all). Read the frames, and if the video has visible text, write the report in that language; otherwise ask the user which language they want and pass `--report-lang`.
- **Detected language contradicts the transcript** (e.g. `language: English` on a visibly Polish transcript) → trust the transcript, write the report in its language, and mention the mismatch in chat. It usually means the caption track was a machine translation.
- **Only the report path got printed, not the report** → you skipped Step 5. Print the report body in chat.

## Token efficiency

This skill burns tokens primarily on frames. Order of magnitude:
- 80 frames at 512px wide is roughly 50-80k image tokens depending on aspect ratio.
- The transcript is cheap (a few thousand tokens at most for a 10-minute video).
- Bumping `--resolution` to 1024 roughly quadruples the image tokens per frame. Only do it when necessary.

If you already watched a video this session and the user asks a follow-up, do **not** re-run the script — you already have the frames and transcript in context. Just answer from what you have.

## Security & Permissions

**What this skill does:**
- Runs `yt-dlp` locally to probe the source's public metadata (to learn its language), then to download the video and pull native captions in that language when the source supports them (public data; the requests go directly to whatever host the URL points at)
- Runs `ffmpeg` / `ffprobe` locally to extract frames as JPEGs and, when whisper is needed, a mono 16 kHz WAV audio clip
- Runs `whisper-cli` (whisper.cpp) locally with the `large-v3-q5_0` model to transcribe audio **entirely on-device** — no network, no API key, no third-party service. The audio never leaves the machine
- Downloads the ggml model from Hugging Face (`huggingface.co/ggerganov/whisper.cpp`) only during setup, if it isn't already present
- Writes the downloaded video, frames, audio, and an intermediate transcript to a working directory under the system temp dir (or `--out-dir` if specified) so Claude can `Read` them
- Writes a `~/.config/watch/.setup_complete` marker (and downloads the model to `~/.config/watch/models/` if no other copy is found)

**What this skill does NOT do:**
- Does not send the video, audio, or transcript to any transcription API or third-party service — all transcription is local (whisper.cpp). The only outbound requests are yt-dlp fetching the source you pointed it at, and the one-time model download during setup
- Does not require or store any API key
- Does not access any platform account (no login, no session cookies, no posting)
- Does not persist anything outside the working directory and `~/.config/watch/` — clean up the working directory when you're done (Step 6)

**Bundled scripts:** `scripts/watch.py` (entry point), `scripts/download.py` (yt-dlp wrapper + source-language probe), `scripts/frames.py` (ffmpeg uniform + scene-change extraction + hero selection), `scripts/pacing.py` (editorial metrics), `scripts/hook.py` (0-10s microscope), `scripts/report.py` (structured report emitter), `scripts/transcribe.py` (WebVTT caption parser), `scripts/whisper_local.py` (local whisper.cpp client — `large-v3-q5_0`, segment + word-level timestamps, language detection), `scripts/languages.py` (language-code → name table), `scripts/setup.py` (preflight + installer)

Review scripts before first use to verify behavior.
