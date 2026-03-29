# Claude Code Skills

Shared Claude Code slash-command skills, synced across machines via git.

## Skills

| Skill | Description |
|-------|-------------|
| `/push` | Commit, push, poll CI/CD & review comments, fix issues in a loop until green |
| `/merge` | Merge current PR to main (CI green + comments resolved), clean up branch & worktree |
| `/ralph-plan` | Planning assistant |

## Setup on a new machine

```bash
git clone https://github.com/JakubAnderwald/claude-skills ~/code/claude-skills

# Symlink each skill into Claude Code commands
mkdir -p ~/.claude/commands
for skill in ~/code/claude-skills/*/SKILL.md; do
  name=$(basename "$(dirname "$skill")")
  ln -sf "$skill" ~/.claude/commands/"$name".md
done
```
