# PR #<N> — Round <iteration> Review

**Pass <k>** — <B> blocking, <A> advisory, <I> incidental open. Closed <c>, rejected <r>, added <a>, carried unexamined <u> this pass.

Generated from a `<reviewers-per-role>`-reviewer review of PR #<N> (`<head-ref>` → `<base-ref>`, Closes #<issue>) at HEAD `<sha>`. Composition: `<reviewers-per-role>` reviewer(s) per role across role(s) `<role-a>`, `<role-b>`, … (`<reviewers-per-role> × <role-count>` reviewer subagents total). Findings are deduped within each role, merged across roles, and grouped by severity tier (blocking first). Each role's findings are confined to the files mapped to it in `guide-map.role`; any file may be read for context. Note for each role which globs scoped it and which files in this PR fell in scope.

**Pass line** — `<k>` is how many review passes have run against this document (1 on the round that created it, incremented by each `--verify` re-review). The open counts describe the finding set below; the deltas describe what this pass changed. `<u>` counts findings carried WITHOUT re-examination — either because their originating role was absent from this pass's role list, or because a reviewer that WAS dispatched returned no disposition for them. They are open and blocking as usual, but nobody looked at them this round, so the count is stated rather than left implicit, and the two causes are recorded separately because they have different remedies. A closed finding leaves the document entirely, with the reason recorded in the commit that removed it; a rejected one leaves the tiers but is recorded in the ledger below, so a later pass cannot re-raise it as new without saying so.

**Retired ids** — <B1, A3, … — every id ever issued and since closed or rejected.> This line is preserved AND extended by every pass: step 8 appends each id as it leaves the tiers, and removes one when a rejected finding is re-opened and reclaims it. New findings take the next id ABOVE the highest id carrying their prefix across BOTH this line and the surviving findings — `max(retired ∪ open) + 1`. The prefix records where a finding was FIRST raised — `B<n>` blocking, `A<n>` advisory, `I<n>` incidental — not where it now sits: a re-tiered finding keeps its id and moves between the sections, so `B4` in Tier 2 is ordinary and the next blocking id is still computed against every `B`. Neither source alone is the maximum. The survivors miss every retired id, so computing from them would reuse one and silently re-point every commit-history and implement-loop citation of it at a different defect; and this line records only ids since closed or rejected, so whenever the highest-ever id is still open — the normal case — it is lower than the open set and computing from it would collide with a finding that is still here.

**Phase-1 blindness** — <"Structural for every role" when each reviewer was dispatched in two turns with no seeded text in the first, which is the normal case. Otherwise name the roles run INLINE, where there is no separate phase-1 prompt to withhold the seeded set from: for those roles the ordering is instructional only, and an independent rediscovery is recorded as ordinary agreement rather than outranking a close.>

**Dedup approach** — Within a role, the consolidator collapses findings that name the same defect at the same reference into one (recording the reviewer agreement count, e.g. `4/5 reviewers`). Across roles, findings about the same defect are merged into a single entry that records every role that raised it; the entry takes the **highest** severity any role assigned, and dissent (a role that rated it lower, or did not raise it) is noted inline.

**Re-tiering** — a finding that changes tier keeps its id and moves between the sections below, and the `**(BLOCKING)**` marker in its heading MUST move with it: strip the marker when a finding moves to Tier 2 or Tier 3, add it when one moves to Tier 1. The parser reads that marker as authoritative OVER the enclosing tier, so a Tier 2 or Tier 3 finding that kept its marker is re-seeded as blocking on the next pass and the chain can never terminate. There is deliberately **no `**(INCIDENTAL)**` marker** and one MUST NOT be introduced: the blocking marker's override only ever promotes a finding INTO the termination predicate, so a stale one costs a wasted pass the next round recovers, whereas a marker that demoted would let a stale heading drop a blocking finding OUT of the predicate silently. Tier 3 membership is by section alone.

**Severity legend** — the tiers are defined by what a finding **is**, not by what it does to approval. **Blocking**: a correctness defect, or an *incorrect intent* finding — the implementation does something other than what the originating issue asked for. Gates termination. **Advisory**: on-issue work that adds to technical debt if it is not addressed now. Does not gate. **Incidental**: the finding does not pertain to the originating issue — a legitimate observation about a file the PR happens to touch, not about the work the issue specified. Does not gate, is not remediated in this PR, and is carried as a candidate for a future issue. An incidental finding is a **deferral, not a dismissal**: it stays here with its id and evidence intact, so the chain records the observation without the observation holding the chain open. The raising role's blocking policy decides whether an ON-ISSUE defect is Blocking or Advisory — a MUST / SHALL violation is the common Blocking case and a SHOULD / MAY observation the common Advisory one, but a policy need not be phrased in those terms — while relevance to the originating issue is what separates Incidental from both, and relevance is **not role-relative**: two roles disagreeing about it are disagreeing about the issue, not about their lenses. *(PR mode only. Paths mode has no originating issue, so there is nothing to test relevance against and this tier is unavailable there.)*

