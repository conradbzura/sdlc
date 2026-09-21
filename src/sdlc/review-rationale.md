---
name: review-rationale
description: >
  Design rationale for the `review` skill. Explains WHY specific blocks in
  `sdlc_review`'s workflow are shaped the way they are. Read on demand — when a
  block misbehaves, or before deviating from an instruction whose reason is not
  obvious. Carries no rules of its own.
---

# Review skill — design rationale

**This document carries NO rules.** Nothing here changes, adds to, or qualifies
anything `review.md` requires. Every MUST, SHALL and STOP lives in the skill;
what lives here is the reasoning behind them — the derivations, the failures
that produced a guard, and the claims that were verified by execution.

Read it **on demand**: when a command block does something you did not expect,
or when you are about to deviate from an instruction you do not understand.
Never read it as a precondition for executing a step, and never quote it into a
reviewer's brief — a reviewer is reviewing code, not this protocol.

Addresses are the `R<n>` ids, not the headings. `review.md` cites `§R4.3`; the
wording of a heading may change, the id may not.

## R1. Modes, markers and the re-review layer

Reviewing before reconciling is what keeps the prior round from setting the agenda for this one, and withholding the seeded set is what makes that ordering real rather than merely instructed. This skill is the **sixth** stage, invoked after the PR has been created and is ready for review. Nothing is posted to GitHub, but the document IS consumed by the `implement` skill: in PR mode a later `sdlc_implement <N>` reads the latest `review-<iteration>.md` for the closing issue straight off disk and routes to `implement-feedback`, walking each finding's pre-selected remediation through a per-finding approval gate (`--review <int>` selects an earlier iteration). Paths-mode documents are not keyed to an issue and so are not picked up automatically; read and apply those directly.

## R3. Arguments — the directive dictionary's fine print

The endpoint emits these directives; the skill describes them. What follows is the detail each description sheds — which branches omit a directive, and why two similar-looking paths are not interchangeable.

In paths mode this line is always present (the endpoint computes the slug); in PR mode it is omitted on the `unresolved` branch. **(re-review)** Always present (the endpoint resolved the directory to load `review-<#>.md` from it). On a fresh round the endpoint resolved `<iteration>` as the next unused iteration deterministically (never overwriting an earlier round); **(re-review)** it is instead the existing `review-<#>.md`, rewritten in place. Present in PR mode (on the resolved-issue branch) and in paths mode; omitted on the PR-mode `unresolved` branch. `Review document in repository: unresolved` therefore survives only for a path symlinked out of an otherwise valid repository. They differ whenever the repository is not the working directory, which is the normal case when `.sdlc` is its own repository. Step 2 captures into a staging directory at acquisition and step 10 promotes the result here once every gate has cleared, then commits from here. This line is emitted whenever a document will be written — it does not depend on whether a *repository* resolved, so it does not come and go with the two repository-relative directives, but it IS absent alongside `Review document:` on the PR-mode unresolved-issue branch.

## R4. Step 2 — the reviewed-state capture

The findings reference `file:line` in a repository whose history is routinely rewritten before merge, so the commits a review was performed against do not survive. Anchor the pass to a point that does.

### R4.1 The anchor, and why the synthetic commit is disposable

The skill states the anchor: the merge-base with the upstream default branch, which by assumption never changes. Everything above it is collapsed into one synthetic commit whose tree is the reviewed state and whose parent is that merge-base. It descends from no branch commit, so rebasing, squashing, and fixups cannot invalidate it. The synthetic commit is a construction device, not a durable artifact — nothing references it, so it is subject to garbage collection.

**When the anchor cannot be resolved.** The skill's rule is that this aborts the capture and not the round. The reason it has to be a soft failure is how ordinary the state is: `refs/remotes/origin/HEAD` is absent after `clone --single-branch`, after `git init` plus `git remote add`, and in most CI checkouts, and `set-head -a` cannot recover it offline, behind an auth prompt, or on a sandboxed runner.

### R4.2 The empty index, the `top` anchor, and the single invocation

