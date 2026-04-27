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
4. If there are no changes to commit, inform the user and skip to Step 4 (push only if there are unpushed commits — Steps 2 and 3 still apply: rebase onto the base branch, then push).

## Step 2: Rebase onto the base branch

Keep the PR current with its merge target so CI runs against the integrated state and the squash-merge commit reflects only the work in this branch. Skip this step entirely if the user has explicitly asked you not to rebase.

1. **Determine the base branch.** Try in this order:
   ```bash
   # If an open PR already exists, use the branch the PR targets
   BASE=$(gh pr view --json baseRefName --jq .baseRefName 2>/dev/null)
   # Otherwise, use the repo's default branch (handles main / master / develop)
   if [[ -z "$BASE" ]]; then
     BASE=$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name 2>/dev/null)
   fi
   BASE=${BASE:-main}
   ```

2. **Refuse to rebase main itself.** If the current branch IS the base branch, skip the rest of this step (you don't rebase a branch onto itself):
   ```bash
   CURRENT=$(git branch --show-current)
   if [[ "$CURRENT" == "$BASE" ]]; then
     echo "On $BASE — skipping rebase step."
   fi
   ```

3. **Fetch the latest base:** `git fetch origin "$BASE"`.

4. **Count how many commits the branch is behind:**
   ```bash
   BEHIND=$(git rev-list --count "HEAD..origin/$BASE")
   ```
   - If `$BEHIND` is `0`, the branch is current — skip to Step 3 with `FORCE_PUSH=0`.
   - If `$BEHIND` is `>0`, proceed.

5. **Rebase:** `git rebase "origin/$BASE"`.
   - **On conflict:** run `git rebase --abort`, surface the conflicting paths, and STOP. `/push` does not auto-resolve conflicts — inform the user and ask whether to (a) drop the rebase and just push, (b) resolve the conflicts manually before resuming, or (c) abort the entire push.
   - **On success:** set `FORCE_PUSH=1` for Step 3 and continue.

6. **Sanity check after rebase.** If the repo has a fast local test or typecheck harness (e.g., `pnpm test` for the touched package, `pnpm typecheck`, `cargo test`, language-specific equivalents), run it once so a silent merge defect doesn't ride into CI. If the harness is too slow to run in full, run the subset that exercises the touched files. Skip this step only if no such harness exists.
   - If the post-rebase sanity check fails, fix the failure (commit on top of the rebased branch) before pushing — don't push a known-broken rebased state.

## Step 3: Push

1. **If you rebased and `FORCE_PUSH=1`:** `git push --force-with-lease`. Never use `--force` without `--with-lease` (it can clobber concurrent pushes from a teammate).
2. **Otherwise:** `git push`.
3. If there is no upstream tracking branch, use `git push -u origin HEAD` (or `git push --force-with-lease -u origin HEAD` after a rebase).
4. If a non-rebase push is rejected (e.g., someone else pushed to the same branch concurrently), pull with rebase first: `git pull --rebase && git push`. If YOUR commits conflict with the remote, abort and inform the user — don't auto-resolve.

## Step 4: Detect the Pull Request

1. Run `gh pr view --json number,url,state 2>/dev/null` to find an existing PR for the current branch.
2. If no PR exists, inform the user: "No open PR found for this branch. Push completed." and stop here.
3. Store the PR number for the polling loop.

## Step 5: Poll for CI/CD Checks and Reviews

Enter a loop. On each iteration:

### 5a. Check ALL checks status (CI + review bots)

Run:
```bash
gh pr checks --json name,state --jq '.[] | [.name, .state] | @tsv'
```

Classify the results across **all** checks — both CI jobs and review bots (e.g., CodeRabbit, SonarCloud):
- **All checks passed** (every state is `SUCCESS` or `SKIPPED`): all checks are green.
- **Any check failed** (state is `FAILURE` or `CANCELLED`): there are failures.
- **Any check still pending** (state is `PENDING` or `QUEUED` or `IN_PROGRESS`): checks are still running.

**CRITICAL:** Do NOT ignore pending non-CI checks. Review bots like CodeRabbit may post new comments after they finish. You must wait for ALL checks to complete before declaring "Done" — otherwise you risk merging before a reviewer has finished and potentially missing new feedback.

### 5b. Check review and PR comments (EVERY iteration)

**IMPORTANT:** You MUST fetch comments on EVERY poll iteration, not just when all checks are green. Review bots frequently post comments while their check status is still PENDING. If you skip fetching comments while waiting for checks, you waste time that could be spent addressing already-posted feedback.

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

4. **Check for reviewer follow-up replies (CRITICAL — easy to miss):**

Review bots often reply to YOUR reply with follow-up concerns or confirmations. These follow-ups are NOT top-level comments — they are replies themselves. You must also check for threads where a reviewer's message is the LAST in the chain:

```bash
gh api repos/{owner}/{repo}/pulls/{number}/comments --jq '
  [group_by(.in_reply_to_id // .id)[] |
   sort_by(.created_at) | last |
   select(.user.login != "github-actions[bot]" and .user.login != "vercel[bot]") |
   {id, login: .user.login, subject: (.body | split("\n")[0] | .[0:120])}] |
  [.[] | select(.login != "<your-github-login>")]'
```

Any thread where a reviewer (not you) posted the last message needs your reply.

### 5c. Decide what to do

| All Checks Status | Unresolved/Unanswered Comments | Action |
|-------------------|--------------------------------|--------|
| Any still running | **Yes** | Address comments immediately (Step 5d), then continue polling — do NOT wait idle when there is work to do |
| Any still running | None | Wait 30 seconds, then poll again (Step 5g) |
| All green | None | Pass the Critical Gate (Step 5f-gate), verify conversations resolved (Step 5f), then go to Step 6 |
| All green | Yes | Address comments (Step 5d), then push and re-poll |
| Any failed | Any | Fix failures (Step 5e), then push and re-poll |

**IMPORTANT:** "Any still running" means ANY check — including review bots like CodeRabbit. Never treat a PENDING check as complete just because it has been pending for a long time. Always wait for every check to reach a terminal state (SUCCESS, FAILURE, CANCELLED, or SKIPPED). However, do NOT sit idle while waiting for checks if there are already unresolved comments posted. Address those comments immediately while CI continues to run.

### 5d. Address review comments

For EACH unresolved or unanswered comment identified in Step 5b:
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
5. Once all comments are addressed and replied to, commit the changes, push to the branch (re-running Steps 2–3 so the new commit lands on top of the latest base), and return to Step 5.

### 5e. Fix CI failures

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
5. Return to the top of the polling loop (Step 5).

### 5f-gate. CRITICAL GATE — Must pass before Step 6

**This gate cannot be skipped under any circumstances.**

Before proceeding to Step 5f or Step 6, you MUST:

1. **Fetch ALL line-level review comments one final time** using the same commands from Step 5b. Do not rely on cached results — new comments may have arrived since your last fetch.
2. **Verify every top-level comment has been replied to** by you (excluding comments from yourself, Claude, `github-actions[bot]`, or `vercel[bot]`).
3. **Verify every reviewer follow-up has been replied to.** Check that YOU are the last commenter in every thread. Review bots frequently reply to your reply — you must address their follow-up before the thread can be resolved.
4. **If ANY unreplied comment exists from a non-ignored author** (whether top-level OR follow-up), go back to Step 5d to address it. Do NOT proceed.
5. Only after confirming zero unreplied comments across all threads, continue to Step 5f.

### 5f. Verify all conversations are resolved AND resolve them on GitHub

Before declaring "Done", confirm that the PR can actually be merged. **Replying to a comment does NOT resolve the GitHub conversation thread.** You must explicitly resolve each thread via the GraphQL API.

1. **Check for reviewer follow-up replies you haven't addressed:**

Review bots (like CodeRabbit) often reply to YOUR reply with follow-up questions or confirmations. These follow-ups need your response too. Check for any comment from a non-ignored author that is the LAST message in its thread and has no reply from you after it:

```bash
# Get the full comment chain to identify threads where a reviewer spoke last
gh api repos/{owner}/{repo}/pulls/{number}/comments --jq '
  [.[] | {id, in_reply_to_id, login: .user.login}]'
```

For each thread, check if the last message is from a reviewer (not you). If so, reply to acknowledge or address it before proceeding.

2. **Resolve all review threads via GraphQL:**

First, find unresolved threads:
```bash
gh api graphql -f query='{
  repository(owner: "{owner}", name: "{repo}") {
    pullRequest(number: {number}) {
      reviewThreads(first: 50) {
        nodes { id isResolved comments(first: 1) { nodes { body author { login } } } }
      }
    }
  }
}' --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false) | .id'
```

Then resolve each unresolved thread:
```bash
gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "<thread_id>"}) { thread { isResolved } } }'
```

**Do this for EVERY unresolved thread.** Do NOT proceed until all threads show `isResolved: true`.

3. **Final verification:**
```bash
gh api graphql -f query='{
  repository(owner: "{owner}", name: "{repo}") {
    pullRequest(number: {number}) {
      reviewThreads(first: 50) {
        nodes { isResolved }
      }
    }
  }
}' --jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)] | length'
```

This must return `0`. If not, go back and resolve the remaining threads.

4. If all conversations are resolved, proceed to Step 6.

### 5g. Wait between polls

If CI is still running, wait 30 seconds before the next iteration:
```bash
sleep 30
```

Do not poll more than 60 times (i.e., ~30 minutes). If the limit is reached, inform the user that CI is taking too long and stop.

## Step 6: Report Success

When all CI checks are green and there are no unresolved review comments:
1. Print a summary:
   - Commit(s) pushed
   - PR URL
   - All checks passed
   - Any comments that were addressed
2. Inform the user that the push cycle is complete.
