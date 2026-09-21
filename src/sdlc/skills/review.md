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
  layers a re-review on either mode: the round's existing document is seeded
  into the reviewers and rewritten in place rather than a new one being
  created. Every round is COMMITTED to a declared git repository — on a
  re-review, one commit per finding-set mutation — alongside a snapshot of the
  code state it reviewed. Does not post to GitHub.
subagent:
  support: optional
  type: general-purpose
  artifacts:
    - review_document_path
    - review_snapshot_path
    - findings_count
    - blocking_count
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

- **Re-review** — a `Re-review: review-<#>` directive is present (alongside the active PR-mode or paths-mode target). This is an ordinary review **seeded with an existing round's findings**, not a different kind of pass: the endpoint has already loaded `review-<#>.md` for the target, rendered its findings into the appended block, and named that same document as the write target. Each reviewer reviews the current files exactly as it would on a fresh round — dispatched with the seeded findings withheld entirely, so it forms its own findings before it has seen them — and is then sent the seeded set and reconciles, returning a disposition for each seeded finding: **close** it (the remediation is present), **reject** it (it does not hold up as written), or **carry** it (it still stands). The seeding is context for that reconciliation, not a worklist to walk. The document is rewritten in place, so it is a living record of one review as it evolves rather than a new round that re-derives findings already agreed. A re-review keeps the base mode's target acquisition (PR head contents or paths-mode file contents), role lenses, and `guide-map.role` confinement; it changes every step marked **(re-review)** below — there are several, and they are not confined to the consolidation steps, so read the markers rather than a list here. When no `Re-review` directive is present, ignore every **(re-review)** marker and run a fresh review.

<!-- rereview:end -->
Where a step below is marked **(PR mode)** or **(paths mode)** it applies only to that base mode; **(re-review)** applies only when the `Re-review` directive is present (layered on whichever base mode is active); unmarked steps apply to all.

Every round — fresh or re-review — is tracked in git. The document is committed to the repository the `Review repository:` directive names, and in a re-review **each finding-set mutation is its own commit** whose message justifies that state change, so the history records why every finding opened, closed, or was thrown out. Step 10 covers the protocol.

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
<!-- rereview:end -->
*Why: `sdlc://review-rationale` §R1 — read it if you are unsure why the two turns cannot be collapsed into one.*

## Invariants

Passages below and in the steps cite `sdlc://review-rationale` §`R<n>` for the reasoning behind a rule. That resource carries **no rules** — it never changes what this document requires, and it is read on demand, not as a precondition for any step.

- MUST NOT post anything to GitHub. This skill produces a local document only — there is no `gh api .../reviews` call, no review event, and no inline comments. In **paths mode** the skill additionally runs no `gh` at all (no repo resolution, no PR fetch, no commit map).
- When the review proceeds to completion, MUST write exactly one consolidated document **file** per invocation, at the endpoint-injected `Review document:` path, used verbatim. Two PR-mode branches may end without writing one: an unresolved linked issue, and a declined large diff. An unresolved review *repository* is NOT one of them — the document IS written and only the commit stops for the user (step 10a). **(re-review)** The injected path is the existing `review-<#>.md`, so the round is rewritten in place. One *file*, but NOT one write: step 10(d) walks it to its consolidated state one finding-set mutation at a time.
*Why: `sdlc://review-rationale` §R1 — read it if you are unsure whether a branch should write a document.*
- MUST write AND commit the document autonomously as the final step (step 10). Neither has an approval gate, on a fresh round or a re-review, except in **two** cases — an unresolved review repository, which stops for the user (step 10a), and **(re-review)** a blocking `reject` or `close` lacking the corroboration the invariant below requires, which stops for the user at step 9. These are the same two step 10 enumerates; if this list and step 10's count ever disagree, one of them is wrong. On a fresh round that is one write and one commit; **(re-review)** it is one commit per finding-set mutation, plus the snapshot-and-header commit that precedes them.
<!-- rereview:begin -->
- **(re-review)** MUST commit each finding-set mutation separately, with a message that justifies that specific state change, and MUST leave the document internally consistent — header counts included — at every commit.
<!-- rereview:end -->
- MUST NOT force-add a path the target repository ignores, and MUST NOT create a repository on its own initiative. When the resolved repository ignores the review documents, or no repository resolves at all, STOP and ask the user to unignore the path, name a different repository, or authorize `git init .sdlc` (step 10a).
- Each reviewer's findings MUST be confined to the files mapped to its role in `guide-map.role` (any file MAY be read for context). The default `general-purpose` role is mapped to `**/*`, so its findings span the whole diff.
- When consolidating, each finding MUST be assigned the **highest** severity any role gives it; where roles disagree, the dissent MUST be noted on the finding.
- For each finding, the consolidator MUST pre-select the recommended remediation option with `[x]`, list any alternatives with `[ ]`, and always include an `Other: ___` slot.
<!-- rereview:begin -->
- **(re-review)** MUST read the seeded `review-<#>.md` back from disk before dispatching any reviewer, for every field the `Seeded findings` block drops — role / agreement attribution, `Tests to add`, the cross-cutting decisions section, the **Rejected in earlier passes** and **Retired ids** ledgers, the pass counter, and full titles. The block is the authoritative **enumeration** of the finding set; it is not the document. Anything not read back is destroyed by the in-place rewrite, and this is the only instruction in this skill whose omission is irreversible rather than a recoverable wrong action. Step 7(0) holds the procedure.
<!-- rereview:end -->
<!-- rereview:begin -->
- **(re-review)** MUST copy the seeded `review-<#>.md` to the step 7(0) scratch path before dispatching any reviewer, and MUST build step 9's consolidated target by reading that copy rather than by recalling it.
<!-- rereview:end -->
<!-- rereview:begin -->
- **(re-review)** MUST dispatch each reviewer in two turns, and the phase-1 message MUST contain no seeded-finding text, no disposition vocabulary and no content from `review-<#>.md`. MUST keep the phase-1 brief's `.sdlc/reviews/` prohibition bullet verbatim. Step 8's rediscovery-outranks-close weighting is earned by these two together and is unfounded without both.
<!-- rereview:end -->
<!-- rereview:begin -->
- **(re-review)** MUST NOT apply a `reject` to a **blocking** finding without either two reviewers agreeing or explicit user confirmation; with neither, treat it as **carry** and note the dissent. MUST NOT close a **blocking** finding without quoting the remediating text from the current file. Both remove a finding from the single predicate termination depends on, at a default composition of one reviewer per role.
<!-- rereview:end -->
<!-- rereview:begin -->
- **(re-review)** A seeded finding nobody dispositioned MUST carry unchanged, keeping its id, text and severity, and MUST be counted in `<u>`. Ids MUST NOT be renumbered between passes, and a new finding's id is `max(retired ∪ open) + 1` within its tier.
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
- `Review document: <dir>/review-<iteration>.md` — the exact, pre-resolved write target for this round, used verbatim. Either way, do NOT glob the directory to recompute it.
*Why: `sdlc://review-rationale` §R3 — read it if you are tempted to recompute the iteration yourself.*
<!-- rereview:begin -->
- `Re-review: review-<#>` — *(re-review only)* marks the run as a re-review of the existing `review-<#>.md`, present only when the user passed `--verify <#>`. Its presence is what switches the **(re-review)** behavior on.
<!-- rereview:end -->
- `Seeded findings —` followed by the pre-rendered findings of `review-<#>.md` — *(re-review only)* the endpoint appends the parsed findings of the document being re-reviewed, under that header line. These are the findings each reviewer dispositions; do NOT re-parse the finding set from the file — the block is the authoritative enumeration, and a finding absent from it is absent from this pass. The block opens with its own `Seeded from:` provenance line, deliberately labelled differently from the `Review document:` write target above it so the two cannot be confused.

  The block is **lossy**, and the document is rewritten in place, so anything it drops is destroyed on every pass unless you read it back. Each finding carries only its id, title, severity, `Reference`, issue, remediation and touched commit. You MUST read the existing `review-<#>.md` for every field the block does not carry and preserve it verbatim on each finding you carry. **Step 7(0) enumerates those fields; follow that list, not a recollection of this sentence** — one enumeration, in one place, so the two cannot drift. Reading the file for these is not re-deriving the finding set; the two are different jobs.
- `Review repository: <absolute path>` — the repository review-document commits belong in, declared via the `review-repo` config key (never inferred from the filesystem). Present whenever a document will be written. The value `unresolved` means no repository could be determined; step 10 covers the question to ask the user in that case. The repository MUST contain the `Review document:` path, which is hardcoded under `.sdlc/reviews/`; one that does not is REFUSED at resolution and reported here as `unresolved` with the reason, rather than named alongside an unresolved document path.
*Why: `sdlc://review-rationale` §R3 — read it if a configured repository is refused and you want the reasoning.*
- `Review document in repository: <path>` — the same file the `Review document:` line names, addressed from the review repository's root instead of the working directory. Every `git` command in step 10 takes THIS path; `Review document:` is where the file is written. This directive and `Review snapshot in repository:` below are **omitted entirely** when `Review repository:` is `unresolved`, and each instead reads `<label>: unresolved` followed by an explanation when the path lies outside the resolved repository. Neither absence nor the literal `unresolved` is a path — step 10(a) stops on either, and the string is never passed to `git`.
*Why: `sdlc://review-rationale` §R3 — read it if the two document paths differ and you are unsure which to use.*
- `Review snapshot directory: <dir>/snapshot-<#>/` — where this pass's capture of the reviewed code state is written, paired 1:1 with the document of the same number. Step 2's capture checks for it before running.
*Why: `sdlc://review-rationale` §R3 — read it if you expected this directive to track the repository directives.*
- `Review snapshot in repository: <path>/` — the snapshot directory addressed from the review repository's root, on the same terms as the document's repository-relative path. This is what `git add` takes.
- `Seeded-role coverage warning: …` — *(re-review only)* emitted when this pass's roles do not cover the roles the seeded findings were raised under, either because an explicit `--roles` list narrowed them or because the seeded document's Composition line could not be read. It names the uncovered roles. Every seeded finding from those roles carries unexamined and MUST be counted in `<u>` at step 8 and reported at step 11 — the warning is the only signal that a blocking finding went unlooked-at this pass.
- `Review commit branch: <branch>` — *(optional)* the branch review-document commits land on, from the `target` argument or the `review-branch` config key. When the line is absent, commit to the branch already checked out. Note this is a commit destination, unlike the target-branch override of `implement` and `pr`, which names a branch to branch from or base against.
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
  > 4. Return a structured summary: accomplishments, the next pipeline step prompt from the skill, and every declared artifact — `review_document_path`, `review_snapshot_path`, `findings_count`, `blocking_count` and `pr_number` on every run, plus `findings_closed`, `findings_rejected`, `findings_added`, `findings_carried_unexamined` and `uncovered_roles` on a re-review (omit those five on a fresh round, where nothing was dispositioned). Step 11's re-review prompt reports the three deltas AND, when `findings_carried_unexamined` is non-zero, names the roles nobody covered — so a `--subagent` run that does not return all five cannot produce it. `findings_carried_unexamined` is the one that matters most: it is the number that keeps a blocking finding nobody looked at from being reported as a reviewed one.

