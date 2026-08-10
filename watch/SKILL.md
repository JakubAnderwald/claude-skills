---
name: watch
description: Watch a video (URL or local path) and report what it actually says. Extracts scene-change frames and on-screen data (tables, charts, lower-thirds); pulls transcript from captions or local whisper.cpp (large-v3-q5_0). Produces a structured `report.md` — premise, process, findings in tables, conclusions — shaped by *why* the user watched it, written in the language the video is spoken in and printed straight into the chat. Craft metrics (hook, cuts/min) stay an appendix unless the user asks about form.
argument-hint: "<video-url-or-path> [why you're watching it]"
allowed-tools: Bash, Read, AskUserQuestion
homepage: https://github.com/taoufik123-collab/claude-watch
repository: https://github.com/taoufik123-collab/claude-watch
author: taoufik
license: MIT
user-invocable: true
---

# /watch — Claude watches a video

You don't have a video input; this skill gives you one. A Python script downloads the video, extracts frames as JPEGs (one per detected shot via scene-change), gets a timestamped transcript (native captions first, then local whisper.cpp — `large-v3-q5_0` — as fallback), runs editorial pacing metrics, and microscopes the first 10 seconds at higher density. You then `Read` each frame path to see the images, mine whatever data the video puts on screen, combine it all with the transcript to answer the user, and fill the structured `report.md`.

**The report is about what the video says, not how it was cut.** A viewer who reads it should end up knowing what the video established — the numbers, the method, the verdict — without having watched it. Craft observations (hook pattern, cuts/min, shot length) are an appendix of raw metrics with no commentary, and only get promoted to real sections when the user actually asks about form.

## What this skill gives you

- **Content-first `report.md`** — every watch emits a structured report at `<workdir>/report.md`: TL;DR → Setup & premise → How it unfolds → **Findings** → Conclusions & caveats → quotes, entities, concepts, transcript. Narrative sections are emitted as `<!-- pending Claude fill: ... -->` markers — you fill them in after answering the user.
- **Findings is the load-bearing section** — every concrete number the video produces, in markdown tables, grouped the way the video groups them. That is what makes the report worth keeping.
- **Scene-change frame sampling** — one frame per detected shot instead of uniform ticks. Cuts the frame budget on long videos while capturing every transition.
- **On-screen data mining** — most informative videos put their real payload in graphics, not narration. Step 3b below finds those frames and reads them at full resolution.
- **Report in the video's own language** — a Polish video gets a Polish report, a Japanese video a Japanese one. The script detects the spoken language and captions are fetched in it (never a machine translation). See "Report language" below.
- **Report printed in chat** — the filled report goes into your reply, not just onto disk. A file path alone is not the deliverable.
- **Craft metrics on demand** — pacing numbers and the 0-10s hook microscope (2 fps + word-level timings from local whisper.cpp) still run every time. They surface as commentary only under `--form-analysis` or a form-shaped `--intent`.

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