(`GIT_INDEX_FILE` is a separate matter: block 2 both exports and unsets it within itself, so a split cannot leave it dangling. `export` rather than a `VAR=value` prefix is still required there, for the reason the restore recipe in step 10 spells out.) The index is built from **empty**, not from `HEAD`: seeding it from `HEAD` stages every path `HEAD` tracks — including a tracked review repository — and the exclusion pathspec below only declines to *update* those entries, it never removes them. The reviewed state IS the working tree, so the `HEAD` baseline buys nothing, and worktree deletions are naturally absent. The pathspec is anchored with `top` because git resolves pathspecs against the **current working directory**: a bare `':!.sdlc'` run from a subdirectory excludes nothing, and the capture then embeds a gitlink to the review repository and changes its tree SHA on every pass. `meta.json` is written **by this block**, not transcribed afterwards: `$remote`, `$ref`, `$base` and `$tree` do not survive the end of the invocation, and `$tree` in particular cannot be recovered without redoing the whole empty-index sequence, by which time the tree may have moved — destroying the exact correspondence this capture exists to guarantee.

### R4.3 Why the exclusion pathspec is relative

`:(exclude,top)` takes a path relative to the repository root. The absolute form — which is literally what the `Review repository:` directive emits, so pasting the directive value verbatim is the likeliest substitution slip — matches nothing, and therefore excludes nothing.

### R4.4 The blocklist post-mortem — why the guard states what it accepts

The guard states what it ACCEPTS. A blocklist here has been wrong twice, in both directions: `.` and `..` were enumerated while the absolute form — which is literally what `Review repository:` emits, so pasting the directive value is the likeliest slip — was not, and neither was the literal `unresolved`. Both of those exclude NOTHING, verified by execution: the review repository is captured into the snapshot of the code it reviews and the tree SHA then churns every pass regardless of the code, defeating the one question the capture exists to answer. The empty-tree sentinel below cannot catch it, because it only fires on over-exclusion, and the restore recipe mirrors the same wrong pathspec back out of `meta.excluded` so the integrity check still passes.

### R4.5 `.gitignore`, tracked-and-ignored paths, and the review repository

Note that a path which is both **tracked and ignored** — force-added at some point, or ignored after the fact — is dropped too, although it is genuinely part of the reviewed state; the integrity check cannot surface this, because the restore mirrors the same empty index and pathspec and still reproduces `tree`. The review repository is excluded by pathspec rather than left to `.gitignore`, since a project that tracks `.sdlc` would otherwise capture it — and starting the index empty is what makes the exclusion actually hold in that case. A review repository that resolves to the reviewed tree's own root, or to any ancestor of it, is a configuration error rather than an exclusion, and the failure is quieter than it looks. The unanchored `':!.'` does exclude everything and yields the empty tree, which the sentinel above catches — but the **anchored** form this block instructs does not: with a relative path of `.` or empty, `':(exclude,top).'` excludes NOTHING, so the capture embeds the review repository in the snapshot of the code it reviews, the tree SHA churns every pass regardless of the code, and no sentinel fires. `git_state.resolve_review_repo` refuses such a value for exactly this reason; if the derived relative exclusion path is ever `.` or empty, abort here rather than capturing.

### R4.6 Why the capture stages rather than writing in place

Despite the "(all modes)" heading, `Review snapshot directory:` is emitted only when a document will be written — so it is absent on the PR-mode unresolved-issue branch, which this subsection runs *before* step 3 resolves. It is NOT absent on the declined-large-diff branch: the endpoint emits it whenever a document will be written, which depends solely on issue resolution, and the endpoint has no knowledge of diff size. That branch declines later, in step 2's own edge case, with the capture already staged and never promoted. On the unresolved-issue branch step 3 STOPS the run — the directory never becomes known within this invocation, so there is nothing to come back for — and the capture happens on the re-run, once the linked issue makes the directive available. Writing in place here would destroy the previous pass's capture before step 5's role-validation halt, before the declined-large-diff branch, and before step 10(a)'s "STOP before committing" — which would make that promise false the moment it is reached.

## R5. Step 3 — resolving the issue, the write target, and the commit destinations

_Pending extraction._

The MCP endpoint performs the relationship check via GitHub's `closingIssuesReferences` connection (issues that close when the PR merges, whether linked via a `Closes #N` keyword or the GitHub UI), with a `Closes` / `Fixes` / `Resolves #N` PR-body fallback. When several issues are linked, the endpoint resolves the **first** of them (the connection has no ordering guarantee), so `<N>` is one closing issue, not necessarily the only one. Their answer cannot be used: directives are injected at tool-call time and cannot appear mid-run, and `Resolved issue:` is derived from GitHub rather than from the reply, so re-deriving the path here is guessing under another name. The endpoint resolved `<iteration>` as the next unused iteration deterministically (never overwriting an earlier round), so you do NOT glob the directory or compute `iteration = max + 1` yourself — take the injected path as-is. This holds in both base modes: in **PR mode** the injected path is `.sdlc/reviews/issue-#<N>/review-<iteration>.md`, and in **PATHS mode** it is `<Review document directory>/review-<iteration>.md` under the endpoint-computed slug directory (successive paths-mode reviews of the same target accumulate their rounds there).

