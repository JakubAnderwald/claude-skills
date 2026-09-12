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

### 2b. Check that every review thread is resolved

**GraphQL `isResolved` is the only authority.** Do not infer resolution from REST reply IDs:
a thread can carry replies and still be unresolved, and a thread can be marked resolved
having never been answered. `/merge` is the gate — it reads thread state and never changes it.

1. **Resolve the identifiers once:**
```bash
read -r OWNER REPO <<<"$(gh repo view --json owner,name --jq '.owner.login + " " + .name')"
NUM=$(gh pr view --json number --jq .number)
```

2. **List every unresolved thread:**
```bash
gh api graphql -f owner="$OWNER" -f repo="$REPO" -F number="$NUM" -f query='
query($owner:String!,$repo:String!,$number:Int!){
  repository(owner:$owner,name:$repo){ pullRequest(number:$number){
    reviewThreads(first:100){ nodes{
      id isResolved isOutdated path line
      comments(first:1){ nodes{ author{login} body } } } } } }
}' --jq '[.data.repository.pullRequest.reviewThreads.nodes[]
          | select(.isResolved == false)
          | "\(.path):\(.line) [\(.comments.nodes[0].author.login)] \(.comments.nodes[0].body | split("\n")[0][0:100])"]
         | .[]'
```

3. **If it prints anything, STOP.** List each `path:line` for the user and tell them to run
   `/push` to address them. Do **not** resolve them here — resolving a thread is a statement
   that you read it and acted on it, and `/merge` has done neither. A merge blocked by an
   open thread is the gate working.

   (If the query returns 100 threads the page is full — re-query with a cursor rather than
   merging on a truncated view.)

4. **Check for reviews requesting changes:**
```bash
gh api "repos/$OWNER/$REPO/pulls/$NUM/reviews" --jq '[.[] | select(.state == "CHANGES_REQUESTED") | {login: .user.login, state}]'
```
If any review has `CHANGES_REQUESTED`, inform the user and stop.

## Step 3: Merge the PR

Use the GitHub API to squash-merge (avoids the worktree issue where `gh pr merge --delete-branch` tries to checkout `main`).

**The merge endpoint is `PUT` — you MUST pass `--method PUT`.** `gh api` defaults to `POST` whenever a field (`-f`) is present, and `POST .../merge` returns **`404 Not Found`** — which looks like a transient error but is actually the wrong HTTP method hitting a route that doesn't exist. Never drop `--method PUT`, and never "simplify" it back to a plain `gh api ... -f`.

**Capture the response and verify `"merged": true` before doing anything else:**

```bash
# $OWNER, $REPO and $NUM are already set from Step 2b — do not re-type them as literals.
MERGE_JSON=$(gh api --method PUT "repos/$OWNER/$REPO/pulls/$NUM/merge" -f merge_method=squash 2>&1)
echo "$MERGE_JSON"
MERGED=$(printf '%s' "$MERGE_JSON" | jq -r '.merged // false' 2>/dev/null)
echo "merged=$MERGED"
```

If `MERGED` is not exactly `true` — for ANY reason (404 wrong-method, 405 "not mergeable", 409 head-changed, branch protection, conflicts) — **STOP IMMEDIATELY.** Inform the user with the raw `$MERGE_JSON` and do **NOT** proceed to Step 4.

> ⚠️ **Destructive-sequence guard:** deleting the branch of an *unmerged* PR makes GitHub **close the PR unmerged** and discards the remote ref. Step 4 (branch delete) and Step 5 (worktree/branch removal) are irreversible relative to the PR. Run them ONLY after you have seen `"merged": true` in this step. A failed merge means: fix the cause (or hand to the user) with the branch and PR fully intact — never clean up after a merge you did not confirm.

## Step 4: Delete the Remote Branch

**Precondition: Step 3 printed `merged=true`.** If it did not, you must not be here.

As a final guard, re-confirm the PR is actually merged before deleting anything:
```bash
gh pr view "$NUM" --json state,mergedAt --jq '"\(.state) \(.mergedAt)"'
# Must print "MERGED <timestamp>". If it prints "CLOSED null" or "OPEN null", STOP — do not delete the branch.
```

Only once you have confirmed `MERGED` with a non-null timestamp, delete the remote branch:
```bash
git push origin --delete $(git branch --show-current)
```

If this fails (e.g., GitHub auto-deleted it on merge), that's fine — continue.

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
