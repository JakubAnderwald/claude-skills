# Claude Code Skills

Shared Claude Code skills, synced across machines via git.

## Skills

| Skill | Description |
|-------|-------------|
| `/push` | Commit, push, poll CI/CD & review comments, fix issues in a loop until green |
| `/merge` | Merge current PR to main (CI green + comments resolved), clean up branch & worktree |
| `/watch` | Watch a video (URL or local path): scene-change frames + on-device transcript + a dense 0–10s hook microscope, into a structured report written in the video's own language and printed into the chat |

## Setup on a new machine

The whole repo is symlinked in as your Claude Code skills directory — so every
subfolder with a `SKILL.md` becomes a live skill automatically (both pure-prompt
skills and code-backed ones like `watch`, which need their `scripts/` dir and
`$CLAUDE_SKILL_DIR` to travel together):

```bash
git clone https://github.com/JakubAnderwald/claude-skills ~/code/claude-skills
ln -sfn ~/code/claude-skills ~/.claude/skills
```

That's it. `~/.claude/skills/watch`, `.../push`, etc. all resolve into the repo.
The repo's `README.md`, `.git/`, etc. sit alongside the skill folders and are
simply ignored (they have no `SKILL.md`).

> Note: because `~/.claude/skills` *is* this repo, don't create a second symlink
> at `~/.claude/skills/<name>` pointing back into the repo — that makes a
> self-referential loop (`ELOOP`) that breaks the shell. Skills are already live
> just by existing as folders here.

## `/watch` prerequisites

`/watch` shells out to local tooling — **no API key, and nothing leaves the machine.** Transcription runs on-device via whisper.cpp. Before first use:

- **`ffmpeg` + `yt-dlp` + `whisper-cpp`** — required. On macOS: `brew install ffmpeg yt-dlp whisper-cpp`.
- **The `large-v3-q5_0` ggml model** (~1.1 GB) — required for videos without native captions, and for the hook microscope's word-level timings. Looked up via `$WATCH_WHISPER_MODEL`, then `~/code/whisper-transcribe/`, then `~/.config/watch/models/`.

Run the installer once — it's idempotent, brew-installs the binaries on macOS, downloads the model if no copy is found, and prints the exact commands instead on Linux/Windows:

```bash
python3 ~/.claude/skills/watch/scripts/setup.py
```

Every `/watch` run silently preflights with `setup.py --check` (exit `2` = missing binaries, `3` = missing model, `4` = both), so a half-installed machine tells you what to fix instead of failing mid-watch.

Optional environment variables:

- `WATCH_WHISPER_MODEL` — path to an existing ggml model, if you keep one outside the search paths.
- `WATCH_WHISPER_LANG` — default spoken language for whisper (`auto` by default; the report is written in whatever language is detected).

## Credits

`/watch` is vendored from [taoufik123-collab/claude-watch](https://github.com/taoufik123-collab/claude-watch) (MIT), itself built on Bradley Bonanno's [claude-video](https://github.com/bradautomates/claude-video). See `watch/LICENSE` and `watch/AUTHORS.md`.

This fork diverges from upstream in two ways: the cloud Whisper backends (Groq/OpenAI) were replaced with on-device whisper.cpp, and the Obsidian auto-save step was dropped — reports stay in the working directory and get printed into the chat.
