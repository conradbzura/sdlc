---
name: review-rationale
description: >
  Design rationale for the `review` skill. Explains WHY specific blocks in
  `sdlc_review`'s workflow are shaped the way they are. Read on demand — when a
  block misbehaves, or before deviating from an instruction whose reason is not
  obvious. Carries no rules of its own.
---

# Review skill — design rationale

**This document carries NO rules.** Nothing here changes, adds to, or qualifies anything `review.md` requires. Every MUST, SHALL and STOP lives in the skill; what lives here is the reasoning behind them — the derivations, the failures that produced a guard, and the claims that were verified by execution.

Read it **on demand**: when a command block does something you did not expect, or when you are about to deviate from an instruction you do not understand. Never read it as a precondition for executing a step, and never quote it into a reviewer's brief — a reviewer is reviewing code, not this protocol.

Addresses are the `R<n>` ids, not the headings. `review.md` cites `§R4.3`; the wording of a heading may change, the id may not.

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

The MCP endpoint performs the relationship check via GitHub's `closingIssuesReferences` connection (issues that close when the PR merges, whether linked via a `Closes #N` keyword or the GitHub UI), with a `Closes` / `Fixes` / `Resolves #N` PR-body fallback. When several issues are linked, the endpoint resolves the **first** of them (the connection has no ordering guarantee), so `<N>` is one closing issue, not necessarily the only one. Their answer cannot be used: directives are injected at tool-call time and cannot appear mid-run, and `Resolved issue:` is derived from GitHub rather than from the reply, so re-deriving the path here is guessing under another name. The endpoint resolved `<iteration>` as the next unused iteration deterministically (never overwriting an earlier round), so you do NOT glob the directory or compute `iteration = max + 1` yourself — take the injected path as-is. This holds in both base modes: in **PR mode** the injected path is `.sdlc/reviews/issue-#<N>/review-<iteration>.md`, and in **PATHS mode** it is `<Review document directory>/review-<iteration>.md` under the endpoint-computed slug directory (successive paths-mode reviews of the same target accumulate their rounds there).

## R6. Steps 5–6 — role validation and the stale-graph rule

The summary lands in the reviewer brief's "architectural context" slot, where it reads as ground truth and competes with the diff for attention — so a graph describing a layout that no longer exists is worse than no graph at all, in all N briefs at once. This project's own graph is the worked example — analyzed at `"initial"`, indexing markdown only, with node ids under a directory layout the tree no longer has.

## R7. Step 7 — the two-turn dispatch

The derivations for this step are held per-topic in the subsections below; cite those ids rather than this one.

### R7.1 Why the seeded read-back is persisted to disk



Between this read and its use sits the seeded block, N phase-1 dispatches with the diff interpolated, N phase-2 dispatches and the whole consolidation — the longest span in this skill, and the middle of your context. This skill already refuses to carry a value across that kind of distance twice (step 3 writes the commit destinations to a scratch file; step 9 writes its target to disk "precisely so this check reads ground truth from the filesystem rather than comparing the file against the orchestrator's recollection"), and this is the one value whose loss the Invariants call irreversible. There is also no detection: the count reconciliation below checks the *enumeration* only, and 10(d)'s terminal `diff` compares the document against a target built by the same context that may already have dropped the fields.

### R7.2 Why the count reconciliation uses awk and not `grep -c`

A raw count therefore reports a mismatch on a document that parsed perfectly, naming phantom ids no pass can resolve, and a MUST-STOP gate that fires on healthy input is a gate an agent learns to reason past — at which point the genuinely drifted heading it exists for goes through. The silent-drop path this guards is narrower than it looks, and worth stating exactly, because a wrong reason invites the conclusion that the gate is obsolete. A `### <id> — ` heading the parser cannot read *inside* a tier does NOT vanish: `pr_state.parse_review_document` raises `ValueError` on it, which propagates out of the endpoint before this skill is ever dispatched, so you would never reach step 7 to notice. What IS skipped silently is a well-formed finding heading that has drifted **outside** the Tier 1 / Tier 2 regions — below `## Rejected in earlier passes` or `## Cross-cutting decisions`, or above `## Tier 1` — where the parser's severity is `None` and the heading is passed over without raising. Under the "block is authoritative" rule that finding is then deleted from the document with no disposition and no commit message. Git history is a recovery path, not a detection path.

