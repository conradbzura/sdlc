---
name: review
description: >
  Review an open pull request, or a set of local file paths, for guide
  compliance, correctness, and code quality. Use this skill whenever the user
  says "review", "review PR #N", "review this PR", "review these files", or
  similar. In PR mode it fetches the diff and metadata; in paths mode it
  expands the supplied paths and globs against the working tree and reviews the
  matched files as they stand. Either way it runs one or more reviewer
  subagents per role (each confined to its role's mapped files), consolidates
  their findings into a single standardized local document under
  `.sdlc/reviews/`, and writes it for the user to drive fixups. Does not post
  to GitHub.
subagent:
  support: optional
  type: general-purpose
  artifacts:
    - review_document_path
    - verify_document_path
    - findings_count
    - pr_number
---

The key words MUST, MUST NOT, SHALL, SHALL NOT, SHOULD, SHOULD NOT, REQUIRED, RECOMMENDED, MAY, and OPTIONAL in this document are to be interpreted as described in RFC 2119.

# Review Skill

Review either a pull request's diff or a set of local file paths through one or more role lenses (N reviewers per role), consolidate the findings into a single standardized local review document under `.sdlc/reviews/`, and write it for the user to drive fixups. This skill writes a local document; it does NOT post to GitHub.

The arguments appended below select the **base mode** by carrying **exactly one** of two target directives:

- **PR mode** — a `Target PR: #<pr-number>` directive is present. Review the PR diff; the steps fetch metadata, the diff, and the branch commit map, and the document lands under `.sdlc/reviews/issue-#<N>/`.
- **PATHS mode** — a `Target paths:` directive is present. There is no PR, no diff, no linked issue, and no `Target repo` directive. Expand the listed literal paths and globs against the working tree and review each matched file's whole contents. The endpoint computes the document directory and injects it as `Review document directory: .sdlc/reviews/<slug>/`. Run no `gh` and post nothing.

A third, orthogonal axis layers on top of whichever base mode is active:

- **Verify mode** — a `Verify mode: review-<#>` directive is present (alongside the active PR-mode or paths-mode target). This is a **verification pass**, not a fresh review: the endpoint has already loaded the existing `review-<#>.md` for the target, rendered its findings into the appended block, and named the write target as `Verify document: <dir>/verify-<#>.md`. Instead of producing new findings, each reviewer judges each injected finding **Resolved** or **Unresolved** against the **current** file contents, and the document written is the verdict report. Verify mode keeps the base mode's target acquisition (PR head contents or paths-mode file contents), role lenses, and `guide-map.role` confinement; it changes steps 3, 7, 8, and 9–11 as marked **(verify mode)** below. When no `Verify mode` directive is present, ignore every **(verify mode)** marker and run the normal review.

Where a step below is marked **(PR mode)** or **(paths mode)** it applies only to that base mode; **(verify mode)** applies only when the verify directive is present (layered on whichever base mode is active); unmarked steps apply to all.

## Pipeline Context

This skill is part of the development workflow pipeline: `issue` → `implement` → `test` → `commit` → `pr` → `review`. This skill is the **sixth** stage, invoked after the PR has been created and is ready for review. Its output — the consolidated review document — is a local artifact under `.sdlc/reviews/` that you and the user read manually to drive fixups. It is NOT auto-consumed by the `implement` skill, and because nothing is posted to GitHub, a later `sdlc_implement` call routes to `implement-continue` (not `implement-feedback`) unless the user separately surfaces the findings.

## Composition

A review runs through one or more **roles**, with N **reviewers per role**. The arguments appended below this prompt supply the role list and the per-role reviewer count:

- **Roles** — the role stems to review through (default: a single `general-purpose` role). Each role is a named lens with a blocking policy, discoverable via `sdlc_roles` and readable at `sdlc://guides/role/<stem>`.
- **Reviewers per role** — N independent reviewer subagents per role (default: 1).

The total number of reviewer subagents is **N × (number of roles)**. Each reviewer reviews the same diff but through exactly one assigned role's lens, confined to the files that role is mapped to, and returns structured findings. The main session agent then consolidates all reviewers' findings into the single review document. A reviewer NEVER writes a file or posts anything — it only returns findings.

**(verify mode)** The same fan-out applies, but each reviewer is a **verifier**: it receives the subset of the injected `review-<#>.md` findings whose `Reference` falls in its in-scope files, and for each returns a **Resolved**/**Unresolved** verdict with evidence quoted from the current file — not new findings. The consolidator turns the verdicts into a verdict report rather than a finding list.

## Invariants

- MUST NOT post anything to GitHub. This skill produces a local document only — there is no `gh api .../reviews` call, no review event, and no inline comments. In **paths mode** the skill additionally runs no `gh` at all (no repo resolution, no PR fetch, no commit map).
- When the review proceeds to completion, MUST write exactly one consolidated document per invocation, at the endpoint-injected `Review document: <dir>/review-<iteration>.md` path (used verbatim), under the retained `Review document directory`. In PR mode `<dir>` is `.sdlc/reviews/issue-#<N>/` (`<N>` = the resolved linked issue); in paths mode `<dir>` is `.sdlc/reviews/<slug>/`, the endpoint-computed slug. The endpoint resolves `<iteration>` as the 1-based next unused iteration in both modes and injects the exact path, so the write never overwrites an earlier round. In PR mode the unresolved-issue branch (the PR has no linked issue) and the declined-large-diff branch may end without writing a document — no document is written when the run does not reach completion on those paths. (Both of those branches are PR-mode only; paths mode has no linked-issue resolution and no remote diff to decline.) **(verify mode)** The single document written is the verdict report at the injected `Verify document: <dir>/verify-<#>.md` instead — a verification pass never writes a `review-<iteration>.md`.
- In verify mode, MUST NOT write `verify-<#>.md` until the user has approved the verdicts, exactly as presented. The review (produce) document is written autonomously as the final step (step 10) and needs no approval gate.
- Each reviewer's findings MUST be confined to the files mapped to its role in `guide-map.role` (any file MAY be read for context). The default `general-purpose` role is mapped to `**/*`, so its findings span the whole diff.
- When consolidating, each finding MUST be assigned the **highest** severity any role gives it; where roles disagree, the dissent MUST be noted on the finding.
- For each finding, the consolidator MUST pre-select the recommended remediation option with `[x]`, list any alternatives with `[ ]`, and always include an `Other: ___` slot.
- MUST NOT fabricate guide requirements that do not exist in the project's actual guides.
- MUST use the `understand-chat` skill to query the knowledge graph for context gathering when `.understand-anything/knowledge-graph.json` exists.

## Arguments

The MCP endpoint appends the following below this skill prompt. **Exactly one** of `Target PR:` / `Target paths:` is present — it selects the mode:

- `Target PR: #<pr-number>` — *(PR mode)* the PR to review.
- `Target paths:` followed by the literal file paths and/or globs to review, one per line — *(paths mode)* the artifacts to review in place against the working tree. No PR, no diff, no linked issue.
- `Roles: <role-a>, <role-b>, …` — the role stems to review through (defaults to `general-purpose`). Same meaning in both modes.
- `Reviewers per role: <N>` — how many independent reviewers to run per role (defaults to 1). Same meaning in both modes.
- `Resolved issue: #<N>` — *(PR mode only)* the linked issue resolved by the endpoint via the `closingIssuesReferences` relationship (or an `unresolved` notice when the PR has no linked issue). Defines the `.sdlc/reviews/issue-#<N>/` path. Absent in paths mode.
- `Review document directory: .sdlc/reviews/<dir>/` — the directory holding this target's review rounds: `issue-#<N>/` in PR mode, or a slug derived deterministically from the raw `paths` strings in paths mode. In paths mode this line is always present (the endpoint computes the slug); in PR mode it is omitted on the `unresolved` branch. It is used to `mkdir -p` the review directory before writing. **(verify mode)** Always present (the endpoint resolved the directory to load `review-<#>.md` from it).
- `Review document: <dir>/review-<iteration>.md` — *(review/produce flow)* the exact, pre-resolved write target for this round. The endpoint resolved `<iteration>` as the next unused iteration deterministically (never overwriting an earlier round), so use this path verbatim as the write target; do NOT glob the directory to recompute it. Present in PR mode (on the resolved-issue branch) and in paths mode; omitted on the PR-mode `unresolved` branch. **(verify mode)** Absent — verify mode writes the `Verify document:` path instead.
- `Verify mode: review-<#>` — *(verify mode only)* marks the run as a verification pass of the existing `review-<#>.md`, present only when the user passed `--verify <#>`. Its presence is what switches the **(verify mode)** behavior on.
- `Verify document: <dir>/verify-<#>.md` — *(verify mode only)* the write target for the verdict report. It pairs 1:1 with `review-<#>.md` (same `<#>`); do NOT compute a new iteration in verify mode.
- The pre-rendered findings of `review-<#>.md` — *(verify mode only)* the endpoint appends the parsed findings of the review document being verified (a `Review document:` header line followed by the numbered findings). These are the findings each verifier judges Resolved/Unresolved; do NOT re-derive them from the file.
- The bundled review-document template (also available as the `sdlc://review-template` resource), which defines the exact structure of the document to write. **(verify mode)** Repurpose it: each finding block becomes a verdict block (Resolved/Unresolved + evidence) and the header carries a `Verification summary — <N> unresolved` line.

**(PR mode)** The tool output also carries a `Target repo: <id>` directive identifying the repository for `gh` commands that reference issues or PRs (the upstream `<owner>/<name>` when the current repo is a fork, otherwise the current repo). Consume it in step 1 rather than re-deriving the target repo. **In paths mode there is no `Target repo` directive** — paths mode runs no `gh`, so skip step 1 entirely.

## Subagent Execution (Optional)

This skill MAY itself be executed in an isolated orchestrator subagent to preserve parent context (distinct from the per-role reviewer subagents this skill spawns internally). When invoked with a `--subagent` flag, execute according to your tool:

**Claude Code:**
- MUST spawn a general-purpose subagent using the Agent tool with this brief:
  > You are executing the **`review`** skill from the SDLC pipeline (`issue` → `implement` → `test` → `commit` → `pr` → `review`).
  > 1. Read the project instructions in `AGENTS.md`
  > 2. Read and execute the complete workflow defined in this skill's markdown
  > 3. Follow every step faithfully, especially the Invariants section
  > 4. Return a structured summary: accomplishments, key artifacts (review document path — or the verify document path in verify mode, findings count or unresolved count, PR number), and the next pipeline step prompt from the skill

- When the subagent returns, reproduce its full output to the user exactly as written — do not summarize, condense, paraphrase, or omit sections. The user needs to review the complete output to give informed approval. Do not repeat work or add your own commentary.

**Other LLM assistants:**
- Subagent execution may not be supported in your tool. Execute the skill inline following the normal workflow.

## Workflow

### Checklist

1. Resolve target repository *(PR mode only)*
2. Acquire the review targets (PR diff + commit map, or the matched paths)
3. Resolve the review-document path
4. Read project guides and styles
5. Resolve each role's lens and mapped files
6. Gather knowledge graph context
7. Dispatch reviewer subagents (N per role)
8. Consolidate the findings
9. Finalize the consolidated document
10. Write the review document
11. Prompt the user with next steps

### 1. Resolve target repository *(PR mode)*

**In paths mode, skip this step** — there is no `Target repo` directive and no `gh` is run; go straight to step 2.

The MCP tool resolves the target repository once and appends a `Target repo: <id>` directive to this skill prompt. Consume it — do NOT run `gh repo view` to re-derive it:

- `Target repo: <owner>/<name>` — the current repo is a fork; `<owner>/<name>` is the upstream. All subsequent `gh` commands that reference issues or pull requests MUST include `--repo <owner>/<name>`.
- `Target repo: current repo — omit --repo …` — the current repo is the target; no `--repo` flag is needed.

If the directive is absent — which only happens when the tool could not reach `gh` — surface that `gh` is unavailable and STOP (or ask the user how to proceed). Every `gh` command in the steps below would fail for the same reason, so there is no actionable fallback; do not guess the target repo.

**User override:** If the user explicitly asks to target the fork — by saying "fork", "on the fork", "fork #N", or similar — the target repo MUST be set to the current (fork) repo instead of the injected upstream. The user's explicit intent always takes precedence over the injected directive.

All `gh` commands in subsequent steps that reference issues or PRs MUST include `--repo <target>` when the target repo differs from the current repo.

### 2. Acquire the review targets

The two base modes acquire different inputs for the reviewers. Follow the subsection for the base mode the appended arguments selected.

**(verify mode)** Acquire the **current** state exactly as the active base mode does — the PR head's changed-file contents in PR mode, or the matched files' whole contents in paths mode. Verifiers judge each finding's resolution against these current files, so this capture is mandatory; the injected `review-<#>.md` findings describe the *prior* state, not the state to read. (PR mode still verifies the local tree is at the PR head so the reviewers' reads line up with the recorded sha.)