- When the subagent returns, reproduce its full output to the user exactly as written — do not summarize, condense, paraphrase, or omit sections. The user needs to review the complete output to give informed approval. Do not repeat work or add your own commentary.

**Other LLM assistants:**
- Subagent execution may not be supported in your tool. Execute the skill inline following the normal workflow.

## Workflow

### Checklist

1. Resolve target repository *(PR mode only)*
2. Acquire the review targets (PR diff + commit map, or the matched paths) **and capture the reviewed state**
3. Resolve the review-document path
4. Read project guides and styles
5. Resolve each role's lens and mapped files
6. Gather knowledge graph context
7. Dispatch reviewer subagents (N per role) — **(re-review)** read the seeded document back first, then dispatch in two turns with the seeded set withheld from the first
8. Consolidate the findings — **(re-review)** dispositions folded in first
9. Finalize the consolidated document — **(re-review)** summarize what moved this pass, and write the target state to disk
10. Write and commit the review document and its snapshot — **(re-review)** one commit per finding-set mutation
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
**(re-review)** Acquire the **current** state exactly as the active base mode does — the PR head's changed-file contents in PR mode, or the matched files' whole contents in paths mode. Reviewers judge both the seeded findings and any new defect against these current files, so this capture is mandatory; the seeded `review-<#>.md` findings describe the *prior* state, not the state to read. (PR mode still verifies the local tree is at the PR head so the reviewers' reads line up with the recorded sha.)
<!-- rereview:end -->

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

If `HEAD` does not equal `headRefOid`, the local tree is not on the PR head (a stale branch, or a different worktree) and the `file:line` references would be off. Note what this check does *not* catch: `git rev-parse HEAD` returns the same sha however dirty the tree is, so a matching sha is not by itself evidence that the working tree is the PR head's content. The capture below tests cleanliness separately and folds it into `head_matches_target`. Fetch and check out the PR head (`gh pr checkout <number> --repo <target>`, or `git fetch` + checkout of `headRefOid`), or — if you cannot or the user declines — warn the user that the recorded `<sha>` assumes the working tree is at the PR head and that references may drift.

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

#### Capture the reviewed state (all modes)

Run this **here**, at acquisition, so the captured state matches what the reviewers read — not later, when the tree may have moved. That correspondence is *proved* only on the branch where the PR-head verification above succeeded; when you continued past a `HEAD != headRefOid` mismatch, the capture records the mismatch rather than claiming a correspondence it cannot support.
*Why: `sdlc://review-rationale` §R4 — read it if you are tempted to move this capture later in the run.*

**First, confirm a snapshot directory was injected.** If the directive is absent, do NOT invent a path: skip the capture and continue to step 3, which settles the branch. Guessing it is forbidden for the same reason step 3 forbids it.
*Why: `sdlc://review-rationale` §R4.6 — read it if you expected the directive and it is absent.*

The anchor is the merge-base with the upstream default branch, which by assumption never changes.
*Why: `sdlc://review-rationale` §R4.1 — read it if you are about to anchor on the PR's base branch instead.*

The three blocks below are ONE sequence — run them in a single shell invocation. `$vcs`, `$ref`, `$base`, `$tree` and `$staging` flow between them, and shell state does not survive between tool calls, so a split leaves `git commit-tree` with an empty parent or tree argument and the heredoc with empty fields.
*Why: `sdlc://review-rationale` §R4.2 — read it if you are about to split this into separate tool calls.*

The capture is written to a **staging directory**, not straight into `Review snapshot directory`. Step 10 promotes it once every gate has cleared.
*Why: `sdlc://review-rationale` §R4.6 — read it if you are about to write the snapshot directory directly.*

Resolve the anchor ref explicitly, preferring a cheap local read. `git remote set-head -a` is a **network call that writes `refs/remotes/<remote>/HEAD` in the user's repository**, so it is a fallback, not the opening move:

```bash
staging="${TMPDIR:-/tmp}/sdlc-review-$(printf '%s' "<Review snapshot directory>" | shasum | cut -c1-12).snapshot"
rm -rf "$staging" && mkdir -p "$staging"

# The review repository's path RELATIVE to the repository root. Substitute it
# ONCE here: the `git add` below, the `git diff` after it and `meta.excluded`
# must all name the same pathspec, and the restore recipe reads it back out of
# `meta.json` instead of repeating a literal.
#
# Derive it from `.sdlc` — the directory the `Review document:` path is
# hardcoded under — and NOT from `Review repository:`, which may read the
# literal `unresolved`. That is not an exotic branch: it is every project's
# FIRST review, and 10(a)'s `git init .sdlc` exception creates the repository
# after this capture has already run. Where `Review repository:` does resolve
# and names something other than `.sdlc`, use ITS path relative to
# `git rev-parse --show-toplevel`.
excl='<review-repo path relative to the repository root — `.sdlc` unless Review repository: resolves to something else>'

# The guard states what it ACCEPTS, deliberately — a blocklist here has been
# wrong twice. See `sdlc://review-rationale` §R4.4 before widening it.
case "$excl" in
    /*)
        echo "review: exclusion pathspec '$excl' is absolute; :(exclude,top) takes a path RELATIVE to the repository root" >&2
        exit 1
        ;;
    unresolved)
        echo "review: 'unresolved' is the Review repository: directive's null value, not a path — use .sdlc, the directory the review document is written under" >&2
        exit 1
        ;;
esac
case "$excl" in
    ''|.|./|..|../*|*/..|*/../*|*/.)
        echo "review: exclusion pathspec '$excl' excludes nothing — the review repository must not be the reviewed tree's root or an ancestor of it" >&2
        exit 1
        ;;
esac

vcs=git; ref=; base=; tree=; remote=
dirty=false

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    vcs=none                                 # not a repository — meta only, null base, no patch
else
    [ -n "$(git status --porcelain)" ] && dirty=true

    # `origin` is the FORK when working from a fork, which is the case step 1 exists
    # for, so prefer a distinct `upstream` remote when one is configured. The DEFAULT
    # branch is the ref that never moves; the PR's base branch is not the same thing
    # and may be deleted once a stacked PR merges.
    remote=$(git remote | grep -qx upstream && echo upstream || echo origin)
    ref=$(git symbolic-ref -q "refs/remotes/$remote/HEAD") || ref=
    if [ -z "$ref" ]; then
        git remote set-head "$remote" -a >/dev/null 2>&1 || true    # NETWORK; writes a ref
        ref=$(git symbolic-ref -q "refs/remotes/$remote/HEAD") || ref=
    fi
    [ -n "$ref" ] && base=$(git merge-base HEAD "$ref" 2>/dev/null)
    if [ -z "$base" ]; then
        vcs=unanchored                       # meta only, null base, no patch
        echo "review: no default-branch ref on '$remote' — capturing provenance only." >&2
        echo "review: run 'git remote set-head $remote -a' when online to fix this." >&2
    fi
fi
```

**An unresolvable anchor aborts the CAPTURE, not the review.** Tell the user the provenance could not be anchored, then carry on to step 3: the reviewers' findings are the round's deliverable, and losing provenance is no reason to lose them. Step 10 stages whatever the capture produced, so a missing patch cannot suppress the document commit.
*Why: `sdlc://review-rationale` §R4.1 — read it if you are about to abort the round over a missing anchor.*

Then capture the tree. The index is built from **empty**, not from `HEAD`. The pathspec is anchored with `top`.
*Why: `sdlc://review-rationale` §R4.2 — read it if the snapshot contains the review repository, or if you are about to drop the `top` anchor.*

```bash
if [ "$vcs" = git ]; then
    idx=$(mktemp -u)
    export GIT_INDEX_FILE="$idx"
    trap 'rm -f "$idx"' EXIT
    git read-tree --empty
    # `$excl` was derived and checked in the first block. A NON-ZERO exit here is
    # expected and is not an error: when the reviewed tree's own `.gitignore`
    # matches the review repository, `git add` prints "The following paths are
    # ignored" and exits 1 while staging the whole tree correctly. The empty-tree
    # sentinel below is the check that actually tests the property.
    git add -A -- ":(exclude,top)$excl" || true
    tree=$(git write-tree)
    unset GIT_INDEX_FILE

    # An all-excluding pathspec silently yields the empty tree, which would pass its
    # own integrity check on every pass while capturing nothing. Derive the sentinel
    # rather than hard-coding it: a `--object-format=sha256` repository has a
    # different empty tree, and a hard-coded SHA-1 value never fires there.
    if [ "$tree" = "$(git hash-object -t tree /dev/null)" ]; then
        echo "review: snapshot tree is empty — git add staged nothing (check the exclusion pathspec and the working directory)" >&2
        exit 1
    fi
fi
```

Then write both artifacts into the staging directory. `meta.json` is written **by this block**, not transcribed afterwards.
*Why: `sdlc://review-rationale` §R4.2 — read it if you are about to record these values and write the file in a later call.*