What the gate compares matters as much as who computes it. Until the enumeration grew its `Outside any tier:` line, both sides of the comparison were `parse_review_document`'s output over the same file — and a heading that has drifted outside the tier regions is invisible to that parser, so it was absent from both sides and the STOP condition could never fire on the one failure this gate exists for. The parser now records those headings separately: they are reported rather than refused, because a review OF a review document quotes finding headings in prose routinely, and refusing one outright would halt a healthy round. Reporting them puts the judgement where it belongs, at this gate, with the document in front of the agent that can repair it.

Two hand-written scanners have stood here and both were wrong. The first matched `/^## +Tier +[12]/`, so it never saw `## Tier 3 — Incidental`: every document carrying an incidental finding reported a phantom mismatch, and the gate's real purpose — catching a heading that drifted outside the tier regions — became unreachable for `I<n>` ids entirely. The second toggled fence state on any run of three or more backticks or tildes, which is not the CommonMark rule: a fence closes only on a run of the SAME character, at least as long as the opener, carrying no info string. On a finding that quotes a fenced sample inside a longer fence — which `pr_state._fence_for` deliberately emits, and which the reviewed artifacts in this chain contain, because findings about review documents routinely quote finding headings — the toggle desynced and read a quoted `### B9 — …` as a real finding. That id is "present in the file but missing from the block", which is the STOP condition, so the pass halted on a healthy document and named an id that does not exist. `pr_state.py`'s rule 1 exists for this defect class and enumerates the scanners inside that module, which is why it reached neither of these: they lived in the skill markdown. The fix was not a third scanner taught CommonMark but the removal of the duplication — the skill now calls the parser it was imitating.

### R7.3 Why the inline path cannot claim the blindness guarantee

There is no separate phase-1 prompt to withhold anything from: the endpoint appends the whole `Seeded findings` block to the tool return you are reading right now, and on the inline path you ARE the reviewer — so your phase-1 pass is conditioned on the seeded text, which is the exact failure the ordering exists to prevent. Prompt omission alone would not be enough — the prior round's findings sit at a fixed, conventional, guessable path *inside the tree the reviewer is reviewing*, put there by step 10 precisely so the next `--verify` finds them, and the brief otherwise grants "You MAY read any other file for context". The prohibition is what closes that, and the two together are what earn step 8's treatment of an independent rediscovery as stronger evidence than agreement.

### R7.4 Why seeded findings route by originating role

A reference match leaves the `(cross-cutting — no single line)` and `issue acceptance criterion #<n>` references — both of which the brief above actively invites — assignable to nobody, and it strands any finding whose file has since left the changed set. Role routing has no such gap. Step 8 defaults a missing disposition to carry — the safe direction — but silently, and dropping an entry from a long enumeration is a well-documented failure mode at the subset sizes this reaches. Routing the gap back to the reviewer as an external observation is cheap and is the pattern this skill prefers elsewhere.

## R8. Step 8 — the disposition rules and their counterexamples

The derivations for this step are held per-topic in the subsections below; cite those ids rather than this one.

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

Sub-sections here use `###`, and top sections use `##`, deliberately: the test harness locates a sub-section by scanning forward to the next `### `, so a `## ` lookup would terminate at the first `### ` beneath it.

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

This is the procedure the capture exists for, and the review workflow never runs it — step 10 writes a snapshot, it does not read one back. It is here for a user who asks to reconstruct a reviewed state, or to check whether what merged is what was reviewed.

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

## R13. The incidental tier — why relevance is a tier rather than a filter