#### PR mode — fetch the PR metadata, diff, and commit map

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

#### PATHS mode — expand the paths and capture file contents

There is no PR, no remote diff, and no commit map in this mode. Instead, expand the literal paths and globs from the `Target paths:` directive against the working tree and collect the files that match:

```bash
# For each entry under `Target paths:` — a literal file is itself; a glob expands.
# e.g. with shell globbing (nullglob), or `git ls-files -- <pattern>` to respect tracking:
git ls-files -- <each Target paths entry>
```

Resolve every entry: a literal path contributes that file (warn if it does not exist); a glob contributes every working-tree file it matches. Deduplicate the union into the **matched file set**. If the union is empty, see the "no files matched" edge case below.

**Capture each matched file's WHOLE contents** (not a diff) — this exact text is interpolated into each reviewer's brief in step 7 (reviewers are spawned into fresh contexts and do NOT inherit your reads). Skip binary files (note them to the user). There is no `headRefOid`, no PR-head verification, and no commit map: the reviewers review the artifacts exactly as they stand in the working tree, and step 8 omits all commit-attribution.

### 3. Resolve the review-document path

**(verify mode)** Skip the iteration computation entirely — the write target is the injected `Verify document: <dir>/verify-<#>.md` path, used verbatim. Verify pairs 1:1 with `review-<#>.md` (same `<#>`), so there is no new round to number; the endpoint already resolved the directory and named the file. (You still create the directory in step 10 if it does not exist.) The rest of this step — consuming the injected `Review document:` write target — applies only to a fresh (non-verify) review.

