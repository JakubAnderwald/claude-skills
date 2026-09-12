---
name: push
description: Commit all changes, push to remote, wait for CI/CD and review comments, and resolve any issues in a loop until everything passes.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
user-invocable: true
---

# /push — Commit, Push, Wait for CI/CD & Reviews, Fix, Repeat

Follow these steps precisely. Do NOT skip the polling loop.

> **The contract this skill enforces:** every review thread blocks the merge. Address each
> one — fix it, or decide no change is needed — then reply on the thread saying which and
> why, and resolve it. **Never resolve a thread you did not act on.** There is no step in
> this skill that resolves threads in bulk, and you must not invent one.

## Step 1: Stage & Commit

1. Run `git status` and `git diff` to review all pending changes (staged and unstaged).
2. Stage all changes: `git add -A`.
3. Create a commit with a concise, descriptive message summarizing the changes. Use conventional-commit style if the repo already uses it. If your environment mandates a commit attribution footer (Claude Code supplies the current one), append exactly that — do not hardcode a model name here, it goes stale.
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

> A rebase moves the lines review threads are anchored to. Threads that no longer point at
> live code come back from Step 5b with `isOutdated: true` — that is a *disposition* you can
> use in Step 5d, not permission to skip them.

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

Resolve these once, before the loop, and reuse them throughout:

```bash
read -r OWNER REPO <<<"$(gh repo view --json owner,name --jq '.owner.login + " " + .name')"
NUM=$(gh pr view --json number --jq .number)
ME=$(gh api user --jq .login)
WORK="${TMPDIR:-/tmp}/pr-review-$NUM"; mkdir -p "$WORK"
```

**Never write scratch files into the repo.** Step 1 runs `git add -A`, so anything you drop
in the working tree gets committed on the next iteration. Everything transient goes in
`$WORK`.

Two `gh` gotchas that bite here:

- `{owner}` and `{repo}` are real `gh api` placeholders and are substituted from the current
  repo — but `{number}` is **not**, and none of the three work inside a GraphQL query body.
  Use `"$OWNER"`, `"$REPO"`, `"$NUM"` explicitly so one convention covers both APIs.
- **REST and GraphQL report bot logins differently.** REST returns `coderabbitai[bot]`;
  GraphQL strips the suffix and returns `coderabbitai`. Never reuse a login filter across the
  two.

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

### 5b. Fetch review threads and comments (EVERY iteration)

**IMPORTANT:** You MUST fetch on EVERY poll iteration, not just when all checks are green. Review bots frequently post comments while their check status is still PENDING. If you skip fetching while waiting for checks, you waste time that could be spent addressing already-posted feedback.

**GraphQL `reviewThreads` is the only authority on what blocks the merge.** `isResolved` is
the real state; REST reply IDs are not a proxy for it, in either direction. A thread can
carry replies and still be unresolved, and a thread can be marked resolved having never been
answered at all.

**1. Unresolved review threads — the blocking set:**

```bash
gh api graphql -f owner="$OWNER" -f repo="$REPO" -F number="$NUM" -f query='
query($owner:String!,$repo:String!,$number:Int!){
  repository(owner:$owner,name:$repo){ pullRequest(number:$number){
    reviewThreads(first:100){ nodes{
      id isResolved isOutdated path line
      comments(first:50){ nodes{ author{login} body } } } } } }
}' --jq '[.data.repository.pullRequest.reviewThreads.nodes[]
          | select(.isResolved == false)
          | {id, path, line, isOutdated,
             lastAuthor: (.comments.nodes | last | .author.login),
             comments: [.comments.nodes[] | {author: .author.login, body}]}]' \
  > "$WORK/threads.json"
jq 'length' "$WORK/threads.json"
```

- **No author filter.** Every unresolved thread blocks, whoever opened it. That is the point.
- Full bodies, not truncated first lines — a CodeRabbit finding's heading tells you nothing
  about what it wants.
- `lastAuthor` replaces the old "did a reviewer speak last?" heuristic. If it is not you, the
  thread needs your answer; if it is you and the thread is still unresolved, you replied and
  forgot to resolve.
- If this returns exactly 100, the page is full — re-query with `after:` and a cursor rather
  than silently reviewing a truncated set.

**2. General PR comments** (issue comments — no thread concept, so track answered state with
a marker you write yourself in Step 5d):

```bash
# piped to real jq, not `gh api --jq`, because only jq proper takes --arg
gh api --paginate "repos/$OWNER/$REPO/issues/$NUM/comments" | jq --arg me "$ME" '
  ([.[].body | scan("<!-- addressed:([0-9]+) -->") | .[0]]) as $done
  | [.[] | select(.user.login != $me)
         | select((.id|tostring) as $i | $done | index($i) | not)
         | {id, login: .user.login, body}]' > "$WORK/issue-comments.json"
jq 'length' "$WORK/issue-comments.json"
```

**3. Reviews requesting changes:**

```bash
gh api "repos/$OWNER/$REPO/pulls/$NUM/reviews" --jq '
  [.[] | select(.state == "CHANGES_REQUESTED" or (.state == "COMMENTED" and (.body | length) > 0))
   | {login: .user.login, state}]'
```

### 5c. Decide what to do