**Step 1 — parse the user input.** Separate the video source from any question the user asked. The question (or the user's prior stated interest) IS the intent — pass it to the script via `--intent`. Example: `/watch https://youtu.be/abc what's the hook pattern?` → source = `https://youtu.be/abc`, intent = `what's the hook pattern?`. If no question is given, use a brief inferred intent ("general summary") so the report's TL;DR has a lens.

The intent does two things: it aims the TL;DR and Conclusions sections, and it decides whether craft sections appear at all. An intent mentioning hook / editing / pacing / montaż / tempo / styl flips the report into form mode; anything else keeps it content-only. Override with `--form-analysis` or `--no-form-analysis` when the inference would get it wrong.

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
- `--form-analysis` / `--no-form-analysis` — force the hook breakdown and editorial profile on or off, overriding what the intent implies

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

**Check coverage before moving on.** Scene-change sampling spends its frame budget wherever the cuts are, so a video with a busy first half can exhaust the budget long before the end — a 20-minute video whose last frame is `t=11:04` has a *nine-minute blind spot* covering, typically, all the results. The report prints a `> **Coverage gap:**` warning when the last frame lands before 85% of the duration. When you see it, re-run focused on the uncovered span (`--start`) before writing anything. Never write Findings over a region you have not seen.

**Step 3b — mine the on-screen data.** Read the frames you already have and ask: *is this video's payload in the pictures?* Result tables, score cards, spec comparisons, benchmark charts, price lower-thirds, dashboards, terminal output. If yes, do not settle for the frames scene-change happened to catch — graphics often appear mid-shot and get missed entirely.

Find them by their visual signature instead. Sample a distinctive strip of the frame at 2 fps through `ffmpeg`, score it in plain Python, then extract only the hits at full resolution:

```bash
# 1. Score a bottom-third strip every 0.5s — here: red header bar + bright data row.
#    Tune the crop and the test to the overlay you actually saw in Step 3.
ffmpeg -v error -i video.mp4 \
  -vf "fps=2,crop=iw*0.76:ih*0.10:iw*0.21:ih*0.845,scale=24:8,format=rgb24" \
  -f rawvideo - | python3 -c "
import sys
d = sys.stdin.buffer.read(); W, H = 24, 8; n = W*H*3
for i in range(len(d)//n):
    px = [d[i*n+j*3:i*n+j*3+3] for j in range(W*H)]
    hdr = px[W:3*W]; dat = px[4*W:7*W]
    red = sum(p[0] for p in hdr)/len(hdr) - sum(p[1]+p[2] for p in hdr)/(2*len(hdr))
    bright = sum(sum(p) for p in dat)/(3*len(dat))
    if red > 45 and bright > 150: print(f'{i/2:.1f}')
"

# 2. Extract each hit as a wide crop of just the overlay — legible and cheap.
ffmpeg -v error -ss 558.5 -i video.mp4 -frames:v 1 \
  -vf "crop=1030:90:240:592,scale=1030:-1" -q:v 2 table_558.jpg
```

Cropping to the overlay instead of grabbing full 1024px frames is what keeps this affordable: a 1030×90 strip costs a fraction of a full frame and the digits are sharper than in any 512px frame. Group consecutive hits into runs and take one frame per run — an overlay that stays up for 6 seconds is one table, not twelve.

Adapt the signature to what you're hunting: a white slab on the lower third, a fixed-position chart, a dark terminal pane. When a video has no such graphics, say so in one line and move on — do not burn passes hunting for tables that aren't there.

**Step 4 — answer the user, then fill the report.** You now have four streams of evidence:
- **Frames** — what's on screen at each timestamp
- **On-screen graphics** — the numbers the video committed to publishing
- **Transcript** — what's said at each timestamp
- **`report.md`** — structured artifact at `<workdir>/report.md` with `<!-- pending Claude fill: ... -->` markers

First, answer the user's question in chat citing timestamps.

Then, **fill in the pending markers in `report.md` using the Edit tool** — every section written in the video's spoken language (see "Report language" below). Each marker states its own brief; the shape of the whole is:

- **TL;DR** — 3-5 bullets that *answer* the intent, leading with the most concrete finding. Not a description of the video.
- **Setup & premise** — the question, the participants, the equipment with prices, the dose/sample, the thresholds used as pass-fail criteria. Tables for anything with 3+ comparable items.
- **How it unfolds** — the process or argument as a numbered list, plus a closing note on what the method does *not* control for.
- **Findings** — **write this one first and give it the most room.** Every result in markdown tables, grouped the way the video groups them, decisive cells bolded, plus a cross-cutting comparison table.
- **Conclusions & caveats** — the verdict in bold in the first sentence, what generalises, where the video overreaches, then a numbered caveat list including ones the video never raises.
- **Notable quotes** — 3-5 lines that carry a claim or a number, **verbatim** (never translated, never tidied).
- **Entities / Concepts** — names as spoken with model numbers and prices attached; concepts explained by mechanism, so a reader who skipped the video can use the term correctly.
- **Hook microscope / Editorial profile** — only present in form mode. In content mode you get a **Production notes** appendix of raw metrics instead: leave it alone, write no commentary on it.

Do not skip the fill — the report is the durable artifact of the watch.

**Step 5 — print the report in chat.** The user reads the report in the console; a link alone doesn't count as delivering it. After the last marker is filled, output the report as normal markdown in your reply:

- Everything from the `# <title>` heading through **Concepts surfaced**, as written in the file.
- Skip the YAML frontmatter, the HTML comments, the **Production notes** appendix, the **All frames** list, and the raw **Transcript** block — they're bulk, and they stay in the file. Replace the last two with one line noting the transcript and frame list are in the report file. If the user explicitly asks for the transcript, print that too.
- Add the metadata that isn't in the body but is worth seeing: duration, spoken language, transcript source.
- End with the path on its own line: `📄 Report: <workdir>/report.md`.

Print it as real markdown — not inside a code fence — so it renders.

**Step 6 — clean up.** The script prints a working directory at the end. If the user isn't going to ask follow-ups, delete it with `rm -rf <dir>`. If they might ask follow-ups (or want the report / frames), leave it in place and point them at `<workdir>/report.md`.

## Trusting the numbers

The Findings section is only worth as much as its digits, and the transcript is the *least* reliable source for them.

**Auto-generated captions mangle numbers.** YouTube ASR routinely drops decimal separators and leading zeros, so `0,09 ‰` comes back as `9 promila`, `0,157 mg/l` as `157000 mg/l`, and `0,2–0,5 ‰` as `od 2 do5 promila`. Read that literally and you publish figures off by two orders of magnitude. The corruption is silent — the sentence still parses.

So: **every number that reaches the report must be confirmed against a frame**, or explicitly marked as narration-only. When a figure exists only in speech, sanity-check it against the video's own internal arithmetic (a unit conversion it states, a threshold it defines, a total it sums) and say in the report that it is unverified.

**Cross-check the arithmetic you can.** If the video gives both a raw reading and a converted one, verify the conversion — matching results confirm you read both correctly. Where a stated conversion factor and two on-screen values agree, all three are almost certainly right.

**Reconstruct, don't guess.** When captions have clearly lost a separator, restore it from context (magnitude, units, neighbouring values, the legal or physical range being discussed) and confirm the reconstruction against at least one frame before treating it as fact.

**Frames beat narration for state, narration beats frames for causation.** What a device displays, what a chart plots, what a scoreboard says — take from the image. Why it happened, what it means, what was controlled for — take from the transcript.

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
- **`> **Coverage gap:**` in the report** → scene-change sampling ran out of budget before the end. Re-run with `--start <last frame timestamp>` and read those frames too. Do not write Findings over the unseen span, and never let the gap pass silently — a report that quietly covers only the first half reads exactly like one that covers all of it.
- **Findings section is thin or has no tables** → you summarised the narration instead of mining the video. Go back to Step 3b: the numbers are usually in on-screen graphics that scene-change sampling skipped.
- **A number looks two orders of magnitude off** → an auto-caption ate a decimal separator. See "Trusting the numbers"; confirm against a frame before publishing it.
- **Report is all craft and no substance** → you wrote against the wrong mode. Check `form_analysis:` in the frontmatter; in content mode the **Production notes** appendix takes no commentary at all.

## Token efficiency

This skill burns tokens primarily on frames. Order of magnitude:
- 80 frames at 512px wide is roughly 50-80k image tokens depending on aspect ratio.
- The transcript is cheap (a few thousand tokens at most for a 10-minute video).
- Bumping `--resolution` to 1024 roughly quadruples the image tokens per frame. Only do it when necessary.
- Step 3b's overlay crops are the cheap way to buy legibility: a 1030×90 strip is a small fraction of a full frame, so a dozen of them cost less than two extra full-resolution frames — and the digits are sharper than in any 512px frame. Never bump `--resolution` globally just to read one table.
- The detection pass itself is free of image tokens: `ffmpeg` scores thumbnails into raw bytes and Python filters them, so only the confirmed hits ever become images.

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

**Bundled scripts:** `scripts/watch.py` (entry point), `scripts/download.py` (yt-dlp wrapper + source-language probe), `scripts/frames.py` (ffmpeg uniform + scene-change extraction + hero selection), `scripts/pacing.py` (editorial metrics), `scripts/hook.py` (0-10s microscope), `scripts/report.py` (structured report emitter + content/form mode gating), `scripts/transcribe.py` (WebVTT caption parser), `scripts/whisper_local.py` (local whisper.cpp client — `large-v3-q5_0`, segment + word-level timestamps, language detection), `scripts/languages.py` (language-code → name table), `scripts/setup.py` (preflight + installer)

Review scripts before first use to verify behavior.