**Branch commit map (for fixup mapping):**
- `<sha>` — `<conventional-commit subject>` (`<touched files>`)
- `<sha>` — `<conventional-commit subject>` (`<touched files>`)
- …

---

## Tier 1 — Blocking

### B1 — <one-line finding title> **(BLOCKING)** — <role(s) / reviewer agreement>
**Reference:** `<file>:<line>` — use `file:line` when a single changed line applies; otherwise a file-level reference (`<file>`) or an issue-level one (`(cross-cutting — no single line)` / `issue acceptance criterion #<n>`) for omissions and diff-spanning concerns that have no single line.

**Issue:** <What is wrong and why it matters. State the evidence concretely — quote the offending text or name the exact symbol — and tie it to the guide rule, correctness property, or role lens it violates. If roles disagreed on severity, say so here and explain the dissent.>

**Remediation:**
- [x] <The recommended fix, pre-selected by the consolidator.> *(Recommended — <one-clause rationale>.)*
- [ ] <An alternative fix, if one is reasonable.>
- [ ] Other: ________________________________________________

**Tests to add:** <Optional — the test(s) that would catch a regression of this finding. Omit the whole line when none apply.>

**Touched commit:** `<sha>`

---

### B2 — <one-line finding title> **(BLOCKING)** — <role(s) / reviewer agreement>
**Reference:** `<file>:<line>` *(or `<file>` / `(cross-cutting — no single line)` / `issue acceptance criterion #<n>` for a line-less finding)*

**Issue:** <…>

**Remediation:**
- [x] <Recommended fix.> *(Recommended — <rationale>.)*
- [ ] <Alternative.>
- [ ] Other: ________________________________________________

**Touched commit:** `<sha>`

---

## Tier 2 — Advisory

### A1 — <one-line finding title> — <role(s) / reviewer agreement>
**Reference:** `<file>:<line>` *(or `<file>` / `(cross-cutting — no single line)` / `issue acceptance criterion #<n>` for a line-less finding)*

<Concise statement of the advisory observation and the lens it comes from.>
- [x] <Recommended fix.> *(Recommended — <rationale>.)*
- [ ] Other: ________________________________________________

**Touched commit:** `<sha>`

---

## Tier 3 — Incidental

<PR mode only — omit this whole section in paths mode, which has no originating issue to test relevance against. Omit it too on a round that found nothing incidental; a later pass adds it when it re-tiers one here.>

### I1 — <one-line finding title> — <role(s) / reviewer agreement>
**Reference:** `<file>:<line>` *(or `<file>` / `(cross-cutting — no single line)` for a line-less finding — an `issue acceptance criterion #<n>` reference cannot apply here, since a finding that traces to a criterion is by definition on-issue)*

<Concise statement of the observation, the lens it comes from, and — the part that puts it in this tier rather than Tier 2 — what shows it is off-issue: the code predates this PR, or no acceptance criterion covers it. Evidence is required here exactly as in the tiers above; deferring a finding is not a lower standard of proof.>
- [x] <Recommended fix, for whoever picks this up later.> *(Recommended — <rationale>.)*
- [ ] Other: ________________________________________________

**Touched commit:** `<sha>`

---

## Rejected in earlier passes

<One line per finding rejected by any pass, preserved and extended across passes — id, title, reference, the pass that rejected it, and the rationale. This section is supplied to a re-review's PHASE-2 message only, never to phase 1, so it records the decision without touching phase-1 blindness. A phase-1 finding restating an entry here is folded into that entry rather than admitted under a new id; a reviewer who thinks the rejection was wrong re-opens it explicitly and says what it missed. Without this, a rejected finding — one whose code was never changed, because the finding did not hold up as written — is re-raised by every subsequent fresh-context pass, takes a new id each time, and a rejected blocking finding blocks forever. Omit the section only on a document that has never rejected anything.>

- `<id>` — <title> (`<reference>`) — rejected pass <k>: <rationale>

## Cross-cutting decisions

<Themes that span multiple findings or a single root cause behind several of them — e.g. a doc-vs-reality mismatch repeated across files, an architectural choice that several findings orbit, or a tension between two roles' lenses that the consolidator resolved a particular way. Record the resolution and its rationale so the fixup pass applies it uniformly. Omit this section if there are no cross-cutting themes.>

## Fixup mapping

<For each blocking finding (and any advisory the user elects to fix), the commit its remediation should be folded into, so the fixup pass can `git commit --fixup=<sha>` against the right target. Group findings by the commit they touch.>

- `<sha>` (`<conventional-commit subject>`) — B1, B2, A1
- `<sha>` (`<conventional-commit subject>`) — B3
