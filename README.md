# Claude Code Skills

Shared Claude Code skills, synced across machines via git.

## Skills

| Skill | Description |
|-------|-------------|
| `/push` | Commit, push, poll CI/CD & review comments, fix issues in a loop until green |
| `/merge` | Merge current PR to main (CI green + comments resolved), clean up branch & worktree |
| `/watch` | Watch a video (URL or local path): scene-change frames + transcript + structured report, a dense 0–10s hook microscope, and optional Obsidian auto-save |

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

`/watch` shells out to local tooling. Before first use:

- **`ffmpeg` + `yt-dlp`** — required. On macOS: `brew install ffmpeg yt-dlp`. The skill's `scripts/setup.py` will auto-install these on macOS/Homebrew and scaffold config; on Linux/Windows it prints the exact commands.
- **Whisper API key (optional)** — `GROQ_API_KEY` (preferred) or `OPENAI_API_KEY` in `~/.config/watch/.env`, used only as a transcript fallback when a video has no native captions. (See also the local-Whisper option below.)
- **Obsidian vault (optional)** — set `WATCH_VAULT_DIR` to auto-ingest reports; otherwise the report is left on disk and that step is skipped.

Run `python3 ~/.claude/skills/watch/scripts/setup.py` once to install deps and scaffold config.

## Credits

`/watch` is vendored from [taoufik123-collab/claude-watch](https://github.com/taoufik123-collab/claude-watch) (MIT), itself built on Bradley Bonanno's [claude-video](https://github.com/bradautomates/claude-video). See `watch/LICENSE` and `watch/AUTHORS.md`.