Before this tier existed there was no relevance gate anywhere in the pipeline. "Scope" meant **file** scope and nothing else: `sdlc_role_scope` hands each reviewer the changed files its role is mapped to, and the brief confines findings to those files — but to anywhere in them, changed lines or not. The reference form `issue acceptance criterion #<n>` was available as a citation shape, and nothing ever asked whether a finding resolved to one. The single negative scope rule in the whole system was `role-guides/aie.md`'s prohibition on flagging in-scope prose for missing citations, so the concept existed; it was simply never generalized.

That interacts badly with the termination condition. Iteration ends on one predicate — no blocking findings remain — so a finding raised at blocking severity holds the chain open whether or not the issue asked for the work. PR #33 is the worked example. Across three passes the open count went 22 → 39 → 47 while nearly every seeded finding closed against quoted evidence each round: the chain was not failing to make progress, it was accumulating findings faster than it resolved them. Auditing pass 3's 47 against issue #32's Expected Outcome, 39 traced to an acceptance criterion or to code the PR introduced, 5 were test-suite conventions on the PR's own new test file, and 3 were substantially pre-existing defects that became reviewable only because the PR touched the file. Separately, pass 3 was the first run with two roles, and `general-purpose` — mapped to `**/*` — saw four modules and five test suites for the first time in that chain, contributing 21 of its 23 findings there. That is coverage arriving late rather than reviewers wandering, and under two tiers the two are indistinguishable.

### R13.1 Why a tier and not a filter

The obvious alternative is to drop off-issue findings at the reviewer, or to have the consolidator discard them. Both throw away the part that is worth keeping. A reviewer that has read the file and found a real defect has produced information; the problem is not that it was found but that it was allowed to gate. A third tier separates those two things — the observation is recorded with its id and evidence, and the chain terminates on the issue being satisfied. Deferral, not dismissal, is the whole distinction, and it is why an incidental finding is held to the same standard of proof as any other: a tier that accepted weaker evidence would become the place findings go to avoid being checked.

### R13.2 Why blocking-versus-incidental is not settled by highest-severity-wins

Highest-severity-wins resolves a disagreement between two lenses, and it is sound for Blocking against Advisory: a role's blocking policy is its own, so the strictest lens governs and the dissent is noted. Relevance is not like that. Whether the issue asked for the work is a fact about the issue, identical for every role, so a role calling a finding incidental is not applying a laxer policy — it is making a claim that can be checked against the acceptance criteria. Ranking the tiers and moving on would record a disagreement that no lens can hold. So the consolidator resolves it against the criteria and writes down which one the finding traces to, or that none does. It stays blocking meanwhile, because the failure directions are not symmetric: leaving an off-issue finding blocking costs a pass, and dropping an on-issue one out of the predicate ends the chain with the defect unaddressed.

### R13.3 Why the re-tier is gated like a rejection

`close` and `reject` are gated because each removes a blocking finding from the single predicate termination depends on, and `Reviewers per role` defaults to 1. Moving a blocking finding to Tier 3 has exactly that effect. Gating the two dispositions by name and leaving the re-tier ungated would preserve the letter of the rule and lose the property it exists for — one agent's judgement could still delete a blocking finding, by calling it off-issue rather than by rejecting it. The gate is therefore stated over the outcome rather than over the vocabulary.

### R13.4 Why there is no `**(INCIDENTAL)**` marker

The `**(BLOCKING)**` marker outranks the tier section a heading sits in, which makes it a second, weaker source of truth about severity. That is tolerable only because the override is **monotone toward blocking**: it can promote a finding into the termination predicate and never out of it, so a marker left behind by a careless re-tier costs a wasted pass that the next round recovers. A demoting marker would break the monotonicity. One stale `**(INCIDENTAL)**` on a Tier 1 heading and the parser reports a blocking finding as a deferral, the chain terminates, and nothing in the document records that it happened. Tier 3 membership is therefore by section alone, and the asymmetry is written down in three places because it looks like an oversight to anyone who meets it once.

