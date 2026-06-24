---
name: implement-feedback
description: >
  Address the findings recorded in a local review document for an open
  pull request. Invoked by the `sdlc_implement` MCP endpoint when a local
  `.sdlc/reviews/issue-#<N>/review-<iteration>.md` document is selected —
  the latest iteration by default, an explicit `--review <int>` iteration,
  or a document freshly converted from a `--review <pr-url>`. Walks through
  findings sequentially with per-finding evaluation, approval, and
  fixup-commit guidance.
subagent:
  support: optional
  type: general-purpose
  artifacts:
    - branch_name
    - pr_url
    - pr_number
    - findings_addressed
---

The key words MUST, MUST NOT, SHALL, SHALL NOT, SHOULD, SHOULD NOT, REQUIRED, RECOMMENDED, MAY, and OPTIONAL in this document are to be interpreted as described in RFC 2119.

# Implement Feedback Skill

Walk through the findings in a local review document systematically, one finding at a time, with per-finding evaluation and approval gates. Generate ready-to-execute fixup-commit commands after each remediation; do not auto-commit.

## Pipeline Context

This skill is part of the development workflow pipeline: `issue` → `implement` → `test` → `commit` → `pr` → `review`. The `sdlc_implement` MCP endpoint dispatches between three sibling prompts based on PR state and the `--review` selector — this skill is returned when a local review document is selected: the latest `.sdlc/reviews/issue-#<N>/review-<iteration>.md` for the closing issue (the default when one exists), an explicit `--review <int>` iteration, or a document just converted from a `--review <pr-url>`. Fresh-start work is routed to the `implement` skill; mid-implementation continuation with no local review document is routed to the `implement-continue` skill.

## Implementation Notes

This skill does **not** use the structured planning interface (`EnterPlanMode` for Claude Code, structured-plan-text for other LLM assistants). Instead, each finding gets its own inline mini-plan and approval gate during the sequential walkthrough. Reserve the planning interface for end-to-end implementation tasks; per-finding remediation works better as a conversational loop.

## Invariants

- MUST verify the server-supplied finding enumeration by re-reading the LOCAL review document the endpoint named before walking through findings.
- MUST order findings by the canonical severity sequence (correctness → code quality → integration tests → unit tests → style → docs), within which the document's own blocking-before-advisory tiering is honored.
- MUST track findings as a todo list, one task per finding, kept visible to the user.
- MUST present findings sequentially. For each finding the agent MUST restate the finding with its `Reference` (which may be `file:line`, a whole-file path, or an issue-level reference), evaluate correctness/relevance, present the document's pre-selected `[x]` remediation as the recommended option (alongside any alternatives), and wait for explicit user approval before editing.
- MUST NOT auto-commit. After each approved remediation, MUST emit a copy-paste-able `git commit --fixup=<sha>` block mapping each touched file back to the commit on the branch that owns that surface. The agent MUST NOT execute these commands.
- MUST prompt the user to run `sdlc_commit` when they are ready to commit the accumulated remediations.
- MUST NOT proceed to the next pipeline step autonomously.
- MUST use the `understand-chat` skill to query the knowledge graph for context gathering when `.understand-anything/knowledge-graph.json` exists.

## Arguments

The MCP endpoint supplies a rendered review-document block appended below this skill prompt. The block carries the source document path (`.sdlc/reviews/issue-#<N>/review-<iteration>.md`), the issue number, the iteration, and the enumerated findings — each with its id, severity, `Reference`, title, issue, and pre-selected remediation, ordered blocking before advisory. The document was selected by the `--review` argument: the latest iteration by default, an explicit `--review <int>` iteration, or a document just converted from a `--review <pr-url>` (in which case each finding carries a generic pre-selected "address the reviewer's comment" remediation that the user disambiguates per finding). The agent MUST treat the rendered block as a starting point and re-read the named local document (step 3) to confirm completeness before walking through findings. The endpoint also appends a `Target repo: <id>` directive identifying the repository for `gh` commands that reference issues or PRs (the upstream `<owner>/<name>` when the current repo is a fork, otherwise the current repo); consume it in step 1 rather than re-deriving the target repo.

## Subagent Execution (Optional)

This skill MAY be executed in an isolated subagent to preserve parent context. When invoked with a `--subagent` flag, execute according to your tool:

**Claude Code:**
- MUST spawn a general-purpose subagent using the Agent tool with this brief:
  > You are executing the **`implement-feedback`** skill from the SDLC pipeline (`issue` → `implement` → `test` → `commit` → `pr` → `review`).
  > 1. Read the project instructions in `AGENTS.md`
  > 2. Read and execute the complete workflow defined in this skill's markdown
  > 3. Follow every step faithfully, especially the Invariants section
  > 4. Return a structured summary: accomplishments, findings addressed, fixup-commit commands emitted, and the next pipeline step prompt from the skill

- When the subagent returns, reproduce its full output to the user exactly as written — do not summarize, condense, paraphrase, or omit sections. The user needs to review the complete output to give informed approval. Do not repeat work or add your own commentary.

**Other LLM assistants:**
- Subagent execution may not be supported in your tool. Execute the skill inline following the normal workflow.

## Workflow

### Checklist

1. Resolve target repository
2. Check out the PR branch
3. Verify findings
4. Order findings by severity
5. Track findings as a todo list
6. Gather context
7. Walk through findings sequentially
8. Emit fixup commands after each remediation
9. Prompt the user to run `sdlc_commit`

### 1. Resolve target repository

The MCP tool resolves the target repository once and appends a `Target repo: <id>` directive to this skill prompt. Consume it — do NOT run `gh repo view` to re-derive it. `Target repo: <owner>/<name>` means the current repo is a fork and `gh` commands referencing issues or PRs MUST include `--repo <owner>/<name>`; `Target repo: current repo …` means no `--repo` flag is needed. If the directive is absent — which only happens when the tool could not reach `gh` — surface that `gh` is unavailable and STOP (or ask the user how to proceed). Every `gh` command in the steps below would fail for the same reason, so there is no actionable fallback; do not guess the target repo.

**User override:** If the user explicitly asks to target the fork — by saying "fork", "on the fork", "fork #N", or similar — the target repo MUST be set to the current (fork) repo instead of the injected upstream. The user's explicit intent always takes precedence over the injected directive.

All `gh` commands in subsequent steps that reference issues or PRs MUST include `--repo <target>` when the target repo differs from the current repo.

### 2. Check out the PR branch

The appended block names the closing issue `#<N>` but not the PR branch, so resolve the PR that closes `#<N>` and check out its head branch. Find the linked PR and read its head ref:

```bash
gh pr list --repo <target> --search "Closes #<N>" --json number,headRefName --jq '.[0]'
```

(Omit `--repo <target>` when the target is the current repo, per step 1.)

Then fetch and check out that branch:

```bash
git fetch origin <branch> && git checkout <branch>
```

If the working tree has uncommitted changes that would conflict with the checkout, stop and ask the user how to proceed. If no open PR closes `#<N>` (the review document predates the PR being reopened, or the branch was deleted), stop and ask the user which branch to work on.

### 3. Verify findings

The server-supplied enumeration is the starting point but MUST be verified against its source — the LOCAL review document named in the appended block. Read it in full:

```bash
cat .sdlc/reviews/issue-#<N>/review-<iteration>.md
```

This is a local artifact `sdlc_review` (or a `--review <pr-url>` conversion) wrote; nothing is re-queried from GitHub. The document is the authoritative finding set for this round — there is no GitHub `isResolved` state to consult, because the review was never posted to GitHub.

The findings are recorded in the document under two severity tiers and BOTH MUST be enumerated:

- **Tier 1 — Blocking** — defects that MUST be resolved before approval per the raising role's blocking policy.
- **Tier 2 — Advisory** — clarity, consistency, or quality observations that do not gate approval; the user elects which to fix.

Each finding carries a stable id, a `Reference` (a `file:line` citation, a whole-file path, or an issue-level reference for line-less findings), an `Issue` section with evidence, and a `Remediation` checklist whose pre-selected `[x]` option is the consolidator's recommendation. If re-reading the document surfaces findings the rendered block abbreviated or omitted, work from the document — it is the source of truth.

### 4. Order findings by severity

Sort the verified findings by the canonical severity sequence so downstream remediations may be obviated by upstream fixes:

1. Correctness bugs in source
2. Code quality / hygiene in source
3. Test issues — integration tests
4. Test issues — unit tests
5. Stylistic issues
6. Documentation issues

**Rationale:** A correctness fix may rewrite the surface a quality finding targeted, and a source-code rename may invalidate a doc finding verbatim. Front-loading impact prevents wasted churn.

### 5. Track findings as a todo list