## R6. Steps 5–6 — role validation and the stale-graph rule

The summary lands in the reviewer brief's "architectural context" slot, where it reads as ground truth and competes with the diff for attention — so a graph describing a layout that no longer exists is worse than no graph at all, in all N briefs at once. This project's own graph is the worked example — analyzed at `"initial"`, indexing markdown only, with node ids under a directory layout the tree no longer has.

## R7. Step 7 — the two-turn dispatch

_Pending extraction._

### R7.1 Why the seeded read-back is persisted to disk



Between this read and its use sits the seeded block, N phase-1 dispatches with the diff interpolated, N phase-2 dispatches and the whole consolidation — the longest span in this skill, and the middle of your context. This skill already refuses to carry a value across that kind of distance twice (step 3 writes the commit destinations to a scratch file; step 9 writes its target to disk "precisely so this check reads ground truth from the filesystem rather than comparing the file against the orchestrator's recollection"), and this is the one value whose loss the Invariants call irreversible. There is also no detection: the count reconciliation below checks the *enumeration* only, and 10(d)'s terminal `diff` compares the document against a target built by the same context that may already have dropped the fields.

### R7.2 Why the count reconciliation uses awk and not `grep -c`

A raw count therefore reports a mismatch on a document that parsed perfectly, naming phantom ids no pass can resolve, and a MUST-STOP gate that fires on healthy input is a gate an agent learns to reason past — at which point the genuinely drifted heading it exists for goes through. The silent-drop path this guards is narrower than it looks, and worth stating exactly, because a wrong reason invites the conclusion that the gate is obsolete. A `### <id> — ` heading the parser cannot read *inside* a tier does NOT vanish: `pr_state.parse_review_document` raises `ValueError` on it, which propagates out of the endpoint before this skill is ever dispatched, so you would never reach step 7 to notice. What IS skipped silently is a well-formed finding heading that has drifted **outside** the Tier 1 / Tier 2 regions — below `## Rejected in earlier passes` or `## Cross-cutting decisions`, or above `## Tier 1` — where the parser's severity is `None` and the heading is passed over without raising. Under the "block is authoritative" rule that finding is then deleted from the document with no disposition and no commit message. Git history is a recovery path, not a detection path.

### R7.3 Why the inline path cannot claim the blindness guarantee

There is no separate phase-1 prompt to withhold anything from: the endpoint appends the whole `Seeded findings` block to the tool return you are reading right now, and on the inline path you ARE the reviewer — so your phase-1 pass is conditioned on the seeded text, which is the exact failure the ordering exists to prevent. Prompt omission alone would not be enough — the prior round's findings sit at a fixed, conventional, guessable path *inside the tree the reviewer is reviewing*, put there by step 10 precisely so the next `--verify` finds them, and the brief otherwise grants "You MAY read any other file for context". The prohibition is what closes that, and the two together are what earn step 8's treatment of an independent rediscovery as stronger evidence than agreement.

### R7.4 Why seeded findings route by originating role

A reference match leaves the `(cross-cutting — no single line)` and `issue acceptance criterion #<n>` references — both of which the brief above actively invites — assignable to nobody, and it strands any finding whose file has since left the changed set. Role routing has no such gap. Step 8 defaults a missing disposition to carry — the safe direction — but silently, and dropping an entry from a long enumeration is a well-documented failure mode at the subset sizes this reaches. Routing the gap back to the reviewer as an external observation is cheap and is the pattern this skill prefers elsewhere.

## R8. Step 8 — the disposition rules and their counterexamples

_Pending extraction._

### R8.1 Retired ids and the max(retired ∪ open) high-water mark

Computing it from the survivors alone is wrong because closed and rejected findings are deleted from the document, so with `B1` closed the next pass sees only `B2`, reuses `B1`, and silently re-points every commit-history and implement-loop citation of `B1` at a different defect. Computing it from the `Retired ids` line alone is wrong for the mirror reason: that line records only ids since closed or rejected, so whenever the highest-ever id is still open — the normal case — it is not the maximum. Run the same example the other way: `B1` closed and `B2` open makes `Retired ids` = `B1`, and "next above the retired line" yields `B2`, colliding with the finding that is still there.

### R8.2 Re-tiering and the `**(BLOCKING)**` marker

