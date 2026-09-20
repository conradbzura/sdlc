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
    - pr_number
---

The key words MUST, MUST NOT, SHALL, SHALL NOT, SHOULD, SHOULD NOT, REQUIRED, RECOMMENDED, MAY, and OPTIONAL in this document are to be interpreted as described in RFC 2119.

# Review Skill

Review either a pull request's diff or a set of local file paths through one or more role lenses (N reviewers per role), consolidate the findings into a single standardized local review document under `.sdlc/reviews/`, and write it for the user to drive fixups. This skill writes a local document; it does NOT post to GitHub.

The arguments appended below select the **base mode** by carrying **exactly one** of two target directives:

- **PR mode** — a `Target PR: #<pr-number>` directive is present. Review the PR diff; the steps fetch metadata, the diff, and the branch commit map, and the document lands under `.sdlc/reviews/issue-#<N>/`.
- **PATHS mode** — a `Target paths:` directive is present. There is no PR, no diff, no linked issue, and no `Target repo` directive. Expand the listed literal paths and globs against the working tree and review each matched file's whole contents. The endpoint computes the document directory and injects it as `Review document directory: .sdlc/reviews/<slug>/`. Run no `gh` and post nothing.

A third, orthogonal axis layers on top of whichever base mode is active:

- **Re-review** — a `Re-review: review-<#>` directive is present (alongside the active PR-mode or paths-mode target). This is an ordinary review **seeded with an existing round's findings**, not a different kind of pass: the endpoint has already loaded `review-<#>.md` for the target, rendered its findings into the appended block, and named that same document as the write target. Each reviewer reviews the current files exactly as it would on a fresh round, and additionally returns a disposition for each seeded finding — **close** it (the remediation is present), **reject** it (it does not hold up as written), or **carry** it (it still stands). The document is rewritten in place, so it is a living record of one review as it evolves rather than a new round that re-derives findings already agreed. A re-review keeps the base mode's target acquisition (PR head contents or paths-mode file contents), role lenses, and `guide-map.role` confinement; it changes steps 7, 8, 9 and 10 as marked **(re-review)** below. When no `Re-review` directive is present, ignore every **(re-review)** marker and run a fresh review.

Where a step below is marked **(PR mode)** or **(paths mode)** it applies only to that base mode; **(re-review)** applies only when the `Re-review` directive is present (layered on whichever base mode is active); unmarked steps apply to all.

Every round — fresh or re-review — is tracked in git. The document is committed to the repository the `Review repository:` directive names, and in a re-review **each finding-set mutation is its own commit** whose message justifies that state change, so the history records why every finding opened, closed, or was thrown out. Step 10 covers the protocol.

## Pipeline Context

This skill is part of the development workflow pipeline: `issue` → `implement` → `test` → `commit` → `pr` → `review`. This skill is the **sixth** stage, invoked after the PR has been created and is ready for review. Its output — the consolidated review document — is a local artifact under `.sdlc/reviews/` that you and the user read manually to drive fixups. It is NOT auto-consumed by the `implement` skill, and because nothing is posted to GitHub, a later `sdlc_implement` call routes to `implement-continue` (not `implement-feedback`) unless the user separately surfaces the findings.

## Composition

A review runs through one or more **roles**, with N **reviewers per role**. The arguments appended below this prompt supply the role list and the per-role reviewer count:

- **Roles** — the role stems to review through (default: a single `general-purpose` role). Each role is a named lens with a blocking policy, discoverable via `sdlc_roles` and readable at `sdlc://guides/role/<stem>`.
- **Reviewers per role** — N independent reviewer subagents per role (default: 1).

The total number of reviewer subagents is **N × (number of roles)**. Each reviewer reviews the same diff but through exactly one assigned role's lens, confined to the files that role is mapped to, and returns structured findings. The main session agent then consolidates all reviewers' findings into the single review document. A reviewer NEVER writes a file or posts anything — it only returns findings.

**(re-review)** The same fan-out applies, and every reviewer stays a reviewer. On top of its normal lens-driven review of the current files, each one receives the subset of the seeded `review-<#>.md` findings whose `Reference` falls in its in-scope files and returns a disposition for each — close, reject, or carry — with evidence quoted from the current file. The consolidator folds those dispositions and any new findings into the updated finding set.

## Invariants

