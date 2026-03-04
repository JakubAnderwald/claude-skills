---
name: ralph-plan
description: Convert a Claude plan into a Ralph-loop compatible implementation plan
disable-model-invocation: true
argument-hint: [plan-file-path] [output-file-path]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
user-invocable: true
---

# /ralph-plan — Convert Plan to Ralph Loop Format

You are converting a Claude plan-mode plan into a Ralph-loop compatible implementation plan. Follow these instructions exactly.

## Step 1: Parse Arguments

- `$ARGUMENTS` contains up to two space-separated paths: `[plan-file-path] [output-file-path]`
- If no plan file path is provided, search for the most recent `.md` plan file in the project's `docs/` directory or ask the user.
- If no output file path is provided, derive one from the plan title as `docs/<kebab-case-title>-plan.md`.

## Step 2: Read the Source Plan

Read the plan file. Identify:
- The plan title and context/summary
- All phases, tasks, and subtasks
- Any architectural decisions, file lists, or key notes
- Any parallelization notes

## Step 3: Generate the Ralph-Loop Plan

Write the output file with this EXACT structure:

### 3a. Header

```markdown
# <Plan Title> — Implementation Plan (Ralph Loop Edition)

## Context

<Preserve/summarize the original plan's context and goals. Include what changes and what stays the same if applicable.>

---
```

### 3b. Ralph Loop Rules

Insert this EXACT block (do not modify):

```markdown
**RALPH LOOP RULES (STRICT):**
You are running in an autonomous, unattended loop. On every single execution, you MUST follow these exact steps in order:

1. **Identify:** Scan the Progress Tracker below and find the _first_ unchecked task `[ ]`.
2. **Scope:** DO NOT attempt multiple tasks. Focus ONLY on that single task.
3. **Implement:** Write the code to satisfy the task's requirements.
4. **Test**: Run the full test suite strictly in CI mode to prevent interactive prompts or watch-mode hangs. Execute exactly this chain: CI=true pnpm test -- --run && CI=true pnpm test:e2e && pnpm lint && pnpm exec tsc --noEmit.
5. **Fix:** If _any_ test or check fails, you must debug, fix the code, and re-run the suite until it is 100% green. Do not proceed until all tests pass.
6. **Record:** Check off the task in this file by changing `[ ]` to `[x]`.
7. **Commit:** Commit and push your changes to git with a descriptive message using the /push protocol. Merge changes to main if CI checks are all resolved and comments replied to.
8. **Exit:** EXIT immediately so the loop can restart with a fresh context window. DO NOT start the next task.

---
```

### 3c. Progress Tracker

```markdown
## Progress Tracker

### Phase N: <Phase Name>

- [ ] N.1 — <task description>
- [ ] N.2 — <task description>
- [ ] N-CP — **Checkpoint**: full suite green
- [ ] N-PUSH — **Push**: `/push` to PR
```

Rules for the Progress Tracker:
- Every task is a checkbox: `- [ ] N.M — description`
- Use sub-letters for related subtasks: `N.Ma`, `N.Mb` (e.g., `1.1a`, `1.1b`)
- Every phase MUST end with two special tasks:
  - `N-CP — **Checkpoint**: full suite green` (optionally add specific verification notes)
  - `N-PUSH — **Push**: \`/push\` to PR`
- Task descriptions should be concise but specific — include what is being built and what tests are needed (e.g., `Login page + tests`, `Notes API routes (CRUD) + unit tests`)
- Keep the tracker compact — details go in the Phase Details section below

### 3d. Key Architectural Decisions (optional)

If the plan includes architectural decisions or important constraints, add:

```markdown
## Key Architectural Decisions

- **Decision name**: description
```

### 3e. Phase Details

For each phase, add a detailed section:

```markdown
## Phase N: <Phase Name>

**Goal:** <one-line goal>

### N.1 — <Task Title>

**Files:** `path/to/file.ts`, `path/to/other.ts`

<Detailed implementation instructions, requirements, and constraints.>

**Tests:**
- Unit: `description of unit tests`
- Integration: `description of integration tests`
- E2E: `description of e2e tests` (if applicable)
```

Rules for Phase Details:
- Include file paths where known
- Include test requirements for each task
- Include code snippets or patterns if the source plan has them
- Keep instructions actionable — an autonomous agent must be able to implement each task from these instructions alone

### 3f. Parallelization Table (optional)

If tasks within a phase can be parallelized, add:

```markdown
## Parallelization

| Group | Tasks | Why parallel |
|-------|-------|-------------|
| A     | N.1a, N.1b | Independent components |
```

### 3g. Additional Sections (optional)

Preserve any additional useful sections from the source plan:
- New Files Summary
- Test Breakage Risk
- Migration notes
- Dependency notes

## Step 4: Write the Output

Write the generated plan to the output file path. Report the file path to the user.

## Important Notes

- Phases should be ordered so each builds on the previous — foundational work first (schema, config, infrastructure), features next, polish last.
- If the source plan has no clear phases, create logical groupings (e.g., "Foundation", "Core Feature", "Testing & Polish").
- Each task should be completable in a single autonomous loop iteration — if a task is too large, split it.
- Aim for 3-8 tasks per phase (excluding CP and PUSH).
- The output should be self-contained — an agent reading only this file should understand what to build and how.