| All Checks Status | Open threads | Unanswered PR comments | Action |
|-------------------|--------------|------------------------|--------|
| Any still running | >0 | any | Address threads immediately (Step 5d), then continue polling — do NOT wait idle when there is work to do |
| Any still running | 0 | >0 | Answer them (Step 5d.6), then continue polling |
| Any still running | 0 | 0 | Wait 30 seconds, then poll again (Step 5g) |
| All green | >0 | any | Address threads (Step 5d), then push and re-poll |
| All green | 0 | >0 | Answer them (Step 5d.6), then push and re-poll |
| All green | 0 | 0 | Verify (Step 5f), then go to Step 6 |
| Any failed | any | any | Fix failures (Step 5e), then push and re-poll |

Green CI with open threads is never a "go to Step 6" row.

**IMPORTANT:** "Any still running" means ANY check — including review bots like CodeRabbit. Never treat a PENDING check as complete just because it has been pending for a long time. Always wait for every check to reach a terminal state (SUCCESS, FAILURE, CANCELLED, or SKIPPED). However, do NOT sit idle while waiting for checks if there is already feedback posted. Address it while CI continues to run.

### 5d. Address review threads — one at a time, reply then resolve

Work through `$WORK/threads.json` **thread by thread** — `TID` below is that thread's
`.id`, and it is the only id involved:

```bash
jq -r '.[].id' "$WORK/threads.json"   # one TID per unresolved thread
```

For each:

1. **Read every comment body in the thread**, in full — not the first line, not just the
   opening comment. Then read the code it points at (`path`:`line`).

2. **Pick exactly one disposition:**
   - **fixed** — make the change.
   - **no change needed** — with a concrete technical reason. "Acknowledged", "good catch",
     or "will address separately" are not dispositions.
   - **outdated** — only when `isOutdated` is true **and** the code it anchors to is genuinely
     gone. Name the commit that superseded it.
   - **needs the user** — the fix is a design decision or the comment is ambiguous. Use
     `AskUserQuestion`. Do **not** reply, do **not** resolve, leave the thread open.

3. **Reply on that exact thread**, saying which disposition and why:
   ```bash
   gh api graphql -f threadId="$TID" -f body="$BODY" -f query='
   mutation($threadId:ID!,$body:String!){
     addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$threadId,body:$body}){
       comment{ url } } }'
   ```

4. **Only then resolve that same id:**
   ```bash
   gh api graphql -f threadId="$TID" -f query='
   mutation($threadId:ID!){
     resolveReviewThread(input:{threadId:$threadId}){ thread{ isResolved } } }'
   ```

> 🚫 **Never pass a thread id to `resolveReviewThread` that you did not pass to
> `addPullRequestReviewThreadReply` in this same run.** Never loop over "all unresolved
> ids". Resolving a thread is your statement that you read it and acted on it; a thread
> resolved with no reply is indistinguishable from feedback thrown away, and defeats
> `required_conversation_resolution` entirely.

Reply and resolve take the **same** `threadId`, so there is no REST-comment-id mapping to get
wrong — stay in GraphQL for both.

5. Once the threads are handled, commit the changes, push (re-running Steps 2–3 so the new
   commit lands on top of the latest base), and return to Step 5.

6. **General PR comments** from `$WORK/issue-comments.json` have no thread to resolve. Answer
   each with a new issue comment whose body ends with a marker naming the comment you are
   answering, so Step 5b can tell answered from unanswered on the next iteration:
   ```bash
   CID=<the comment id you are answering>   # from $WORK/issue-comments.json
   gh api "repos/$OWNER/$REPO/issues/$NUM/comments" \
     -f body="$(printf '%s\n\n<!-- addressed:%s -->' "$REPLY_TEXT" "$CID")"
   ```

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

### 5f. Verify — observe, do not act

**This step takes no mutating action.** It re-reads the state and decides whether Step 6 is
allowed. If it finds work outstanding, the answer is to go back to Step 5d or to stop and
tell the user — never to resolve anything here.

1. **Re-run Step 5b query 1.** Do not reuse the earlier result; new comments arrive while you
   work.

2. **Count what is still open:**
   ```bash
   jq 'length' "$WORK/threads.json"
   ```

3. **If the count is not `0`,** those are threads you deliberately left open (the
   **needs the user** disposition) or threads that arrived since your last pass:
   - Newly arrived → back to Step 5d.
   - Waiting on the user → **report them and stop.** Print each as `path:line — <why it is
     open>`, and tell the user the PR cannot merge until they are answered.
   - **Do not resolve them to make the count zero.** That is the failure mode this step
     exists to prevent.

4. **Check nothing is waiting on you elsewhere:** `$WORK/issue-comments.json` must be empty,
   and no review may be in `CHANGES_REQUESTED`.

5. Only with zero open threads, zero unanswered PR comments, and no `CHANGES_REQUESTED`,
   proceed to Step 6.

### 5g. Wait between polls

If CI is still running and there is nothing to address, wait 30 seconds before the next iteration:
```bash
sleep 30
```

Do not poll more than 60 times (i.e., ~30 minutes). If the limit is reached, inform the user that CI is taking too long and stop.

## Step 6: Report Success

When all CI checks are green and every review thread is genuinely resolved:
1. Print a summary:
   - Commit(s) pushed
   - PR URL
   - All checks passed
   - Each review thread addressed, with its disposition (fixed / no change needed / outdated)
   - Any threads left open and why (if any — in which case this is not a success report)
2. Inform the user that the push cycle is complete.
