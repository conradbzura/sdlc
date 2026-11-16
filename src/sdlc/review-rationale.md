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

The endpoint emits these directives; the skill describes them. What follows is the detail each description sheds.

`Review document directory:` is always present in paths mode, where the endpoint computes the slug, and on a re-review, where the endpoint had to resolve the directory to load the seeded round from it. In PR mode it is omitted on the `unresolved` branch, since without a linked issue there is no `issue-#<N>/` to name.

`Review document:` names a file that does not exist yet, in every mode. On a fresh review the endpoint resolved the next unused review number; on a re-review it listed the rounds of that review on disk and named the one after the highest. Both resolutions read filenames, which is why the skill is told not to recompute either — the agent's `ls` and the endpoint's would agree today and disagree the first time a filename shape changes. It is present in paths mode and on PR mode's resolved-issue branch, and `Review round:` and `Review metadata:` appear and disappear with it: all three describe one write.

## R4. Step 2 — recording the reviewed state

The findings reference `file:line` on a branch whose history is routinely rewritten before merge, so the commits a review was performed against do not survive. The record is taken at acquisition because that is the one moment the tree is known to match what the reviewers read; taken later, it describes whatever the tree has become.

### R4.1 The anchor, the tree SHA, and why there is no patch

The anchor is the merge-base with the upstream default branch, which by assumption never changes; the PR's base branch is a different ref and may be deleted once a stacked PR merges. The tree SHA is content-addressed, so it identifies the reviewed content exactly, whatever later happens to the commits that carried it. An earlier design also stored a `git diff --binary` from base to tree, so the state could be restored byte for byte into any clone. It was dropped with the review repository: at roughly a megabyte per round it is the largest artifact a review produces, and it was only affordable while every round overwrote the last and git kept the history. The tree SHA still answers the question that matters afterwards — whether what merged is what was reviewed — by hashing the merged tree the same way and comparing.

**When the anchor cannot be resolved** the record is written with a null `base` and the round continues. It has to be a soft failure because the state is ordinary: `refs/remotes/origin/HEAD` is absent after `clone --single-branch`, after `git init` plus `git remote add`, and in most CI checkouts, and `set-head -a` cannot recover it offline. The tree does not depend on the anchor, so it is recorded regardless.

### R4.2 The empty index, the `top` anchor, and the derived exclusion

The index is built from **empty**, not from `HEAD`: seeding it from `HEAD` stages every path `HEAD` tracks, and an exclusion pathspec only declines to *update* those entries — it never removes them — so a project that tracks `.sdlc/reviews` would hash it anyway. Each command takes `GIT_INDEX_FILE` as a prefix rather than through `export`, so a block that dies midway cannot leave later commands pointed at a throwaway index.

The review documents are excluded because this round is about to add one: hashing them makes the tree SHA change every round regardless of the code, which defeats the one comparison the record exists for. The pathspec is anchored with `top` because git resolves pathspecs against the **current working directory**, and it is DERIVED from `git rev-parse --show-prefix` because the documents live under the working directory, not necessarily under the repository top. An earlier version had the agent substitute the path by hand; from a subdirectory the literal `.sdlc` named a directory at the top that did not exist, nothing was excluded, the tree was non-empty so no sentinel fired, and the SHA churned silently. A path that is both tracked and ignored is dropped from the hash too, since `git add -A` honours `.gitignore`; nothing surfaces that, and it is the price of not hashing build output.

## R5. Step 3 — resolving the issue and the write target

The MCP endpoint performs the relationship check via GitHub's `closingIssuesReferences` connection (issues that close when the PR merges, whether linked via a `Closes #N` keyword or the GitHub UI), with a `Closes` / `Fixes` / `Resolves #N` PR-body fallback. When several issues are linked, the endpoint resolves the **first** of them (the connection has no ordering guarantee), so `<N>` is one closing issue, not necessarily the only one. When no issue resolves, the skill asks the user which one the PR closes — and their answer cannot be used to rebuild the write target: directives are injected at tool-call time and cannot appear mid-run, and `Resolved issue:` is derived from GitHub rather than from the reply, so re-deriving the path here is guessing under another name. The endpoint resolved the write target as the next unused file deterministically — a new review number on a fresh review, the next round of an existing review on a re-review — so you do NOT glob the directory or compute either yourself; take the injected path as-is. This holds in both base modes: in **PR mode** the path lies under `.sdlc/reviews/issue-#<N>/`, and in **PATHS mode** under the endpoint-computed slug directory, where successive paths-mode reviews of the same target accumulate.

## R6. Steps 5–6 — role validation and the stale-graph rule

