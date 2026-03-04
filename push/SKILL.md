---
name: push
description: Commit all changes, push to remote, wait for CI/CD and review comments, and resolve any issues in a loop until everything passes.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
user-invocable: true
---

# /push — Commit, Push, Wait for CI/CD & Reviews, Fix, Repeat

Follow these steps precisely. Do NOT skip the polling loop.

## Step 1: Stage & Commit

1. Run `git status` and `git diff` to review all pending changes (staged and unstaged).
2. Stage all changes: `git add -A`.
3. Create a commit with a concise, descriptive message summarizing the changes. Use conventional-commit style if the repo already uses it. End the commit message with:
   ```
   Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
   ```
4. If there are no changes to commit, inform the user and skip to Step 3 (push only if there are unpushed commits).

## Step 2: Push

1. Push to the remote branch: `git push`.
2. If there is no upstream tracking branch, use `git push -u origin HEAD`.
3. If the push is rejected (e.g., behind remote), pull with rebase first: `git pull --rebase && git push`.

## Step 3: Detect the Pull Request

1. Run `gh pr view --json number,url,state 2>/dev/null` to find an existing PR for the current branch.
2. If no PR exists, inform the user: "No open PR found for this branch. Push completed." and stop here.
3. Store the PR number for the polling loop.

## Step 4: Poll for CI/CD Checks and Reviews

Enter a loop. On each iteration:

### 4a. Check ALL checks status (CI + review bots)

Run:
```bash
gh pr checks --json name,state --jq '.[] | [.name, .state] | @tsv'
```

Classify the results across **all** checks — both CI jobs and review bots (e.g., CodeRabbit, SonarCloud):
- **All checks passed** (every state is `SUCCESS` or `SKIPPED`): all checks are green.
- **Any check failed** (state is `FAILURE` or `CANCELLED`): there are failures.
- **Any check still pending** (state is `PENDING` or `QUEUED` or `IN_PROGRESS`): checks are still running.

**CRITICAL:** Do NOT ignore pending non-CI checks. Review bots like CodeRabbit may post new comments after they finish. You must wait for ALL checks to complete before declaring "Done" — otherwise you risk merging before a reviewer has finished and potentially missing new feedback.

### 4b. Check review and PR comments

**IMPORTANT:** Use JSON output (not TSV) to avoid parsing issues with multi-line markdown bodies.

Run these commands to fetch BOTH line-level review comments and general PR comments:

1. **Get line-level review comments (with reply counts):**
```bash
gh api repos/{owner}/{repo}/pulls/{number}/comments --jq '
  [.[] | {id, type: "line", login: .user.login, path, line: (.line // .original_line),
           subject: (.body | split("\n")[0] | .[0:120]),
           has_replies: (if .in_reply_to_id then true else false end)}]
  | [.[] | select(.has_replies == false)]' > pr_comments.json
```

This filters to only **top-level comments without replies** (i.e., unresolved threads).

2. **Get general PR comments:**
```bash
gh api repos/{owner}/{repo}/issues/{number}/comments --jq '
  [.[] | {id, type: "general", login: .user.login,
           subject: (.body | split("\n")[0] | .[0:120])}]' >> pr_comments.json
```

3. **Check for PR-level reviews requesting changes or containing actionable comments:**
```bash
gh api repos/{owner}/{repo}/pulls/{number}/reviews --jq '
  [.[] | select(.state == "CHANGES_REQUESTED" or (.state == "COMMENTED" and (.body | length) > 0))
   | {login: .user.login, state}]'
```

*Crucial Step:* Analyze `pr_comments.json`. Apply these filters:
- **Ignore** comments authored by yourself, Claude, `github-actions[bot]`, or `vercel[bot]`
- **Include** comments from all other reviewers (human or bot reviewers like `coderabbitai[bot]`)
- A comment is **unresolved** if it is a top-level comment with no reply from you in this loop
- Count the number of unresolved comments to decide next action

### 4c. Decide what to do