```bash
if [ "$vcs" = git ]; then
    snap=$(git commit-tree "$tree" -p "$base" -m "review snapshot")
    # The same exclusion the index used. Without it the diff reports the excluded
    # review repository as DELETED whenever the project tracks it, so the restore
    # loses it and the merged-tree comparison can never succeed.
    git diff --binary --full-index "$base" "$snap" -- ":(exclude,top)$excl" > "$staging/review.patch"
fi

cat > "$staging/meta.json" <<EOF
{
  "mode": "<pr|paths>",
  "pr": <PR number — PR mode only; omit this WHOLE LINE in paths mode, trailing comma included>,
  "pass": <k>,
  "vcs": "$vcs",
  "excluded": ["$excl"],
  "upstream": "$(git remote get-url "$remote" 2>/dev/null)",
  "anchor_ref": "$ref",
  "base": "$base",
  "tree": "$tree",
  "head": "$(git rev-parse --verify -q HEAD 2>/dev/null)",
  "worktree_dirty": $dirty,
  "head_matches_target": <true|false — PR mode only; omit this WHOLE LINE in paths mode. See below>,
  "target_head": <the headRefOid sha, quoted — omit this WHOLE LINE, trailing comma included, whenever head_matches_target is true or absent>,
  "captured_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
```

Only the `<…>` placeholders are yours to substitute; every `$` field is filled by the shell — `$excl` included, which is why the exclusion is written once in the first block rather than repeated as a literal in three places. On the `none` and `unanchored` paths `base` and `tree` are empty strings and no `review.patch` is written — that is the documented outcome, not a failure to retry. `head` is empty the same way on an unborn `HEAD`: `--verify -q` is what makes that true, since a bare `git rev-parse HEAD` prints the literal string `HEAD` there, which a later reader cannot tell from a real sha.

`pass` is `<k>`, how many passes have run against this document — `1` on a fresh round, and on a re-review the `<k>` carried in the existing document's pass line, incremented by one. You read that pass line as part of the mandatory read-back of the fields the seeded block does not carry.

`excluded` records the pathspec the index and the diff both used, so a later restore cannot drift from the capture — which is why the capture writes it down here rather than leaving a restore to repeat a literal. A restore MUST use exactly the pathspec `meta.excluded` records. `worktree_dirty` is `true` when `git status --porcelain` was non-empty.

`head_matches_target` records whether the reviewed state corresponds to the PR head. **(PR mode)** Set it `true` only when `HEAD == headRefOid` **and** `worktree_dirty` is `false`. The sha check alone is not enough: `git rev-parse HEAD` returns the same sha however dirty the tree is, while the capture is `git add -A` over the **working tree** and deliberately includes uncommitted and untracked work — so a dirty tree yields a `tree` that is not the PR head's tree while the sha check passes. When either condition fails, write `false` and record `"target_head": "<headRefOid>"` beside it: `tree` still states what was captured, but it is NOT a claim about the PR head, and step 10's restore comparison cannot answer whether what merged is what was reviewed. **(paths mode)** There is no PR head, so omit `head_matches_target` and `target_head` entirely.

What travels is `base`, the patch, and `tree`; those three reconstruct the state in any clone that can reach `base`.
*Why: `sdlc://review-rationale` §R4.1 — read it if you are about to record the synthetic commit's sha as if it were durable.*

`git add -A` honours `.gitignore`, so ignored files stay out of the snapshot. If the derived relative exclusion path is ever `.` or empty, abort here rather than capturing.
*Why: `sdlc://review-rationale` §R4.5 — read it if the tree SHA churns between passes on unchanged code, or a tracked path is missing from the snapshot.*

Reviewing the default branch itself yields `base == HEAD`, so the patch contains exactly the uncommitted and untracked work — empty only when the tree is clean. Record `$ref` as `anchor_ref` so a reader can tell which branch the base was taken from.

### 3. Resolve the review-document path

<!-- rereview:begin -->
**(re-review)** The injected `Review document:` line names the existing `review-<#>.md`, which this round rewrites in place, so there is no new iteration to compute — the endpoint already resolved the directory and named the file. Apart from that, this step reads exactly as it does for a fresh round.
<!-- rereview:end -->

**The write target is injected — use it verbatim.** For the review/produce flow the endpoint appends a `Review document: <dir>/review-<iteration>.md` line that IS the exact path to write this round to. Do NOT create the directory or file yet — that happens in step 10.
*Why: `sdlc://review-rationale` §R5 — read it if you are about to compute the iteration yourself.*

**(paths mode)** There is no linked-issue resolution in this mode (skip the `<N>` discussion below); the injected `Review document:` line is all you need.

**(PR mode)** The remainder of this step resolves which `issue-#<N>/` directory the injected path names; paths mode is fully covered above.

**`<N>` — the linked issue — is resolved for you.** It appends the result below this prompt as `Resolved issue: #<N>`, together with the `Review document directory`. Use the provided `<N>` directly; do NOT re-derive it. If you can tell the PR closes more than one issue, surface a note to the user confirming the chosen `issue-#<N>/` directory before writing. If the appended directive reports the issue as **unresolved** (the PR has no linked issue), ask the user which issue the PR addresses, then **STOP this run**. Tell them to link the issue to the PR — `gh pr edit <number> --body "Closes #<N>"`, or via the GitHub UI — and re-run `sdlc_review`, which then emits every directive this run lacked. Do NOT guess the path and do NOT continue to step 4.
*Why: `sdlc://review-rationale` §R5 — read it if you are about to re-derive the issue, or to continue after an unresolved one.*

**`<iteration>` — the 1-based review round — is resolved for you.** The endpoint has already scanned the issue's review directory and injected the next unused round as the `Review document: .sdlc/reviews/issue-#<N>/review-<iteration>.md` line; use that path verbatim as the write target. Do NOT `ls` the directory to recompute the iteration — the endpoint's resolution is deterministic and never overwrites an earlier round. Do NOT create the directory or file yet — that happens in step 10.

**Transcribe the commit destinations before going further.** Step 10 interpolates five injected values into every `git` command it runs — `Review repository:`, `Review document in repository:`, `Review snapshot in repository:`, `Review commit branch:` and `Review snapshot directory:` — and it does so hundreds of lines and many tool calls later, with the reviewer dispatch and (on a re-review) an arbitrarily large seeded dump in between. Their failure mode is a quiet commit to the wrong place, or passing the literal string `unresolved` to `git add`. Write the five values verbatim into a scratch file now and read them back in step 10, rather than recalling them:

```bash
cat > "$(cd "${TMPDIR:-/tmp}" && pwd -P)/sdlc-review-$(printf '%s' "<Review document>" | shasum | cut -c1-12).directives" <<'EOF'
Review repository: <value, or the literal `unresolved`>
Review document in repository: <value, or `unresolved`, or ABSENT>
Review snapshot in repository: <value, or `unresolved`, or ABSENT>
Review snapshot directory: <value, or ABSENT>
Review commit branch: <value, or ABSENT>
EOF
```

Record each one exactly as the directive block states it — including `unresolved`, and including the fact that a directive is missing entirely, since step 10(a) branches on both. This is the same reasoning step 9 applies to its consolidated target: ground truth from the filesystem beats the orchestrator's recollection of something it read many tool calls ago.

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

**Check the graph is current before using it, and treat a stale one as absent.** Read the graph's recorded analysis commit and its node paths: when that commit does not descend from the reviewed base, or when the files under review do not appear among its nodes, SKIP this step, tell the user the graph is stale and why, and omit the architectural-context bullet from the brief rather than passing through a summary you could not validate.
*Why: `sdlc://review-rationale` §R6 — read it if you are unsure whether a graph is stale enough to skip.*