**The write target is injected — use it verbatim.** For the review/produce flow the endpoint appends a `Review document: <dir>/review-<iteration>.md` line that IS the exact path to write this round to. The endpoint resolved `<iteration>` as the next unused iteration deterministically (never overwriting an earlier round), so you do NOT glob the directory or compute `iteration = max + 1` yourself — take the injected path as-is. This holds in both base modes: in **PR mode** the injected path is `.sdlc/reviews/issue-#<N>/review-<iteration>.md`, and in **PATHS mode** it is `<Review document directory>/review-<iteration>.md` under the endpoint-computed slug directory (successive paths-mode reviews of the same target accumulate their rounds there). Do NOT create the directory or file yet — that happens in step 10.

**(PATHS mode)** There is no linked-issue resolution in this mode (skip the `<N>` discussion below); the injected `Review document:` line is all you need.

**(PR mode)** The remainder of this step resolves which `issue-#<N>/` directory the injected path names; paths mode is fully covered above.

**`<N>` — the linked issue — is resolved for you.** The MCP endpoint performs the relationship check via GitHub's `closingIssuesReferences` connection (issues that close when the PR merges, whether linked via a `Closes #N` keyword or the GitHub UI), with a `Closes` / `Fixes` / `Resolves #N` PR-body fallback. When several issues are linked, the endpoint resolves the **first** of them (the connection has no ordering guarantee), so `<N>` is one closing issue, not necessarily the only one. It appends the result below this prompt as `Resolved issue: #<N>`, together with the `Review document directory`. Use the provided `<N>` directly; do NOT re-derive it. If you can tell the PR closes more than one issue, surface a note to the user confirming the chosen `issue-#<N>/` directory before writing. If the appended directive reports the issue as **unresolved** (the PR has no linked issue), ask the user which issue the PR addresses before proceeding; do NOT guess the path.

