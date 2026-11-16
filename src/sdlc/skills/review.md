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
  `.sdlc/reviews/`, and writes it for the user to drive fixups. `--verify <#>`
  layers a re-review on either mode: the review's latest round is seeded into
  the reviewers and the result is written as the NEXT round, a new file beside
  the earlier ones, which are never modified. Each round records the code
  state it reviewed in a small metadata file. Runs no git commit and does not
  post to GitHub.
subagent:
  support: optional
  type: general-purpose
  artifacts:
    - review_document_path
    - review_metadata_path
    - review_round
    - findings_count
    - blocking_count
    - incidental_count
    - findings_closed
    - findings_rejected
    - findings_added
    - findings_carried_unexamined
    - uncovered_roles
    - pr_number
---

The key words MUST, MUST NOT, SHALL, SHALL NOT, SHOULD, SHOULD NOT, REQUIRED, RECOMMENDED, MAY, and OPTIONAL in this document are to be interpreted as described in RFC 2119.

# Review Skill

Review either a pull request's diff or a set of local file paths through one or more role lenses (N reviewers per role), consolidate the findings into a single standardized local review document under `.sdlc/reviews/`, and write it for the user to drive fixups. This skill writes a local document; it does NOT post to GitHub.

The arguments appended below select the **base mode** by carrying **exactly one** of two target directives:

- **PR mode** — a `Target PR: #<pr-number>` directive is present. Review the PR diff; the steps fetch metadata, the diff, and the branch commit map, and the document lands under `.sdlc/reviews/issue-#<N>/`.
- **PATHS mode** — a `Target paths:` directive is present. There is no PR, no diff, no linked issue, and no `Target repo` directive. Expand the listed literal paths and globs against the working tree and review each matched file's whole contents. The endpoint computes the document directory and injects it as `Review document directory: .sdlc/reviews/<slug>/`. Run no `gh` and post nothing.

<!-- rereview:begin -->
A third, orthogonal axis layers on top of whichever base mode is active:

- **Re-review** — a `Re-review: review-<#>` directive is present (alongside the active PR-mode or paths-mode target). This is an ordinary review **seeded with an existing round's findings**, not a different kind of pass: the endpoint has already loaded the latest round of review `<#>` for the target, rendered its findings into the appended block, and named the NEXT round — a new file — as the write target. Each reviewer reviews the current files exactly as it would on a fresh round — dispatched with the seeded findings withheld entirely, so it forms its own findings before it has seen them — and is then sent the seeded set and reconciles, returning a disposition for each seeded finding: **close** it (the remediation is present), **reject** it (it does not hold up as written), or **carry** it (it still stands). The seeding is context for that reconciliation, not a worklist to walk. Each round is a new version of the same review, written beside the earlier ones rather than over them, so the files together are the record of how the review evolved and no round re-derives findings already agreed. A re-review keeps the base mode's target acquisition (PR head contents or paths-mode file contents), role lenses, and `guide-map.role` confinement; it changes every step marked **(re-review)** below — there are several, and they are not confined to the consolidation steps, so read the markers rather than a list here. When no `Re-review` directive is present, ignore every **(re-review)** marker and run a fresh review.

<!-- rereview:end -->
Where a step below is marked **(PR mode)** or **(paths mode)** it applies only to that base mode; unmarked steps apply to all.
A step or clause marked **(re-review)** applies only when the `Re-review` directive is present, layered on whichever base mode is active. A fresh round is not given those steps at all, so a marker that OPENS a step, bullet or command block should never reach one; an inline clause inside a rule both modes need is left unfenced deliberately, and several do survive here.

Every round — fresh or re-review — is its own file: `review-<#>.md` for round 1 and `review-<#>.<k>.md` for each round after it. **No round is ever overwritten and nothing is committed** — this skill runs no `git commit`, and whether `.sdlc/reviews/` is tracked anywhere is the project's business. A round records what it closed and why in its own **Closed this round** ledger, so the reason for every state change lives in the documents rather than in a history beside them.

## Pipeline Context

This skill is part of the development workflow pipeline: `issue` → `implement` → `test` → `commit` → `pr` → `review`. Its output — the consolidated review document — is a local artifact under `.sdlc/reviews/`.

*Why: `sdlc://review-rationale` §R1 — read it if you are unsure how this document reaches the implement loop.*

## Composition

A review runs through one or more **roles**, with N **reviewers per role**. The arguments appended below this prompt supply the role list and the per-role reviewer count:

- **Roles** — the role stems to review through (default: a single `general-purpose` role). Each role is a named lens with a blocking policy, discoverable via `sdlc_roles` and readable at `sdlc://guides/role/<stem>`.
- **Reviewers per role** — N independent reviewer subagents per role (default: 1).

The total number of reviewer subagents is **N × (number of roles)**. Each reviewer reviews the same diff but through exactly one assigned role's lens, confined to the files that role is mapped to, and returns structured findings. The main session agent then consolidates all reviewers' findings into the single review document. A reviewer NEVER writes a file or posts anything — it only returns findings.

<!-- rereview:begin -->
**(re-review)** The same fan-out applies, and every reviewer stays a reviewer, but each is dispatched in two turns. The first carries the ordinary fresh-round brief and no seeded text at all; the reviewer performs its normal lens-driven review of the current files and returns its own findings, settled and recorded. Only then does a second message deliver the subset of the seeded `review-<#>.md` findings its role raised last round, for which it returns a disposition each — close, reject, or carry — with evidence quoted from the current file. The consolidator folds those dispositions and any new findings into the updated finding set.

*Why: `sdlc://review-rationale` §R1 — read it if you are unsure why the two turns cannot be collapsed into one.*
<!-- rereview:end -->

## Context and scope

Two different bounds, and they are not the same bound. Reading a file and being answerable for what is in it are separate permissions, so they are defined separately here and every "confined to" below means the second.

**Review context** — the **entire repository**. A reviewer MAY read any file, at any time, to understand what it is looking at: the module a changed test exercises, a caller, a config, a sibling implementation. Reading is never restricted, costs the review nothing, and is never, by itself, grounds for a finding.

*Why: `sdlc://review-rationale` §R14.1 — read it before restricting what a reviewer may read.*

**Review scope** — the code a reviewer is **responsible for**. A defect in scope is a finding it is obliged to raise. **(PR mode)** scope is the union of **(a)** code logically related to the originating issue's expected outcomes, **whether or not this PR touched it** — a change an acceptance criterion required and nobody made is in scope precisely because it is missing — and **(b)** code this PR introduced or changed, wherever it landed, since damage this PR caused is this PR's responsibility. That union is then intersected with the files the role's `guide-map.role` globs match, which is the hard outer bound and the only mechanical one: `general-purpose` maps to `**/*`, so a default single-role pass is bounded by issue relevance alone. **(paths mode)** scope is the matched files. The paths the user named ARE the intent statement, and there is no issue to derive relatedness from, so nothing widens scope there.

Something real noticed **outside** scope — a pre-existing defect in a file this PR happened to touch, anything met while reading context — is not discarded. It is an **Incidental** finding: recorded with its evidence, not gating, not remediated in this PR. Scope decides what a reviewer must go and find; Tier 3 is where what it merely noticed goes, which is what lets scope be this tight without losing information.

*Why: `sdlc://review-rationale` §R14.2 — read it if you are about to drop an observation because it fell outside scope.*

## Invariants

Passages below and in the steps cite `sdlc://review-rationale` §`R<n>` for the reasoning behind a rule. That resource carries **no rules** — it never changes what this document requires, and it is read on demand, not as a precondition for any step.

- MUST NOT post anything to GitHub. This skill produces a local document only — there is no `gh api .../reviews` call, no review event, and no inline comments. In **paths mode** the skill additionally runs no `gh` at all (no repo resolution, no PR fetch, no commit map).
- When the review proceeds to completion, MUST write exactly one consolidated document **file** per invocation, at the endpoint-injected `Review document:` path, used verbatim. Two PR-mode branches may end without writing one: an unresolved linked issue, and a declined large diff. **(re-review)** The injected path is the NEXT round of the review, `review-<#>.<k>.md`, and it MUST NOT exist yet: a round is written once, to a new file, and the seeded document is never modified.

  *Why: `sdlc://review-rationale` §R1 — read it if you are unsure whether a branch should write a document.*