Otherwise, if the graph exists, MUST use the `understand-chat` skill with a query listing the file paths under review (the PR's changed files in PR mode, or the matched file set from step 2 in paths mode) to gather architectural context — component summaries, relationships, and layer assignments — that reveals how changed components fit into the broader architecture and informs review quality. If the graph does not exist, skip this step and continue. When a graph exists, pass the resulting summary to the reviewer subagents via the optional architectural-context slot in the step-7 brief (the reviewers do NOT inherit this `understand-chat` output otherwise); omit that slot when no graph exists.

### 7. Dispatch reviewer subagents (N per role)

For each role, spawn **N independent reviewer subagents** (N = reviewers per role). A reviewer reviews the artifacts (the PR diff in PR mode, or the matched files in paths mode) through exactly one role's lens and returns structured findings — it MUST NOT write any file or post anything.

**Claude Code:** Spawn each reviewer using the Agent tool. Run all reviewers concurrently where the tool allows. A reviewer is spawned into a fresh, isolated context: it inherits none of your reads, so every input it needs MUST be interpolated into its brief (replace each `<…>` placeholder with the actual value before spawning). Each reviewer's brief MUST include:

> You are a **reviewer** for the SDLC `review` skill, assigned the **`<role-stem>`** role.
> - Your lens and blocking policy: `<the role document body>`.
> - Your findings are confined to these files (matched from `guide-map.role`): `<the role's in-scope changed files>`. You MAY read any other file for context, but raise findings ONLY against your in-scope files.
> - Apply your role's blocking policy to classify each finding as **Blocking** or **Advisory**.
> - The artifacts under review — interpolate the slot for the active mode (include exactly one):
>   - **(PR mode)** The PR diff under review (full text): `<pr-diff>` — the `gh pr diff` output captured in step 2. Review THIS diff; do not infer the diff from whatever branch or working tree you happen to be on.
>   - **(paths mode)** The files under review, each as its whole current contents (no diff): for each matched file from step 2, `<file-path>` followed by `<the file's full contents>`. Review these artifacts as they stand in the working tree — there is no PR, no diff, and no base to compare against.
> - The project guides to review against (full text): `<AGENTS.md body + the body of each resolved test and style guide from step 4>`. Cite guide rules only from this text — do NOT fabricate requirements that are not in it.
> - Architectural context for the files under review (when a knowledge graph exists): `<the understand-chat summary from step 6>`. *(Omit this bullet entirely when no knowledge graph exists.)*
> - Do NOT read anything under `.sdlc/reviews/`. Those are review artifacts, not the code under review; a prior round's findings live there and reading them would replace your own judgement with the last reviewer's.
> - **(PR mode)** Read each in-scope changed file from the local checkout. Interpolate exactly one of these, chosen by whether step 2's PR-head verification actually succeeded: **(verified)** "the checkout is at the PR head `<sha>`, so your `file:line` references line up with the diff above"; **(not verified)** "the checkout is at `<HEAD sha>`, which does **not** match the PR head `<headRefOid>` — line numbers may not correspond to the diff above, so prefer file-level references and say so whenever you cite a line." Never assert the first when step 2 continued past a mismatch: the reviewer has no way to check it, and a wrong reference seeded into the document is cited in commit subjects and costs a later pass a disposition to undo. If a changed file is a test, also read the module it tests (and vice versa). **(paths mode)** Your in-scope files' whole contents are supplied above; you MAY read any other file for context, and if an in-scope file is a test, also read the module it tests (and vice versa). Drop the PR-head / `<sha>` wording in paths mode — there is no PR head.
> - Investigate through your assigned lens: apply the focus areas your role's lens / blocking policy defines above. **Only** when your role is `general-purpose` (or its document does not enumerate its own focus) fall back to the generic checklist: guide compliance (cite the specific MUST / SHALL / SHOULD rule), naming and convention drift, coverage regressions (new public APIs without tests, removed tests without justification), correctness bugs (logic errors, race conditions, missing error handling at boundaries, incorrect API use), and code quality (unnecessary complexity, dead code, duplicated logic). Do not pull yourself off your lens to chase items the generic list names but your role does not.
> - Return **structured findings only** — for each: a short title, severity, a reference, the issue with concrete evidence, a recommended remediation (and any alternatives), and optional tests-to-add. The reference is `file:line` when a single line applies; otherwise use a file-level reference (`<file>`) or a cross-cutting one (`(cross-cutting — no single line)`; in PR mode an issue-level `issue acceptance criterion #<n>` is also available). Omissions and file-spanning architectural concerns are first-class findings even without a line — raise them. **(PR mode only)** Do NOT attribute a commit sha — the orchestrator owns commit attribution in step 8. *(In paths mode there are no commits to attribute, so there is nothing to omit here.)* Do NOT write a file, do NOT post to GitHub, do NOT consolidate — return your raw findings to the orchestrator.

<!-- rereview:begin -->
**(re-review) 0. Read the seeded document back, BEFORE dispatching anyone.** The seeded block is lossy and the document is rewritten in place, so every field it drops is destroyed on this pass unless you read it now. Open `review-<#>.md` at the `Review document:` path and take from it:

- each finding's **role / agreement attribution**, stripped off its title by the parser — step 7 routes the seeded subset by originating role, and step 8 folds this pass's agreement into it, so without this the routing below has nothing to route on;
- each finding's **`Tests to add`** line;
- the whole **Cross-cutting decisions** section, and the **Rejected in earlier passes** and **Retired ids** ledgers;
- the header's **pass counter `<k>`**, which step 2's `meta.json` and the new pass line both increment from;
- each finding's **full title**. The block carries it intact for a template-conformant heading — a blocking heading is split on `**(BLOCKING)**` and not on ` — ` at all, and an advisory one splits on the LAST ` — ` so only the attribution goes. The residual risk runs the other way: an advisory heading with **no** ` — <attribution>` suffix, which the template permits, loses its own last segment, so `### A1 — Empty patch claim is false — the usual case` arrives as `Empty patch claim is false`. The file's heading is the authority either way.

**Copy the file before you do anything else, and read it back from the copy in step 9.**
*Why: `sdlc://review-rationale` §R7.1 — read it if you are about to rely on recall instead of the copy.*

```bash
seed="$(cd "${TMPDIR:-/tmp}" && pwd -P)/sdlc-review-$(printf '%s' "<Review document>" | shasum | cut -c1-12).seed.md"
cp "<Review document>" "$seed"
echo "$seed"
```

Derived from `Review document:` alone — the working-directory path, present whenever a document will be written at all — for the same reason step 9's target is: the repository-relative directives are absent exactly on the unresolved-repository branch, which is the branch where there is no git history to recover from either. Preserve all of it verbatim on every finding you carry, and build step 9's consolidated target by reading `$seed` rather than by recalling it.
*Why: `sdlc://review-rationale` §R7.1 — read it if you are about to key the scratch path on a repository-relative directive.*

Note that "preserve verbatim" is not uniform across these. The **Cross-cutting decisions** section, each finding's `Tests to add` line, the role attributions and the full titles are preserved **unchanged**. The two ledgers are preserved **and extended**: step 8 appends every id that leaves the tiers to `Retired ids`, appends every rejection to **Rejected in earlier passes**, and removes an id from `Retired ids` when a finding is re-opened. The pass counter is preserved **and incremented**.

**Reconcile the counts while you are here.** Compare the file's finding ids against the ids in the block, whose `Findings (N):` line states the count. Compare **id sets**, not counts, and compute the file's set the way the parser does — outside fenced code blocks, and inside the Tier 1 / Tier 2 regions only:

```bash
awk '
  /^([`]{3,}|[~]{3,})/ { fence = 1 - fence; next }
  fence             { next }
  /^## +Tier +[12]/ { tier = 1; next }
  /^## /            { tier = 0; next }
  tier && /^### /   { print $2 }
' "<Review document>"
```

A naive `grep -c '^### '` is **wrong here**, and wrong in the direction that costs the round: `pr_state.parse_review_document` skips fenced headings deliberately, and the reviewed artifacts in this chain ARE review documents, so findings about them routinely quote finding headings — this instruction's own document does. On a real mismatch, STOP and name the ids present in the file but missing from the block.
*Why: `sdlc://review-rationale` §R7.2 — read it if the reconciliation reports ids you cannot find.*

**(re-review)** Each reviewer stays a reviewer and performs the full review above — it hunts for defects in the current files exactly as it would on a fresh round. The seeded findings are **context for reconciliation, not a worklist**, and the order the reviewer works in decides which of those it actually is: a reviewer that reads the prior findings first tends to confirm them rather than review the code, and a remediation that resolved every prior finding while introducing a new one sails through that.

That ordering is **structural, not an instruction**. A brief is read as a single context, so a reviewer told not to read ahead has already read ahead — its phase-1 findings are conditioned on the seeded text no matter what order the text asks for. The seeded findings therefore must not be in the phase-1 prompt at all. Dispatch each reviewer in two turns:

1. **Phase 1 — review.** Spawn the reviewer with the fresh-round brief above and **no seeded-finding content**: no seeded finding, no disposition vocabulary, and nothing from `review-<#>.md`. Keep the brief's `.sdlc/reviews/` prohibition bullet exactly as written — it is load-bearing, and naming the directory is not the same as disclosing what a prior round found. It reviews the current files through its lens and returns findings exactly as on a fresh round.

   The prohibition is on seeded **content**, not on operational scaffolding, so append this one bullet to the phase-1 brief:

   > - Stay available after you reply: a follow-up message will arrive with a second task, and it will ask you about the findings you are about to return. Keep them individually addressable rather than compressing them into a summary.

   It discloses nothing about what a prior round found, so it costs the blindness guarantee nothing — and phase 2 depends on the reviewer still holding its phase-1 findings per-finding, which a reviewer that believes its reply is terminal has no reason to do.
2. Collect its phase-1 findings.
3. **Phase 2 — reconcile.** Send the SAME reviewer a follow-up message carrying the seeded findings scoped to it. It still holds its phase-1 context, so it reconciles against work it has already done rather than forming an opinion for the first time.
4. Collect its dispositions, and **reconcile them against the subset you dispatched.** Compare the returned ids against the ids you sent that reviewer. Re-send any missing ids to the same reviewer once, then fall back to carry, recording which ids took that path so the pass header's `<u>` can distinguish them.
*Why: `sdlc://review-rationale` §R7.4 — read it if a reviewer returns fewer dispositions than you dispatched.*

**Claude Code:** spawn with the Agent tool for phase 1, then continue that same agent with `SendMessage` for phase 2. Here the guarantee is **structural**, and it is worth stating precisely rather than overstating: **the phase-1 prompt contains no seeded-finding text, and the phase-1 brief forbids reading `.sdlc/reviews/`**.

**Other LLM assistants:** where agent messaging is unavailable, run the two phases as two separate inline passes per role, and do not read the seeded set until the phase-1 findings are written down. **The guarantee is NOT the same on this path, and this skill will not claim it is.** The ordering here is instructional, and instructional ordering is better than none, but it is not blindness. Two consequences follow and both are mandatory: step 8's rediscovery-outranks-close weighting does NOT apply to a role run inline — treat such a rediscovery as ordinary agreement — and the pass header MUST record that phase-1 blindness was unavailable for those roles, so a later pass reading the document knows which weighting was in force.
*Why: `sdlc://review-rationale` §R7.3 — read it if you are running inline and unsure what the ordering does and does not buy.*

**Scoping the seeded subset.** Route each seeded finding to the reviewers of its **originating role**, which the document records on every finding, rather than by matching its `Reference` against a file set. A seeded finding whose originating role is not in this pass's role list has no reviewer at all; step 8 carries it unchanged and records that it was not re-examined.
*Why: `sdlc://review-rationale` §R7.4 — read it if you are about to route seeded findings by their file reference.*

The phase-2 message to each reviewer:

> - **Phase 2 — reconcile.** Your own findings are settled and recorded. Now read the seeded findings below — the subset your role raised in the previous round — and return exactly one disposition for each, with concrete evidence quoted from the current file: `<the seeded findings for this role>`
>   - **close** — the remediation the finding calls for is present. Quote the text that shows it was addressed.
>   - **reject** — the finding does not hold up as written: it cites a guide rule that is not in the guide text you were given, names the wrong symbol or reference, or carries a severity your lens does not support. Say which, and give either the corrected finding or a recommendation to withdraw it outright.
>   - **carry** — the defect is still present and the finding still states it correctly. Quote the evidence that it remains.
> - **The `Reference` on a seeded finding is where the defect stood in the pass that RAISED it, not where it stands now.** Between passes the user ran `sdlc_implement --review <#>`, which by construction edited those files, so every line number below may have moved. Locate each defect by the symptom its Issue describes, in the current file. A missing or unrelated line at the cited offset is **NOT** evidence of a close and **NOT** grounds for "names the wrong symbol or reference" — re-reference the finding and carry it. Both failure directions here delete a blocking finding on a citation that simply drifted.
> - Where one of your phase-1 findings describes the same defect as a seeded finding, say so and **carry the seeded one** — do NOT raise both. The seeded finding keeps its id, which the commit history and the implement loop cite. Where no seeded finding matches, your phase-1 finding stands on its own as new.
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