- MUST NOT post anything to GitHub. This skill produces a local document only — there is no `gh api .../reviews` call, no review event, and no inline comments. In **paths mode** the skill additionally runs no `gh` at all (no repo resolution, no PR fetch, no commit map).
- When the review proceeds to completion, MUST write exactly one consolidated document per invocation, at the endpoint-injected `Review document: <dir>/review-<iteration>.md` path (used verbatim), under the retained `Review document directory`. In PR mode `<dir>` is `.sdlc/reviews/issue-#<N>/` (`<N>` = the resolved linked issue); in paths mode `<dir>` is `.sdlc/reviews/<slug>/`, the endpoint-computed slug. The endpoint resolves `<iteration>` as the 1-based next unused iteration in both modes and injects the exact path, so the write never overwrites an earlier round. In PR mode the unresolved-issue branch (the PR has no linked issue) and the declined-large-diff branch may end without writing a document — no document is written when the run does not reach completion on those paths. (Both of those branches are PR-mode only; paths mode has no linked-issue resolution and no remote diff to decline.) **(re-review)** The injected `Review document:` path is the existing `review-<#>.md` rather than a new iteration, so the round is rewritten in place; a re-review never creates a new `review-<iteration>.md`.
- MUST write AND commit the document autonomously as the final step (step 10). Neither has an approval gate, on a fresh round or a re-review.
- **(re-review)** MUST commit each finding-set mutation separately, with a message that justifies that specific state change, and MUST leave the document internally consistent — header counts included — at every commit.
- MUST NOT force-add a path the target repository ignores. When the resolved repository ignores `.sdlc`, initialize `.sdlc` as its own repository instead (step 10).
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
- `Resolved issue: #<N>` — *(PR mode only)* the linked issue resolved by the endpoint via the `closingIssuesReferences` relationship (or an `unresolved` notice when the PR has no linked issue). Defines the `.sdlc/reviews/issue-#<N>/` path. Present on fresh rounds and re-reviews alike. Absent in paths mode.
- `Review document directory: .sdlc/reviews/<dir>/` — the directory holding this target's review rounds: `issue-#<N>/` in PR mode, or a slug derived deterministically from the raw `paths` strings in paths mode. In paths mode this line is always present (the endpoint computes the slug); in PR mode it is omitted on the `unresolved` branch. It is used to `mkdir -p` the review directory before writing. **(re-review)** Always present (the endpoint resolved the directory to load `review-<#>.md` from it).
- `Review document: <dir>/review-<iteration>.md` — the exact, pre-resolved write target for this round, used verbatim. On a fresh round the endpoint resolved `<iteration>` as the next unused iteration deterministically (never overwriting an earlier round); **(re-review)** it is instead the existing `review-<#>.md`, rewritten in place. Either way, do NOT glob the directory to recompute it. Present in PR mode (on the resolved-issue branch) and in paths mode; omitted on the PR-mode `unresolved` branch.
- `Re-review: review-<#>` — *(re-review only)* marks the run as a re-review of the existing `review-<#>.md`, present only when the user passed `--verify <#>`. Its presence is what switches the **(re-review)** behavior on.
- `Seeded findings —` followed by the pre-rendered findings of `review-<#>.md` — *(re-review only)* the endpoint appends the parsed findings of the document being re-reviewed, under that header line. These are the findings each reviewer dispositions; do NOT re-derive them from the file. The block opens with its own `Seeded from:` provenance line, deliberately labelled differently from the `Review document:` write target above it so the two cannot be confused.
- `Review repository: <absolute path>` — the repository review-document commits belong in, declared via the `review-repo` config key (never inferred from the filesystem). Present whenever a document will be written. The value `unresolved` means no repository could be determined; step 10 covers the question to ask the user in that case.
- `Review document in repository: <path>` — the same file the `Review document:` line names, addressed from the review repository's root instead of the working directory. Every `git` command in step 10 takes THIS path; `Review document:` is where the file is written. They differ whenever the repository is not the working directory, which is the normal case when `.sdlc` is its own repository. This directive and `Review snapshot in repository:` below are **omitted entirely** when `Review repository:` is `unresolved`, and each instead reads `<label>: unresolved` followed by an explanation when the path lies outside the resolved repository. Neither absence nor the literal `unresolved` is a path — step 10(a) stops on either, and the string is never passed to `git`.
- `Review snapshot directory: <dir>/snapshot-<#>/` — where this pass's capture of the reviewed code state is written, paired 1:1 with the document of the same number. Step 2 writes the contents directly here, at acquisition; step 10 commits them from here. Unlike the two repository-relative directives, this line is emitted whether or not a repository resolved, so the three do not appear and disappear together.
- `Review snapshot in repository: <path>/` — the snapshot directory addressed from the review repository's root, on the same terms as the document's repository-relative path. This is what `git add` takes.
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
  > 4. Return a structured summary: accomplishments, key artifacts (review document path, findings count, remaining blocking count, PR number), and the next pipeline step prompt from the skill

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
7. Dispatch reviewer subagents (N per role)
8. Consolidate the findings
9. Finalize the consolidated document
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