- MUST write the document autonomously as the final step (step 10). It has no approval gate on a fresh round. **(re-review)** There is exactly **one** gate: a blocking `reject`, `close`, or re-tier to incidental lacking the corroboration the invariant below requires stops for the user at step 9. Step 10 states the same one; if the two ever disagree, one of them is wrong.
- MUST NOT overwrite an existing review document, and MUST NOT run `git commit`, `git add` or `git init` for a review document. If the `Review document:` path already exists, STOP and tell the user — the endpoint resolved it as unused, so something else wrote it.
- Every finding in the document MUST sit in the scope of the role it is attributed to, as **Context and scope** above defines scope — that is, its file MUST match that role's `guide-map.role` globs. Stated over the finished document rather than over what a reviewer may say, because the consolidator is the only party that can check it, and step 8 now does. A reviewer working at the edge of its lens is not the failure; a document that credits a role with a finding outside its map is.
- When consolidating, each finding MUST be assigned the **highest** severity any role gives it, ranking `blocking > advisory > incidental`; where roles disagree, the dissent MUST be noted on the finding. A **blocking**-versus-**incidental** split is a disagreement about relevance rather than severity: resolve it against the originating issue's acceptance criteria, and until it is resolved the finding stays blocking. **(paths mode)** there is no originating issue, so the incidental tier is unavailable.
- For each finding, the consolidator MUST pre-select the recommended remediation option with `[x]`, list any alternatives with `[ ]`, and always include an `Other: ___` slot.
<!-- rereview:begin -->
- **(re-review)** MUST build step 9's consolidated document by reading the `Seeded document:` file itself rather than from the injected block or from recall. The block is an OUTLINE of that document, not a re-render of it, and **Step 7(0) is the one enumeration of what it does and does not carry** — do not restate that list here or anywhere else. The seeded document stays on disk untouched, so nothing is destroyed by a mistake here; what is lost is carried findings whose bodies were paraphrased instead of copied, and the next round seeds from the paraphrase.
<!-- rereview:end -->
<!-- rereview:begin -->
- **(re-review)** MUST dispatch each reviewer in two turns, and the phase-1 message MUST contain no seeded-finding text, no disposition vocabulary and no content from any round of the review. MUST keep the phase-1 brief's `.sdlc/reviews/` prohibition bullet verbatim. Step 8's rediscovery-outranks-close weighting is earned by these two together and is unfounded without both.
<!-- rereview:end -->
<!-- rereview:begin -->
- **(re-review)** MUST NOT apply a `reject` to a **blocking** finding, nor re-tier one to **incidental**, without either two reviewers agreeing or explicit user confirmation; with neither, treat it as **carry** and note the dissent. MUST NOT close a **blocking** finding without quoting the remediating text from the current file and — unless at least **two reviewers that were dispatched that finding** returned `close` independently — without explicit user confirmation; uncorroborated, treat it as **carry** and note the dissent. All three remove a finding from the single predicate termination depends on, at a default composition of one reviewer per role.
<!-- rereview:end -->
<!-- rereview:begin -->
- **(re-review)** A seeded finding nobody dispositioned MUST carry unchanged, keeping its id, text and severity, and MUST be counted in `<u>`. Ids MUST NOT be renumbered between passes, and a new finding's id is `max(retired ∪ open) + 1` computed over every id carrying that prefix, across BOTH the surviving findings and the `Retired ids` line, regardless of the tier each now sits in. A re-tiered finding keeps its id and moves between the sections, so a `B4` sitting in Tier 2 still counts against the next `B`.
<!-- rereview:end -->
<!-- rereview:begin -->
- **(re-review)** MUST fetch a finding's body with `sdlc_review_findings` before applying any disposition, re-tier or correction to it. The seeded block is an outline: it carries the enumeration, not the bodies, and reasoning about a finding from its heading is reasoning about a title. Step 9 verifies it.
<!-- rereview:end -->
- MUST NOT fabricate guide requirements that do not exist in the project's actual guides.
- MUST use the `understand-chat` skill to query the knowledge graph for context gathering when `.understand-anything/knowledge-graph.json` exists **and is current** for the reviewed tree. A graph whose analysis commit does not descend from the reviewed base, or whose nodes do not cover the files under review, is treated as ABSENT — step 6 has the check. Its summary would otherwise enter every reviewer's brief as architectural ground truth.

## Arguments

The MCP endpoint appends the following below this skill prompt. **Exactly one** of `Target PR:` / `Target paths:` is present — it selects the mode:

- `Target PR: #<pr-number>` — *(PR mode)* the PR to review.
- `Target paths:` followed by the literal file paths and/or globs to review, one per line — *(paths mode)* the artifacts to review in place against the working tree. No PR, no diff, no linked issue.
- `Roles: <role-a>, <role-b>, …` — the role stems to review through (defaults to `general-purpose`). Same meaning in both modes.
- `Reviewers per role: <N>` — how many independent reviewers to run per role (defaults to 1). Same meaning in both modes.
- `Resolved issue: #<N>` — *(PR mode only)* the linked issue resolved by the endpoint via the `closingIssuesReferences` relationship (or an `unresolved` notice when the PR has no linked issue). Defines the `.sdlc/reviews/issue-#<N>/` path. Present on fresh rounds and re-reviews alike. Absent in paths mode.
- `Review document directory: .sdlc/reviews/<dir>/` — the directory holding this target's review rounds: `issue-#<N>/` in PR mode, or a slug derived deterministically from the raw `paths` strings in paths mode. It is used to `mkdir -p` the review directory before writing.

  *Why: `sdlc://review-rationale` §R3 — read it if the directive is absent and you are unsure which branch you are on.*
- `Review document: <dir>/review-<#>.md` or `<dir>/review-<#>.<k>.md` — the exact, pre-resolved write target for this round, used verbatim: a file that does not exist yet. Round 1 of a review takes the first form and every later round the second. Do NOT glob the directory to recompute it.
- `Review round: <k>` — which round of the review this run writes: `1` on a fresh review, and on a re-review one more than the round it was seeded from. It is the `<k>` of the template's pass line, the `<k>` in this round's `## Pass <k>` heading, and the `pass` field of the metadata file — one number, supplied here, never derived by reading a pass line and incrementing it.
- `Review metadata: <dir>/review-<#>[.<k>].meta.json` — where step 2 records the code state this round reviewed, named after the document it sits beside.

  *Why: `sdlc://review-rationale` §R3 — read it if you are tempted to recompute the iteration yourself.*
<!-- rereview:begin -->
- `Re-review: review-<#>` — *(re-review only)* marks the run as a further round of review `<#>`, present only when the user passed `--verify <#>`. Its presence is what switches the **(re-review)** behavior on.
- `Seeded document: <path>` — *(re-review only)* the latest existing round of the review, which this round was seeded from. READ it; never write it.
<!-- rereview:end -->
<!-- rereview:begin -->
- `Seeded findings —` followed by the pre-rendered findings of the seeded document — *(re-review only)* the endpoint appends the parsed findings of the document being re-reviewed, under that header line. These are the findings each reviewer dispositions; do NOT re-parse the finding set from the file — the block is the authoritative enumeration, and a finding absent from it is absent from this pass. The block opens with its own `Seeded from:` provenance line, deliberately labelled differently from the `Review document:` write target above it so the two cannot be confused.

  The block is an **outline** of the document on disk: every field arrives verbatim except each finding's `**Issue:**` paragraph and `**Remediation:**` checklist, which are elided behind one marker apiece and fetched with `sdlc_review_findings` at the point of use. **Step 7(0) enumerates what arrives verbatim and what does not; follow that list, not a recollection of this sentence** — one enumeration, in one place, so the two cannot drift. Reading the file is not re-deriving the finding set; the two are different jobs.
<!-- rereview:end -->
<!-- rereview:begin -->
- `Seeded-role coverage warning: …` — *(re-review only)* emitted when this pass's roles do not cover the roles the seeded findings were raised under, either because an explicit `--roles` list narrowed them or because the seeded document's Composition line could not be read. It names the uncovered roles. Every seeded finding from those roles carries unexamined and MUST be counted in `<u>` at step 8 and reported at step 11 — the warning is the only signal that a blocking finding went unlooked-at this pass.
<!-- rereview:end -->
- The bundled review-document template (also available as the `sdlc://review-template` resource), which defines the exact structure of the document to write. It is the same template on a fresh round and a re-review — one document shape for the whole chain.

**(PR mode)** The tool output also carries a `Target repo: <id>` directive identifying the repository for `gh` commands that reference issues or PRs (the upstream `<owner>/<name>` when the current repo is a fork, otherwise the current repo). Consume it in step 1 rather than re-deriving the target repo. **In paths mode there is no `Target repo` directive** — paths mode runs no `gh`, so skip step 1 entirely.

## Subagent Execution (Optional)

This skill MAY itself be executed in an isolated orchestrator subagent to preserve parent context (distinct from the per-role reviewer subagents this skill spawns internally). When invoked with a `--subagent` flag, execute according to your tool:

**Claude Code:**
- MUST spawn a general-purpose subagent using the Agent tool with this brief:
  > You are executing the **`review`** skill from the SDLC pipeline (`issue` → `implement` → `test` → `commit` → `pr` → `review`).
  > 1. Read the project instructions in `AGENTS.md`
  > 2. Read and execute the complete workflow defined in this skill's markdown
  > 3. Follow every step faithfully, especially the Invariants section
  > 4. Return a structured summary: accomplishments, the next pipeline step prompt from the skill, and every declared artifact — `review_document_path`, `review_metadata_path`, `review_round`, `findings_count`, `blocking_count`, `incidental_count` and `pr_number` on every run, plus `findings_closed`, `findings_rejected`, `findings_added`, `findings_carried_unexamined` and `uncovered_roles` on a re-review (omit those five on a fresh round, where nothing was dispositioned). Step 11's re-review prompt reports the three deltas AND, when `findings_carried_unexamined` is non-zero, names the roles nobody covered — so a `--subagent` run that does not return all five cannot produce it. `findings_carried_unexamined` is the one that matters most: it is the number that keeps a blocking finding nobody looked at from being reported as a reviewed one.

- When the subagent returns, reproduce its full output to the user exactly as written — do not summarize, condense, paraphrase, or omit sections. The user needs to review the complete output to give informed approval. Do not repeat work or add your own commentary.

**Other LLM assistants:**
- Subagent execution may not be supported in your tool. Execute the skill inline following the normal workflow.

## Workflow

### Checklist

1. Resolve target repository *(PR mode only)*
2. Acquire the review targets (PR diff + commit map, or the matched paths) **and record the reviewed state**
3. Resolve the review-document path
4. Read project guides and styles
5. Resolve each role's lens and mapped files
6. Gather knowledge graph context
7. Dispatch reviewer subagents (N per role)
<!-- rereview:begin -->
   — **(re-review)** dispatch in two turns with the seeded set withheld from the first, fetching each role's finding bodies before its phase-2 message
<!-- rereview:end -->
8. Consolidate the findings
<!-- rereview:begin -->
   — **(re-review)** dispositions folded in first
<!-- rereview:end -->
9. Finalize the consolidated document
<!-- rereview:begin -->
   — **(re-review)** summarize what moved this round
<!-- rereview:end -->
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