- **Apply each disposition** — a finding whose consolidated disposition is **close** is REMOVED from the document; one that is **rejected** is either corrected in place (re-tiered, reference fixed, evidence restated) or removed when the recommendation is to withdraw it outright; one that is **carried** stays as it is. When reviewers disagree about a seeded finding, **carry** wins over **close** — a single reviewer holding that the defect remains keeps it open — and a **reject** is applied only when no reviewer carried it. A return that does not classify cleanly ("looks addressed but I would keep an eye on it") is treated as **carry**: the safe disposition is the one that keeps a finding open, and the reviewer is the only party who read the evidence. **Every id that LEAVES the tiers — closed, or rejected-and-withdrawn — MUST be appended to the header's `Retired ids` line, in tier order, in the same mutation commit that removes it.** That line is half of `max(retired ∪ open) + 1`, and nothing else in this workflow writes it: step 7(0) preserves it, step 10(d) updates the header's counts. Without this write the line freezes at whatever it held, `max(retired ∪ open)` collapses to `max(open)` on the pass after a closure, and a closed id is reissued to a different defect that every commit-message and implement-loop citation of it then points at.
- **A re-tier MUST move the `**(BLOCKING)**` marker with the finding** — re-tiering is the primary outcome of a `reject`, and ids are never renumbered, so a re-tiered finding keeps its id and moves between tiers. Blocking → advisory MUST strip `**(BLOCKING)**` from the heading; advisory → blocking MUST add it.
*Why: `sdlc://review-rationale` §R8.2 — read it if a chain will not terminate although its blocking findings were re-tiered.*
- **A seeded finding nobody dispositioned carries unchanged** — its originating role was not in this pass's role list, or its reviewers returned nothing for it. It is NOT dropped and NOT closed: it keeps its id, its text and its severity, and the pass header records that it was carried without re-examination. **Record which of the two causes applied**, per finding: they have different remedies — a role change versus a re-dispatch or a higher reviewer count — and step 11 has a prompt for each.
*Why: `sdlc://review-rationale` §R8.4 — read it if you are tempted to drop a finding nobody dispositioned.*
- **A disposition whose only evidence is absence at a line is a carry** — "nothing at `<file>:<line>`" says the reference drifted, which it did for every finding the last remediation touched; it does not say the defect is gone. Treat such a `close` or `reject` as **carry**, and update the finding's `Reference` to where the defect actually stands now.
- **Fold phase-1 rediscoveries into the seeded finding** — where a reviewer reported that one of its phase-1 findings describes the same defect as a seeded finding, the seeded finding **carries** and the phase-1 finding is NOT added as a separate entry. Record the independent rediscovery as agreement on the carried finding: a reviewer that found the defect without being told about it is stronger evidence it remains than one that read the finding and agreed, so it outranks any **close** disposition on that finding. **Corroborate the claim before granting it that weight.** Match the claimed rediscovery against them yourself; where none matches, treat it as ordinary agreement rather than as the upgraded signal. This weighting is earned by the two-turn dispatch in step 7 — the phase-1 prompt carried no seeded-finding text, and the phase-1 brief forbade seeking it out on disk — and would be unfounded without both; it therefore does NOT apply to a role run inline, where neither condition holds.
*Why: `sdlc://review-rationale` §R8.3 — read it before granting a rediscovery more weight than ordinary agreement.*
- **A blocking finding is rejected only with corroboration** — `reject` removes a blocking finding outright, it applies only when no reviewer carried it, and `Reviewers per role` defaults to 1, so without a gate one agent's judgement deletes a blocking finding on the single predicate termination depends on. Require either **two reviewers agreeing** on the rejection or an explicit user confirmation before applying it to a **blocking** finding; with neither, treat it as **carry** and note the dissent. `carry` stays autonomous — it keeps the finding open, so the worst case is a wasted pass. So closing a **blocking** finding MUST quote the remediating text from the current file rather than assert its presence, and when `Reviewers per role` is 1 and a single role covers it, the closures MUST be surfaced for explicit user confirmation at step 9 rather than as an informational summary.
*Why: `sdlc://review-rationale` §R8.3 — read it before removing a blocking finding on one reviewer's judgement.*
- **Record every rejection in the ledger** — a rejected finding leaves the document, so without a record the next pass's phase-1 reviewers, working in fresh contexts with the seeded set deliberately withheld, have every reason to raise the same claim again; step 8 below then classifies it as new and gives it a fresh id, and a blocking finding rejected each pass blocks forever. Append it to the document's **Rejected in earlier passes** ledger — id, title, reference, the pass that rejected it, and the rationale — and preserve the ledger across passes. It is supplied to the **phase-2** message only, NEVER to phase 1, so blindness is untouched. A phase-1 finding matching a ledger entry is folded into that entry rather than admitted as a new id.
- **A re-opened finding RECLAIMS its original id** — `reopen` is a normal disposition and it needs an id rule, because the finding's id is sitting in `Retired ids` while `max(retired ∪ open) + 1` would hand it a fresh one. It is the same defect, and the commit history already cites the original, so the original is what it takes: restore the finding to its tier under its old id, **remove that id from `Retired ids`**, and leave the ledger entry in place annotated with the pass that re-opened it and what the rejection missed. This is the one case where an id leaves the retired line, and it is why that line is a ledger rather than an append-only log.
- **Keep finding IDs stable** — a carried or corrected finding KEEPS its original id. Ids are cited in the commit history and in `sdlc_implement --review <#>`, so they MUST NOT be renumbered between passes. New findings take the next id **above the highest id in that tier across BOTH the surviving findings and the `Retired ids` line** — that is, `max(retired ∪ open) + 1`. Neither source alone is the maximum.
*Why: `sdlc://review-rationale` §R8.1 — read it if you are about to compute the next id from one source alone.*
- **Count what changed** — record how many findings were closed (`<c>`), rejected (`<r>`) and added (`<a>`) this pass, how many blocking (`<B>`) and advisory (`<A>`) findings remain open, and how many were **carried without re-examination** (`<u>`) — which has **two** causes and they are not interchangeable: the finding's originating role was absent from this pass, or a reviewer that WAS dispatched returned no disposition for it. Record the split, because step 11's prompt for the first tells the user to re-run with the missing roles, and telling them that when the role already ran is a false diagnosis with an inapplicable remedy. Those are the symbols the template's pass line and step 11's prompts use; `<u>` in particular is the one number that keeps an unexamined blocking finding from being reported as a reviewed one. These fill the template's pass header, drive the commits in step 10, and decide the prompt in step 11.

<!-- rereview:end -->
The main session agent (NOT a reviewer) merges every reviewer's findings into one set:

- **Dedup within a role** — collapse findings from the same role that name the same defect at the same reference into a single finding, recording the reviewer agreement (e.g. `4/5 reviewers`).
- **Merge across roles** — combine findings about the same defect raised by different roles into one entry that records every role that raised it.
- **Highest severity wins** — assign each finding the highest severity any role gave it. Where roles disagree (one rated it Blocking, another Advisory or did not raise it), NOTE the dissent on the finding.
- **Assign stable IDs** — `B1, B2, …` for blocking findings, `A1, A2, …` for advisory, in a stable order. **(re-review)** Only NEW findings are assigned here, taking the next unused id in their tier; findings carried over from the seeded set keep the ids they already have.
- **Pre-select remediation** — for each finding, choose the recommended remediation and mark it `[x]`, list reasonable alternatives as `[ ]`, and always append an `Other: ___` slot.
- **Group by severity tier, blocking first** — Tier 1 (Blocking) then Tier 2 (Advisory).
- **(PR mode) Attribute each finding to a commit** — using the **branch commit map** built in step 2, match each finding's `file:line` (or file-level reference) against the commit that touched that file to set its `Touched commit`. The consolidator owns this attribution; do not rely on any sha from a reviewer (the reviewers were told not to supply one). A finding with no single file (cross-cutting / issue-level) maps to the commit(s) most responsible, or is grouped under the relevant commit in the fixup mapping with a note. **(paths mode) Skip this bullet entirely** — there is no commit map, so findings carry no `Touched commit`.
- Populate the document header and fill the **cross-cutting decisions** section, following the bundled template appended below this prompt exactly. **(PR mode)** The header carries roles used, reviewers per role, target HEAD sha, dedup approach, severity legend, and the branch commit map from step 2; also fill the **fixup mapping** section. **(paths mode)** The header carries roles used, reviewers per role, dedup approach, and severity legend, and identifies the reviewed paths in place of the PR / HEAD-sha / Closes line; **omit the branch-commit-map line, every finding's `Touched commit`, and the entire fixup-mapping section** — none of them have meaning without a PR. Keep the severity tiers, stable IDs, references, evidence, and remediation checklists exactly as in PR mode.

  **The Composition line is machine-read, so its shape is a contract.** `sdlc_review --verify` parses it to inherit the roles this round ran under, so the next pass dispatches them without the user restating `--roles`. Render the role stems **backticked and comma-separated, immediately after the literal `role(s)`**, and put nothing but stems between that literal and the opening parenthesis. A line it cannot read yields no roles, and the pass falls back to `general-purpose`: every seeded finding raised by another role then carries unexamined while the pass still reports progress. The endpoint says so when it happens (`Seeded-role coverage warning`), but the cheap fix is upstream — **(re-review)** step 7(0) preserves this line verbatim along with the rest of the header.

Severity definitions (the raising role's blocking policy is authoritative — the MUST/SHALL gloss is one common example, not the definition, since a role's policy need not be phrased in MUST/SHALL terms):

- **Blocking** — a defect that MUST be resolved before the PR can be approved per the raising role's blocking policy (for example, a violation of a MUST / SHALL guide rule, or a correctness defect on a consequential path).
- **Advisory** — clarity, consistency, or quality observations that do not gate approval per that policy (for example, SHOULD / MAY observations or optional improvements).

### 9. Finalize the consolidated document

Render the full consolidated document and present it to the user as informational. On a **fresh round** there is no approval gate to clear before writing: the document is written autonomously as the final step (step 10). Presenting it gives the user visibility into what was found and a chance to steer follow-up: they MAY

- **Remove** any finding they disagree with.
- **Edit** the text, reference, or remediation options of any finding.
- **Add** new findings the reviewers missed.
- **Change** the severity of any finding (re-tiering it).
- **Re-select** which remediation option is recommended.

Fold any such adjustments into the document, then proceed straight to writing it in step 10 — on a fresh round, do not block on an explicit "approved" from the user.

<!-- rereview:begin -->
**(re-review)** Present the updated document the same way, and additionally summarize what moved this pass — which findings closed, which were rejected and why, and which are new — so the user can see the round's progress before it is written and committed.

**This is the step the blocking-disposition gate fires at.** Step 8 requires corroboration before a **blocking** finding may be removed from the termination predicate, and routes the uncorroborated case here. So, before going to step 10:

- List every **blocking** `close` whose corroboration is a single reviewer of a single role — that is, where `Reviewers per role` is 1 and only one role covers the finding. Quote, for each, the remediating text from the current file. Ask the user to confirm the closures explicitly, and treat anything they do not confirm as **carry**.
- List every **blocking** `reject` that neither two reviewers agreed on nor the user has already confirmed. Ask for that confirmation, and treat anything unconfirmed as **carry** with the dissent noted.
- Where neither list has an entry — the ordinary case at a composition of several reviewers per role — say so in one line and continue without a gate. The gate is a function of the composition, not a step to perform ceremonially.

Everything else about step 9 is unchanged: fold in any adjustment the user offers, then go to step 10. Advisory dispositions, and blocking `carry`, never gate — `carry` keeps the finding open, so its worst case is a wasted pass.

Then write the consolidated result — the exact target state, every disposition applied — to a scratch file, and leave `review-<#>.md` itself untouched:

```bash
target="$(cd "${TMPDIR:-/tmp}" && pwd -P)/sdlc-review-$(printf '%s' "<Review document>" | shasum | cut -c1-12).target.md"
echo "$target"
```

Step 10(d) walks the real document toward this file one commit at a time and diffs against it at the end, so the target must survive every intervening tool call as a file rather than as remembered text. It is deliberately NOT written under `<Review snapshot directory>`: 10(c) mirrors that directory wholesale into the worktree, which would commit the target alongside the snapshot artifacts. The key is `Review document:` alone — the working-directory path, which is present whenever a document will be written at all — and NOT the repository-relative pair 10(b) keys its worktree on, because both of those directives are absent when the review repository is unresolved, which is precisely a branch on which this file is still needed.

<!-- rereview:end -->
### 10. Write and commit the review document

The document is written AND committed autonomously — neither has an approval gate. There are **two** exceptions, both questions only the user can answer: an unresolved review repository (10(a) below), and — on a re-review — rejecting or closing a **blocking** finding without the corroboration step 8 requires.

**Read the commit destinations back from disk first.** Step 3(b) wrote the five values to a scratch file precisely so this step does not interpolate them from recollection across the reviewer dispatch and the seeded dump. Read that file now and use what it says — it is ground truth, in the same way step 9's target file is:

```bash
cat "$(cd "${TMPDIR:-/tmp}" && pwd -P)/sdlc-review-$(printf '%s' "<Review document>" | shasum | cut -c1-12).directives"
```

A value that reads `unresolved`, or a line recorded as ABSENT, is a branch below — never a path. Do not pass either to `git`.

**(a) Resolve the repository.** The `Review repository:` directive names where review-document commits belong. It is **declared, never inferred** — the endpoint reads it from the `review-repo` config key, falling back to `.sdlc` only when that is already a repository.

- `Review repository: <absolute path>` — commit there. Call it `<repo>` below.
- `Review repository: unresolved` — **write the document first**, at the working-directory-relative `Review document:` path, which needs no repository; a round's reviewer work is not discarded because its commit destination is unknown. Then STOP before **committing** and ask the user, exactly as an unresolved linked issue is handled. Offer the two options the directive names: point `review-repo` at an existing repository, or create one with `git init .sdlc`. Once they choose, record it:

  ```bash
  git init .sdlc      # only when they chose to create one
  ```

  Then write their choice into `.sdlc/config.json` as `"review-repo"` (creating the file if absent, preserving any existing keys). The server re-reads its config at the start of each review, so from the next call on the question is not asked again. MUST NOT guess a repository, and MUST NOT commit until one is resolved.

<!-- rereview:begin -->
  **(re-review)** "Write the document first" means something different here, and the difference matters: on a re-review the document is normally walked forward one mutation at a time by (d), and (d) never runs on this branch. Copy step 9's consolidated target over `review-<#>.md` in the working directory instead — the whole pass in one write — so a round of reviewer work is not discarded for want of a commit destination. **Then promote the staged snapshot from (c) anyway**, before stopping: it is a filesystem move and needs no repository, and skipping it leaves this pass's capture in `$staging` for the next pass's `rm -rf` to clear while `snapshot-<#>/` still holds the PREVIOUS pass's `meta.json` — now sitting beside a document rewritten to this pass's finding set. Pairing the document with a snapshot that no longer describes it is the exact outcome the staging design exists to prevent. Record for the user that the per-mutation history could NOT be written and that this round therefore has no commits; step 11 has the matching prompt. Do not attempt (d) afterwards: the document already holds the target state, so there is no residual change to walk.

<!-- rereview:end -->
  **This one-write clause applies only when the user does NOT authorize a repository.** If they answer `git init .sdlc`, the exception below takes over and the round goes through (c) and (d) normally, with its per-mutation history — which is the feature the question exists to enable, so the user who said yes gets it.

  **The repository MUST contain the document.** That leaves `.sdlc` itself — the only directory that both contains the hardcoded `.sdlc/reviews/` document path and does not contain the tree under review — or a directory beneath it.
*Why: `sdlc://review-rationale` §R10.1 — read it if the user proposes a repository outside the reviewed tree.*

**Validate the resolved repository before committing.** Three checks. All are cheap, and all are silent failures when skipped.

First, the repository-relative directives may themselves be unresolved. If either repository-relative directive is absent or reads `unresolved`, STOP and relay the explanation to the user — never pass the string `unresolved` to `git add`.
*Why: `sdlc://review-rationale` §R10.1 — read it if the three snapshot directives do not appear together as you expect.*

**Exception — a repository created during this run.** Do NOT stop a second time on that absence — it is the expected state, not a new failure. Derive the two paths instead, by re-expressing `Review document:` and `Review snapshot directory:` relative to `<repo>` (with `<repo>` = `.sdlc`, the document `.sdlc/reviews/issue-#<N>/review-<#>.md` addresses as `reviews/issue-#<N>/review-<#>.md`), and commit this round.
*Why: `sdlc://review-rationale` §R10.1 — read it if you are unsure why the directives are absent right after a `git init`.*

Second, the repository may ignore the review artifacts. Check BOTH paths — invariant "MUST NOT force-add a path the target repository ignores" covers every path this step adds, and a `<repo>/.gitignore` carrying `*.patch`, `*.json` or `snapshot-*/` leaves the snapshot ignored while the document is clean:

```bash
git -C "<repo>" check-ignore "<Review document in repository>" "<Review snapshot in repository>"
```

Note the absence of `-q`. With more than one pathname `--quiet` is **fatal** — `fatal: --quiet is only valid with a single pathname`, exit 128 — which this step would misread as "not ignored". The non-quiet form is the one with the needed semantics: it exits **0** when *any* argument is ignored and prints which, and exits **1** when none is.

- **Exit 0** — at least one path is ignored, and stdout names it. Do NOT force-add it; tell the user their `review-repo` ignores that path and ask them to unignore it or name a different repository.
- **Exit 1** — neither path is ignored. Proceed.
- **Any other exit** — `check-ignore` itself failed (128 for a path outside the repository, for instance). Surface the error; do NOT read it as "not ignored".

An ignored path is not a silent no-op at commit time: `git add` errors with "The following paths are ignored" and takes the whole multi-pathspec add down with it, so on a re-review the snapshot commit fails before any finding mutation is applied.
*Why: `sdlc://review-rationale` §R10.2 — read it if `git add` reports ignored paths.*

Third, the repository MUST NOT be the reviewed tree's own root, nor any ancestor of it. If a future change lets such a value through, refuse it here and tell the user to move the review repository to a subdirectory such as `.sdlc`.
*Why: `sdlc://review-rationale` §R10.1 — read it if you are about to accept an ancestor as the review repository.*

**(b) Resolve the branch.** When a `Review commit branch: <branch>` directive is present AND `<branch>` differs from the branch checked out in `<repo>`, do every write and commit below inside a temporary worktree, so the tree under review is never disturbed. Read the checked-out branch rather than assuming it:

```bash
git -C "<repo>" branch --show-current
```

A freshly initialized repository has no commits, and `git worktree add` cannot attach to a branch that does not exist yet — the first-run state for every project that sets `review-branch`. Give `HEAD` a commit first, then create the branch if needed.

The worktree path is **deterministic**, so (b), (c) and (d) each re-derive it identically instead of carrying a shell variable across tool calls.
*Why: `sdlc://review-rationale` §R10.3 — read it if two projects collide on one worktree.*

```bash
worktree="$(cd "${TMPDIR:-/tmp}" && pwd -P)/sdlc-review-$(printf '%s' "<repo>/<Review document in repository>" | shasum | cut -c1-12)"

git -C "<repo>" rev-parse --verify -q HEAD >/dev/null \
  || git -C "<repo>" commit -q --allow-empty -m "review: Initialize the review document repository"

if git -C "<repo>" worktree list --porcelain | grep -Fqx "worktree $worktree"; then
    :                                   # already registered to THIS repository — reuse it
elif [ -e "$worktree" ]; then
    echo "worktree path $worktree exists but is not registered to <repo>" >&2
    echo "if an earlier pass crashed here, run 'git worktree prune' in the review repository" >&2
    exit 1                              # stale or foreign — never adopt it
elif git -C "<repo>" show-ref --verify --quiet "refs/heads/<branch>"; then
    git -C "<repo>" worktree add -q "$worktree" "<branch>"
else
    git -C "<repo>" worktree add -q -b "<branch>" "$worktree"
fi
```

Testing *registration* rather than mere existence is what makes a collision loud.
*Why: `sdlc://review-rationale` §R10.3 — read it before relaxing this to a bare directory test.*

Both sides of that test must name the path the same way, which is why the derivation resolves `$TMPDIR` with `cd … && pwd -P` rather than interpolating it.
*Why: `sdlc://review-rationale` §R10.3 — read it if the reuse branch never fires, or a pass aborts on its own worktree.*

The worktree is removed at the END of (d), after the last commit; on a re-review that is several commits later, not at the end of this sub-step. The removal command lives there.

When the directive is absent, or names the branch already checked out, write and commit in place and ignore every `"$worktree"` mention below.

**(c) Write the artifacts.** Two paths are injected and they are not interchangeable:

- `Review document: <path>` — relative to the working directory. This is where the document is WRITTEN, so the reviewed tree, `sdlc_implement --review` and the next `sdlc_review --verify` all find it where they expect.
- `Review document in repository: <path>` — the same file addressed from `<repo>`'s root. This is what every `git` command below takes.