**`<iteration>` — the 1-based review round — is resolved for you.** The endpoint has already scanned the issue's review directory and injected the next unused round as the `Review document: .sdlc/reviews/issue-#<N>/review-<iteration>.md` line; use that path verbatim as the write target. Do NOT `ls` the directory to recompute the iteration — the endpoint's resolution is deterministic and never overwrites an earlier round. Do NOT create the directory or file yet — that happens in step 10.

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

If the graph exists, MUST use the `understand-chat` skill with a query listing the file paths under review (the PR's changed files in PR mode, or the matched file set from step 2 in paths mode) to gather architectural context — component summaries, relationships, and layer assignments — that reveals how changed components fit into the broader architecture and informs review quality. If the graph does not exist, skip this step and continue. When a graph exists, pass the resulting summary to the reviewer subagents via the optional architectural-context slot in the step-7 brief (the reviewers do NOT inherit this `understand-chat` output otherwise); omit that slot when no graph exists.

### 7. Dispatch reviewer subagents (N per role)

For each role, spawn **N independent reviewer subagents** (N = reviewers per role). A reviewer reviews the artifacts (the PR diff in PR mode, or the matched files in paths mode) through exactly one role's lens and returns structured findings — it MUST NOT write any file or post anything.

**Claude Code:** Spawn each reviewer using the Agent tool. Run all reviewers concurrently where the tool allows. A reviewer is spawned into a fresh, isolated context: it inherits none of your reads, so every input it needs MUST be interpolated into its brief (replace each `<…>` placeholder with the actual value before spawning). Each reviewer's brief MUST include:

> You are a **reviewer** for the SDLC `review` skill, assigned the **`<role-stem>`** role.
> - Your lens and blocking policy: `<the role document body>`.
> - Your findings are confined to these files (matched from `guide-map.role`): `<the role's in-scope changed files>`. You MAY read any other file for context, but raise findings ONLY against your in-scope files.
> - Apply your role's blocking policy to classify each finding as **Blocking** or **Advisory**.
> - The artifacts under review — interpolate the slot for the active mode (include exactly one):
>   - **(PR mode)** The PR diff under review (full text): `<pr-diff>` — the `gh pr diff` output captured in step 2. Review THIS diff; do not infer the diff from whatever branch or working tree you happen to be on.
>   - **(PATHS mode)** The files under review, each as its whole current contents (no diff): for each matched file from step 2, `<file-path>` followed by `<the file's full contents>`. Review these artifacts as they stand in the working tree — there is no PR, no diff, and no base to compare against.
> - The project guides to review against (full text): `<AGENTS.md body + the body of each resolved test and style guide from step 4>`. Cite guide rules only from this text — do NOT fabricate requirements that are not in it.
> - Architectural context for the files under review (when a knowledge graph exists): `<the understand-chat summary from step 6>`. *(Omit this bullet entirely when no knowledge graph exists.)*
> - **(PR mode)** Read each in-scope changed file from the local checkout, which is at the PR head `<sha>` (the orchestrator verified this in step 2); if a changed file is a test, also read the module it tests (and vice versa). **(PATHS mode)** Your in-scope files' whole contents are supplied above; you MAY read any other file for context, and if an in-scope file is a test, also read the module it tests (and vice versa). Drop the PR-head / `<sha>` wording in paths mode — there is no PR head.
> - Investigate through your assigned lens: apply the focus areas your role's lens / blocking policy defines above. **Only** when your role is `general-purpose` (or its document does not enumerate its own focus) fall back to the generic checklist: guide compliance (cite the specific MUST / SHALL / SHOULD rule), naming and convention drift, coverage regressions (new public APIs without tests, removed tests without justification), correctness bugs (logic errors, race conditions, missing error handling at boundaries, incorrect API use), and code quality (unnecessary complexity, dead code, duplicated logic). Do not pull yourself off your lens to chase items the generic list names but your role does not.
> - Return **structured findings only** — for each: a short title, severity, a reference, the issue with concrete evidence, a recommended remediation (and any alternatives), and optional tests-to-add. The reference is `file:line` when a single line applies; otherwise use a file-level reference (`<file>`) or a cross-cutting one (`(cross-cutting — no single line)`; in PR mode an issue-level `issue acceptance criterion #<n>` is also available). Omissions and file-spanning architectural concerns are first-class findings even without a line — raise them. **(PR mode only)** Do NOT attribute a commit sha — the orchestrator owns commit attribution in step 8. *(In paths mode there are no commits to attribute, so there is nothing to omit here.)* Do NOT write a file, do NOT post to GitHub, do NOT consolidate — return your raw findings to the orchestrator.

**(verify mode)** Each reviewer is a **verifier** rather than a finder. It keeps its role lens and `guide-map.role` confinement, but instead of hunting for new defects it judges the resolution of the injected `review-<#>.md` findings. Replace the "Investigate through your assigned lens" and "Return structured findings only" bullets above with this verifier brief:

> - You are **verifying** an earlier review, not producing a new one. You are assigned the **`<role-stem>`** role and confined to these in-scope files (matched from `guide-map.role`): `<the role's in-scope files>`.
> - The findings to verify — the subset of `review-<#>.md` whose `Reference` falls in your in-scope files: `<the injected findings for this role's files>`. (Findings outside your in-scope files belong to other verifiers; ignore them.)
> - For EACH assigned finding, read the **current** contents of the referenced file and judge it **Resolved** or **Unresolved** through your role lens:
>   - **Resolved** — the remediation the finding calls for is present in the current file. Quote the concrete evidence (the changed text / the now-correct symbol) that shows it was addressed.
>   - **Unresolved** — the defect is still present (the remediation is absent or only partially applied). Quote the concrete evidence in the current file that shows it remains.
> - Return **per-finding verdicts only** — for each assigned finding: its id, the verdict (Resolved/Unresolved), and the quoted evidence from the current file. Do NOT raise new findings, do NOT write a file, do NOT post to GitHub, do NOT consolidate — return your verdicts to the orchestrator.

**Other LLM assistants:** If subagents are unavailable, perform each role's review (or, in verify mode, each role's verification) inline, one role at a time, holding each role's findings or verdicts separately so they can be consolidated in step 8.