<!-- rereview:begin -->
**(re-review)** Acquire the **current** state exactly as the active base mode does — the PR head's changed-file contents in PR mode, or the matched files' whole contents in paths mode. Reviewers judge both the seeded findings and any new defect against these current files, so this capture is mandatory; the seeded findings describe the *prior* state, not the state to read. (PR mode still verifies the local tree is at the PR head so the reviewers' reads line up with the recorded sha.)
<!-- rereview:end -->

#### PR mode — fetch the PR metadata, diff, and commit map

```bash
gh pr view <number> --repo <target> --json title,body,headRefName,baseRefName,changedFiles,headRefOid
gh pr diff <number> --repo <target>
```

If the PR does not exist, inform the user and stop. Parse the PR title, body, branch names, the list of changed files, and `headRefOid` (the target HEAD sha recorded in the document header). The `--repo <target>` flag ensures commands operate against the upstream repo when working from a fork (as resolved in step 1). If the target repo is the current repo, the flag MAY be omitted.

**Capture the diff text** returned by `gh pr diff` — this exact text is interpolated into each reviewer's brief in step 7 (the reviewers are spawned into fresh contexts and do NOT inherit this read).

**Fetch the originating issue too, and capture its body the same way.** `<N>` is the `Resolved issue: #<N>` directive appended below this prompt; do not re-derive it.

```bash
gh issue view <N> --repo <target> --json title,body
```

A reviewer cannot tell an on-issue defect from an incidental one without the acceptance criteria to test against, and confinement to a role's mapped files is *file* scope, not relevance — it says where a reviewer may look, not what the work was. So this body is interpolated into each reviewer's brief in step 7 alongside the diff. If the appended directive reports the issue as **unresolved**, skip this fetch: step 3 stops the run on that branch, so there is nothing to brief.

**Verify the local working tree is at the PR head.** The diff above comes from the remote, but reviewers read the changed files from the local filesystem, so the recorded `headRefOid` and the lines they read must correspond:

```bash
git rev-parse HEAD
```

If `HEAD` does not equal `headRefOid`, the local tree is not on the PR head (a stale branch, or a different worktree) and the `file:line` references would be off. Note what this check does *not* catch: `git rev-parse HEAD` returns the same sha however dirty the tree is, so a matching sha is not by itself evidence that the working tree is the PR head's content. The block below tests cleanliness separately and folds it into `head_matches_target`. Fetch and check out the PR head (`gh pr checkout <number> --repo <target>`, or `git fetch` + checkout of `headRefOid`), or — if you cannot or the user declines — warn the user that the recorded `<sha>` assumes the working tree is at the PR head and that references may drift.

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

#### Record the reviewed state (all modes)

Run this **here**, at acquisition, so the recorded state matches what the reviewers read — not later, when the tree may have moved. That correspondence is *proved* only on the branch where the PR-head verification above succeeded; when you continued past a `HEAD != headRefOid` mismatch, the record states the mismatch rather than claiming a correspondence it cannot support.

*Why: `sdlc://review-rationale` §R4 — read it if you are tempted to move this later in the run.*

**First, confirm a `Review metadata:` path was injected.** If the directive is absent, do NOT invent a path: skip this block and continue to step 3, which settles the branch.

The record is one small JSON file beside the document it describes: the merge-base with the upstream default branch, a content-addressed tree SHA for the working tree as reviewed, and the head it was taken at. It carries no patch. Findings cite `file:line` in a branch whose commits are routinely rewritten before merge; the tree SHA is what still identifies the reviewed content afterwards.

*Why: `sdlc://review-rationale` §R4.1 — read it if you are about to anchor on the PR's base branch instead, or want the patch back.*

Run the block as ONE shell invocation — its variables do not survive between tool calls, and the heredoc at the end reads all of them. `git remote set-head -a` is a **network call that writes `refs/remotes/<remote>/HEAD` in the user's repository**, so it is a fallback, not the opening move.

```bash
meta="<Review metadata>"
mkdir -p "$(dirname "$meta")"
q() { [ -n "$1" ] && printf '"%s"' "$1" || printf null; }
vcs=git; ref=; base=; tree=; remote=; head=; excl=; dirty=false

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    vcs=none                                 # not a repository — null base and tree
else
    # The review documents live in the tree under review, and this round is
    # about to add one. Leave them out of the hash, or the tree SHA changes
    # every round whatever the code does. DERIVED, never substituted: the
    # pathspec is anchored to the repository top, so it needs the working
    # directory's prefix whenever that is not the top.
    excl="$(git rev-parse --show-prefix).sdlc/reviews"
    [ -n "$(git status --porcelain -- ":(exclude,top)$excl")" ] && dirty=true
    head=$(git rev-parse --verify -q HEAD) || head=

    # `origin` is the FORK when working from a fork, so prefer a distinct
    # `upstream` remote. The DEFAULT branch is the ref that never moves; the
    # PR's base branch may be deleted once a stacked PR merges.
    remote=$(git remote | grep -qx upstream && echo upstream || echo origin)
    ref=$(git symbolic-ref -q "refs/remotes/$remote/HEAD") || ref=
    if [ -z "$ref" ]; then
        git remote set-head "$remote" -a >/dev/null 2>&1 || true    # NETWORK; writes a ref
        ref=$(git symbolic-ref -q "refs/remotes/$remote/HEAD") || ref=
    fi
    [ -n "$ref" ] && base=$(git merge-base HEAD "$ref" 2>/dev/null)
    if [ -z "$base" ]; then
        vcs=unanchored                       # null base; the tree is still recorded
        echo "review: no default-branch ref on '$remote' — recording the tree without an anchor." >&2
        echo "review: run 'git remote set-head $remote -a' when online to fix this." >&2
    fi

    # A throwaway index built from EMPTY, so uncommitted and untracked work is
    # hashed without touching the real index. A non-zero exit from `git add`
    # is expected when `.gitignore` already covers the excluded path.
    idx=$(mktemp -u)
    GIT_INDEX_FILE="$idx" git read-tree --empty
    GIT_INDEX_FILE="$idx" git add -A -- ":(exclude,top)$excl" 2>/dev/null || true
    tree=$(GIT_INDEX_FILE="$idx" git write-tree)
    rm -f "$idx"
    if [ "$tree" = "$(git hash-object -t tree /dev/null)" ]; then
        echo "review: the recorded tree is empty — nothing was staged (check the working directory)." >&2
        tree=
    fi
fi

cat > "$meta" <<EOF
{
  "mode": "<pr|paths>",
  "pr": <PR number — PR mode only; omit this WHOLE LINE in paths mode, trailing comma included>,
  "pass": <Review round>,
  "vcs": "$vcs",
  "excluded": $(q "$excl"),
  "upstream": "$(git remote get-url "$remote" 2>/dev/null)",
  "anchor_ref": $(q "$ref"),
  "base": $(q "$base"),
  "tree": $(q "$tree"),
  "head": $(q "$head"),
  "worktree_dirty": $dirty,
  "head_matches_target": <true|false — PR mode only; omit this WHOLE LINE in paths mode. See below>,
  "target_head": <the headRefOid sha, quoted — omit this WHOLE LINE, trailing comma included, whenever head_matches_target is true or absent>,
  "captured_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
```

Only the `<…>` placeholders are yours to substitute; every `$` field is filled by the shell. `pass` is the `Review round:` directive, verbatim. On the `none` path `base` and `tree` are empty, which `q()` serialises as JSON `null`; on the `unanchored` path only `base` is. Neither is a failure to retry, and neither stops the review: tell the user the state could not be anchored and carry on to step 3, since the reviewers' findings are the round's deliverable.

*Why: `sdlc://review-rationale` §R4.2 — read it if the tree SHA changes between rounds on unchanged code, or if you are about to drop the `top` anchor or seed the index from `HEAD`.*

`worktree_dirty` is `true` when `git status --porcelain`, **over the same pathspec `excluded` records**, was non-empty — review documents written by earlier rounds do not make the reviewed tree dirty. `head_matches_target` records whether the reviewed state corresponds to the PR head. **(PR mode)** Set it `true` only when `HEAD == headRefOid` **and** `worktree_dirty` is `false`. The sha check alone is not enough: `git rev-parse HEAD` returns the same sha however dirty the tree is, while `tree` is hashed over the **working tree** and deliberately includes uncommitted and untracked work. When either condition fails, write `false` and record `"target_head": "<headRefOid>"` beside it: `tree` still states what was reviewed, but it is NOT a claim about the PR head. **(paths mode)** There is no PR head, so omit `head_matches_target` and `target_head` entirely.

`git add -A` honours `.gitignore`, so ignored files stay out of the hash. To check later whether what merged is what was reviewed, hash the merged tree the same way — empty index, `git add -A` with the pathspec `excluded` records — and compare.

### 3. Resolve the review-document path

<!-- rereview:begin -->
**(re-review)** The injected `Review document:` line names the NEXT round of the review — `review-<#>.<k>.md`, a file that does not exist yet — and `Seeded document:` names the round it was seeded from, which is read and never written. There is no new review number to compute. Apart from that, this step reads exactly as it does for a fresh round.
<!-- rereview:end -->

**The write target is injected — use it verbatim.** For the review/produce flow the endpoint appends a `Review document:` line that IS the exact path to write this round to. Do NOT create the directory or file yet — that happens in step 10.

*Why: `sdlc://review-rationale` §R5 — read it if you are about to compute the iteration yourself.*

**(paths mode)** There is no linked-issue resolution in this mode (skip the `<N>` discussion below); the injected `Review document:` line is all you need.

**(PR mode)** The remainder of this step resolves which `issue-#<N>/` directory the injected path names; paths mode is fully covered above.

**`<N>` — the linked issue — is resolved for you.** It appends the result below this prompt as `Resolved issue: #<N>`, together with the `Review document directory`. Use the provided `<N>` directly; do NOT re-derive it. If you can tell the PR closes more than one issue, surface a note to the user confirming the chosen `issue-#<N>/` directory before writing. If the appended directive reports the issue as **unresolved** (the PR has no linked issue), ask the user which issue the PR addresses, then **STOP this run**. Tell them to link the issue to the PR — `gh pr edit <number> --body "Closes #<N>"`, or via the GitHub UI — and re-run `sdlc_review`, which then emits every directive this run lacked. Do NOT guess the path and do NOT continue to step 4.

*Why: `sdlc://review-rationale` §R5 — read it if you are about to re-derive the issue, or to continue after an unresolved one.*

**The review number and the round are resolved for you.** The endpoint has already scanned the review directory and injected the next unused file as the `Review document:` line, with its round as `Review round:`; use both verbatim. Do NOT `ls` the directory to recompute either — the endpoint's resolution is deterministic and never names a file that exists. Do NOT create the directory or file yet — that happens in step 10.

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
- **Seed the role's scope** by calling `sdlc_role_scope(<the PR's changed files>, "<stem>")`. This returns the changed files the role's globs match — it performs the `guide-map.role` reverse lookup over the server's already-merged config (default deep-merged with `.sdlc/config.json`) and applies the `pathlib.PurePath.full_match` matching for you, so you do NOT re-derive the merge or the glob match by hand. The default `general-purpose` role maps to `**/*`, so every changed file is seeded. **This is the seed, not the boundary.** It can only ever return files the PR changed, and scope is defined by the issue rather than by the diff (**Context and scope** above), so a reviewer extends it to related files this PR did not touch. The role's globs — which this call applies but does not report — remain the outer bound; step 8 checks each finding against them.

  *Why: `sdlc://review-rationale` §R14.3 — read it if you are about to let a reviewer extend past its role's globs.*

Distinguish the two empty-scope cases: an empty result for a **discovered** role means it maps to none of this PR's changed files (it has nothing to review here — note it in the header and skip dispatching reviewers for it). A role with **no `guide-map.role` entry at all** also returns empty; warn the user it will contribute nothing before skipping it. (An unknown / misspelled stem was already rejected by the validation above.)

### 6. Gather knowledge graph context

MUST check whether a knowledge graph exists:

```bash
test -f .understand-anything/knowledge-graph.json && echo "exists" || echo "missing"
```

**Check the graph is current before using it, and treat a stale one as absent.** Read the graph's recorded analysis commit and its node paths: when that commit does not descend from the reviewed base, or when the files under review do not appear among its nodes, SKIP this step, tell the user the graph is stale and why, and omit the architectural-context bullet from the brief rather than passing through a summary you could not validate.

*Why: `sdlc://review-rationale` §R6 — read it if you are unsure whether a graph is stale enough to skip.*

Otherwise, if the graph exists, MUST use the `understand-chat` skill with a query listing the file paths under review (the PR's changed files in PR mode, or the matched file set from step 2 in paths mode) to gather architectural context — component summaries, relationships, and layer assignments — that reveals how changed components fit into the broader architecture and informs review quality. If the graph does not exist, skip this step and continue. When a graph exists, pass the resulting summary to the reviewer subagents via the optional architectural-context slot in the step-7 brief (the reviewers do NOT inherit this `understand-chat` output otherwise); omit that slot when no graph exists.

### 7. Dispatch reviewer subagents (N per role)

For each role, spawn **N independent reviewer subagents** (N = reviewers per role). A reviewer reviews the artifacts (the PR diff in PR mode, or the matched files in paths mode) through exactly one role's lens and returns structured findings — it MUST NOT write any file or post anything.

*Why: `sdlc://review-rationale` §R14.4 — read it before deriving how much scope to hand a reviewer, or before withholding an extension you are unsure of.*

**Claude Code:** Spawn each reviewer using the Agent tool. Run all reviewers concurrently where the tool allows. A reviewer is spawned into a fresh, isolated context: it inherits none of your reads, so every input it needs MUST be interpolated into its brief (replace each `<…>` placeholder with the actual value before spawning). Each reviewer's brief MUST include:

> You are a **reviewer** for the SDLC `review` skill, assigned the **`<role-stem>`** role.
> - Your lens and blocking policy: `<the role document body>`.
> - **Context — read anything.** The whole repository is available to you: the module a changed test exercises, a caller, a sibling implementation, a config. Reading is never restricted and is never by itself grounds for a finding.
> - **Scope — what you are answerable for.** Your **starting point** is this set, the files your role's `guide-map.role` globs match in this PR's diff: `<the role's in-scope changed files>`. It is a starting point and not a boundary, because it can only contain files the PR changed. **(PR mode)** extend it to any file **your role covers** that is logically related to one of the acceptance criteria above — whether or not this PR touched it — and **name the criterion** that puts it in scope when you raise against it. Your role's subject matter is what its document above describes and this list exemplifies; if you are unsure whether a file is yours, raise the finding and say you are unsure, because the orchestrator owns attribution and would rather re-attribute a finding than lose it. Do NOT extend to a file you cannot tie to a criterion: that is scope creep, and an observation you merely noticed while reading belongs in the Incidental tier instead. **(paths mode)** your scope is exactly the files supplied below — the paths the user named are the intent statement, and there is nothing to widen it with.
> - **(PR mode)** The issue this PR closes, whose acceptance criteria are what "on-issue" means: `<the originating issue's title and body, captured in step 2>`.
> - Classify each finding as **Blocking**, **Advisory** or **Incidental**. Two questions, in this order. **First, does it pertain to the issue above?** A finding traces to an acceptance criterion, or to code this PR introduced, or it does not; one that does not is **Incidental** — a real observation about a file this PR happens to touch, not about the work the issue specified. Say which criterion, or say that none covers it; relevance is a claim you evidence like any other, not an aside. **Then, for an on-issue finding, apply your role's blocking policy**: a correctness defect, or an implementation that does something other than what the issue asked for, is **Blocking**; work that adds to technical debt if it is not addressed now is **Advisory**. An incidental finding is a deferral and not a dismissal — it is recorded with its evidence intact — so hold it to the same standard of proof as the other two, and do NOT use the tier to park a finding you have not evidenced. **(paths mode)** There is no originating issue and therefore no relevance to test, so the Incidental tier is unavailable: classify as **Blocking** or **Advisory** only, and omit the issue slot above.
> - The artifacts under review — interpolate the slot for the active mode (include exactly one):
>   - **(PR mode)** The PR diff under review (full text): `<pr-diff>` — the `gh pr diff` output captured in step 2. Review THIS diff; do not infer the diff from whatever branch or working tree you happen to be on.
>   - **(paths mode)** The files under review, each as its whole current contents (no diff): for each matched file from step 2, `<file-path>` followed by `<the file's full contents>`. Review these artifacts as they stand in the working tree — there is no PR, no diff, and no base to compare against.
> - The project guides to review against (full text): `<AGENTS.md body + the body of each resolved test and style guide from step 4>`. Cite guide rules only from this text — do NOT fabricate requirements that are not in it.
> - Architectural context for the files under review (when a knowledge graph exists): `<the understand-chat summary from step 6>`. *(Omit this bullet entirely when no knowledge graph exists.)*
> - Do NOT read anything under `.sdlc/reviews/`. Those are review artifacts, not the code under review; a prior round's findings live there and reading them would replace your own judgement with the last reviewer's.
> - **(PR mode)** Read each in-scope changed file from the local checkout. Interpolate exactly one of these, chosen by whether step 2's PR-head verification actually succeeded: **(verified)** "the checkout is at the PR head `<sha>`, so your `file:line` references line up with the diff above"; **(not verified)** "the checkout is at `<HEAD sha>`, which does **not** match the PR head `<headRefOid>` — line numbers may not correspond to the diff above, so prefer file-level references and say so whenever you cite a line." Never assert the first when step 2 continued past a mismatch: the reviewer has no way to check it, and a wrong reference seeded into the document is carried into every later round and costs one of them a disposition to undo. If a changed file is a test, also read the module it tests (and vice versa). **(paths mode)** Your in-scope files' whole contents are supplied above; you MAY read any other file for context, and if an in-scope file is a test, also read the module it tests (and vice versa). Drop the PR-head / `<sha>` wording in paths mode — there is no PR head.
> - **(PR mode) Sweep the acceptance criteria before you finish.** For each criterion in the issue above, identify the code that should satisfy it and verify that it does. **A change that should have been made and was not is a first-class finding** — the strongest one a review can make, and the only one a diff cannot show you, because an omission leaves no trace in it. Reference it at the file level, or as `issue acceptance criterion #<n>` where no single file applies, and say what you looked at to conclude the code is absent rather than elsewhere. *(In paths mode there are no criteria to sweep; skip this bullet.)*
> - Investigate through your assigned lens: apply the focus areas your role's lens / blocking policy defines above. **Only** when your role is `general-purpose` (or its document does not enumerate its own focus) fall back to the generic checklist: guide compliance (cite the specific MUST / SHALL / SHOULD rule), naming and convention drift, coverage regressions (new public APIs without tests, removed tests without justification), correctness bugs (logic errors, race conditions, missing error handling at boundaries, incorrect API use), and code quality (unnecessary complexity, dead code, duplicated logic). Do not pull yourself off your lens to chase items the generic list names but your role does not.
> - Return **structured findings only** — for each: a short title, severity, a reference, the issue with concrete evidence, a recommended remediation (and any alternatives), and optional tests-to-add. The reference is `file:line` when a single line applies; otherwise use a file-level reference (`<file>`) or a cross-cutting one (`(cross-cutting — no single line)`; in PR mode an issue-level `issue acceptance criterion #<n>` is also available). Omissions and file-spanning architectural concerns are first-class findings even without a line — raise them. **(PR mode only)** Do NOT attribute a commit sha — the orchestrator owns commit attribution in step 8. *(In paths mode there are no commits to attribute, so there is nothing to omit here.)* Do NOT write a file, do NOT post to GitHub, do NOT consolidate — return your raw findings to the orchestrator.

*Why: `sdlc://review-rationale` §R13.1 — read it before dropping an off-issue finding a reviewer returned, rather than tiering it.*

<!-- rereview:begin -->
**(re-review) 0. Know what the seeded block carries, and what it does not.** The block is the seeded document's own structure with each finding's issue text and remediation checklist elided. Everything else arrives **verbatim** and needs no read-back: each finding's role / agreement attribution and full title (they are in the heading, not reconstructed from it), each `Tests to add` line, the seeded round's own `## Pass <k> — cross-cutting decisions` section, and the **Rejected in earlier passes**, **Retired ids** and **Closed this round** ledgers.

One **second** class of content can be elided besides the finding bodies, and this is the one enumeration that says so: a document written before rounds were separate files may carry several `## Pass <k>` sections, and every one earlier than its header's pass counter is replaced by a supersession marker. They are intact in the `Seeded document:` file. A round written by this version of the skill carries only its own section, so on those there is nothing to elide.

*Why: `sdlc://review-rationale` §R15.1 — read it before reading the document back for a field the block already carries.*

What it does NOT carry is each finding's **body** — the `**Issue:**` paragraph and the `**Remediation:**` checklist, replaced by one marker per finding. Fetch the bodies you act on with `sdlc_review_findings(<the Seeded document path>, [<ids>])`, batching a whole role's subset in one call. This fetch is **required, not advisory**: a disposition is judged against a body, so applying one to a finding you have not fetched is applying it to text you never read.

**The seeded document is read, never written.** This round goes to a new file, so the `Seeded document:` path stays exactly as the last round left it and is the ground truth for everything you carry: build step 9's document by reading it, not by recalling the block.

*Why: `sdlc://review-rationale` §R7.1 — read it if you are about to rely on recall, or to edit the seeded document.*

What a new round carries forward is not uniform. Each carried finding keeps its heading, role attribution, full title, body and `Tests to add` line **unchanged**. `Retired ids` and **Rejected in earlier passes** are cumulative: copy them **and extend** them — step 8 appends every id that leaves the tiers to `Retired ids`, appends every rejection to the ledger, and removes an id from `Retired ids` when a finding is re-opened. **Closed this round** and the cross-cutting section are **per round**: write this round's only, and do not copy the seeded round's — they stay in the file that recorded them.

**Reconcile the counts while you are here.** Compare the file's finding ids against the ids in the block, whose `Findings (N):` line states the count. Compare **id sets**, not counts, and get the file's set from the parser itself — across all three tiers, and outside fenced code blocks — by calling the fetch tool with an EMPTY id list:

`sdlc_review_findings(<the Seeded document path>, [])`

It returns one `id / severity / reference / title` line per finding, then an `Outside any tier:` line, then a trailing `Ids:` line; compare `Ids:` against the block's ids, and treat a non-empty `Outside any tier:` as a failure in its own right.

**Call the parser; do not re-implement it.** The tool runs the same `parse_review_document` that produced the seeded enumeration, so the two id SETS cannot disagree; `Outside any tier:` is the side that can. STOP on either a set mismatch or a non-empty `Outside any tier:` and tell the user which heading drifted — the seeded document is theirs to repair, since this skill does not write earlier rounds. Do NOT substitute `grep -c '^### '`, a hand-written `awk`, or a shell-out to `uv run python -c "from sdlc import ..."`: every hand-rolled scanner here has been wrong in the direction that costs the round, and the shell-out resolves against the REVIEWED project's environment, where this package is not installed. On a real mismatch, STOP and name the ids present in the file but missing from the block.

*Why: `sdlc://review-rationale` §R7.2 — read it if the reconciliation reports ids you cannot find.*

**(re-review)** Each reviewer stays a reviewer and performs the full review above — it hunts for defects in the current files exactly as it would on a fresh round. The seeded findings are **context for reconciliation, not a worklist**, and the order the reviewer works in decides which of those it actually is: a reviewer that reads the prior findings first tends to confirm them rather than review the code, and a remediation that resolved every prior finding while introducing a new one sails through that.

That ordering is **structural, not an instruction**. A brief is read as a single context, so a reviewer told not to read ahead has already read ahead — its phase-1 findings are conditioned on the seeded text no matter what order the text asks for. The seeded findings therefore must not be in the phase-1 prompt at all. Dispatch each reviewer in two turns:

1. **Phase 1 — review.** Spawn the reviewer with the fresh-round brief above and **no seeded-finding content**: no seeded finding, no disposition vocabulary, and nothing from any round of the review. Keep the brief's `.sdlc/reviews/` prohibition bullet exactly as written — it is load-bearing, and naming the directory is not the same as disclosing what a prior round found. It reviews the current files through its lens and returns findings exactly as on a fresh round.

   The prohibition is on seeded **content**, not on operational scaffolding, so append this one bullet to the phase-1 brief:

   > - Stay available after you reply: a follow-up message will arrive with a second task, and it will ask you about the findings you are about to return. Keep them individually addressable rather than compressing them into a summary.

   It discloses nothing about what a prior round found, so it costs the blindness guarantee nothing — and phase 2 depends on the reviewer still holding its phase-1 findings per-finding, which a reviewer that believes its reply is terminal has no reason to do.
2. Collect its phase-1 findings.
3. **Phase 2 — reconcile.** **Fetch the bodies first.** The seeded block carries this role's findings with their bodies elided, and a reviewer cannot disposition a finding it was not shown — call `sdlc_review_findings(<the Seeded document path>, [<this role's seeded ids>])` and compose the message from what it returns. You MUST NOT interpolate a marker, a heading alone, or your own summary of a finding in place of its body. Then send the SAME reviewer a follow-up message carrying those findings. It still holds its phase-1 context, so it reconciles against work it has already done rather than forming an opinion for the first time.
4. Collect its dispositions, and **reconcile them against the subset you dispatched.** Compare the returned ids against the ids you sent that reviewer. Re-send any missing ids to the same reviewer once, then fall back to carry, recording which ids took that path so the pass header's `<u>` can distinguish them.

   *Why: `sdlc://review-rationale` §R7.4 — read it if a reviewer returns fewer dispositions than you dispatched.*

**Claude Code:** spawn a **`general-purpose`** subagent with the Agent tool for phase 1 — **never a fork**, which inherits this context including the seeded block and voids the blindness this dispatch exists to create — then continue that same agent with `SendMessage` for phase 2. Here the guarantee is **structural**, and it is worth stating precisely rather than overstating: **the phase-1 prompt contains no seeded-finding text, and the phase-1 brief forbids reading `.sdlc/reviews/`**. Both halves rest on the reviewer starting from a fresh context, so the type is named here rather than left to the harness default.

**Other LLM assistants:** where agent messaging is unavailable, run the two phases as two separate inline passes per role, and do not read the seeded set until the phase-1 findings are written down. **The guarantee is NOT the same on this path, and this skill will not claim it is.** The ordering here is instructional, and instructional ordering is better than none, but it is not blindness. Two consequences follow and both are mandatory: step 8's rediscovery-outranks-close weighting does NOT apply to a role run inline — treat such a rediscovery as ordinary agreement — and the pass header MUST record that phase-1 blindness was unavailable for those roles, so a later pass reading the document knows which weighting was in force.

*Why: `sdlc://review-rationale` §R7.3 — read it if you are running inline and unsure what the ordering does and does not buy.*

**Scoping the seeded subset.** Route each seeded finding to the reviewers of **every role recorded on it** that is in this pass's role list, rather than by matching its `Reference` against a file set. The document records `<role(s) / reviewer agreement>` and step 8 deliberately produces multi-role entries, so "the originating role" is not always singular: routing such a finding to one role arbitrarily halves the corroboration the step-8 and step-9 gates count. A seeded finding is unexamined only when **none** of its recorded roles ran; step 8 then carries it unchanged and records that it was not re-examined.

*Why: `sdlc://review-rationale` §R7.4 — read it if you are about to route seeded findings by their file reference.*

The phase-2 message to each reviewer:

> - **Phase 2 — reconcile.** Your own findings are settled and recorded. Now read the seeded findings below — the subset your role raised in the previous round — and return exactly one disposition for each, with concrete evidence quoted from the current file: `<the seeded findings for this role>`
>   - **close** — the remediation the finding calls for is present. Quote the text that shows it was addressed.
>   - **reject** — the finding does not hold up as written: it cites a guide rule that is not in the guide text you were given, names the wrong symbol or reference, or carries a severity your lens does not support. Say which, and give either the corrected finding or a recommendation to withdraw it outright.
>   - **carry** — the defect is still present and the finding still states it correctly. Quote the evidence that it remains.
> - **The `Reference` on a seeded finding is where the defect stood in the pass that RAISED it, not where it stands now.** Between passes the user ran `sdlc_implement --review <#>`, which by construction edited those files, so every line number below may have moved. Locate each defect by the symptom its Issue describes, in the current file. A missing or unrelated line at the cited offset is **NOT** evidence of a close and **NOT** grounds for "names the wrong symbol or reference" — re-reference the finding and carry it. Both failure directions here delete a blocking finding on a citation that simply drifted.
> - Where one of your phase-1 findings describes the same defect as a seeded finding, say so and **carry the seeded one** — do NOT raise both. The seeded finding keeps its id, which earlier rounds and the implement loop cite. Where no seeded finding matches, your phase-1 finding stands on its own as new.
> - A defect introduced by the remediation of a seeded finding is a **new finding**, not a disposition; raise it normally.
> - Findings rejected in earlier passes, with the reasoning that rejected them: `<the Rejected in earlier passes ledger>`. This is given to you and NOT to your phase-1 self, deliberately. If one of your phase-1 findings restates a ledger entry, say so: either accept the recorded reasoning, or **re-open** it explicitly and say what the earlier rejection missed. Do not silently raise it again under a new id.
> - Open your reply with a disposition block — one line per seeded finding, every finding you were given getting exactly one line — then the evidence for each below it:
>
>   ```
>   B1 | carry  | rediscovered | the unguarded index write is still at parser.py:204
>   B2 | close  | —            | nil guard now present at server.py:318
>   A3 | reject | —            | cited MUST rule is not in the supplied guide text
>   B7 | reopen | —            | the rejection missed the paths-mode branch; the rule IS in the guide at python.md:244
>   ```
>
>   Four `|`-separated fields: the finding id; the disposition (`close`, `reject`, `carry`, or `reopen` for a ledger entry you are re-opening); whether one of your phase-1 findings independently rediscovered the defect (`rediscovered`, else `—`); and the evidence, quoted from the current file. A `reopen` line is keyed on the **ledger** id rather than on a seeded finding — it is the only disposition that is not one-per-seeded-finding, and it is the signal that keeps a wrongly rejected blocking finding from blocking forever, so it gets a slot rather than riding in prose. The separator is `|` rather than ` — ` because `—` is also the third field's "not rediscovered" value, and a line carrying both reads as two em-dash fields. Do not hedge a disposition; if you genuinely cannot settle one, write `carry` and say why.

<!-- rereview:end -->
**Other LLM assistants:** If subagents are unavailable, perform each role's review inline, one role at a time, holding each role's findings — and, in a re-review, its dispositions — separately so they can be consolidated in step 8.

### 8. Consolidate the findings

<!-- rereview:begin -->
**(re-review)** Fold the seeded findings' dispositions in FIRST, then run the consolidation below over the reviewers' new findings — with one change to its scope, stated here because it is easy to miss: **"Merge across roles" runs over the union of the CARRIED seeded findings and this pass's new findings, not over the new findings alone.** Seeded findings are routed by originating role, so a reviewer never sees another role's subset and cannot report a cross-role rediscovery as a disposition. Without this widening, role A's phase-1 reviewer independently finding a defect role B raised last round produces a *second open id for one defect*: `<B>` is inflated, termination is delayed, `sdlc_implement --review <#>` walks the same remediation twice, and id stability breaks. A new finding that merges with a carried one is folded INTO it, keeps the carried id, and is recorded as cross-role agreement — outranking a `close` from the originating role exactly as a same-role rediscovery does. Two roles covering one file is the ordinary configuration here, not a corner case.

- **Fetch before you apply** — the seeded block elides every finding's body, so a disposition, a re-tier or a correction MUST NOT be applied to a finding whose body you have not fetched with `sdlc_review_findings`. Phase-2 dispatch already fetched each role's subset; anything you touch outside that set — a cross-role merge, a ledger re-open, a finding you are correcting in place — needs its own fetch. Reasoning about a finding from its heading is reasoning about a title.

  *Why: `sdlc://review-rationale` §R15.2 — read it if you are about to treat this fetch as optional the way a rationale pointer is.*
- **Apply each disposition** — a finding whose consolidated disposition is **close** is REMOVED from the tiers and recorded in this round's **Closed this round** ledger — id, title, reference, and the reason with the remediating text quoted from the current file, which is the only place the reason for a closure is kept; one that is **rejected** is either corrected in place (re-tiered, reference fixed, evidence restated) or removed when the recommendation is to withdraw it outright; one that is **carried** stays as it is. When reviewers disagree about a seeded finding, **carry** wins over **close** — a single reviewer holding that the defect remains keeps it open — and a **reject** is applied only when no reviewer carried it. A return that does not classify cleanly ("looks addressed but I would keep an eye on it") is treated as **carry**: the safe disposition is the one that keeps a finding open, and the reviewer is the only party who read the evidence. **Every id that LEAVES the tiers — closed, or rejected-and-withdrawn — MUST be appended to the header's `Retired ids` line, in tier order.** That line is half of `max(retired ∪ open) + 1`, and nothing else in this workflow writes it. Without this write the line freezes at whatever the seeded round held, `max(retired ∪ open)` collapses to `max(open)` on the round after a closure, and a closed id is reissued to a different defect that every earlier-round and implement-loop citation of it then points at.
- **A re-tier MUST move the `**(BLOCKING)**` marker with the finding** — re-tiering is the primary outcome of a `reject`, and ids are never renumbered, so a re-tiered finding keeps its id and moves between tiers. Blocking → advisory, and blocking → incidental into Tier 3, MUST strip `**(BLOCKING)**` from the heading; advisory or incidental → blocking MUST add it. Do NOT invent an `**(INCIDENTAL)**` counterpart: the blocking marker outranks the enclosing tier, and that override only ever promotes a finding INTO the termination predicate, so a stale one costs a pass the next round recovers — where a demoting marker would drop a blocking finding OUT of the predicate silently. Tier 3 membership is by section alone.

  *Why: `sdlc://review-rationale` §R8.2 — read it if a chain will not terminate although its blocking findings were re-tiered, and §R13.4 before inventing a marker for Tier 3.*
- **A seeded finding nobody dispositioned carries unchanged** — its originating role was not in this pass's role list, or its reviewers returned nothing for it. It is NOT dropped and NOT closed: it keeps its id, its text and its severity, and the pass header records that it was carried without re-examination. **Record which of the two causes applied**, per finding: they have different remedies — a role change versus a re-dispatch or a higher reviewer count — and step 11 has a prompt for each.

  *Why: `sdlc://review-rationale` §R8.4 — read it if you are tempted to drop a finding nobody dispositioned.*
- **A disposition whose only evidence is absence at a line is a carry** — "nothing at `<file>:<line>`" says the reference drifted, which it did for every finding the last remediation touched; it does not say the defect is gone. Treat such a `close` or `reject` as **carry**, and update the finding's `Reference` to where the defect actually stands now.
- **Fold phase-1 rediscoveries into the seeded finding** — where a reviewer reported that one of its phase-1 findings describes the same defect as a seeded finding, the seeded finding **carries** and the phase-1 finding is NOT added as a separate entry. Record the independent rediscovery as agreement on the carried finding: a reviewer that found the defect without being told about it is stronger evidence it remains than one that read the finding and agreed, so it outranks any **close** disposition on that finding. **Corroborate the claim before granting it that weight.** Match the claimed rediscovery against them yourself; where none matches, treat it as ordinary agreement rather than as the upgraded signal. This weighting is earned by the two-turn dispatch in step 7 — the phase-1 prompt carried no seeded-finding text, and the phase-1 brief forbade seeking it out on disk — and would be unfounded without both; it therefore does NOT apply to a role run inline, where neither condition holds.

  *Why: `sdlc://review-rationale` §R8.3 — read it before granting a rediscovery more weight than ordinary agreement.*
- **A blocking finding leaves the termination predicate only with corroboration** — `reject` applies only when no reviewer carried it, and requires either **two reviewers agreeing** or an explicit user confirmation; with neither, treat it as **carry** and note the dissent. Closing a **blocking** finding MUST quote the remediating text from the current file rather than assert its presence, and unless at least **two reviewers that were dispatched that finding** returned `close` independently, the closures MUST be surfaced for explicit user confirmation at step 9 rather than as an informational summary. The count is over the reviewers that actually judged the finding, NOT over the roles whose globs cover its file: seeded findings are routed by role, so glob coverage can be two while the number of agents that ever saw the finding is `Reviewers per role` — which defaults to 1. **Re-tiering a blocking finding to incidental takes the same gate**, by the same route. Uncorroborated, the finding stays **blocking** with the dissent noted. `carry` stays autonomous.

  *Why: `sdlc://review-rationale` §R13.3 — read it before re-tiering a blocking finding off-issue on one reviewer's judgement.*

*Why: `sdlc://review-rationale` §R8.3 — read it before removing a blocking finding on one reviewer's judgement.*
- **Record every rejection in the ledger** — a rejected finding leaves the document, so without a record the next pass's phase-1 reviewers, working in fresh contexts with the seeded set deliberately withheld, have every reason to raise the same claim again; step 8 below then classifies it as new and gives it a fresh id, and a blocking finding rejected each pass blocks forever. Append it to the document's **Rejected in earlier passes** ledger — id, title, reference, the pass that rejected it, and the rationale — and preserve the ledger across passes. It is supplied to the **phase-2** message only, NEVER to phase 1, so blindness is untouched. A phase-1 finding matching a ledger entry is folded into that entry rather than admitted as a new id.
- **A re-opened finding RECLAIMS its original id** — `reopen` is a normal disposition and it needs an id rule, because the finding's id is sitting in `Retired ids` while `max(retired ∪ open) + 1` would hand it a fresh one. It is the same defect, and earlier rounds already cite the original, so the original is what it takes: restore the finding to its tier under its old id, **remove that id from `Retired ids`**, and leave the ledger entry in place annotated with the pass that re-opened it and what the rejection missed. This is the one case where an id leaves the retired line, and it is why that line is a ledger rather than an append-only log. Count a re-opened finding in `<a>`: it re-enters the open set this round exactly as a new one does.
- **Keep finding IDs stable** — a carried or corrected finding KEEPS its original id. Ids are cited by earlier rounds' ledgers and in `sdlc_implement --review <#>`, so they MUST NOT be renumbered between rounds. New findings take the next id **computed over every id carrying that prefix, across BOTH the surviving findings and the `Retired ids` line, regardless of the tier each now sits in** — that is, `max(retired ∪ open) + 1`. Neither source alone is the maximum, and the tier is not part of the computation: a re-tiered finding keeps its id, so a `B4` in Tier 2 still blocks `B4` from being reissued.

  *Why: `sdlc://review-rationale` §R8.1 — read it if you are about to compute the next id from one source alone.*
- **Count what changed** — record how many findings were closed (`<c>`), rejected (`<r>`) and added (`<a>`) this pass, how many blocking (`<B>`), advisory (`<A>`) and incidental (`<I>`) findings remain open, and how many were **carried without re-examination** (`<u>`) — which has **two** causes and they are not interchangeable: the finding's originating role was absent from this pass, or a reviewer that WAS dispatched returned no disposition for it. Record the split, because step 11's prompt for the first tells the user to re-run with the missing roles, and telling them that when the role already ran is a false diagnosis with an inapplicable remedy. Those are the symbols the template's pass line and step 11's prompts use; `<u>` in particular is the one number that keeps an unexamined blocking finding from being reported as a reviewed one. These fill the template's pass header and decide the prompt in step 11.

<!-- rereview:end -->
The main session agent (NOT a reviewer) merges every reviewer's findings into one set:

- **Dedup within a role** — collapse findings from the same role that name the same defect at the same reference into a single finding, recording the reviewer agreement (e.g. `4/5 reviewers`).
- **Merge across roles** — combine findings about the same defect raised by different roles into one entry that records every role that raised it.
- **Highest severity wins** — assign each finding the highest severity any role gave it, ranking `blocking > advisory > incidental`. Where roles disagree (one rated it Blocking, another Advisory or did not raise it), NOTE the dissent on the finding. **Blocking versus Incidental is the one disagreement this rule does not settle by itself**: it is not a disagreement about severity but about **relevance** — whether the issue asked for the work at all — and relevance is not role-relative, so neither lens outranks the other. Resolve it against the originating issue's acceptance criteria, state which criterion the finding traces to or that none does, and record the resolution on the finding. Until it is resolved the finding **stays blocking**, so nothing leaves the termination predicate by default while the question is open. *Why: `sdlc://review-rationale` §R13.2 — read it if you are about to settle a blocking-versus-incidental split by ranking the tiers.*
- **Assign stable IDs** — `B1, B2, …` for blocking findings, `A1, A2, …` for advisory, `I1, I2, …` for incidental, in a stable order. The prefix records where a finding was FIRST raised, not where it sits now: a re-tiered finding keeps its id, so `max(retired ∪ open) + 1` is computed per PREFIX rather than per section. **(re-review)** Only NEW findings are assigned here, by that same per-prefix rule; findings carried over from the seeded set keep the ids they already have.
- **Pre-select remediation** — for each finding, choose the recommended remediation and mark it `[x]`, list reasonable alternatives as `[ ]`, and always append an `Other: ___` slot.
- **Group by severity tier, blocking first** — Tier 1 (Blocking), Tier 2 (Advisory), then Tier 3 (Incidental). **(paths mode)** omit Tier 3 entirely; it has no originating issue to test relevance against.
- **(PR mode) Attribute each finding to a commit** — using the **branch commit map** built in step 2, match each finding's `file:line` (or file-level reference) against the commit that touched that file to set its `Touched commit`. The consolidator owns this attribution; do not rely on any sha from a reviewer (the reviewers were told not to supply one). A finding with no single file (cross-cutting / issue-level) maps to the commit(s) most responsible, or is grouped under the relevant commit in the fixup mapping with a note. **A finding that reports a change which was never made has no commit that touched its file** — that is what the finding says. Map it to the commit most responsible for the related criterion where one exists, so the remediation lands beside the work it completes; where none does, write `(no commit — omission)` and group it in the fixup mapping under a **new commit**, since `git commit --fixup` against a sha that does not exist is not a thing the user can run. **(paths mode) Skip this bullet entirely** — there is no commit map, so findings carry no `Touched commit`.
- **Validate each finding's attribution** — call `sdlc_role_scope([<the finding's file>], "<the raising role>")` for every finding with a file-level or `file:line` reference. An empty result means the file is outside that role's `guide-map.role` map, which reviewers can now reach by extending their own scope. The finding is **NOT dropped**: re-attribute it to a role in this pass whose globs DO cover the file, folding it into that role's finding on the same defect if there is one; where no role in this pass covers it, keep the finding and note in the header that it fell outside every role's map, which tells the user a glob is missing. Dropping it would trade a real defect for a bookkeeping rule, and the rule exists to keep a role's findings reflecting its lens — not to discard evidence. *(A cross-cutting or issue-level finding has no file to check; skip it.)*

  *Why: `sdlc://review-rationale` §R14.3 — read it if you are tempted to drop a finding that fell outside the raising role's map.*
- Populate the document header and fill the **cross-cutting decisions** section, headed `## Pass <k> — cross-cutting decisions` with `<k>` the `Review round:` directive — the same number the pass line carries. It holds this round's decisions only. *Why: `sdlc://review-rationale` §R15.4 — read it if you expected an earlier round's cross-cutting section in this document.* Fill it following the bundled template appended below this prompt exactly. **The template is the one enumeration of the header's shape** — fill every field it carries and do not work from a list restated here. A local enumeration outcompetes a general "follow the template" directive, and the two that used to be here were each shorter than the template by several load-bearing fields. **(PR mode)** also fill the **fixup mapping** section, and take the branch commit map from step 2. **(paths mode)** identify the reviewed paths in place of the PR / HEAD-sha / Closes line; **omit the branch-commit-map line, every finding's `Touched commit`, and the entire fixup-mapping section** — none of them have meaning without a PR. Keep the severity tiers, stable IDs, references, evidence, and remediation checklists exactly as in PR mode.

  **The Composition line is machine-read, so its shape is a contract.** `sdlc_review --verify` parses it to inherit the roles this round ran under, so the next pass dispatches them without the user restating `--roles`. Render the role stems **backticked and comma-separated, immediately after the literal `role(s)`**, and put nothing but stems between that literal and the opening parenthesis. A line it cannot read yields no roles, and the pass falls back to `general-purpose`: every seeded finding raised by another role then carries unexamined while the pass still reports progress. The endpoint says so when it happens (`Seeded-role coverage warning`), but the cheap fix is upstream: write the line in this shape every round.

Severity definitions. The tiers are defined by what a finding **is**, not by what it does to approval — the two are not the same question, and only the first one a reviewer can answer from the code. These are the definitions the template's legend carries; the consolidator fills that legend from here, so the two MUST say the same thing.

- **Blocking** — a correctness defect, or an *incorrect intent* finding: the implementation does something other than what the originating issue asked for. Gates termination.
- **Advisory** — on-issue work that adds to technical debt if it is not addressed now. Does not gate.
- **Incidental** — the finding **does not pertain to the originating issue**: a legitimate observation about a file the PR happens to touch, not about the work the issue specified. Does not gate, is not remediated in this PR, and is carried as a candidate for a future issue. A **deferral, not a dismissal** — the finding keeps its id and its evidence, so the chain records the observation without the observation holding the chain open. **(paths mode)** unavailable: there is no originating issue to test relevance against, so an off-issue observation is Advisory there.

The raising role's blocking policy is authoritative for the Blocking / Advisory split on ON-ISSUE work — a MUST / SHALL violation is the common Blocking case and a SHOULD / MAY observation the common Advisory one, but a policy need not be phrased in those terms. Relevance to the originating issue is what separates Incidental from both, and relevance is **not role-relative**: two roles disagreeing about it are disagreeing about the issue, not about their lenses.

### 9. Finalize the consolidated document

Render the full consolidated document and present it to the user as informational. On a **fresh round** there is no approval gate to clear before writing: the document is written autonomously as the final step (step 10). Presenting it gives the user visibility into what was found and a chance to steer follow-up: they MAY

- **Remove** any finding they disagree with.
- **Edit** the text, reference, or remediation options of any finding.
- **Add** new findings the reviewers missed.
- **Change** the severity of any finding (re-tiering it).
- **Re-select** which remediation option is recommended.

Fold any such adjustments into the document, then proceed straight to writing it in step 10 — on a fresh round, do not block on an explicit "approved" from the user.

<!-- rereview:begin -->
**(re-review)** Present the updated document the same way, and additionally summarize what moved this pass — which findings closed, which were rejected and why, and which are new — so the user can see the round's progress before it is written.

**This is the step the blocking-disposition gate fires at.** Step 8 requires corroboration before a **blocking** finding may be removed from the termination predicate, and routes the uncorroborated case here. So, before going to step 10:

- List every **blocking** `close` that fewer than **two reviewers that were dispatched that finding** returned independently. Quote, for each, the remediating text from the current file. Ask the user to confirm the closures explicitly. **STOP here and wait for the user's answer.** Do not infer it, and do not proceed on the assumption that they would confirm. Anything they do not confirm explicitly is **carry** with the dissent noted.
- List every **blocking** `reject` that neither two reviewers agreed on nor the user has already confirmed. Ask for that confirmation, and treat anything unconfirmed as **carry** with the dissent noted.
- List every **blocking** finding this pass would re-tier to **incidental**, with the criterion it was judged not to trace to. That move removes it from the termination predicate as surely as a reject does, so it takes the same corroboration; anything unconfirmed stays **blocking** with the dissent noted.
- **Reconcile the fetched set against the dispositioned set.** Every finding this pass closes, rejects, re-tiers or corrects MUST appear in the set of ids passed to `sdlc_review_findings` during step 7. Where an id was dispositioned without being fetched, STOP and say which: the disposition rests on a heading, and no marker in the outline can tell you what the body said. Fetch it and re-derive that one disposition before continuing. This is the same read-back-from-ground-truth the id reconciliation performs; without it the fetch is the one load-bearing rule in this skill that nothing verifies.
- Where none of the three lists has an entry — the case at a composition of several reviewers per role; at the default of one reviewer per role, expect entries — say so in one line and continue without a gate. The gate is a function of the composition, not a step to perform ceremonially.

Everything else about step 9 is unchanged: fold in any adjustment the user offers, then go to step 10. Advisory dispositions, and blocking `carry`, never gate — `carry` keeps the finding open, so its worst case is a wasted pass.

<!-- rereview:end -->
### 10. Write the review document

The document is written autonomously — there is no approval gate on a fresh round. **(re-review)** There is exactly **one** exception, a question only the user can answer: rejecting, closing or re-tiering to incidental a **blocking** finding without the corroboration step 8 requires, which stopped at step 9.

Write the consolidated document to the injected `Review document:` path, verbatim, as ONE write:

```bash
mkdir -p "<Review document directory>"
[ -e "<Review document>" ] && { echo "review: <Review document> already exists — refusing to overwrite it" >&2; exit 1; }
```

Then write the file — one document, whole.

*Why: `sdlc://review-rationale` §R15.3 — read it before splitting the review document into one file per finding.*

The path was resolved by the endpoint as unused, so the guard firing means something else wrote it since — another run on the same target, most likely. STOP and tell the user; do not pick another name, and do not overwrite. Re-running `sdlc_review` resolves the next unused path.

**Nothing is committed, and no earlier round is touched.** Do not run `git add`, `git commit` or `git init` for a review document, and do not edit, move or delete any other `review-*.md` — whether and where `.sdlc/reviews/` is tracked is the project's decision, and each round's file is the record of that round.

<!-- rereview:begin -->
**(re-review)** The seeded document stays where it is, unchanged. What this round did to the finding set is stated IN the new document, by three things that MUST agree with one another and with the tiers: the pass line's `<c>` / `<r>` / `<a>` / `<u>` deltas, the **Closed this round** ledger (one entry per `<c>`), and the entries this round appended to **Rejected in earlier passes** (one per `<r>`). Check that before writing — a closed finding with no ledger entry has lost the only record of why it closed.

*Why: `sdlc://review-rationale` §R10 — read it if you are about to rewrite the seeded document instead, or want the per-finding history back.*
<!-- rereview:end -->

Confirm the metadata file step 2 wrote is beside the document — `Review metadata:` — and names this round. If step 2 skipped it, say so in step 11 rather than writing one now: the tree may have moved since the reviewers read it.

### 11. Prompt the user with next steps

After the document is written, prompt the user. **(PR mode):**

> Review written to `<Review document>`, with the reviewed state recorded beside it. Nothing was committed or posted to GitHub. A later `sdlc_implement <N>` picks this document up automatically — it reads the review's latest round off disk and walks each finding's pre-selected remediation through a per-finding approval gate, emitting the fixup commands from the mapping section. Read it yourself first if you want to drop or re-tier anything. When the findings are resolved and you are satisfied, run `gh pr ready <number>` to mark the PR ready for merge.

**(paths mode):**

> Review written to `<Review document>`, with the reviewed state recorded beside it. This document is a local artifact — nothing was committed or posted to GitHub, and the `implement` skill does not read it automatically. Read it yourself (or with the user) and use each finding's pre-selected remediation as the work list, applying the fixups directly to the reviewed files. To continue this review once they are fixed, run `sdlc_review --verify <#> --roles <the roles this round used>` over the same paths — that seeds this document's findings and writes the next round beside it. Running a bare `review` over the same paths instead starts a SEPARATE review at a new number. There is no PR or fixup mapping in this mode.

<!-- rereview:begin -->
**(re-review):** After the document is written, prompt based on the remaining blocking count:

> Round `<k>` of review `<#>` written to `<Review document>` — `<B>` blocking, `<A>` advisory, `<I>` incidental remaining. Closed `<c>`, rejected `<r>`, added `<a>` this round; the reasons are in its **Closed this round** and rejection ledgers. The previous round is unchanged at `<Seeded document>`. Nothing was committed or posted to GitHub.

When `<u>` is non-zero, say which of its two causes applied, so an unexamined blocking finding is never reported as a reviewed one and the remedy offered is the one that fits. Emit whichever variants have entries — both, if the round hit both:

> `<n>` finding(s) were carried WITHOUT re-examination — their originating role(s) `<roles>` were not in this pass. Re-run with `--roles <those roles>` to have them looked at.

> `<n>` finding(s) were carried WITHOUT re-examination — `<ids>` were dispatched to a reviewer of role `<r>`, which returned no disposition for them and did not supply one when re-asked. Re-running the same composition may cover them; a higher `subagents` (`Reviewers per role`) is the more reliable fix.

The second variant exists because the first one's remedy is actively wrong for it: the role DID run, so telling the user to re-run with that role names a list that already ran and diagnoses a cause that was not the cause.

When `<c>`, `<r>` and `<a>` are all zero, no finding changed. Say so, then continue with the blocking/non-blocking branch below:

> Round `<k>` of review `<#>` written to `<Review document>` with the finding set unchanged — `<B>` blocking, `<A>` advisory, `<I>` incidental still open. Every seeded finding carried. Nothing was committed or posted to GitHub.
<!-- rereview:end -->

- When `<B>` > 0:
  > `<B>` blocking finding(s) remain. Re-enter the implement loop to address them: `sdlc_implement <target> --review <#>` (the same target, with the review number `<#>`; it reads the latest round). After fixing, re-run `sdlc_review --verify <#> --roles <the roles this round used>` for the next round.

  Name the roles explicitly. The endpoint inherits them from the document's Composition line when `--roles` is omitted, but stating them keeps the chain legible and survives a document whose header predates that line — and a pass run under a narrower role list carries every finding of the missing roles unexamined.
- When `<B>` == 0:
  > No blocking findings remain — review `<#>` is complete. `<A>` advisory finding(s) and `<I>` incidental finding(s) are carried and neither gates. They are different backlogs and are reported as two numbers for that reason: the advisory count is debt this PR took on and can still pay, while the incidental count is observations that do not pertain to this issue at all and belong to a future one. Run another pass if you want the advisories addressed. In PR mode you may now mark the PR ready (`gh pr ready <number>`); in paths mode the reviewed artifacts are clean.

DO NOT proceed on your own.

## Edge Cases

**Paths mode runs no `gh` and posts nothing:** In paths mode the skill performs no repo resolution, no PR fetch, and no commit-map enumeration — there is no GitHub interaction at all. The document lands under the endpoint-computed `.sdlc/reviews/<slug>/` directory.

*Why: `sdlc://review-rationale` §R12.1 — read it before running any `gh` command in paths mode.*

**No files matched the paths/globs (paths mode):** If expanding the `Target paths:` entries against the working tree yields no files (every literal path is missing and every glob matches nothing), inform the user that nothing matched, list the entries you tried, and stop — there is nothing to review and no document is written. If only some entries are empty, note the misses and proceed with the files that did match.

**PR is already merged or closed (PR mode):** Inform the user that the PR is not open and stop.

**No findings:** If every reviewer returns clean, present the empty-findings document (header plus empty severity tiers) as informational (step 9) and write it autonomously (step 10) so the round is recorded; inform the user that no issues were found and the target looks clean. On a fresh round there is no approval gate on the review (produce) document — the empty-findings document is written the same way a document with findings is.

*Why: `sdlc://review-rationale` §R12.2 — read it before treating a clean round as a reason to skip the document.*

<!-- rereview:begin -->
**A finding heading the parser cannot read (re-review):** `sdlc_review --verify` fails before this skill is dispatched, with `ValueError: … unparsed finding heading in a severity tier: '### B2 - …'`. The review's latest round has been hand-edited into a heading that is not `### <id> — <title>` with a spaced em dash — an en dash or a hyphen is the usual cause.

*Why: `sdlc://review-rationale` §R12.3 — read it before trying to repair a seeded document the parser refused.*
<!-- rereview:end -->

<!-- rereview:begin -->
**Re-review target has no review document:** This is raised upstream by the tool before this skill runs — when the target has no round of review `<#>` (the directory is absent or that review is missing), `sdlc_review --verify <#>` raises a `ValueError` and the skill is never dispatched. You will not reach this skill with a missing review document, so there is no in-skill fallback to handle; the user sees the tool's error and runs a fresh `review` first.
<!-- rereview:end -->

<!-- rereview:begin -->
**Every seeded finding closes (re-review):** When every seeded finding is closed and no new one is raised, the new round is written with empty severity tiers, a pass header recording the closures, and a **Closed this round** entry for each. Write it exactly as usual, so the chain's completion is recorded, then give the `<B>` == 0 next-step prompt.
<!-- rereview:end -->

<!-- rereview:begin -->
**Every seeded finding carries (re-review):** The opposite extreme, and the common one early in a fix loop. When nothing closes, is rejected, or is added, the round is STILL written: a new file whose finding set matches the seeded one, with fresh dispositions, references re-checked against the current files, and its own metadata.

*Why: `sdlc://review-rationale` §R12.4 — read it before skipping the document for a round where nothing changed.*
<!-- rereview:end -->

**No originating issue in paths mode (the incidental tier is unavailable):** Paths mode reviews files as they stand, with no PR and no linked issue, so there is nothing for a finding's relevance to be tested against. Tier 3 is omitted from the document, the reviewer brief drops both the issue slot and the third classification, and an observation that would have been incidental in PR mode is **Advisory** there — it is still real, it still does not gate, and it is still recorded. Do not invent a stand-in for the issue: the paths a run was given say which files to read, not what work was asked for.

*Why: `sdlc://review-rationale` §R13.5 — read it if you are about to substitute something for the missing issue in paths mode.*

**No linked issue (PR mode — the endpoint reports `Resolved issue: unresolved`):** Ask the user which issue the PR addresses; do not guess the `.sdlc/reviews/issue-#<N>/` path. *(Paths mode has no linked issue and uses the injected `<slug>` directory, so this never arises there.)*

**Unknown / misspelled role:** A requested role with no discovered document (not among `sdlc_roles`, or whose `sdlc://guides/role/<stem>` read returns `Error: guide ... not found`) MUST halt the run with a corrective prompt asking the user to fix the role name. Do NOT dispatch a reviewer with an empty or error lens.

**A role exists but has no `guide-map.role` entry:** `sdlc_role_scope` returns empty for it just as it does for an unmapped role. Warn the user the role will contribute nothing (it is not scoped to any files), then skip it.

**A role maps to globs that match none of the reviewed files:** Note in the header that the discovered, mapped role had no in-scope files on this target (the PR's changed files, or paths mode's matched files) and skip its reviewers; it contributes no findings.

**Binary files:** Binary files MUST be skipped during analysis — in both the PR diff and a paths-mode match. Note their presence to the user but do not attempt to review them.

**Very large diffs (PR mode):** For PRs with more than 20 changed files or more than 1000 lines changed, the agent SHOULD summarize the scope to the user and ask whether to review the full diff, focus on specific files, or decline the review entirely. On a decline the run ends and no document is written: delete the `Review metadata:` file step 2 wrote, since it describes a round that produced none.

*Why: `sdlc://review-rationale` §R12.5 — read it before deciding how much of a large diff to put in each brief.*

**Files outside the repository's guide coverage:** If reviewed files are in a language or domain not covered by any project guide, review them for general correctness and code quality only. Do not fabricate guide requirements that do not exist.