**(re-review)** Acquire the **current** state exactly as the active base mode does — the PR head's changed-file contents in PR mode, or the matched files' whole contents in paths mode. Reviewers judge both the seeded findings and any new defect against these current files, so this capture is mandatory; the seeded `review-<#>.md` findings describe the *prior* state, not the state to read. (PR mode still verifies the local tree is at the PR head so the reviewers' reads line up with the recorded sha.)

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

#### Capture the reviewed state (all modes)

The findings reference `file:line` in a repository whose history is routinely rewritten before merge, so the commits a review was performed against do not survive. Anchor the pass to a point that does. Run this **here**, at acquisition, so the captured state matches what the reviewers read — not later, when the tree may have moved. That correspondence is *proved* only on the branch where the PR-head verification above succeeded; when you continued past a `HEAD != headRefOid` mismatch, the capture records the mismatch rather than claiming a correspondence it cannot support.

The anchor is the merge-base with the upstream default branch, which by assumption never changes. Everything above it is collapsed into one synthetic commit whose tree is the reviewed state and whose parent is that merge-base. It descends from no branch commit, so rebasing, squashing, and fixups cannot invalidate it.

The three blocks below are ONE sequence — run them in a single shell invocation. `$ref`, `$base` and `$tree` flow between them, and shell state does not survive between tool calls; splitting them would leave `GIT_INDEX_FILE` unset and stage the user's real index.

Resolve the anchor ref explicitly, and fail loudly when it cannot be resolved — an unresolvable ref otherwise leaves `base` empty and `git commit-tree -p ""` errors in the middle of the block:

```bash
# `origin` is the FORK when working from a fork, which is the case step 1 exists
# for, so prefer a distinct `upstream` remote when one is configured. The DEFAULT
# branch is the ref that never moves; the PR's base branch is not the same thing
# and may be deleted once a stacked PR merges.
remote=$(git remote | grep -qx upstream && echo upstream || echo origin)
git remote set-head "$remote" -a >/dev/null 2>&1 || true
ref=$(git symbolic-ref -q "refs/remotes/$remote/HEAD") || ref=
[ -n "$ref" ] || { echo "review: no default-branch ref on '$remote' — cannot anchor the snapshot" >&2; exit 1; }
base=$(git merge-base HEAD "$ref") || { echo "review: no merge-base between HEAD and $ref" >&2; exit 1; }
```

Record `$ref` as `anchor_ref` in `meta.json` so a reader can tell which branch the base was taken from. Reviewing the default branch itself yields `base == HEAD` and an empty patch, which is the correct representation of "the reviewed state is the base".

Then capture the tree. The index is built from **empty**, not from `HEAD`: seeding it from `HEAD` stages every path `HEAD` tracks — including a tracked review repository — and the exclusion pathspec below only declines to *update* those entries, it never removes them. The reviewed state IS the working tree, so the `HEAD` baseline buys nothing, and worktree deletions are naturally absent.

```bash
export GIT_INDEX_FILE=$(mktemp -u)
git read-tree --empty
git add -A -- ':!.sdlc'          # or the configured review-repo path inside this tree
tree=$(git write-tree)
unset GIT_INDEX_FILE

# An all-excluding pathspec silently yields the empty tree, which would pass its
# own integrity check on every pass while capturing nothing.
[ "$tree" = 4b825dc642cb6eb9a060e54bf8d69288fbee4904 ] \
  && { echo "review: snapshot tree is empty — the exclusion pathspec covers the whole tree" >&2; exit 1; }
```

Write the artifacts straight into the injected `Review snapshot directory`, clearing it first. Nothing is held for a later step: the directory is a directive, so every step addresses it identically without carrying shell state across tool calls. The directory is overwritten each pass, so a stale `review.patch` must not be left to survive beside a `meta.json` that no longer describes it.

```bash
mkdir -p <Review snapshot directory>
rm -f <Review snapshot directory>/review.patch <Review snapshot directory>/meta.json

snap=$(git commit-tree "$tree" -p "$base" -m "review snapshot")
git diff --binary --full-index "$base" "$snap" > <Review snapshot directory>/review.patch
```

`git add -A` honours `.gitignore`, so ignored files stay out of the snapshot. They are not part of the reviewed state. The review repository is excluded by pathspec rather than left to `.gitignore`, since a project that tracks `.sdlc` would otherwise capture it — and starting the index empty is what makes the exclusion actually hold in that case. When `Review repository:` names a path inside the reviewed tree other than `.sdlc`, exclude that path instead. A review repository that resolves to `.` or to the reviewed repository's own root is a configuration error rather than an exclusion — `':!.'` excludes everything — so refuse it and tell the user to move the review repository to a subdirectory or outside the tree.

The synthetic commit is a construction device, not a durable artifact — nothing references it, so it is subject to garbage collection. What travels is `base`, the patch, and `tree`; those three reconstruct the state in any clone that can reach `base`.

Write `meta.json` beside the patch, at `<Review snapshot directory>/meta.json`:

```json
{
  "mode": "pr",
  "pr": 33,
  "pass": 1,
  "upstream": "<git remote get-url $remote>",
  "anchor_ref": "<the $ref resolved above>",
  "base": "<base sha>",
  "tree": "<tree sha>",
  "head": "<HEAD sha, for context only — expected to be rewritten>",
  "head_matches_target": true,
  "captured_at": "<ISO-8601 UTC>"
}
```

`pass` is `<k>`, how many passes have run against this document — `1` on a fresh round, and on a re-review the `<k>` carried in the existing document's pass line, incremented by one. (Step 10 reads that header anyway, for the fields the seeded block does not carry.) It is the only thing distinguishing one capture from another, since the directory is overwritten.

`head_matches_target` records whether the PR-head verification above succeeded. **(PR mode)** When `HEAD != headRefOid` and you continued anyway, write `false` and record `"target_head": "<headRefOid>"` beside it: `tree` still states what was captured, but with the flag `false` it is NOT a claim about the PR head, and the restore comparison in step 10 cannot answer whether what merged is what was reviewed. **(paths mode)** There is no PR head, so omit the field entirely.

In paths mode `pr` is omitted and `mode` is `paths`. When the reviewed tree is **not** a git repository, write `meta.json` alone with `"vcs": "none"`, a null `base`, no `anchor_ref`, and no patch; there is nothing to anchor to and that is worth recording explicitly. The `rm -f` above is what keeps a prior pass's patch from surviving into this case.


### 3. Resolve the review-document path

**(re-review)** The injected `Review document:` line names the existing `review-<#>.md`, which this round rewrites in place, so there is no new iteration to compute — the endpoint already resolved the directory and named the file. Apart from that, this step reads exactly as it does for a fresh round.

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

**(re-review)** Each reviewer stays a reviewer and performs the full review above — it hunts for defects in the current files exactly as it would on a fresh round. It is additionally handed the seeded findings in its scope and must account for each one. APPEND these bullets to the brief above; do NOT remove any of the existing ones:

> - You are **re-reviewing**: this target already has a round of findings, and `review-<#>.md` is being rewritten in place. The seeded findings in your scope — the subset whose `Reference` falls in your in-scope files: `<the seeded findings for this role's files>`. (Findings outside your in-scope files belong to other reviewers; ignore them.)
> - For EACH seeded finding, read the **current** contents of the referenced file and return exactly one disposition, with concrete evidence quoted from that file:
>   - **close** — the remediation the finding calls for is present. Quote the text that shows it was addressed.
>   - **reject** — the finding does not hold up as written: it cites a guide rule that is not in the guide text supplied above, names the wrong symbol or reference, or carries a severity your lens does not support. Say which, and give either the corrected finding or a recommendation to withdraw it outright.
>   - **carry** — the defect is still present and the finding still states it correctly. Quote the evidence that it remains.
> - Return your dispositions ALONGSIDE your new findings — a re-review produces both. A defect introduced by the remediation of a seeded finding is a **new finding**, not a disposition; raise it normally.

**Other LLM assistants:** If subagents are unavailable, perform each role's review inline, one role at a time, holding each role's findings — and, in a re-review, its dispositions — separately so they can be consolidated in step 8.

### 8. Consolidate the findings

**(re-review)** Fold the seeded findings' dispositions in FIRST, then run the consolidation below unchanged over the reviewers' new findings:

- **Apply each disposition** — a finding whose consolidated disposition is **close** is REMOVED from the document; one that is **rejected** is either corrected in place (re-tiered, reference fixed, evidence restated) or removed when the recommendation is to withdraw it outright; one that is **carried** stays as it is. When reviewers disagree about a seeded finding, **carry** wins over **close** — a single reviewer holding that the defect remains keeps it open — and a **reject** is applied only when no reviewer carried it.
- **Keep finding IDs stable** — a carried or corrected finding KEEPS its original id. Ids are cited in the commit history and in `sdlc_implement --review <#>`, so they MUST NOT be renumbered between passes. New findings take the next unused id in their tier, and the ids of closed or rejected findings are retired, never reused.
- **Count what changed** — record how many findings were closed, rejected, and added this pass, and how many blocking and advisory findings remain open. These fill the template's pass header, drive the commits in step 10, and decide the prompt in step 11.

The main session agent (NOT a reviewer) merges every reviewer's findings into one set:

- **Dedup within a role** — collapse findings from the same role that name the same defect at the same reference into a single finding, recording the reviewer agreement (e.g. `4/5 reviewers`).
- **Merge across roles** — combine findings about the same defect raised by different roles into one entry that records every role that raised it.
- **Highest severity wins** — assign each finding the highest severity any role gave it. Where roles disagree (one rated it Blocking, another Advisory or did not raise it), NOTE the dissent on the finding.
- **Assign stable IDs** — `B1, B2, …` for blocking findings, `A1, A2, …` for advisory, in a stable order. **(re-review)** Only NEW findings are assigned here, taking the next unused id in their tier; findings carried over from the seeded set keep the ids they already have.
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

**(re-review)** Present the updated document the same way, and additionally summarize what moved this pass — which findings closed, which were rejected and why, and which are new — so the user can see the round's progress before it is written and committed. The absence of an approval gate is the same: fold in any adjustment the user offers, then go to step 10.

### 10. Write and commit the review document

The document is written AND committed autonomously — neither has an approval gate. The one exception is an unresolved repository, which is a question only the user can answer.

**(a) Resolve the repository.** The `Review repository:` directive names where review-document commits belong. It is **declared, never inferred** — the endpoint reads it from the `review-repo` config key, falling back to `.sdlc` only when that is already a repository.

- `Review repository: <absolute path>` — commit there. Call it `<repo>` below.
- `Review repository: unresolved` — STOP before writing anything and ask the user, exactly as an unresolved linked issue is handled. Offer the two options the directive names: point `review-repo` at an existing repository, or create one with `git init .sdlc`. Once they choose, record it:

  ```bash
  git init .sdlc      # only when they chose to create one
  ```

  Then write their choice into `.sdlc/config.json` as `"review-repo"` (creating the file if absent, preserving any existing keys), so the question is asked once and never again. MUST NOT guess a repository, and MUST NOT commit until one is resolved.

**Validate the resolved repository before committing.** Two checks. Both are cheap, and both are silent failures when skipped.

First, the repository-relative directives may themselves be unresolved. `Review document in repository:` and `Review snapshot in repository:` are omitted entirely when no repository resolved, and each carries the literal value `unresolved`, followed by an explanation, when the path lies outside `<repo>`. Note that `Review snapshot directory:` is emitted either way, so the three do not appear and disappear together. If either repository-relative directive is absent or reads `unresolved`, STOP and relay the explanation to the user — never pass the string `unresolved` to `git add`.

Second, the repository may ignore the review documents, in which case the commit would silently do nothing:

```bash
git -C <repo> check-ignore -q <Review document in repository>
```

A zero exit means the path is ignored. Do NOT force-add it — tell the user their `review-repo` ignores the review documents, and ask them to unignore the path or name a different repository.

**(b) Resolve the branch.** When a `Review commit branch: <branch>` directive is present AND `<branch>` differs from the branch checked out in `<repo>`, do every write and commit below inside a temporary worktree, so the tree under review is never disturbed.

A freshly initialized repository has no commits, and `git worktree add` cannot attach to a branch that does not exist yet — the first-run state for every project that sets `review-branch`. Give `HEAD` a commit first, then create the branch if needed:

```bash
git -C <repo> rev-parse --verify -q HEAD >/dev/null \
  || git -C <repo> commit -q --allow-empty -m "review: Initialize the review document repository"

worktree=$(mktemp -d)
if git -C <repo> show-ref --verify --quiet refs/heads/<branch>; then
    git -C <repo> worktree add -q "$worktree" <branch>
else
    git -C <repo> worktree add -q -b <branch> "$worktree"
fi
# … write and commit inside "$worktree" …
git -C <repo> worktree remove "$worktree"
```

When the directive is absent, or names the branch already checked out, write and commit in place.

**(c) Write the document.** Two paths are injected and they are not interchangeable:

- `Review document: <path>` — relative to the working directory. This is where the document is WRITTEN, so the reviewed tree and `sdlc_implement` both find it where they expect.
- `Review document in repository: <path>` — the same file addressed from `<repo>`'s root. This is what every `git` command below takes. When a worktree is in use, the document is written at this path inside `"$worktree"` instead.

Create both directories and write:

```bash
mkdir -p <Review document directory> <Review snapshot directory>
cp "$scratch/review.patch" "$scratch/meta.json" <Review snapshot directory>
```

The snapshot files come from the scratch directory step 2 filled. Do NOT regenerate them here — recapturing at this point would record the tree as it stands now rather than as the reviewers read it, and the two can differ.

**(c) Write the artifacts.** Two paths are injected and they are not interchangeable:

- `Review document: <path>` — relative to the working directory. This is where the document is WRITTEN, so the reviewed tree, `sdlc_implement --review` and the next `sdlc_review --verify` all find it where they expect.
- `Review document in repository: <path>` — the same file addressed from `<repo>`'s root. This is what every `git` command below takes.

The snapshot is already on disk: step 2 wrote `review.patch` and `meta.json` into `<Review snapshot directory>` at acquisition. Do NOT regenerate them here — recapturing at this point would record the tree as it stands now rather than as the reviewers read it, and the two can differ.

**What is written depends on the round.**

- **(fresh round)** Write the full document at `Review document:`, following the bundled template structure exactly: the header — including the pass line carrying the open counts and this pass's deltas — the severity-tiered findings (blocking first) with stable IDs / titles / severities / `Reference` (`file:line`, or a file-level / issue-level reference for a line-less finding) / Issue + evidence / Remediation checklist (`[x]` recommended, `[ ]` alternatives, `Other: ___`) / optional Tests-to-add, plus the cross-cutting-decisions section. **(PR mode)** also include each finding's `Touched commit` and the fixup-mapping section; **(paths mode)** omit both — there are no commits to attribute or fold into.
- **(re-review)** Write NOTHING to `review-<#>.md` here. Leave it on disk at the seeded content this pass found, because (d) walks it forward one finding-set mutation at a time and each of those mutations is its own commit. Writing the reconciled document now would leave (d) with no residual change to apply, collapsing the pass into a single commit and defeating the per-mutation history. Step 9's consolidated document is the **target state** (d) walks toward, not something to write here.

**Where it is written depends on the branch resolved in (b).**

- **In place** (no worktree) — the injected paths are all there is. The document goes to `Review document:`, the snapshot is already at `<Review snapshot directory>`, and the `<repo>`-relative paths address those same files.
- **Worktree** — write to the working-directory paths **in addition to** the copies inside `"$worktree"`, never instead of them. The working-directory copies are what the reviewed tree and the rest of the pipeline read; the copies inside the worktree are what gets committed. Mirror both artifacts:

  ```bash
  worktree="${TMPDIR:-/tmp}/sdlc-review-<#>"
  mkdir -p "$worktree/$(dirname <Review document in repository>)" "$worktree/<Review snapshot in repository>"
  cp <Review document> "$worktree/<Review document in repository>"
  cp <Review snapshot directory>/* "$worktree/<Review snapshot in repository>"
  ```

  On a re-review, repeat the document `cp` after each mutation in (d), so the committed copy tracks the working-directory copy commit by commit.

Do NOT post anything to GitHub.

**(d) Commit.** On a **fresh round** the document and its snapshot are a single commit:

```bash
git -C <repo> add <Review document in repository> <Review snapshot in repository>
git -C <repo> commit -F <message-file>
```

```
review: Add review-1 with 3 blocking and 2 advisory findings
```

**(re-review)** The snapshot is committed FIRST, before any finding mutation, because the dispositions in this pass were derived from it:

```bash
git -C <repo> add <Review snapshot in repository>
git -C <repo> commit -F <message-file>
```

```
review: Capture the reviewed state at <short-base>..<short-tree>
```

Each finding-set mutation is then its OWN commit, walking `review-<#>.md` from its seeded content toward step 9's consolidated result. Apply the mutations in the order **close → reject → add**, so the history reads as what got fixed, what was wrong, and what is newly broken. For each mutation in turn: edit the document to apply ONLY that change — updating the header's counts along with it, so every commit leaves the document internally consistent — then stage and commit just that change:

```bash
git -C <repo> add <Review document in repository>
git -C <repo> commit -F <message-file>
```

After the last mutation, the file on disk MUST equal step 9's consolidated document. If it does not, a mutation was missed — apply the remainder as one further commit rather than amending the history.

Commit messages follow the `commit` skill's subject rules — 72 characters maximum, imperative mood, first word capitalized, no trailing period, plain text with no markup — with one addition: review-document commits take a `review:` type prefix, which exists for this purpose and is never used for code commits. The subject names the disposition and the finding id, and carries the justification when it fits; longer reasoning goes in the body.

```
review: Close B2 — nil guard now present at server.py:318
review: Reject B1 — cited MUST rule is not in the style guide
review: Add B4 — new guard misses the paths-mode branch
```

A rejection that withdraws a finding outright and one that corrects it are both `Reject`; the subject says which, and the body carries the reasoning. Do NOT post anything to GitHub.

**Restoring a snapshot.** In any clone that can reach `base`. Run it in a detached worktree so the recipe never mutates the tree it is invoked from:

```bash
restore="${TMPDIR:-/tmp}/sdlc-restore-$$"
git worktree add -q --detach "$restore" <meta.base>
cd "$restore"
git apply <path to review.patch>

# Mirror the capture exactly — same empty index, same exclusion pathspec.
# `export` is required: a `VAR=value cmd` prefix scopes to the single command it
# prefixes, so `git add` would use the throwaway index while `git write-tree`
# read the REAL one and returned base's tree on every non-empty patch.
export GIT_INDEX_FILE=$(mktemp -u)
git read-tree --empty
git add -A -- ':!.sdlc'        # the same pathspec the capture excluded
git write-tree                 # MUST equal meta.tree
unset GIT_INDEX_FILE
```

The recomputed tree SHA is content-addressed, so equality with `meta.tree` proves the restoration is byte-identical to what was captured. When `meta.head_matches_target` is `true`, comparing `meta.tree` against the tree of whatever eventually landed on the default branch answers a further and useful question — whether what merged is what was reviewed. When it is `false`, the capture was not taken at the PR head and cannot answer that.


### 11. Prompt the user with next steps

After the document is written, prompt the user. **(PR mode):**

> Review written to `.sdlc/reviews/issue-#<N>/review-<iteration>.md`. This document is a local artifact — nothing was posted to GitHub, and the `implement` skill does not read it automatically. Read it yourself (or with the user) and use each finding's pre-selected remediation and fixup-mapping entry as the work list, applying the fixups directly; then re-run `commit`, `pr`, and `review` as needed. When the findings are resolved and you are satisfied, run `gh pr ready <number>` to mark the PR ready for merge.

**(PATHS mode):**

> Review written to `<Review document directory>/review-<iteration>.md`. This document is a local artifact — nothing was posted to GitHub, and the `implement` skill does not read it automatically. Read it yourself (or with the user) and use each finding's pre-selected remediation as the work list, applying the fixups directly to the reviewed files; then re-run `review` over the same paths as needed. There is no PR or fixup mapping in this mode.

**(re-review):** After the document is written and committed, prompt based on the remaining blocking count:

> `review-<#>.md` rewritten in place — `<B>` blocking, `<A>` advisory remaining. Closed `<c>`, rejected `<r>`, added `<a>` this pass, each as its own commit in `<repo>`. Nothing was posted to GitHub.

- When `<B>` > 0:
  > `<B>` blocking finding(s) remain. Re-enter the implement loop to address them: `sdlc_implement <target> --review <#>` (the same target, with the review iteration `<#>`). After fixing, re-run `sdlc_review --verify <#>` for the next pass.
- When `<B>` == 0:
  > No blocking findings remain — review `<#>` is complete. `<A>` advisory finding(s) are carried and do not gate; run another pass if you want them addressed. In PR mode you may now mark the PR ready (`gh pr ready <number>`); in paths mode the reviewed artifacts are clean.

DO NOT proceed on your own.

## Edge Cases

**Paths mode runs no `gh` and posts nothing:** In paths mode the skill performs no repo resolution, no PR fetch, and no commit-map enumeration — there is no GitHub interaction at all. The document lands under the endpoint-computed `.sdlc/reviews/<slug>/` directory. The PR-only edge cases below (`PR is already merged or closed`, `No linked issue`, and `Very large diffs`) do not apply in paths mode.

**No files matched the paths/globs (paths mode):** If expanding the `Target paths:` entries against the working tree yields no files (every literal path is missing and every glob matches nothing), inform the user that nothing matched, list the entries you tried, and stop — there is nothing to review and no document is written. If only some entries are empty, note the misses and proceed with the files that did match.

**PR is already merged or closed (PR mode):** Inform the user that the PR is not open and stop.

**No findings:** If every reviewer returns clean, present the empty-findings document (header plus empty severity tiers) as informational (step 9) and write and commit it autonomously (step 10) so the round is recorded; inform the user that no issues were found and the target looks clean. There is no approval gate on the review (produce) document — the empty-findings document is written the same way a document with findings is. Do not post anything.

**Re-review target has no review document:** This is raised upstream by the tool before this skill runs — when the target has no `review-<#>.md` (the directory is absent or that iteration is missing), `sdlc_review --verify <#>` raises a `ValueError` and the skill is never dispatched. You will not reach this skill with a missing review document, so there is no in-skill fallback to handle; the user sees the tool's error and runs a fresh `review` first.

**Every seeded finding closes (re-review):** When every seeded finding is closed and no new one is raised, the document is rewritten with empty severity tiers and a pass header recording the closures. Write and commit it exactly as usual — one commit per closure — so the chain's completion is recorded in the history, then give the `<B>` == 0 next-step prompt.

**No linked issue (PR mode — the endpoint reports `Resolved issue: unresolved`):** Ask the user which issue the PR addresses; do not guess the `.sdlc/reviews/issue-#<N>/` path. *(Paths mode has no linked issue and uses the injected `<slug>` directory, so this never arises there.)*

**Unknown / misspelled role:** A requested role with no discovered document (not among `sdlc_roles`, or whose `sdlc://guides/role/<stem>` read returns `Error: guide ... not found`) MUST halt the run with a corrective prompt asking the user to fix the role name. Do NOT dispatch a reviewer with an empty or error lens.

**A role exists but has no `guide-map.role` entry:** `sdlc_role_scope` returns empty for it just as it does for an unmapped role. Warn the user the role will contribute nothing (it is not scoped to any files), then skip it.

**A role maps to globs that match none of the reviewed files:** Note in the header that the discovered, mapped role had no in-scope files on this target (the PR's changed files, or paths mode's matched files) and skip its reviewers; it contributes no findings.

**Binary files:** Binary files MUST be skipped during analysis — in both the PR diff and a paths-mode match. Note their presence to the user but do not attempt to review them.

**Very large diffs (PR mode):** For PRs with more than 20 changed files or more than 1000 lines changed, the agent SHOULD summarize the scope to the user and ask whether to review the full diff or focus on specific files before dispatching reviewers. *(This is PR-mode only — paths mode reviews exactly the files the user named.)*

**Files outside the repository's guide coverage:** If reviewed files are in a language or domain not covered by any project guide, review them for general correctness and code quality only. Do not fabricate guide requirements that do not exist.