### 8. Consolidate the findings

**(verify mode)** The main session agent consolidates **verdicts**, not new findings — one row per original `review-<#>.md` finding, in the original order. For each finding, fold in the verifier verdict(s) for it: when more than one verifier judged the same finding (N>1 reviewers on a role, or overlapping roles), any **Unresolved** verdict makes the consolidated verdict **Unresolved** (a single dissent that the defect remains gates resolution); record the per-verdict evidence. Compute the **unresolved count** — the number of findings whose consolidated verdict is Unresolved. Reuse the bundled `review-template.md`, repurposing each finding block into a verdict block (the finding's id / title / reference, its **Resolved**/**Unresolved** verdict, and the quoted evidence) and adding a `Verification summary — <N> unresolved` line to the header. There is no severity re-tiering, no remediation pre-selection, no commit attribution, and no fixup mapping in a verdict report — drop those template slots. Then skip the remaining (fresh-review) bullets in this step and go to step 9.

The main session agent (NOT a reviewer) merges every reviewer's findings into one set:

- **Dedup within a role** — collapse findings from the same role that name the same defect at the same reference into a single finding, recording the reviewer agreement (e.g. `4/5 reviewers`).
- **Merge across roles** — combine findings about the same defect raised by different roles into one entry that records every role that raised it.
- **Highest severity wins** — assign each finding the highest severity any role gave it. Where roles disagree (one rated it Blocking, another Advisory or did not raise it), NOTE the dissent on the finding.
- **Assign stable IDs** — `B1, B2, …` for blocking findings, `A1, A2, …` for advisory, in a stable order.
- **Pre-select remediation** — for each finding, choose the recommended remediation and mark it `[x]`, list reasonable alternatives as `[ ]`, and always append an `Other: ___` slot.
- **Group by severity tier, blocking first** — Tier 1 (Blocking) then Tier 2 (Advisory).
- **(PR mode) Attribute each finding to a commit** — using the **branch commit map** built in step 2, match each finding's `file:line` (or file-level reference) against the commit that touched that file to set its `Touched commit`. The consolidator owns this attribution; do not rely on any sha from a reviewer (the reviewers were told not to supply one). A finding with no single file (cross-cutting / issue-level) maps to the commit(s) most responsible, or is grouped under the relevant commit in the fixup mapping with a note. **(PATHS mode) Skip this bullet entirely** — there is no commit map, so findings carry no `Touched commit`.
- Populate the document header and fill the **cross-cutting decisions** section, following the bundled template appended below this prompt exactly. **(PR mode)** The header carries roles used, reviewers per role, target HEAD sha, dedup approach, severity legend, and the branch commit map from step 2; also fill the **fixup mapping** section. **(PATHS mode)** The header carries roles used, reviewers per role, dedup approach, and severity legend, and identifies the reviewed paths in place of the PR / HEAD-sha / Closes line; **omit the branch-commit-map line, every finding's `Touched commit`, and the entire fixup-mapping section** — none of them have meaning without a PR. Keep the severity tiers, stable IDs, references, evidence, and remediation checklists exactly as in PR mode.

Severity definitions (the raising role's blocking policy is authoritative — the MUST/SHALL gloss is one common example, not the definition, since a role's policy need not be phrased in MUST/SHALL terms):

- **Blocking** — a defect that MUST be resolved before the PR can be approved per the raising role's blocking policy (for example, a violation of a MUST / SHALL guide rule, or a correctness defect on a consequential path).
- **Advisory** — clarity, consistency, or quality observations that do not gate approval per that policy (for example, SHOULD / MAY observations or optional improvements).

### 9. Finalize the consolidated document

Render the full consolidated document and present it to the user as informational — the review (produce) document is written autonomously as the final step (step 10), so there is no approval gate to clear before writing. Presenting it gives the user visibility into what was found and a chance to steer follow-up: they MAY

- **Remove** any finding they disagree with.
- **Edit** the text, reference, or remediation options of any finding.
- **Add** new findings the reviewers missed.
- **Change** the severity of any finding (re-tiering it).
- **Re-select** which remediation option is recommended.

Fold any such adjustments into the document, then proceed straight to writing it in step 10 — do not block on an explicit "approved" from the user.

**(verify mode)** Present the verdict report instead — the per-finding Resolved/Unresolved verdicts with their evidence and the `Verification summary — <N> unresolved` line. The same approval gate applies: the user MAY override a verdict (flip Resolved/Unresolved), correct the evidence, or adjust the unresolved count before anything is written. Do NOT write `verify-<#>.md` until the user approves.

### 10. Write the review document

As the final step, create the directory (the injected `Review document directory` — `.sdlc/reviews/issue-#<N>/` in PR mode, `.sdlc/reviews/<slug>/` in paths mode) and write the document autonomously — no approval gate:

```bash
mkdir -p <Review document directory>
```

Write the consolidated document to the injected `Review document: <dir>/review-<iteration>.md` path verbatim (the endpoint resolved the next unused iteration; the `mkdir -p` above uses the retained `Review document directory` line), following the bundled template structure exactly: the header, the severity-tiered findings (blocking first) with stable IDs / titles / severities / `Reference` (`file:line`, or a file-level / issue-level reference for a line-less finding) / Issue + evidence / Remediation checklist (`[x]` recommended, `[ ]` alternatives, `Other: ___`) / optional Tests-to-add, plus the cross-cutting-decisions section. **(PR mode)** also include each finding's `Touched commit` and the fixup-mapping section; **(paths mode)** omit both (no commits exist to attribute or fold into). Do NOT post anything to GitHub.

**(verify mode)** Create the directory if needed (`mkdir -p <Review document directory>`) and write the approved **verdict report** to the injected `Verify document: <dir>/verify-<#>.md` path — NOT a `review-<iteration>.md`. The report carries the `Verification summary — <N> unresolved` header line and one verdict block per original finding (id / title / reference, Resolved/Unresolved, quoted evidence), with the severity-tier / remediation / commit / fixup slots dropped as covered in step 8. Do NOT post anything to GitHub.

### 11. Prompt the user with next steps

After the document is written, prompt the user. **(PR mode):**

> Review written to `.sdlc/reviews/issue-#<N>/review-<iteration>.md`. This document is a local artifact — nothing was posted to GitHub, and the `implement` skill does not read it automatically. Read it yourself (or with the user) and use each finding's pre-selected remediation and fixup-mapping entry as the work list, applying the fixups directly; then re-run `commit`, `pr`, and `review` as needed. When the findings are resolved and you are satisfied, run `gh pr ready <number>` to mark the PR ready for merge.

**(PATHS mode):**

> Review written to `<Review document directory>/review-<iteration>.md`. This document is a local artifact — nothing was posted to GitHub, and the `implement` skill does not read it automatically. Read it yourself (or with the user) and use each finding's pre-selected remediation as the work list, applying the fixups directly to the reviewed files; then re-run `review` over the same paths as needed. There is no PR or fixup mapping in this mode.

**(verify mode):** After writing `verify-<#>.md`, prompt based on the unresolved count:

> Verification of `review-<#>.md` written to `<dir>/verify-<#>.md` — `<N>` unresolved. Nothing was posted to GitHub.

- When `<N>` > 0: 
  > `<N>` finding(s) remain unresolved. Re-enter the implement loop to address them: `sdlc_implement <target> --review <#>` (the same target you verified, with the review iteration `<#>`). After fixing, re-run this verify pass to confirm.
- When `<N>` == 0: 
  > All findings are resolved — review round `<#>` is verified complete. In PR mode you may now mark the PR ready (`gh pr ready <number>`); in paths mode the reviewed artifacts are clean for this round.

DO NOT proceed on your own.

## Edge Cases

**Paths mode runs no `gh` and posts nothing:** In paths mode the skill performs no repo resolution, no PR fetch, and no commit-map enumeration — there is no GitHub interaction at all. The document lands under the endpoint-computed `.sdlc/reviews/<slug>/` directory. The PR-only edge cases below (`PR is already merged or closed`, `No linked issue`, and `Very large diffs`) do not apply in paths mode.

**No files matched the paths/globs (paths mode):** If expanding the `Target paths:` entries against the working tree yields no files (every literal path is missing and every glob matches nothing), inform the user that nothing matched, list the entries you tried, and stop — there is nothing to review and no document is written. If only some entries are empty, note the misses and proceed with the files that did match.

**PR is already merged or closed (PR mode):** Inform the user that the PR is not open and stop.

**No findings:** If every reviewer returns clean, present the empty-findings document (header plus empty severity tiers) as informational (step 9) and write it autonomously (step 10) so the round is recorded; inform the user that no issues were found and the target looks clean. There is no approval gate on the review (produce) document — the empty-findings document is written the same way a document with findings is. Do not post anything.

**Verify target has no review document (verify mode):** This is raised upstream by the tool before this skill runs — when the target has no `review-<#>.md` (the directory is absent or that iteration is missing), `sdlc_review --verify <#>` raises a `ValueError` and the skill is never dispatched. You will not reach this skill with a missing review document, so there is no in-skill fallback to handle; the user sees the tool's error and runs a fresh `review` first.

**All findings resolved (verify mode):** If every verifier judges its findings Resolved, the verdict report has zero unresolved. Present it for approval as in step 9 and, after approval, write `verify-<#>.md` with the `Verification summary — 0 unresolved` line and the all-Resolved verdict blocks, then give the `<N>` == 0 next-step prompt (round verified complete). The report is still written so the verification is recorded.

**No linked issue (PR mode — the endpoint reports `Resolved issue: unresolved`):** Ask the user which issue the PR addresses; do not guess the `.sdlc/reviews/issue-#<N>/` path. *(Paths mode has no linked issue and uses the injected `<slug>` directory, so this never arises there.)*

**Unknown / misspelled role:** A requested role with no discovered document (not among `sdlc_roles`, or whose `sdlc://guides/role/<stem>` read returns `Error: guide ... not found`) MUST halt the run with a corrective prompt asking the user to fix the role name. Do NOT dispatch a reviewer with an empty or error lens.

**A role exists but has no `guide-map.role` entry:** `sdlc_role_scope` returns empty for it just as it does for an unmapped role. Warn the user the role will contribute nothing (it is not scoped to any files), then skip it.

**A role maps to globs that match none of the reviewed files:** Note in the header that the discovered, mapped role had no in-scope files on this target (the PR's changed files, or paths mode's matched files) and skip its reviewers; it contributes no findings.

**Binary files:** Binary files MUST be skipped during analysis — in both the PR diff and a paths-mode match. Note their presence to the user but do not attempt to review them.

**Very large diffs (PR mode):** For PRs with more than 20 changed files or more than 1000 lines changed, the agent SHOULD summarize the scope to the user and ask whether to review the full diff or focus on specific files before dispatching reviewers. *(This is PR-mode only — paths mode reviews exactly the files the user named.)*

**Files outside the repository's guide coverage:** If reviewed files are in a language or domain not covered by any project guide, review them for general correctness and code quality only. Do not fabricate guide requirements that do not exist.