### R13.5 Why paths mode has no third tier

Paths mode reviews files as they stand, with no PR and no linked issue. The paths a run was given say which files to read; they say nothing about what work was asked for, so there is nothing for relevance to be measured against. A stand-in — the commit range, the user's phrasing, the files themselves — would be an inferred intent presented as the issue's, which is the failure the tier exists to prevent rather than a lesser version of it. An observation that would be incidental in PR mode is Advisory there: still real, still non-gating, still recorded.

## R14. Context and scope — why scope is the issue's shape, not the diff's

For most of this skill's life "scope" meant one thing: the subset of the PR's changed files that a role's `guide-map.role` globs matched. That definition has a hole you cannot see from inside it. If an acceptance criterion required a change to a module and nobody made the change, the module is not in the diff, so it is in no reviewer's scope, so no reviewer can raise the omission as a finding against the code. The chain then terminates — correctly, by its own rule, with no blocking findings — on a PR that does not satisfy the issue. A review that can only inspect what was written can never report what was not.

The three-tier split (§R13) narrowed this from the other end by asking whether a finding traces to an acceptance criterion. That test can only *demote* a finding already raised. It cannot admit one, because the reviewer was never given the file to look at.

### R14.1 Why context is deliberately unbounded

Reading and being answerable are different permissions, and conflating them is what made the old definition look adequate. A reviewer needs the module a changed test exercises, the caller of a changed signature, the sibling implementation that establishes the convention — none of which it should necessarily raise findings against. Restricting reads would degrade every finding it *does* make and buys nothing: reading costs the review nothing and produces no output on its own. So context is the whole repository, stated as its own concept so that "you MAY read any file" is no longer a parenthesis inside a confinement rule, where it read as an exception rather than as a permission of equal standing.

### R14.2 Why an out-of-scope observation is tiered rather than dropped

Tightening scope without somewhere for the overflow to go would destroy information, which is the argument §R13.1 already makes about relevance. The two mechanisms compose: scope says what a reviewer must go and find, and Tier 3 says where what it merely noticed goes. A pre-existing defect in a file this PR happened to touch is the ordinary case — real, worth recording, and nothing the issue asked anyone to fix. A reviewer that has read a file and found something has produced information; the only question this skill asks is whether that something gates, and scope answers it without anyone having to discard the finding to get the answer.

### R14.3 Why the role glob stays a hard bound

Unbounded context plus "logically related to the expected outcomes" is, read literally, a licence to review the repository — relatedness is a judgement, and a judgement with no mechanical bound drifts outward under pressure. The `guide-map.role` intersection is the one bound in the definition a machine can check, so it stays, and step 8 checks it rather than trusting the brief to have been followed. The cost is a real gap: in a multi-role pass whose globs do not cover the repository, a related untouched file that matches no role is reachable by nobody. That is the same gap an unmapped changed file already has, it is visible in the header, and its remedy is a role mapping or a `general-purpose` pass — which is a better failure than a bound nothing enforces.

### R14.4 Why the seed is the orchestrator's and the extension is the reviewer's

Relatedness cannot be computed, and the party best placed to judge it is the one holding the lens and reading the code. Having the orchestrator derive every reviewer's whole scope would put that judgement in the one agent with no lens at all, and a file it failed to relate would be missed by everyone at once. Having each reviewer derive its whole scope would cost the document its ability to state what was reviewed, and would make two reviewers of the same role incomparable. So the orchestrator seeds scope with the changed files, exactly as before — nothing regresses, and the diff stays the first thing a reviewer reads — and the brief authorizes extension from there, requiring the criterion that admits each added file. The burden of justification sits on the widening, which is where it belongs: an extension nobody can tie to a criterion is scope creep, and saying so is cheap. An extension a reviewer is unsure of is still raised, because a finding the orchestrator re-attributes costs a line in the header and a finding withheld costs the round.

