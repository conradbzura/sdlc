# PR #<N> — Round <iteration> Review

**Pass <k>** — <B> blocking, <A> advisory open. Closed <c>, rejected <r>, added <a>, carried unexamined <u> this pass.

Generated from a `<reviewers-per-role>`-reviewer review of PR #<N> (`<head-ref>` → `<base-ref>`, Closes #<issue>) at HEAD `<sha>`. Composition: `<reviewers-per-role>` reviewer(s) per role across role(s) `<role-a>`, `<role-b>`, … (`<reviewers-per-role> × <role-count>` reviewer subagents total). Findings are deduped within each role, merged across roles, and grouped by severity tier (blocking first). Each role's findings are confined to the files mapped to it in `guide-map.role`; any file may be read for context. Note for each role which globs scoped it and which files in this PR fell in scope.

**Pass line** — `<k>` is how many review passes have run against this document (1 on the round that created it, incremented by each `--verify` re-review). The open counts describe the finding set below; the deltas describe what this pass changed. `<u>` counts findings carried WITHOUT re-examination — either because their originating role was absent from this pass's role list, or because a reviewer that WAS dispatched returned no disposition for them. They are open and blocking as usual, but nobody looked at them this round, so the count is stated rather than left implicit, and the two causes are recorded separately because they have different remedies. A closed finding leaves the document entirely, with the reason recorded in the commit that removed it; a rejected one leaves the tiers but is recorded in the ledger below, so a later pass cannot re-raise it as new without saying so.

**Retired ids** — <B1, A3, … — every id ever issued and since closed or rejected.> This line is preserved AND extended by every pass: step 8 appends each id as it leaves the tiers, and removes one when a rejected finding is re-opened and reclaims it. New findings take the next id ABOVE the highest id in their tier across BOTH this line and the surviving findings — `max(retired ∪ open) + 1`. Neither source alone is the maximum. The survivors miss every retired id, so computing from them would reuse one and silently re-point every commit-history and implement-loop citation of it at a different defect; and this line records only ids since closed or rejected, so whenever the highest-ever id is still open — the normal case — it is lower than the open set and computing from it would collide with a finding that is still here.

**Phase-1 blindness** — <"Structural for every role" when each reviewer was dispatched in two turns with no seeded text in the first, which is the normal case. Otherwise name the roles run INLINE, where there is no separate phase-1 prompt to withhold the seeded set from: for those roles the ordering is instructional only, and an independent rediscovery is recorded as ordinary agreement rather than outranking a close.>

**Dedup approach** — Within a role, the consolidator collapses findings that name the same defect at the same reference into one (recording the reviewer agreement count, e.g. `4/5 reviewers`). Across roles, findings about the same defect are merged into a single entry that records every role that raised it; the entry takes the **highest** severity any role assigned, and dissent (a role that rated it lower, or did not raise it) is noted inline.

**Re-tiering** — a finding that changes tier keeps its id and moves between the sections below, and the `**(BLOCKING)**` marker in its heading MUST move with it: strip the marker when a finding moves to Tier 2, add it when one moves to Tier 1. The parser reads that marker as authoritative OVER the enclosing tier, so a Tier 2 finding that kept its marker is re-seeded as blocking on the next pass and the chain can never terminate.

**Severity legend** (the raising role's blocking policy is authoritative; the MUST/SHALL gloss is one example, not the definition) — **Blocking**: a defect that MUST be resolved before the PR can be approved per the raising role's blocking policy (for example, a violation of a MUST / SHALL guide rule, or a correctness defect on a consequential path). **Advisory**: clarity, consistency, or quality observations that do not gate approval per that policy (for example, SHOULD / MAY observations or optional improvements).

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

## Rejected in earlier passes

<One line per finding rejected by any pass, preserved and extended across passes — id, title, reference, the pass that rejected it, and the rationale. This section is supplied to a re-review's PHASE-2 message only, never to phase 1, so it records the decision without touching phase-1 blindness. A phase-1 finding restating an entry here is folded into that entry rather than admitted under a new id; a reviewer who thinks the rejection was wrong re-opens it explicitly and says what it missed. Without this, a rejected finding — one whose code was never changed, because the finding did not hold up as written — is re-raised by every subsequent fresh-context pass, takes a new id each time, and a rejected blocking finding blocks forever. Omit the section only on a document that has never rejected anything.>

- `<id>` — <title> (`<reference>`) — rejected pass <k>: <rationale>

## Cross-cutting decisions

<Themes that span multiple findings or a single root cause behind several of them — e.g. a doc-vs-reality mismatch repeated across files, an architectural choice that several findings orbit, or a tension between two roles' lenses that the consolidator resolved a particular way. Record the resolution and its rationale so the fixup pass applies it uniformly. Omit this section if there are no cross-cutting themes.>

## Fixup mapping

<For each blocking finding (and any advisory the user elects to fix), the commit its remediation should be folded into, so the fixup pass can `git commit --fixup=<sha>` against the right target. Group findings by the commit they touch.>

- `<sha>` (`<conventional-commit subject>`) — B1, B2, A1
- `<sha>` (`<conventional-commit subject>`) — B3