`parse_review_document` reads the heading marker as authoritative OVER the enclosing tier, so a finding moved to Tier 2 that keeps its marker is re-seeded as blocking on the next pass and the termination predicate never clears — a reviewer that correctly rejects an over-severe finding would produce a chain that cannot end.

### R8.3 Rediscovery, corroboration, and the default composition of one

The `rediscovered` column is the reviewer's own judgement of its own prior trace, made in the turn in which it has just been shown the answer — but you collected its phase-1 findings verbatim in step 7 and can check. This is the same ground-truth-over-recollection move step 9 makes for its target file. Treat it as stronger evidence absent a contrary signal, not as an override that cannot be argued with. A phase-1 finding matching nothing in the seeded set is new and takes a fresh id below.

`close` stays autonomous too, but not unconditionally: it also removes a blocking finding from the termination predicate, it is also decided by one agent at the default composition, and it leaves less behind than a rejection does (a bare id in `Retired ids`, where a rejection keeps its rationale in the ledger). A model asked whether its own prior round's finding was fixed is the canonical premature-completion case, and the two safeguards that exist — carry-beats-close and rediscovery-outranks-close — both need a second opinion the default composition does not supply.

### R8.4 The unexamined count and its two causes

Dropping it would let the chain report clean on a blocking defect nobody looked at, since termination is "no blocking findings remain".

## R10. Step 10 — the commit protocol

Sub-sections here use `###`, and top sections use `##`, deliberately: the test
harness locates a sub-section by scanning forward to the next `### `, so a
`## ` lookup would terminate at the first `### ` beneath it.

### R10.1 Why the repository must contain the document, and cannot be an ancestor

`Review document in repository:` and `Review snapshot in repository:` are omitted entirely when no repository resolved, and each carries the literal value `unresolved`, followed by an explanation, when the path lies outside `<repo>`. Note that `Review snapshot directory:` is emitted either way, so the three do not appear and disappear together. Directives are injected at tool-call time and cannot appear mid-run, so immediately after the user authorizes `git init .sdlc` above, both repository-relative directives are still absent. The recorded `review-repo` makes the directives correct from the next call on.

`Review document:` is hardcoded under `.sdlc/reviews/`, so a repository that does not contain that path reports `Review document in repository: unresolved` on every call and can never commit. A reviews repository somewhere else is therefore not a workable answer to this question, and `resolve_review_repo` refuses one rather than resolving it — so naming one here returns you to this same question with a different reason attached. Nor is an ancestor: `resolve_review_repo` refuses the reviewed tree's root and anything above it, because no top-anchored relative pathspec can exclude a directory that CONTAINS the tree. `git_state.resolve_review_repo` refuses such a value and the directive then reads `unresolved`, so in practice the first check catches it — but the reason belongs here, where the validations are enumerated, rather than only in step 2's discussion of the exclusion pathspec: the snapshot excludes the review repository from the reviewed tree by a top-anchored RELATIVE pathspec, and there is no such pathspec for a directory that contains the tree — the relative path is `.` or empty, and `':(exclude,top).'` excludes nothing. The capture then embeds the review repository in the snapshot of the code it reviews and the tree SHA churns every pass regardless of the code, silently, because the empty-tree sentinel only fires on an empty tree. (The unanchored `':!.'` does yield the empty tree, but that is not the form step 2 instructs.)

### R10.2 Why `check-ignore` is run without `-q`

This check exists to give the user an actionable message instead of that failure.

### R10.3 Why the worktree path is derived rather than carried

It is keyed on the repository AND the document rather than on the round number alone: `$TMPDIR` is per-user, not per-project, so a bare `sdlc-review-1` names the same directory for every project and every issue on the machine. A bare `[ ! -d "$worktree" ]` skips creation for a directory belonging to some other repository — or left behind by a crashed earlier run — and every commit below then lands somewhere other than where this round belongs. `git worktree list --porcelain` prints the **normalized** path — symlinks resolved, `//` collapsed — while string concatenation does not: on macOS `$TMPDIR` ends in `/` and `/var` is a symlink to `/private/var`, so the derived and the printed paths differ by both and the membership test never matches. The reuse branch would then be unreachable, and the `elif` would fire on the *correct* worktree, aborting every pass after an interrupted one with a message asserting the opposite of the truth. `grep -Fqx` for the same reason: the path is interpolated into a pattern, and an unescaped `.` in it is a wildcard.

### R10.4 The commit protocol's mechanics