Create one task per finding so the user can see progress. The task description SHOULD include the finding's id and `Reference` and a short summary so each task is self-contained when read out of context.

### 6. Gather context

Before walking through findings, MUST read enough of the codebase to evaluate them confidently:

- MUST check whether `.understand-anything/knowledge-graph.json` exists. If it does, MUST use the `understand-chat` skill with a query synthesized from the highest-severity finding to gather architectural context. If the graph does not exist, skip this bullet and continue.
- MUST read source files named in any finding's `Reference` (the file in a `file:line` or whole-file reference; the region the issue text points to for an issue-level reference).
- MUST read existing tests for the affected modules.
- MUST resolve applicable test guides by calling `sdlc_guides_for` with the candidate or referenced source-file paths and `kind="test"`, then read every returned URI to internalize the relevant testing conventions.
- MUST read project-level instructions (`AGENTS.md`) for build tooling, documentation style, and architecture context.

### 7. Walk through findings sequentially

For each finding, in severity order:

1. **Restate the finding** with its `Reference` (which may be a `file:line` citation, a whole-file path, or an issue-level reference such as `issue acceptance criterion #3`), its id, and its `Issue` text. Mark the corresponding todo as in-progress.
2. **Evaluate correctness/relevance.** The consolidated review can be wrong or out of date. Read the code at the cited reference (or, for an issue-level reference, the relevant region). State whether the finding is valid, partially valid, or stale, and explain why.
3. **Present the document's pre-selected remediation** as the recommended option. The `[x]`-marked option in the finding's `Remediation` checklist is the consolidator's recommendation; surface it as such, list any `[ ]` alternatives and the `Other:` slot, and call out which you would pick grounded in the PR's objectives. For a document converted from a `--review <pr-url>`, the pre-selected remediation is a generic "address the reviewer's comment" — restate the underlying GitHub comment and propose a concrete fix for the user to confirm.
4. **Wait for explicit user approval** before editing. Allow the user to push back, ask clarifying questions, or pick a different option (including `Other:`). The agent MUST NOT edit any file before approval is given.
5. **Implement the approved option.** Edit only the files in scope of the approved option.
6. **Mark the todo complete** after the user confirms the remediation looks right (or after step 8's fixup-command block has been emitted, whichever the user prefers).

### 8. Emit fixup commands after each remediation

After each approved remediation, map every touched file back to the commit on the branch that owns that surface, and emit a copy-paste-able block of `git commit --fixup=<sha>` commands. To find the owning commit:

```bash
git log --oneline main..HEAD -- <touched-file>
```

The most recent commit touching the file is usually the right target. Include the target commit's subject as a trailing comment so the user can sanity-check the mapping:

```bash
git add path/to/touched/file.py
git commit --fixup=<sha>      # <commit subject as appears in git log>
```

**Fixup vs new commit:** Prefer `git commit --fixup=<sha>` when the remediation touches code that already belongs to an existing commit on the branch. An autosquash rebase later folds these in cleanly. Net-new commits are warranted ONLY when the remediation introduces an entirely new subsystem, feature, or concept. If the remediation *replaces* something already in a prior commit, fixup that prior commit instead.

The agent MUST NOT execute these commands. The user reviews and runs them.

### 9. Prompt the user to run `sdlc_commit`

Once all findings have been remediated (or the user chooses to stop early), do NOT auto-commit. Prompt the user with the next pipeline step:

> Ready to commit the remediations? Run the `commit` skill (`sdlc_commit`) to stage and commit the changes; an autosquash rebase against `main` will fold the fixups into their owning commits. Then re-run `sdlc_pr` to update the PR description.

DO NOT proceed on your own.

## Edge Cases

- **Branch checkout fails (uncommitted changes):** Stop and ask the user how to handle the conflict.
- **Branch checkout fails (missing remote ref):** Stop and report the situation; the supplied branch name may be stale.
- **Reviewer's intent is ambiguous:** Ask the user to clarify before proposing solutions; do not guess.
- **Finding is already addressed by an earlier remediation in this session:** Mark the corresponding todo complete with a note (e.g., "obviated by remediation of finding #1") and move on.
- **Finding is obviated by a newer review iteration:** If a later `review-<iteration>.md` exists that supersedes the selected one, surface the discrepancy and ask the user which iteration to work from; do not silently merge them.
- **No file owns the touched surface (entirely new code):** A net-new commit is appropriate. Emit `git commit -m "<subject>"` instead of a fixup, with a recommended subject in the conventional-commit style.
