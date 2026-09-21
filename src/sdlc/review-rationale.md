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

_Pending extraction._

## R2. Invariants — why the block is duplicative on purpose

_Pending extraction._

## R3. Arguments — the directive dictionary's fine print

_Pending extraction._

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

## R5. Step 3 — why the commit destinations go to disk

_Pending extraction._

## R6. Steps 5–6 — role validation and the stale-graph rule

_Pending extraction._

## R7. Step 7 — the two-turn dispatch

_Pending extraction._

## R8. Step 8 — the disposition rules and their counterexamples

_Pending extraction._

## R9. Step 9 — why the consolidated target is written to disk

_Pending extraction._

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

## R11. Step 11 — why each prompt variant exists

_Pending extraction._

## R12. Edge cases — the reasoning behind the branches

_Pending extraction._
