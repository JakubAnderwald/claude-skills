---
name: push
description: Commit all changes, push to remote, wait for CI/CD and review comments, and resolve any issues in a loop until everything passes.
disable-model-invocation: true
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

### 4a. Check CI/CD status

Run:
```bash
gh pr checks --json name,state,conclusion --jq '.[] | [.name, .state, .conclusion] | @tsv'
```

Classify the results:
- **All checks passed** (every conclusion is `SUCCESS` or `SKIPPED`): CI is green.
- **Any check failed** (conclusion is `FAILURE` or `CANCELLED`): CI has failures.
- **Any check still pending** (state is `PENDING` or `QUEUED` or `IN_PROGRESS`): CI is still running.

### 4b. Check review comments

Run:
```bash
gh api repos/{owner}/{repo}/pulls/{number}/comments --jq '.[] | select(.position != null) | [.id, .path, .body, .user.login] | @tsv'
```

Also check for PR-level reviews requesting changes:
```bash
gh pr review list --json author,state --jq '.[] | select(.state == "CHANGES_REQUESTED") | [.author.login, .state] | @tsv'
```

### 4c. Decide what to do

| CI Status | Unresolved Comments | Action |
|-----------|-------------------|--------|
| Still running | Any | Wait 30 seconds, then poll again |
| Green | None | **Done!** Go to Step 5 |
| Green | Yes | Address comments (Step 4d), then push and re-poll |
| Failed | Any | Fix CI failures (Step 4e), then push and re-poll |

### 4d. Address review comments

For each unresolved review comment:
1. Read the referenced file and understand the comment.
2. If the fix is clear, make the change.
3. If the fix is ambiguous or involves a design decision, ask the user using AskUserQuestion.
4. After fixing, reply to the comment on GitHub explaining what was changed:
   ```bash
   gh api repos/{owner}/{repo}/pulls/{number}/comments/{comment_id}/replies -f body="Fixed: <brief explanation>"
   ```

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

### 4f. Wait between polls

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