The summary lands in the reviewer brief's "architectural context" slot, where it reads as ground truth and competes with the diff for attention — so a graph describing a layout that no longer exists is worse than no graph at all, in all N briefs at once. This project's own graph is the worked example — analyzed at `"initial"`, indexing markdown only, with node ids under a directory layout the tree no longer has.

## R7. Step 7 — the two-turn dispatch

The derivations for this step are held per-topic in the subsections below; cite those ids rather than this one.

### R7.1 Why the seeded document is read back rather than recalled

The seeded block is an outline, and between reading it and writing the new round sit N phase-1 dispatches with the diff interpolated, N phase-2 dispatches and the whole consolidation — the longest span in this skill, and the middle of your context. A carried finding's body reconstructed from that distance is a paraphrase, and the next round seeds from it, so the drift compounds. The seeded document is on disk, unchanged, for the whole run: each round is a new file, so nothing the run does can alter what it was seeded from. An earlier design rewrote the document in place and had to copy it to a scratch path first, because the rewrite destroyed the only ground truth; with rounds as separate files the original IS the copy. That is also why the skill never repairs a seeded document, even a malformed one — an earlier round is a record, and the user is the one who edits records.

### R7.2 Why the count reconciliation calls the parser rather than scanning the file

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

Computing it from the survivors alone is wrong because closed and rejected findings are deleted from the document, so with `B1` closed the next pass sees only `B2`, reuses `B1`, and silently re-points every earlier-round and implement-loop citation of `B1` at a different defect. Computing it from the `Retired ids` line alone is wrong for the mirror reason: that line records only ids since closed or rejected, so whenever the highest-ever id is still open — the normal case — it is not the maximum. Run the same example the other way: `B1` closed and `B2` open makes `Retired ids` = `B1`, and "next above the retired line" yields `B2`, colliding with the finding that is still there.

### R8.2 Re-tiering and the `**(BLOCKING)**` marker

`parse_review_document` reads the heading marker as authoritative OVER the enclosing tier, so a finding moved to Tier 2 that keeps its marker is re-seeded as blocking on the next pass and the termination predicate never clears — a reviewer that correctly rejects an over-severe finding would produce a chain that cannot end.

### R8.3 Rediscovery, corroboration, and the default composition of one

The `rediscovered` column is the reviewer's own judgement of its own prior trace, made in the turn in which it has just been shown the answer — but you collected its phase-1 findings verbatim in step 7 and can check. This is the same ground-truth-over-recollection move step 9 makes for its target file. Treat it as stronger evidence absent a contrary signal, not as an override that cannot be argued with. A phase-1 finding matching nothing in the seeded set is new and takes a fresh id below.

`close` stays autonomous too, but not unconditionally: it also removes a blocking finding from the termination predicate, it is also decided by one agent at the default composition, and it leaves less behind than a rejection does (a bare id in `Retired ids`, where a rejection keeps its rationale in the ledger). A model asked whether its own prior round's finding was fixed is the canonical premature-completion case, and the two safeguards that exist — carry-beats-close and rediscovery-outranks-close — both need a second opinion the default composition does not supply.

### R8.4 The unexamined count and its two causes

Dropping it would let the chain report clean on a blocking defect nobody looked at, since termination is "no blocking findings remain".

## R10. Step 10 — one write, to a new file

An earlier design committed every round to a git repository nested at `.sdlc`, one commit per finding-set mutation, so the history recorded why each finding opened, closed or was thrown out. It was removed, and the reasons are worth keeping because each one is a pull back toward it.

The machinery cost more than the record was worth. Committing needed a repository, so the skill had to resolve one, refuse the reviewed tree's root and its ancestors, check the path was not ignored, and ask the user when nothing resolved; an optional commit branch needed a temporary worktree; walking the document forward one mutation at a time needed a scratch copy of the seeded state, a scratch copy of the target, and a terminal diff between them. That was roughly a third of the skill, and review after review found defects in it rather than in the reviewing — a gate that checked a directory where the ignored thing was a file, advice that named a configuration the next check refused, a snapshot silently dropped from a commit that still exited zero.

Separate files give the same guarantees more cheaply. Nothing is overwritten, so no run can destroy an earlier round and there is nothing to stage, promote or recover. The reason for a closure moves from a commit subject into the round's **Closed this round** ledger, where the next round's reviewers can be shown it and a reader does not need the repository to find it. What is given up is granularity: a round is one state change, not one per finding. The pass line's deltas and the two ledgers state what moved, and a text diff between two rounds shows the rest.

The refusal to overwrite is the one mechanical guard left. The endpoint names an unused path, so an existing file at that path means another run wrote it in between; picking a different name would fork the review silently, and overwriting would destroy a round.