**Promote the staged snapshot.** Every gate has now cleared, so move it into place. Clear the destination wholesale rather than removing two named files, so no third artifact from an earlier pass survives into a capture that no longer describes it:
*Why: `sdlc://review-rationale` §R10.4 — read it if a stale artifact survives beside a newer `meta.json`.*

```bash
staging="${TMPDIR:-/tmp}/sdlc-review-$(printf '%s' "<Review snapshot directory>" | shasum | cut -c1-12).snapshot"

# A snapshot directory always has a `snapshot-<#>` component. `Review document
# directory:` differs from `Review snapshot directory:` by one word and is the
# PARENT of every round for this target, so a substitution slip here would
# `rm -rf` them all.
case "<Review snapshot directory>" in
    */snapshot-*|*/snapshot-*/) ;;
    *) echo "review: refusing to rm -rf a path that is not a snapshot directory" >&2; exit 1;;
esac

# Promote only when there is something to promote. Step 2 has abort paths that
# leave `$staging` empty or never create it, and clearing the destination first
# would then destroy the previous pass's capture and replace it with nothing —
# the exact outcome staging exists to prevent.
if [ -d "$staging" ] && [ -n "$(ls -A "$staging" 2>/dev/null)" ]; then
    rm -rf "<Review snapshot directory>"
    mkdir -p "<Review snapshot directory>"
    cp -R "$staging/." "<Review snapshot directory>/"
    rm -rf "$staging"
else
    echo "review: nothing captured — leaving <Review snapshot directory> untouched" >&2
fi
```

Do NOT regenerate the capture here — recapturing at this point would record the tree as it stands now rather than as the reviewers read it, and the two can differ. If the capture was skipped (step 2 found no snapshot directive) or aborted unanchored, the staging directory holds `meta.json` alone or nothing at all; promote what is there and continue.
*Why: `sdlc://review-rationale` §R10.4 — read it if the staging directory is empty or missing.*

**What is written depends on the round.**

- **(fresh round)** Write the full document at `Review document:`, following the bundled template structure exactly: the header — including the pass line carrying the open counts and this pass's deltas — the severity-tiered findings (blocking first) with stable IDs / titles / severities / `Reference` (`file:line`, or a file-level / issue-level reference for a line-less finding) / Issue + evidence / Remediation checklist (`[x]` recommended, `[ ]` alternatives, `Other: ___`) / optional Tests-to-add, plus the cross-cutting-decisions section. **(PR mode)** also include each finding's `Touched commit` and the fixup-mapping section; **(paths mode)** omit both — there are no commits to attribute or fold into.
<!-- rereview:begin -->
- **(re-review)** Write NOTHING to `review-<#>.md` here **except the pass-header bump**, which is instructed here rather than left to be inferred from (d)'s rationale: edit the pass line to `**Pass <k+1>**`, leave `<B>` and `<A>` at the SEEDED counts, and set `<c>`, `<r>` and `<a>` to `0` with `<u>` at its final value. That is the one mutation (d)'s snapshot-and-header commit carries; without it that commit has nothing staged and fails on a pass where the capture was also skipped. The zeroes are not a placeholder — invariant :73 requires the header to agree with the document at every commit, and at this commit no disposition has been applied yet, so the deltas ARE zero and (d)'s mutation commits walk them up one at a time. Otherwise leave the document on disk at the seeded content this pass found, because (d) walks it forward one finding-set mutation at a time and each of those mutations is its own commit. Writing the reconciled document now would leave (d) with no residual change to apply, collapsing the pass into a single commit and defeating the per-mutation history. Step 9's consolidated document is the **target state** (d) walks toward — it is already on disk at the scratch path step 9 wrote it to, and is not something to write here.

**Where it is written depends on the branch resolved in (b).**

- **In place** (no worktree) — the injected paths are all there is. The document goes to `Review document:`, the snapshot is already at `<Review snapshot directory>`, and the `<repo>`-relative paths address those same files.
- **Worktree** — write to the working-directory paths **in addition to** the copies inside `"$worktree"`, never instead of them. The working-directory copies are what the reviewed tree and the rest of the pipeline read; the copies inside the worktree are what gets committed. Mirror both artifacts:

  ```bash
  worktree="$(cd "${TMPDIR:-/tmp}" && pwd -P)/sdlc-review-$(printf '%s' "<repo>/<Review document in repository>" | shasum | cut -c1-12)"
  mkdir -p "$worktree/$(dirname "<Review document in repository>")" "$worktree/<Review snapshot in repository>"
  cp "<Review document>" "$worktree/<Review document in repository>"
  cp "<Review snapshot directory>"/* "$worktree/<Review snapshot in repository>"
  ```

<!-- rereview:end -->
  On a re-review, repeat the document `cp` before **every** commit in (d) — the snapshot-and-header commit included, since that one carries the pass-header bump — so the committed copy tracks the working-directory copy commit by commit. Without it the bump is committed from stale content, or rides along with the first mutation commit whose message justifies a different state change; and on a pass where every finding carries there is no mutation commit at all, so the bump is never committed and the committed document permanently disagrees with the working one. The terminal check at the end of (d) cannot catch any of that — it compares two working-directory copies.

Do NOT post anything to GitHub.

**(d) Commit.** Every `git` command in this sub-step has two variants. When (b) created a worktree, use the `-C "$worktree"` form — the worktree is where (c) put the copies that get committed, and `-C <repo>` would commit from the repository's main worktree, still on whatever branch it had checked out. Otherwise use the `-C <repo>` form. Each block below re-derives `$worktree` for itself: shell state does not survive between tool calls, so a block that reads the handle must also assign it.

**`<message-file>` is a file you write first.**
*Why: `sdlc://review-rationale` §R10.4 — read it if a commit subject or body arrives mangled.*

**Stage the snapshot only when there is one.** Step 2 skips the capture when no snapshot directive was injected, and writes `meta.json` alone when the anchor could not be resolved. Omit `<Review snapshot in repository>` from the `add` when the promote above produced nothing — `git add` on a pathspec matching no file exits 128 and stages *nothing*, taking the document down with it, so a missing capture would otherwise convert a provenance gap into an unrecorded round.

On a **fresh round** the document and its snapshot are a single commit:

```bash
# in place
git -C "<repo>" add "<Review document in repository>" "<Review snapshot in repository>"
git -C "<repo>" commit -F "<message-file>"

# worktree
worktree="$(cd "${TMPDIR:-/tmp}" && pwd -P)/sdlc-review-$(printf '%s' "<repo>/<Review document in repository>" | shasum | cut -c1-12)"
git -C "$worktree" add "<Review document in repository>" "<Review snapshot in repository>"
git -C "$worktree" commit -F "<message-file>"
```

```
review: Add review-1 with 3 blocking and 2 advisory findings
```

<!-- rereview:begin -->
**(re-review)** The snapshot is committed FIRST, before any finding mutation, because the dispositions in this pass were derived from it. This commit also carries the **pass-header bump**: `<k>` counts passes, not finding changes, so it belongs to no mutation below — editing the pass line here gives it a home, and gives a pass in which nothing changed a coherent round of its own.
<!-- rereview:end -->

```bash
# in place
git -C "<repo>" add "<Review snapshot in repository>" "<Review document in repository>"
git -C "<repo>" commit -F "<message-file>"

# worktree — repeat (c)'s copy first: this commit carries the pass-header bump,
# so the worktree copy is stale until it is re-mirrored
worktree="$(cd "${TMPDIR:-/tmp}" && pwd -P)/sdlc-review-$(printf '%s' "<repo>/<Review document in repository>" | shasum | cut -c1-12)"
mkdir -p "$worktree/$(dirname "<Review document in repository>")"
cp "<Review document>" "$worktree/<Review document in repository>"
git -C "$worktree" add "<Review snapshot in repository>" "<Review document in repository>"
git -C "$worktree" commit -F "<message-file>"
```

```
review: Capture the reviewed state at <short-base>..<short-tree>
```

Each finding-set mutation is then its OWN commit, walking `review-<#>.md` from its seeded content toward step 9's consolidated result. Apply the mutations in the order **close → reject → add**, so the history reads as what got fixed, what was wrong, and what is newly broken. For each mutation in turn: edit the document to apply ONLY that change — updating the header's counts along with it, so every commit leaves the document internally consistent — then stage and commit just that change:

```bash
# in place
git -C "<repo>" add "<Review document in repository>"
git -C "<repo>" commit -F "<message-file>"

# worktree — repeat (c)'s copy first, so the committed file tracks the working one
worktree="$(cd "${TMPDIR:-/tmp}" && pwd -P)/sdlc-review-$(printf '%s' "<repo>/<Review document in repository>" | shasum | cut -c1-12)"
cp "<Review document>" "$worktree/<Review document in repository>"
git -C "$worktree" add "<Review document in repository>"
git -C "$worktree" commit -F "<message-file>"
```

When every seeded finding carries, there is no finding-set mutation to commit and the snapshot-and-header commit above is the entire round. Do NOT manufacture an empty commit to fill the gap.

After the last mutation, verify the document against step 9's target. Step 9 wrote that target to disk precisely so this check reads ground truth from the filesystem rather than comparing the file against the orchestrator's recollection of a document it rendered many tool calls earlier:

```bash
target="$(cd "${TMPDIR:-/tmp}" && pwd -P)/sdlc-review-$(printf '%s' "<Review document>" | shasum | cut -c1-12).target.md"
diff -u "$target" "<Review document>" && rm -f "$target"   # diff MUST produce no output
```

If `diff` reports a difference, a mutation was missed — apply the remainder as one further commit rather than amending the history, then run the check again.
*Why: `sdlc://review-rationale` §R10.4 — read it if the terminal diff keeps reporting a difference.*

Finally, when (b) created a worktree, remove it — after the LAST commit above, never earlier:

```bash
worktree="$(cd "${TMPDIR:-/tmp}" && pwd -P)/sdlc-review-$(printf '%s' "<repo>/<Review document in repository>" | shasum | cut -c1-12)"
git -C "<repo>" worktree remove --force "$worktree"
git -C "<repo>" worktree prune
```

`--force` is required: (c) mirrors copies into the worktree that git sees as untracked, and a plain `worktree remove` refuses with exit 128 ("contains modified or untracked files"), leaving the directory behind for the next run to trip over.

