---
name: merge
description: Merge the current PR to main (ensuring CI is green and all comments are resolved), then clean up the branch and worktree.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write, AskUserQuestion
user-invocable: true
---

# /merge — Merge PR, Clean Up Branch & Worktree

Follow these steps precisely. This command merges the current branch's PR into main and cleans up so you're ready for the next task.

## Step 1: Identify the PR

1. Confirm you are NOT on `main`:
```bash
git branch --show-current
```
If on `main`, inform the user and stop — there is nothing to merge.

2. Find the PR for the current branch:
```bash
gh pr view --json number,url,state,title,headRefName,baseRefName
```
If no PR exists, inform the user and stop.

3. If the PR state is not `OPEN`, inform the user (e.g., already merged or closed) and skip to Step 5 (cleanup).

## Step 2: Ensure CI Is Green and All Comments Are Resolved

### 2a. Check all checks status

Run:
```bash
gh pr checks --json name,state --jq '.[] | [.name, .state] | @tsv'
```

Classify results:
- **All passed** (every state is `SUCCESS` or `SKIPPED`): checks are green.
- **Any failed** (state is `FAILURE` or `CANCELLED`): there are failures — inform the user and stop. Do NOT attempt to fix failures in this skill (use `/push` for that).
- **Any still running** (state is `PENDING` or `QUEUED` or `IN_PROGRESS`): wait 30 seconds and re-check. Repeat up to 60 times (~30 minutes). If still not done, inform the user and stop.

### 2b. Check for unresolved review comments

Fetch all review comments and verify every thread is resolved:

1. **Get top-level comment IDs:**
```bash
TOP_IDS=$(gh api repos/{owner}/{repo}/pulls/{number}/comments --jq '[.[] | select(.in_reply_to_id == null) | .id]')
```

2. **Get reply-to IDs:**
```bash
REPLY_IDS=$(gh api repos/{owner}/{repo}/pulls/{number}/comments --jq '[.[] | select(.in_reply_to_id != null) | .in_reply_to_id] | unique')
```

3. Compare: any ID in `TOP_IDS` not present in `REPLY_IDS` is an unresolved thread. If unresolved threads exist, inform the user and stop — use `/push` to address them first.

4. **Check for reviews requesting changes:**
```bash
gh api repos/{owner}/{repo}/pulls/{number}/reviews --jq '[.[] | select(.state == "CHANGES_REQUESTED") | {login: .user.login, state}]'
```
If any review has `CHANGES_REQUESTED`, inform the user and stop.

## Step 3: Merge the PR

Use the GitHub API to squash-merge (avoids the worktree issue where `gh pr merge --delete-branch` tries to checkout `main`):

```bash
gh api repos/{owner}/{repo}/pulls/{number}/merge -f merge_method=squash
```

If the merge fails (e.g., merge conflicts, branch protection), inform the user with the error and stop.

## Step 4: Delete the Remote Branch

After a successful merge, delete the remote branch:
```bash
git push origin --delete $(git branch --show-current)
```

If this fails (e.g., branch already deleted by GitHub), that's fine — continue.

## Step 5: Clean Up Local Worktree and Branch

1. **Detect if we're in a worktree:**
```bash
git rev-parse --git-common-dir
```
If the common dir differs from `.git`, we're in a worktree.

2. **If in a worktree:**
   - Store the current worktree path and branch name:
   ```bash
   WORKTREE_PATH=$(pwd)
   BRANCH_NAME=$(git branch --show-current)
   MAIN_REPO=$(git rev-parse --git-common-dir | sed 's|/\.git$||' | sed 's|/\.git/worktrees/.*$||')
   ```
   - Navigate to the main repo:
   ```bash
   cd "$MAIN_REPO"
   ```
   - Remove the worktree:
   ```bash
   git worktree remove "$WORKTREE_PATH" --force
   ```
   - Delete the local branch:
   ```bash
   git branch -D "$BRANCH_NAME"
   ```
   - Update main:
   ```bash
   git checkout main && git pull origin main
   ```

3. **If NOT in a worktree:**
   - Store the branch name:
   ```bash
   BRANCH_NAME=$(git branch --show-current)
   ```
   - Switch to main and pull:
   ```bash
   git checkout main && git pull origin main
   ```
   - Delete the local branch:
   ```bash
   git branch -D "$BRANCH_NAME"
   ```

## Step 6: Report Success

Print a summary:
- PR title and URL
- Merge method (squash)
- Branch deleted (remote and local)
- Worktree removed (if applicable)
- Current state: on `main`, up to date
- **Ready to start a new task** — suggest the user run `/clear` to reset context
