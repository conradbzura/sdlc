---
name: review
description: >
  Review an open pull request for guide compliance, correctness, and code
  quality. Use this skill whenever the user says "review", "review PR #N",
  "review this PR", or similar. Fetches the PR diff and metadata, runs one or
  more reviewer subagents per role (each confined to its role's mapped files),
  consolidates their findings into a single standardized local document under
  `.sdlc/reviews/`, and presents it. Does not post to GitHub.
subagent:
  support: optional
  type: general-purpose
  artifacts:
    - review_document_path
    - findings_count
    - pr_number
---

The key words MUST, MUST NOT, SHALL, SHALL NOT, SHOULD, SHOULD NOT, REQUIRED, RECOMMENDED, MAY, and OPTIONAL in this document are to be interpreted as described in RFC 2119.

# Review Skill

Fetch a pull request, review its diff through one or more role lenses (N reviewers per role), consolidate the findings into a single standardized local review document under `.sdlc/reviews/`, and present it for the user to drive fixups. This skill writes a local document; it does NOT post to GitHub.

## Pipeline Context

This skill is part of the development workflow pipeline: `issue` → `implement` → `test` → `commit` → `pr` → `review`. This skill is the **sixth** stage, invoked after the PR has been created and is ready for review. Its output — the consolidated review document — is a local artifact under `.sdlc/reviews/` that you and the user read manually to drive fixups. It is NOT auto-consumed by the `implement` skill, and because nothing is posted to GitHub, a later `sdlc_implement` call routes to `implement-continue` (not `implement-feedback`) unless the user separately surfaces the findings.

## Composition

A review runs through one or more **roles**, with N **reviewers per role**. The arguments appended below this prompt supply the role list and the per-role reviewer count:

- **Roles** — the role stems to review through (default: a single `general-purpose` role). Each role is a named lens with a blocking policy, discoverable via `sdlc_roles` and readable at `sdlc://guides/role/<stem>`.
- **Reviewers per role** — N independent reviewer subagents per role (default: 1).

The total number of reviewer subagents is **N × (number of roles)**. Each reviewer reviews the same diff but through exactly one assigned role's lens, confined to the files that role is mapped to, and returns structured findings. The main session agent then consolidates all reviewers' findings into the single review document. A reviewer NEVER writes a file or posts anything — it only returns findings.

## Invariants

- MUST NOT post anything to GitHub. This skill produces a local document only — there is no `gh api .../reviews` call, no review event, and no inline comments.
- When the review proceeds to completion, MUST write exactly one consolidated document per invocation, at `.sdlc/reviews/issue-#<N>/review-<iteration>.md`, where `<N>` is the resolved linked issue and `<iteration>` is the 1-based next iteration. The unresolved-issue branch (the PR has no linked issue) and the declined-large-diff branch may end without writing a document — no document is written when the run does not reach completion on those paths.
- MUST NOT write the document until the user has approved the consolidated findings, exactly as presented.
- Each reviewer's findings MUST be confined to the files mapped to its role in `guide-map.role` (any file MAY be read for context). The default `general-purpose` role is mapped to `**/*`, so its findings span the whole diff.
- When consolidating, each finding MUST be assigned the **highest** severity any role gives it; where roles disagree, the dissent MUST be noted on the finding.
- For each finding, the consolidator MUST pre-select the recommended remediation option with `[x]`, list any alternatives with `[ ]`, and always include an `Other: ___` slot.
- MUST NOT fabricate guide requirements that do not exist in the project's actual guides.
- MUST use the `understand-chat` skill to query the knowledge graph for context gathering when `.understand-anything/knowledge-graph.json` exists.

## Arguments

The MCP endpoint appends the following below this skill prompt:

- `Target PR: #<pr-number>` — the PR to review.
- `Roles: <role-a>, <role-b>, …` — the role stems to review through (defaults to `general-purpose`).
- `Reviewers per role: <N>` — how many independent reviewers to run per role (defaults to 1).
- `Resolved issue: #<N>` — the linked issue resolved by the endpoint via the `closingIssuesReferences` relationship (or an `unresolved` notice when the PR has no linked issue). Defines the `.sdlc/reviews/issue-#<N>/` path.
- `Review document directory: .sdlc/reviews/issue-#<N>/` — the directory holding this PR's review rounds.
- The bundled review-document template (also available as the `sdlc://review-template` resource), which defines the exact structure of the document to write.

## Subagent Execution (Optional)

This skill MAY itself be executed in an isolated orchestrator subagent to preserve parent context (distinct from the per-role reviewer subagents this skill spawns internally). When invoked with a `--subagent` flag, execute according to your tool:

**Claude Code:**
- MUST spawn a general-purpose subagent using the Agent tool with this brief:
  > You are executing the **`review`** skill from the SDLC pipeline (`issue` → `implement` → `test` → `commit` → `pr` → `review`).
  > 1. Read the project instructions in `AGENTS.md`
  > 2. Read and execute the complete workflow defined in this skill's markdown
  > 3. Follow every step faithfully, especially the Invariants section
  > 4. Return a structured summary: accomplishments, key artifacts (review document path, findings count, PR number), and the next pipeline step prompt from the skill

- When the subagent returns, reproduce its full output to the user exactly as written — do not summarize, condense, paraphrase, or omit sections. The user needs to review the complete output to give informed approval. Do not repeat work or add your own commentary.

**Other LLM assistants:**
- Subagent execution may not be supported in your tool. Execute the skill inline following the normal workflow.

## Workflow

### Checklist

1. Resolve target repository
2. Fetch the PR metadata, diff, and commit map
3. Resolve the review-document path
4. Read project guides and styles
5. Resolve each role's lens and mapped files
6. Gather knowledge graph context
7. Dispatch reviewer subagents (N per role)
8. Consolidate the findings
9. Present the consolidated document for approval
10. Write the review document
11. Prompt the user with next steps

### 1. Resolve target repository

```bash
gh repo view --json isFork,parent
```

If `isFork` is `true`, extract `parent.owner.login` and `parent.name` to form the upstream repo identifier (`<owner>/<name>`). This upstream identifier becomes the **target repo** for all subsequent `gh` commands that reference issues or pull requests. If the repo is not a fork, the target repo is the current repo and no `--repo` flag is needed.

**User override:** If the user explicitly asks to target the fork — by saying "fork", "on the fork", "fork #N", or similar — the target repo MUST be set to the current (fork) repo instead of upstream. The user's explicit intent always takes precedence.

All `gh` commands in subsequent steps that reference issues or PRs MUST include `--repo <target>` when the target repo differs from the current repo.

### 2. Fetch the PR metadata, diff, and commit map

```bash
gh pr view <number> --repo <target> --json title,body,headRefName,baseRefName,changedFiles,headRefOid
gh pr diff <number> --repo <target>
```

If the PR does not exist, inform the user and stop. Parse the PR title, body, branch names, the list of changed files, and `headRefOid` (the target HEAD sha recorded in the document header). The `--repo <target>` flag ensures commands operate against the upstream repo when working from a fork (as resolved in step 1). If the target repo is the current repo, the flag MAY be omitted.

**Capture the diff text** returned by `gh pr diff` — this exact text is interpolated into each reviewer's brief in step 7 (the reviewers are spawned into fresh contexts and do NOT inherit this read).

**Verify the local working tree is at the PR head.** The diff above comes from the remote, but reviewers read the changed files from the local filesystem, so the recorded `headRefOid` and the lines they read must correspond:

```bash
git rev-parse HEAD
```

If `HEAD` does not equal `headRefOid`, the local tree is not on the PR head (stale branch, different worktree, or dirty tree) and the `file:line` references would be off. Fetch and check out the PR head (`gh pr checkout <number> --repo <target>`, or `git fetch` + checkout of `headRefOid`), or — if you cannot or the user declines — warn the user that the recorded `<sha>` assumes the working tree is at the PR head and that references may drift.

**Build the branch commit map.** The header commit map, each finding's `Touched commit`, and the fixup mapping all need each commit's sha, conventional-commit subject, and touched files. No earlier step supplies these, so enumerate them now from the PR's commit range:

```bash
git log <baseRefName>..<headRefName> --name-only --pretty=format:'%h %s'
```

(or `gh pr view <number> --repo <target> --json commits` combined with the `--name-only` log). This yields the per-commit `(<sha>, <conventional-commit subject>, <touched files>)` tuples. Hold this **branch commit map** for use in step 8: it fills the header commit map, attributes each finding's `file:line` to the commit that owns that file, and builds the fixup mapping. Do NOT improvise shas — derive them from this command.

### 3. Resolve the review-document path

The document lives at `.sdlc/reviews/issue-#<N>/review-<iteration>.md`.

**`<N>` — the linked issue — is resolved for you.** The MCP endpoint performs the relationship check via GitHub's `closingIssuesReferences` connection (issues that close when the PR merges, whether linked via a `Closes #N` keyword or the GitHub UI), with a `Closes` / `Fixes` / `Resolves #N` PR-body fallback. When several issues are linked, the endpoint resolves the **first** of them (the connection has no ordering guarantee), so `<N>` is one closing issue, not necessarily the only one. It appends the result below this prompt as `Resolved issue: #<N>`, together with the `Review document directory`. Use the provided `<N>` directly; do NOT re-derive it. If you can tell the PR closes more than one issue, surface a note to the user confirming the chosen `issue-#<N>/` directory before writing. If the appended directive reports the issue as **unresolved** (the PR has no linked issue), ask the user which issue the PR addresses before proceeding; do NOT guess the path.

**Resolve `<iteration>` — the 1-based review round.** Inspect the issue's review directory for existing rounds:

```bash
ls .sdlc/reviews/issue-#<N>/review-*.md 2>/dev/null
```

`<iteration>` is one greater than the highest `<n>` among existing `review-<n>.md` files. If the directory does not exist or contains no `review-*.md`, `<iteration>` is `1`. The target document path is therefore `.sdlc/reviews/issue-#<N>/review-<iteration>.md`. Do NOT create the directory or file yet — that happens in step 10, after approval.

### 4. Read project guides and styles

MUST read the following files to establish the review baseline:

- `AGENTS.md` — project-level instructions, architecture context, docstring conventions.
- Resolve applicable test guides by calling `sdlc_guides_for` with the changed test-file paths and `kind="test"`. Read every returned URI.
- Resolve applicable style guides by calling `sdlc_guides_for` with the changed file paths and `kind="style"`. Read every returned URI.

Only the guides relevant to the changed files are returned by the resolver — no manual filtering required. If `sdlc_guides_for` returns an empty list for a kind, no guide of that kind applies to the diff.

### 5. Resolve each role's lens and mapped files

**Validate the role list first.** Call `sdlc_roles` to list the discovered roles. Every supplied role stem MUST appear among them. If a stem is not a discovered role — or if reading its document at `sdlc://guides/role/<stem>` returns a string beginning with `Error: guide ... not found` — the role does not exist (likely a typo). In that case you MUST stop and ask the user to correct the role name; do NOT brief a reviewer with the error text as its lens. (`sdlc://config/default` is the unmerged package default; do not treat it as the live merged map.)

For every validated role in the role list:

- Read the role document at `sdlc://guides/role/<stem>` to obtain its **lens / identity** and **blocking policy**.
- Determine the **files the role's findings are confined to** by calling `sdlc_role_scope(<the PR's changed files>, "<stem>")`. This returns the changed files in scope for the role — it performs the `guide-map.role` reverse lookup over the server's already-merged config (default deep-merged with `.sdlc/config.json`) and applies the `pathlib.PurePath.full_match` matching for you, so you do NOT re-derive the merge or the glob match by hand. The default `general-purpose` role maps to `**/*`, so every changed file is in scope.

Distinguish the two empty-scope cases: an empty result for a **discovered** role means it maps to none of this PR's changed files (it has nothing to review here — note it in the header and skip dispatching reviewers for it). A role with **no `guide-map.role` entry at all** also returns empty; warn the user it will contribute nothing before skipping it. (An unknown / misspelled stem was already rejected by the validation above.)

### 6. Gather knowledge graph context

MUST check whether a knowledge graph exists:

```bash
test -f .understand-anything/knowledge-graph.json && echo "exists" || echo "missing"
```

If the graph exists, MUST use the `understand-chat` skill with a query listing the changed file paths from the PR diff to gather architectural context — component summaries, relationships, and layer assignments — that reveals how changed components fit into the broader architecture and informs review quality. If the graph does not exist, skip this step and continue. When a graph exists, pass the resulting summary to the reviewer subagents via the optional architectural-context slot in the step-7 brief (the reviewers do NOT inherit this `understand-chat` output otherwise); omit that slot when no graph exists.

### 7. Dispatch reviewer subagents (N per role)

For each role, spawn **N independent reviewer subagents** (N = reviewers per role). A reviewer reviews the diff through exactly one role's lens and returns structured findings — it MUST NOT write any file or post anything.

**Claude Code:** Spawn each reviewer using the Agent tool. Run all reviewers concurrently where the tool allows. A reviewer is spawned into a fresh, isolated context: it inherits none of your reads, so every input it needs MUST be interpolated into its brief (replace each `<…>` placeholder with the actual value before spawning). Each reviewer's brief MUST include:

> You are a **reviewer** for the SDLC `review` skill, assigned the **`<role-stem>`** role.
> - Your lens and blocking policy: `<the role document body>`.
> - Your findings are confined to these files (matched from `guide-map.role`): `<the role's in-scope changed files>`. You MAY read any other file for context, but raise findings ONLY against your in-scope files.
> - Apply your role's blocking policy to classify each finding as **Blocking** or **Advisory**.
> - The PR diff under review (full text): `<pr-diff>` — the `gh pr diff` output captured in step 2. Review THIS diff; do not infer the diff from whatever branch or working tree you happen to be on.
> - The project guides to review against (full text): `<AGENTS.md body + the body of each resolved test and style guide from step 4>`. Cite guide rules only from this text — do NOT fabricate requirements that are not in it.
> - Architectural context for the changed files (when a knowledge graph exists): `<the understand-chat summary from step 6>`. *(Omit this bullet entirely when no knowledge graph exists.)*
> - Read each in-scope changed file from the local checkout, which is at the PR head `<sha>` (the orchestrator verified this in step 2); if a changed file is a test, also read the module it tests (and vice versa).
> - Investigate through your assigned lens: apply the focus areas your role's lens / blocking policy defines above. **Only** when your role is `general-purpose` (or its document does not enumerate its own focus) fall back to the generic checklist: guide compliance (cite the specific MUST / SHALL / SHOULD rule), naming and convention drift, coverage regressions (new public APIs without tests, removed tests without justification), correctness bugs (logic errors, race conditions, missing error handling at boundaries, incorrect API use), and code quality (unnecessary complexity, dead code, duplicated logic). Do not pull yourself off your lens to chase items the generic list names but your role does not.
> - Return **structured findings only** — for each: a short title, severity, a reference, the issue with concrete evidence, a recommended remediation (and any alternatives), and optional tests-to-add. The reference is `file:line` when a single changed line applies; otherwise use a file-level reference (`<file>`) or an issue-level one (`(cross-cutting — no single line)` / `issue acceptance criterion #<n>`). Issue-level omissions (something the PR missed) and diff-spanning architectural concerns are first-class findings even without a line — raise them. Do NOT attribute a commit sha (the orchestrator owns commit attribution in step 8). Do NOT write a file, do NOT post to GitHub, do NOT consolidate — return your raw findings to the orchestrator.

**Other LLM assistants:** If subagents are unavailable, perform each role's review inline, one role at a time, holding each role's findings separately so they can be consolidated in step 8.

### 8. Consolidate the findings

The main session agent (NOT a reviewer) merges every reviewer's findings into one set:

- **Dedup within a role** — collapse findings from the same role that name the same defect at the same reference into a single finding, recording the reviewer agreement (e.g. `4/5 reviewers`).
- **Merge across roles** — combine findings about the same defect raised by different roles into one entry that records every role that raised it.
- **Highest severity wins** — assign each finding the highest severity any role gave it. Where roles disagree (one rated it Blocking, another Advisory or did not raise it), NOTE the dissent on the finding.
- **Assign stable IDs** — `B1, B2, …` for blocking findings, `A1, A2, …` for advisory, in a stable order.
- **Pre-select remediation** — for each finding, choose the recommended remediation and mark it `[x]`, list reasonable alternatives as `[ ]`, and always append an `Other: ___` slot.
- **Group by severity tier, blocking first** — Tier 1 (Blocking) then Tier 2 (Advisory).
- **Attribute each finding to a commit** — using the **branch commit map** built in step 2, match each finding's `file:line` (or file-level reference) against the commit that touched that file to set its `Touched commit`. The consolidator owns this attribution; do not rely on any sha from a reviewer (the reviewers were told not to supply one). A finding with no single file (cross-cutting / issue-level) maps to the commit(s) most responsible, or is grouped under the relevant commit in the fixup mapping with a note.
- Populate the document header (roles used, reviewers per role, target HEAD sha, dedup approach, severity legend, and the branch commit map from step 2), and fill the **cross-cutting decisions** and **fixup mapping** sections, following the bundled template appended below this prompt exactly.

Severity definitions (the raising role's blocking policy is authoritative — the MUST/SHALL gloss is one common example, not the definition, since a role's policy need not be phrased in MUST/SHALL terms):

- **Blocking** — a defect that MUST be resolved before the PR can be approved per the raising role's blocking policy (for example, a violation of a MUST / SHALL guide rule, or a correctness defect on a consequential path).
- **Advisory** — clarity, consistency, or quality observations that do not gate approval per that policy (for example, SHOULD / MAY observations or optional improvements).

### 9. Present the consolidated document for approval

Render the full consolidated document and present it to the user before writing anything. The user MUST be given the opportunity to:

- **Remove** any finding they disagree with.
- **Edit** the text, reference, or remediation options of any finding.
- **Add** new findings the reviewers missed.
- **Change** the severity of any finding (re-tiering it).
- **Re-select** which remediation option is recommended.

The document MUST NOT be written until the user explicitly approves the final consolidated set, exactly as it will be written.

### 10. Write the review document

After approval, create the directory and write the document:

```bash
mkdir -p .sdlc/reviews/issue-#<N>
```

Write the approved consolidated document to `.sdlc/reviews/issue-#<N>/review-<iteration>.md`, following the bundled template structure exactly: the header, the severity-tiered findings (blocking first) with stable IDs / titles / severities / `Reference` (`file:line`, or a file-level / issue-level reference for a line-less finding) / Issue + evidence / Remediation checklist (`[x]` recommended, `[ ]` alternatives, `Other: ___`) / optional Tests-to-add / Touched commit, and the cross-cutting-decisions and fixup-mapping sections. Do NOT post anything to GitHub.

### 11. Prompt the user with next steps

After the document is written, prompt the user:

> Review written to `.sdlc/reviews/issue-#<N>/review-<iteration>.md`. This document is a local artifact — nothing was posted to GitHub, and the `implement` skill does not read it automatically. Read it yourself (or with the user) and use each finding's pre-selected remediation and fixup-mapping entry as the work list, applying the fixups directly; then re-run `commit`, `pr`, and `review` as needed. When the findings are resolved and you are satisfied, run `gh pr ready <number>` to mark the PR ready for merge.

DO NOT proceed on your own.

## Edge Cases

**PR is already merged or closed:** Inform the user that the PR is not open and stop.

**No findings:** If every reviewer returns clean, present the empty-findings document (header plus empty severity tiers) for approval as in step 9, and only after the user approves, write it so the round is recorded; inform the user that no issues were found and the PR looks ready. The approval gate still applies on the clean path — do not write before approval. Do not post anything.

**No linked issue (the endpoint reports `Resolved issue: unresolved`):** Ask the user which issue the PR addresses; do not guess the `.sdlc/reviews/issue-#<N>/` path.

**Unknown / misspelled role:** A requested role with no discovered document (not among `sdlc_roles`, or whose `sdlc://guides/role/<stem>` read returns `Error: guide ... not found`) MUST halt the run with a corrective prompt asking the user to fix the role name. Do NOT dispatch a reviewer with an empty or error lens.

**A role exists but has no `guide-map.role` entry:** `sdlc_role_scope` returns empty for it just as it does for an unmapped role. Warn the user the role will contribute nothing (it is not scoped to any files), then skip it.

**A role maps to globs that match none of the changed files:** Note in the header that the discovered, mapped role had no in-scope files on this PR and skip its reviewers; it contributes no findings.

**Binary files in diff:** Binary files MUST be skipped during analysis. Note their presence to the user but do not attempt to review them.

**Very large diffs:** For PRs with more than 20 changed files or more than 1000 lines changed, the agent SHOULD summarize the scope to the user and ask whether to review the full diff or focus on specific files before dispatching reviewers.

**Files outside the repository's guide coverage:** If changed files are in a language or domain not covered by any project guide, review them for general correctness and code quality only. Do not fabricate guide requirements that do not exist.