Step 2 captured into a staging directory rather than writing `<Review snapshot directory>` directly, so that an abandoned run — a role-validation halt, a declined large diff, an unresolved repository — cannot destroy the previous pass's capture. The target is removed only once it matches, which is why the `rm` is chained to the `diff` rather than following it: an unconditional delete destroys the ground truth on exactly the path the check exists to serve, leaving the re-run to compare against a file that is no longer there. The subject names the disposition and the finding id, and carries the justification when it fits; longer reasoning goes in the body.

When it holds nothing at all — or was never created — the guard above leaves the previous pass's capture in place and (d) omits the snapshot from its `add`, so the round is still recorded. Every `commit` below reads its message from disk rather than taking a `-m` string, so the subject and body survive shell quoting intact. Write it with your file tool to the `commit` skill's convention — `/tmp/commit_msg.txt` — immediately before each commit, overwriting the previous one; the commits in (d) are sequential, so one path is reused rather than one file per finding.

### R10.5 Restoring a snapshot

This is the procedure the capture exists for, and the review workflow never
runs it — step 10 writes a snapshot, it does not read one back. It is here for
a user who asks to reconstruct a reviewed state, or to check whether what
merged is what was reviewed.

In any clone that can reach `base`. Run it in a detached worktree so the recipe never mutates the tree it is invoked from. Substitute `<path to review.patch>` as an **absolute** path: the recipe `cd`s into the worktree, so the repository- or cwd-relative form every other path in this skill uses no longer resolves once it gets there.

```bash
restore="${TMPDIR:-/tmp}/sdlc-restore-$$"
git worktree add -q --detach "$restore" "<meta.base>"
cd "$restore"

# A clean tree at `base == HEAD` captures an EMPTY patch, which this document
# blesses as correct. A bare `git apply` refuses it with "No valid patches in
# input" and exit 128, so the one recovery procedure the snapshot exists for
# would abort on a state the capture calls valid.
[ -s "<path to review.patch>" ] && git apply "<path to review.patch>"

# Mirror the capture exactly — same empty index, same exclusion pathspec.
# `export` is required: a `VAR=value cmd` prefix scopes to the single command it
# prefixes, so `git add` would use the throwaway index while `git write-tree`
# read the REAL one and returned base's tree on every non-empty patch.
idx=$(mktemp -u)
export GIT_INDEX_FILE="$idx"
trap 'rm -f "$idx"' EXIT
git read-tree --empty
git add -A -- ':(exclude,top)<meta.excluded — the value meta.json records, not a literal>'
git write-tree                        # MUST equal meta.tree
unset GIT_INDEX_FILE

# Leave nothing registered behind: without this every restore adds a worktree
# to the user's repository that no later run removes or prunes.
cd - >/dev/null
git worktree remove --force "$restore"
git worktree prune
```

Use exactly the pathspec `meta.excluded` records; capture and restore must not drift, which is why the capture writes it down rather than leaving both ends to repeat a literal.

The recomputed tree SHA is content-addressed, so equality with `meta.tree` proves the restoration is byte-identical to what was captured. When `meta.head_matches_target` is `true`, comparing `meta.tree` against the tree that eventually landed on the default branch — **with `meta.excluded` applied to that tree too** — answers a further and useful question: whether what merged is what was reviewed. The exclusion has to be applied to both sides, because `meta.tree` can never contain the excluded review-repository path while the merged tree will whenever the project tracks it. When `head_matches_target` is `false`, the capture was not taken at the PR head — a different sha, or a dirty working tree — and cannot answer that question at all.

## R12. Edge cases — the reasoning behind the branches

Each edge case in the skill states its branch rule. The reasoning that justifies the branch, and the states that make it reachable, are here.

The PR-only edge cases below (`PR is already merged or closed`, `No linked issue`, and `Very large diffs`) do not apply in paths mode. **(re-review)** A pass that ends with no blocking findings is the pass that TERMINATES the chain, so any blocking `close` or `reject` that got it there still clears step 9's gate first; an empty document is the strongest reason to check, not a reason to skip. Do not post anything. Tell the user which heading, and that the fix is in the file rather than in the tool; the same error from `sdlc_implement --review <#>` has the same cause. A heading that has drifted OUTSIDE the tier regions does not raise — it is silently skipped — which is what step 7(0)'s count reconciliation exists to catch. The snapshot-and-header commit of 10(d) is the whole round — it carries the pass-counter bump, so the document does change and `git add` has something to stage — and the finding set is byte-identical to the pass before. Do NOT manufacture an empty commit, and give the zero-delta variant of step 11's prompt. *(This is PR-mode only — paths mode reviews exactly the files the user named.)*