## R12. Edge cases — the reasoning behind the branches

Each edge case in the skill states its branch rule. The reasoning that justifies the branch, and the states that make it reachable, are here.

Each edge case in the skill states its branch rule; the reasoning that justifies it, and the states that make it reachable, are below — one subsection per case, because five separate pointers used to land on one undifferentiated paragraph and an agent arriving on any of them had to read the other four.

### R12.1 Why paths mode runs no `gh` at all

Three of the skill's edge cases — `PR is already merged or closed`, `No linked issue` and `Very large diffs` — are properties of a pull request, and paths mode has none. There is no PR to query, no linked issue to resolve and no diff to bound, so the branches do not merely go unused: the `gh` calls that would evaluate them have nothing to address. Posting is out for the same reason, and it is the stronger half of the rule — a paths-mode round is a local artifact from end to end, so there is no thread for a comment to attach to and nothing about the run that GitHub is entitled to learn.

### R12.2 Why a clean round still writes the document

A pass that ends with no blocking findings is the pass that TERMINATES the chain, which makes it the one whose bookkeeping matters most rather than the one that can be skipped. Any blocking `close` or `reject` that got it to zero cleared step 9's gate on the way, so the gate has already run; what remains is the record of it. An empty tier section is the strongest reason to check the document, not a reason to leave it unwritten — a chain that terminated without a final state on disk cannot be audited afterwards, and the next `--verify` has nothing to seed from.

### R12.3 Why a heading the parser refused is repaired in the file

`parse_review_document` raises on a `### <id> — ` heading it cannot read INSIDE a tier — an en dash or a hyphen where the em dash belongs, most likely — and the error propagates out of the endpoint before the skill is dispatched, so the round never starts. The fix is in the document rather than in the tool, and the same error out of `sdlc_implement --review <#>` has the same cause and the same repair. Telling the user which heading is what makes that actionable, since the document is the one thing they can edit.

A heading that has drifted OUTSIDE the tier regions is the opposite case and the more dangerous one: it does not raise, because the parser's severity is `None` there and the heading is passed over. That is what step 7(0)'s reconciliation exists to catch, and why the enumeration reports those ids on its own `Outside any tier:` line — while they were merely skipped, both sides of that comparison came from this same parser and the gate could not fire on them by construction.

### R12.4 Why a round where nothing changed is still written

When every seeded finding carries, the new file's finding set matches the one before it, and writing it can look like noise. It is not: the round re-checked every finding against the current files, re-referenced the ones whose lines moved, and recorded the state it was run against. Without the file, a round that examined everything and changed nothing is indistinguishable from a round that never ran, and the next `--verify` would seed from the older references. Step 11's zero-delta variant is what tells the user which kind of round it was.

### R12.5 Why a very large diff is bounded rather than truncated

A diff too large to interpolate is a PR-mode problem only: paths mode reviews exactly the files the user named, so its size is the user's own choice and bounding it would override a decision already made deliberately. In PR mode the diff is machine-selected and can be arbitrarily large, and the failure mode is not a refused tool call but a reviewer that read a prefix and reported on it as though it were the whole. Deciding how much goes in each brief is therefore a question about what the reviewer can be held to, which is why the skill asks rather than truncating silently.

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

The obvious reading of "break the document up" is one file per finding. The bulk cost was never the filesystem, though — it was what the endpoint injected, and a tool slices one file perfectly well. Splitting by finding would break review and round discovery, which read filenames, and the document's readability as one artifact a person opens. A file per ROUND is a different cut and the one this design makes: it splits along time, where nothing needs to be read across the seam except the round immediately before.

What splitting by finding would genuinely help is the **write** path: step 9 still materializes the full document, so the orchestrator holds every carried finding's text even where nothing happened to it. That cost is accepted. The alternative — applying dispositions as edits to a copy of the seeded round — reintroduces a mutable working file and the read-back checks that guarded the old in-place rewrite.

### R15.4 Why a round carries only its own cross-cutting section

A cross-cutting-decisions section records what one round concluded about the finding set as a whole. While the document was rewritten in place they accumulated — 2,643, 4,106, 7,234, 11,456 bytes over four passes of one chain, roughly doubling each round — and the outline had to elide every section earlier than the header's pass counter so they were not re-read on every pass. With rounds as separate files there is nothing to accumulate: each file holds its own round's decisions and the earlier ones stay where they were written. The elision is kept for documents written the old way, keyed on the pass number in the heading rather than on position, and a section carrying no pass number is never elided, since nothing establishes that anything superseded it.