## R15. Incremental disclosure — why the document is outlined rather than dumped

The review document became the largest artifact in the pipeline without anyone measuring it. At 55 findings this chain's own `review-1.md` rendered to 108,405 bytes — more than the whole fresh review prompt, which #37 had just spent thirteen commits cutting to 102,452. Every budget in the suite watched a file the project writes; none watched the file the pipeline writes, and that is the one that grows with every pass of every chain.

No consumer ever needed it whole. A re-review routes seeded findings by originating role and composes one phase-2 message at a time; each reviewer sees only its own role's subset; the implement walk takes findings one at a time behind an approval gate it already had. Every consumer was already incremental. Only the injection was not.

### R15.1 Why an outline of the file, and why the enumeration stays inline

Disclosure is safe exactly to the degree that nothing can be lost to it. The finding-set enumeration is the one thing a pass cannot reconstruct — a finding absent from the seeded block is absent from the round, gets no disposition, and leaves no trace — so it stays whole and inline: every id, severity, reference and title. What moves behind a fetch is the issue text and the remediation checklist, read when a finding is acted on and at no other time. Each elided body leaves **one visible marker** rather than a silent gap, because a gap that does not announce itself is an invitation to supply the missing text from recollection.

It is an outline of the real file rather than a manifest assembled from parsed fields, and that is the larger half of the argument. `ReviewFindings.format` re-renders what the parser kept, and the parse is lossy in ways nobody chose: role attribution is stripped off the title and discarded, an advisory title containing an em dash loses its last segment, and the ledgers and cross-cutting sections were never carried at all. Step 7(0) existed to recover those from disk before any reviewer was dispatched, and the skill called it the one instruction whose omission is irreversible. Eliding from the real text means all of it arrives verbatim, because it is the file — so the read-back is retired rather than merely made cheaper. Two properties follow and both are tested: the outline is **itself a valid review document**, parsing to the same findings with empty bodies, so a consumer that re-parses what it was handed is not given a different shape from the file on disk.

### R15.2 Why the fetch is required where a rationale pointer is optional

These two mechanisms look alike and are opposites. A rationale pointer is italic, trigger-gated and skippable — the cost of not reading it is that an agent proceeds without knowing why a rule exists, which is the ordinary case. A finding body is what a disposition or a remediation is *judged against*: acting on an unfetched finding means acting on a title. So the fetch is stated as a requirement at all three points of use — phase-2 dispatch, step 8's application, and the implement walk — and a test asserts no `sdlc_review_findings` mention is written in the pointer idiom, because a later pass tidying the two into one shape would silently turn a required read into an optional one.

### R15.3 Why the file is not split

The obvious reading of "break the document up" is one file per finding. The bulk cost was never the filesystem, though — it was what the endpoint injected, and a tool slices one file perfectly well. Splitting would break `review-*.md` iteration discovery in six places, the single-file git history that a re-review chain exists to produce, and the document's readability as one artifact a person opens.

What splitting would genuinely help is the **write** path, which this design does not touch: step 9 still materializes the full consolidated target, so the orchestrator holds every carried finding's text even where nothing happened to it. The narrower fix there is to apply dispositions as edits rather than by rewriting from a materialized target, and it is a separate piece of work with its own risk — it touches the per-mutation commit protocol, which is the product.

### R15.4 Why superseded cross-cutting sections go too

A chain writes a cross-cutting-decisions section per pass, and they accumulate: 2,643, 4,106, 7,234, 11,456 bytes over four passes here, roughly doubling each round. Only the current pass's decisions are operative; the rest are history that was being re-read on every pass. The elision is keyed on the pass number in the heading rather than on position, because a document that ordered its sections newest-first would otherwise lose the operative one — and unlike a finding body there is no fetch to recover a section with, since it is prose rather than an addressable finding. A section carrying no pass number is never elided: nothing establishes that anything superseded it.