| All Checks Status | Unresolved/Unanswered Comments | Action |
|-------------------|--------------------------------|--------|
| Any still running | Any | Wait 30 seconds, then poll again (Step 4g) |
| All green | None | Verify conversations resolved (Step 4f), then go to Step 5 |
| All green | Yes | Address comments (Step 4d), then push and re-poll |
| Any failed | Any | Fix failures (Step 4e), then push and re-poll |

**IMPORTANT:** "Any still running" means ANY check — including review bots like CodeRabbit. Never proceed to Step 5 while a review bot is still running. It may post new comments that need to be addressed.

### 4d. Address review comments

For EACH unresolved or unanswered comment identified in Step 4b:
1. Read the referenced file/context and understand the comment.
2. If the fix is clear, make the change in the code.
3. If the fix is ambiguous, involves a design decision, or requires clarification, ask the user using `AskUserQuestion`.
4. **Mandatory Reply:** After fixing the code or deciding on an action, you MUST reply to the comment on GitHub so it is marked as addressed.
   
   *For Line Comments (from the pulls API):*
   ```bash
   gh api repos/{owner}/{repo}/pulls/{number}/comments/{comment_id}/replies -f body="Fixed: <brief explanation of what you did>"
   ```
   
   *For General PR Comments (from the issues API):*
   ```bash
   gh api repos/{owner}/{repo}/issues/{number}/comments -f body="> Reply to comment {comment_id}: Fixed: <brief explanation>"
   ```
5. Once all comments are addressed and replied to, commit the changes, push to the branch, and return to Step 4.

### 4e. Fix CI failures

1. Get the failed check's log:
   ```bash
   gh run view <run_id> --log-failed
   ```
   If the run ID is not directly available, list recent runs:
   ```bash
   gh run list --branch $(git branch --show-current) --limit 5 --json databaseId,status,conclusion,name --jq '.[] | select(.conclusion == "failure") | [.databaseId, .name] | @tsv'
   ```
2. Read the failure logs and identify the root cause.
3. Fix the issue in the code.
4. Stage, commit (with a message like "fix: resolve CI failure in <check name>"), and push.
5. Return to the top of the polling loop (Step 4).

### 4f. Verify all conversations are resolved

Before declaring "Done", confirm that the PR can actually be merged by checking for unresolved conversations (repos with `required_conversation_resolution` branch protection will block merge otherwise):

1. **Count unresolved review threads:**
```bash
gh api repos/{owner}/{repo}/pulls/{number}/comments --jq '
  [.[] | select(.in_reply_to_id == null)] |
  [.[] | .id] as $top_ids |
  ($top_ids | length) as $total |
  [.[] | select(.in_reply_to_id != null) | .in_reply_to_id] | unique | length |
  . as $replied |
  ($total - $replied)'
```

Actually, use a simpler approach — check each top-level comment has at least one reply:
```bash
# Get all top-level comment IDs
TOP_IDS=$(gh api repos/{owner}/{repo}/pulls/{number}/comments --jq '[.[] | select(.in_reply_to_id == null) | .id]')
# Get all reply-to IDs
REPLY_IDS=$(gh api repos/{owner}/{repo}/pulls/{number}/comments --jq '[.[] | select(.in_reply_to_id != null) | .in_reply_to_id] | unique')
```

Compare: any ID in `TOP_IDS` not present in `REPLY_IDS` is an unresolved conversation. If unresolved conversations remain, go back to Step 4d to reply to them.

2. If all conversations are resolved, proceed to Step 5.

### 4g. Wait between polls

If CI is still running, wait 30 seconds before the next iteration:
```bash
sleep 30
```

Do not poll more than 60 times (i.e., ~30 minutes). If the limit is reached, inform the user that CI is taking too long and stop.

## Step 5: Report Success

When all CI checks are green and there are no unresolved review comments:
1. Print a summary:
   - Commit(s) pushed
   - PR URL
   - All checks passed
   - Any comments that were addressed
2. Inform the user that the push cycle is complete.
