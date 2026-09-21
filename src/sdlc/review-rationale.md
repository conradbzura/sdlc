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

_Pending extraction._

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

### R10.5 Restoring a snapshot

This is the procedure the capture exists for, and the review workflow never
runs it — step 10 writes a snapshot, it does not read one back. It is here for
a user who asks to reconstruct a reviewed state, or to check whether what
merged is what was reviewed.

**Restoring a snapshot.** In any clone that can reach `base`. Run it in a detached worktree so the recipe never mutates the tree it is invoked from. Substitute `<path to review.patch>` as an **absolute** path: the recipe `cd`s into the worktree, so the repository- or cwd-relative form every other path in this skill uses no longer resolves once it gets there.

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
