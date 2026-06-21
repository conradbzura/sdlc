# PR #<N> — Round <iteration> Review

Generated from a `<reviewers-per-role>`-reviewer review of PR #<N> (`<head-ref>` → `<base-ref>`, Closes #<issue>) at HEAD `<sha>`. Composition: `<reviewers-per-role>` reviewer(s) per role across role(s) `<role-a>`, `<role-b>`, … (`<reviewers-per-role> × <role-count>` reviewer subagents total). Findings are deduped within each role, merged across roles, and grouped by severity tier (blocking first). Each role's findings are confined to the files mapped to it in `guide-map.role`; any file may be read for context. Note for each role which globs scoped it and which files in this PR fell in scope.

**Dedup approach** — Within a role, the consolidator collapses findings that name the same defect at the same reference into one (recording the reviewer agreement count, e.g. `4/5 reviewers`). Across roles, findings about the same defect are merged into a single entry that records every role that raised it; the entry takes the **highest** severity any role assigned, and dissent (a role that rated it lower, or did not raise it) is noted inline.

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

## Cross-cutting decisions

<Themes that span multiple findings or a single root cause behind several of them — e.g. a doc-vs-reality mismatch repeated across files, an architectural choice that several findings orbit, or a tension between two roles' lenses that the consolidator resolved a particular way. Record the resolution and its rationale so the fixup pass applies it uniformly. Omit this section if there are no cross-cutting themes.>

## Fixup mapping

<For each blocking finding (and any advisory the user elects to fix), the commit its remediation should be folded into, so the fixup pass can `git commit --fixup=<sha>` against the right target. Group findings by the commit they touch.>

- `<sha>` (`<conventional-commit subject>`) — B1, B2, A1
- `<sha>` (`<conventional-commit subject>`) — B3