Commit messages follow the `commit` skill's subject rules — 72 characters maximum, imperative mood, first word capitalized, no trailing period, plain text with no markup — with one addition: review-document commits take a `review:` type prefix, which exists for this purpose and is never used for code commits.
*Why: `sdlc://review-rationale` §R10.4 — read it when composing a mutation commit's subject.*

```
review: Close B2 — nil guard now present at server.py:318
review: Reject B1 — cited MUST rule is not in the style guide
review: Add B4 — new guard misses the paths-mode branch
```

A rejection that withdraws a finding outright and one that corrects it are both `Reject`; the subject says which, and the body carries the reasoning. Do NOT post anything to GitHub.

**Restoring a snapshot.** The recipe is at `sdlc://review-rationale` §R10.5.
*Why: read it when the user asks to restore a captured state, or to check whether what merged is what was reviewed — this workflow never runs it.*

### 11. Prompt the user with next steps

After the document is written, prompt the user. **(PR mode):**

> Review written to `.sdlc/reviews/issue-#<N>/review-<iteration>.md` and committed to the review repository. Nothing was posted to GitHub. A later `sdlc_implement <N>` picks this document up automatically — it reads the latest round off disk and walks each finding's pre-selected remediation through a per-finding approval gate, emitting the fixup commands from the mapping section. Read it yourself first if you want to drop or re-tier anything. When the findings are resolved and you are satisfied, run `gh pr ready <number>` to mark the PR ready for merge.

When the review repository was unresolved and the user has not yet answered the step-10(a) question, the document exists but the round is not recorded. Say that instead of claiming a commit:

> Review written to `.sdlc/reviews/issue-#<N>/review-<iteration>.md`. It is **not committed** — no review repository is resolved. Answer the question above and this round will be committed; nothing was posted to GitHub.

<!-- rereview:begin -->
**(re-review)** Use this instead, which says what was actually lost. The finding set is current, but the per-mutation history — the thing a re-review chain exists to produce — was not written, and no later pass can reconstruct it:

> `review-<#>.md` rewritten in place — `<B>` blocking, `<A>` advisory remaining. Closed `<c>`, rejected `<r>`, added `<a>` this pass. The round is **not committed** and has no per-finding history — no review repository is resolved, so the document was written in one pass rather than walked forward one mutation at a time. Answer the question above and the NEXT pass will be committed; this one's history cannot be recovered. Nothing was posted to GitHub.

**(paths mode):**

> Review written to `<Review document directory>/review-<iteration>.md` and committed to the review repository, alongside the reviewed-state snapshot in `<Review document directory>/snapshot-<iteration>/`.

When the review repository was unresolved in paths mode, use this instead — paths mode is the mode reachable with no `gh` at all, so it is the likeliest first contact with the tool and therefore the likeliest to meet an unresolved repository:

> Review written to `<Review document directory>/review-<iteration>.md`. It is **not committed** — no review repository is resolved — and the reviewed-state snapshot may not have been promoted. Answer the question above and the next round will be committed; nothing was posted to GitHub.

The committed variant above continues: This document is a local artifact — nothing was posted to GitHub, and the `implement` skill does not read it automatically. Read it yourself (or with the user) and use each finding's pre-selected remediation as the work list, applying the fixups directly to the reviewed files. To continue this review once they are fixed, run `sdlc_review --verify <iteration> --roles <the roles this pass used>` over the same paths — that seeds this document's findings and rewrites it in place. Running a bare `review` over the same paths instead starts a SEPARATE chain at a new iteration. There is no PR or fixup mapping in this mode.

**(re-review):** After the document is written and committed, prompt based on the remaining blocking count:

> `review-<#>.md` rewritten in place — `<B>` blocking, `<A>` advisory remaining. Closed `<c>`, rejected `<r>`, added `<a>` this pass, each as its own commit in `<repo>`. Nothing was posted to GitHub.

<!-- rereview:end -->
When `<u>` is non-zero, say which of its two causes applied, so an unexamined blocking finding is never reported as a reviewed one and the remedy offered is the one that fits. Emit whichever variants have entries — both, if the pass hit both:

> `<n>` finding(s) were carried WITHOUT re-examination — their originating role(s) `<roles>` were not in this pass. Re-run with `--roles <those roles>` to have them looked at.

> `<n>` finding(s) were carried WITHOUT re-examination — `<ids>` were dispatched to a reviewer of role `<r>`, which returned no disposition for them and did not supply one when re-asked. Re-running the same composition may cover them; a higher `--reviewers-per-role` is the more reliable fix.

The second variant exists because the first one's remedy is actively wrong for it: the role DID run, so telling the user to re-run with that role names a list that already ran and diagnoses a cause that was not the cause.

When `<c>`, `<r>` and `<a>` are all zero, no finding changed and there are no per-mutation commits to report. Use this instead, then continue with the blocking/non-blocking branch below:

> `review-<#>.md` unchanged this pass — `<B>` blocking, `<A>` advisory still open. Every seeded finding carried, so only the reviewed-state capture and the pass header were committed. Nothing was posted to GitHub.

- When `<B>` > 0:
  > `<B>` blocking finding(s) remain. Re-enter the implement loop to address them: `sdlc_implement <target> --review <#>` (the same target, with the review iteration `<#>`). After fixing, re-run `sdlc_review --verify <#> --roles <the roles this pass used>` for the next pass.

  Name the roles explicitly. The endpoint inherits them from the document's Composition line when `--roles` is omitted, but stating them keeps the chain legible and survives a document whose header predates that line — and a pass run under a narrower role list carries every finding of the missing roles unexamined.
- When `<B>` == 0:
  > No blocking findings remain — review `<#>` is complete. `<A>` advisory finding(s) are carried and do not gate; run another pass if you want them addressed. In PR mode you may now mark the PR ready (`gh pr ready <number>`); in paths mode the reviewed artifacts are clean.

DO NOT proceed on your own.

## Edge Cases

**Paths mode runs no `gh` and posts nothing:** In paths mode the skill performs no repo resolution, no PR fetch, and no commit-map enumeration — there is no GitHub interaction at all. The document lands under the endpoint-computed `.sdlc/reviews/<slug>/` directory.
*Why: `sdlc://review-rationale` §R12 — read it if this branch does not behave as described.*

**No files matched the paths/globs (paths mode):** If expanding the `Target paths:` entries against the working tree yields no files (every literal path is missing and every glob matches nothing), inform the user that nothing matched, list the entries you tried, and stop — there is nothing to review and no document is written. If only some entries are empty, note the misses and proceed with the files that did match.

**PR is already merged or closed (PR mode):** Inform the user that the PR is not open and stop.

**No findings:** If every reviewer returns clean, present the empty-findings document (header plus empty severity tiers) as informational (step 9) and write and commit it autonomously (step 10) so the round is recorded; inform the user that no issues were found and the target looks clean. On a fresh round there is no approval gate on the review (produce) document — the empty-findings document is written the same way a document with findings is.
*Why: `sdlc://review-rationale` §R12 — read it if this branch does not behave as described.*

<!-- rereview:begin -->
**A finding heading the parser cannot read (re-review):** `sdlc_review --verify` fails before this skill is dispatched, with `ValueError: … unparsed finding heading in a severity tier: '### B2 - …'`. The document has been hand-edited into a heading that is not `### <id> — <title>` with a spaced em dash — an en dash or a hyphen is the usual cause.
<!-- rereview:end -->
*Why: `sdlc://review-rationale` §R12 — read it if this branch does not behave as described.*

**Re-review target has no review document:** This is raised upstream by the tool before this skill runs — when the target has no `review-<#>.md` (the directory is absent or that iteration is missing), `sdlc_review --verify <#>` raises a `ValueError` and the skill is never dispatched. You will not reach this skill with a missing review document, so there is no in-skill fallback to handle; the user sees the tool's error and runs a fresh `review` first.

<!-- rereview:begin -->
**Every seeded finding closes (re-review):** When every seeded finding is closed and no new one is raised, the document is rewritten with empty severity tiers and a pass header recording the closures. Write and commit it exactly as usual — one commit per closure — so the chain's completion is recorded in the history, then give the `<B>` == 0 next-step prompt.
<!-- rereview:end -->

<!-- rereview:begin -->
**Every seeded finding carries (re-review):** The opposite extreme, and the common one early in a fix loop. When nothing closes, is rejected, or is added, there is no finding-set mutation and therefore no per-mutation commit.
<!-- rereview:end -->
*Why: `sdlc://review-rationale` §R12 — read it if this branch does not behave as described.*

**No linked issue (PR mode — the endpoint reports `Resolved issue: unresolved`):** Ask the user which issue the PR addresses; do not guess the `.sdlc/reviews/issue-#<N>/` path. *(Paths mode has no linked issue and uses the injected `<slug>` directory, so this never arises there.)*

**Unknown / misspelled role:** A requested role with no discovered document (not among `sdlc_roles`, or whose `sdlc://guides/role/<stem>` read returns `Error: guide ... not found`) MUST halt the run with a corrective prompt asking the user to fix the role name. Do NOT dispatch a reviewer with an empty or error lens.

**A role exists but has no `guide-map.role` entry:** `sdlc_role_scope` returns empty for it just as it does for an unmapped role. Warn the user the role will contribute nothing (it is not scoped to any files), then skip it.

**A role maps to globs that match none of the reviewed files:** Note in the header that the discovered, mapped role had no in-scope files on this target (the PR's changed files, or paths mode's matched files) and skip its reviewers; it contributes no findings.

**Binary files:** Binary files MUST be skipped during analysis — in both the PR diff and a paths-mode match. Note their presence to the user but do not attempt to review them.

**Very large diffs (PR mode):** For PRs with more than 20 changed files or more than 1000 lines changed, the agent SHOULD summarize the scope to the user and ask whether to review the full diff, focus on specific files, or decline the review entirely. On a decline the run ends: no document and no snapshot are written, and whatever step 2 staged is left in `$staging` for the next run's `rm -rf` — this is the **declined-large-diff branch** the earlier steps refer to.
*Why: `sdlc://review-rationale` §R12 — read it if this branch does not behave as described.*

**Files outside the repository's guide coverage:** If reviewed files are in a language or domain not covered by any project guide, review them for general correctness and code quality only. Do not fabricate guide requirements that do not exist.
