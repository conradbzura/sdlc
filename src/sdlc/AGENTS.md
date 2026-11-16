# SDLC Pipeline for LLM Agents

This document describes the skill definitions and guides that form a structured software development lifecycle (SDLC) pipeline for LLM agents. It is the canonical source for all pipeline behaviour.

## Architecture

The SDLC pipeline is an MCP (Model Context Protocol) server. Skills are exposed as MCP tools and guides as MCP resources. Any MCP-compatible client (Claude Code, VS Code, JetBrains, etc.) can connect via stdio transport.

### MCP Tools

Each tool returns the full workflow instructions for its pipeline stage. The LLM reads these instructions and executes them step-by-step, respecting human-in-the-loop approval gates.

| Tool | Stage | Purpose |
|------|-------|---------|
| `sdlc_issue` | 1st | Draft and push a GitHub issue |
| `sdlc_implement` | 2nd | Implement a GitHub issue, continue an in-progress PR, or address a local review document's findings (`--review` selects an iteration or a PR URL to convert) |
| `sdlc_test` | 3rd | Analyze coverage and write comprehensive tests |
| `sdlc_commit` | 4th | Stage and commit changes with atomic commits |
| `sdlc_pr` | 5th | Review changes and create a draft pull request |
| `sdlc_review` | 6th | Review an open PR (diff) **or** a set of local file paths/globs, writing a consolidated local review document under `.sdlc/reviews/` (no GitHub posting); `--verify <review #>` instead runs a further round of review `<#>`, seeded from its latest round and written beside it as `review-<#>.<k>.md` with findings closed, rejected, or added |
| `sdlc_understand_chat` | — | Query the codebase knowledge graph |
| `sdlc_guides_for` | — | Resolve which test or style guides apply to a list of file paths |
| `sdlc_roles` | — | List the available review roles as resource URIs |
| `sdlc_role_scope` | — | Reverse-lookup the changed files that SEED a role's review scope (over the merged `guide-map.role`) |
| `sdlc_review_findings` | — | Fetch named findings' full bodies from a review document (the endpoints inject it as an outline) |
| `sdlc_role` | — | Author a review role document (lens, blocking policy, focus globs) |

The `implement`, `test`, and `commit` tools are iterative — they can be invoked multiple times for a given issue to address review feedback or refine implementation. `sdlc_implement` accepts either an issue number or a PR number plus a polymorphic `--review` selector, and dispatches between three sibling skill prompts:

- `implement` — fresh start (the number is an issue with no linked PR, and no local review document applies).
- `implement-continue` — a PR is in scope but no local review document exists for its closing issue.
- `implement-feedback` — a local review document is selected and its findings drive the remediation walk-through.

`--review` chooses the finding source for the feedback path:

- **omitted / `None`** — load the latest `.sdlc/reviews/issue-#<N>/review-<iteration>.md` for the closing issue `<N>` when one exists; otherwise fall through to `implement-continue` (linked PR) or `implement` (bare issue). Missing local docs are NOT an error on this default path.
- **`int`** — load that exact local iteration. A missing iteration is surfaced as a clear diagnostic, never a silent fresh fallback.
- **PR URL (`str`)** — fetch that PR's review threads and review-body comments, render them into a NEW local review document at the next iteration (never overwriting), and consume it. A string that is not a GitHub PR URL is rejected — a numeric string is never coerced into an iteration.

The dispatcher no longer auto-detects GitHub review threads: GitHub findings enter the implement loop only through an explicit `--review <pr-url>` conversion. Local documents are read directly off disk and need no `gh` round-trip.

#### Target-repo resolution

The deterministic target-repository fact — which repo `gh` commands should address — is computed **once by the tools and injected into the skills**, not recomputed per skill. Every tool whose skill runs `gh` against issues or PRs (`sdlc_issue`, `sdlc_implement`, `sdlc_test`, `sdlc_commit`, `sdlc_pr`, `sdlc_review`) resolves the repo via `pr_state.resolve_repo()` and appends a `Target repo: <id>` directive to the skill output: the upstream `<owner>/<name>` when the current repo is a fork (so issues and PRs are addressed against the upstream), or a "current repo — omit `--repo`" form otherwise. This mirrors how `sdlc_implement` and `sdlc_pr` append `Target issue` / `Target PR` / `Branch` / the target-branch-override directive. Each skill's "Resolve target repository" step consumes this directive instead of shelling out to `gh repo view --json isFork,parent`, eliminating the redundant round-trip and keeping the tool's computed value and the skill's view of the target repo in agreement by construction. Resolution degrades gracefully: if `gh` is unavailable the tool appends no directive, and the skill surfaces that `gh` is unavailable and stops (the `commit` skill, whose operations are local, instead proceeds and notes the fork relationship is unknown) — there is no fork-status fallback to run, since the directive is absent precisely when `gh` cannot be reached. The conversation-dependent fork override ("review the fork", "fork #N") stays in each skill, since the MCP tool signature never receives the user's prose — and it always takes precedence over the injected default.

### MCP Resources

| URI | Content |
|-----|---------|
| `sdlc://guides/test/{stem}` | Test guide identified by `{stem}` — bundled or user-supplied (e.g. `python`) |
| `sdlc://guides/style/{stem}` | Style guide identified by `{stem}` — bundled or user-supplied (e.g. `markdown`) |
| `sdlc://guides/role/{stem}` | Review role identified by `{stem}` — bundled (e.g. `general-purpose`, `aie`) or user-supplied |
| `sdlc://config/default` | Package-default `config.json` content (read this to discover the bundled guide-map) |
| `sdlc://role-template` | Bundled role-document template (the Lens and Blocking policy sections) |
| `sdlc://review-template` | Bundled consolidated-review-document template (pass line, retired-id line, three severity tiers, rejected-in-earlier-passes ledger, cross-cutting decisions, fixup mapping) |
| `sdlc://review-rationale` | Design rationale for the `review` skill — derivations, the failures that produced each guard, and the claims verified by execution. Read on demand when a block misbehaves; carries no rules |
| `sdlc://agents-md` | This file (project-level agent instructions) |
| `sdlc://knowledge-graph` | Codebase knowledge graph (if generated) |

Use the `sdlc_guides_for` tool to discover which `{stem}` values apply to a given set of file paths — see "Project Configuration" below.

## Project Configuration

Projects can extend or override the bundled test-, style-, and role-guides by dropping markdown files under `.sdlc/guides/{test,style,role}/` and (optionally) declaring a glob-to-guides map in `.sdlc/config.json`. The MCP server merges this user config on top of the package default at startup. Review roles use the same `guide-map` mechanism as `test` and `style` guides — a `role` namespace maps globs to role stems — with one difference in how they are consumed: a role is selected explicitly by name, and its `guide-map.role` entries bound which files the selected role's findings may apply to. That bound is the outer one, not the whole of scope — see **Review context and scope** below.

### Discovery

Guides are discovered from two sources at startup. Within each `kind` namespace (`test`, `style`, `role`), user guides win on stem collision.

1. **Bundled** — `src/sdlc/{test,style,role}-guides/*.md` shipped with the package.
2. **User** — files under the directory named by `guides-dir` (resolved relative to the config file's parent directory), or the convention path `<cwd>/.sdlc/guides/` when `guides-dir` is unset. Must contain `test/`, `style/`, and/or `role/` subdirectories with `*.md` files.

The stem is the filename without `.md`. Each discovered guide is exposed at `sdlc://guides/{kind}/{stem}`.

All three kinds (`test`, `style`, `role`) are configured via `guide-map`. `test` and `style` guides are resolved from changed file paths; `role` guides are listed by name via `sdlc_roles`, read at `sdlc://guides/role/<stem>`, and selected explicitly. A role's `guide-map.role` entries bound which files a reviewer running that role may raise findings against — resolved by a **reverse lookup** over `guide-map.role` (given a role stem, the globs mapped to it; the inverse of `sdlc_guides_for`'s path-to-stems direction). The `sdlc_review` tool consumes selected roles: it runs N reviewers per role, each bounded by its role's globs (see the Review pipeline below).

### Config file

`.sdlc/config.json` (kebab-case keys, all fields optional):

```json
{
  "guides-dir": ".sdlc/guides",
  "guide-map": {
    "test":  { "**/*.py": ["python", "pytest-patterns"] },
    "style": { "**/*.py": ["python"], "**/*.md": ["markdown"] },
    "role":  { "src/**/*.py": ["architect"] }
  }
}
```

The block carries no comments because JSON has none: `guides.load_user_config` raises `Malformed JSON in …/.sdlc/config.json` on one, and since `server.py` loads the config at import, a copied-in comment takes down every `sdlc_*` call for that project.

The example above is illustrative: `pytest-patterns`, the `style` `**/*.py` → `python` entry, and the `architect` role are hypothetical user-supplied entries. Only `python` (test), `markdown` (style), and the `general-purpose` and `aie` roles ship by default. The bundled `guide-map.role` maps only `**/*` → `general-purpose`; `aie` ships as a role document but is scoped per-project (its files are project-specific), so a project that wants it adds its own `guide-map.role` entry. See `sdlc://config/default` for the authoritative bundled map.

- `guides-dir` — path to a directory containing `test/`, `style/`, and/or `role/` subdirs of `*.md` guides. Resolved relative to the config file's parent directory. Defaults to the convention path `<cwd>/.sdlc/guides`.
- `guide-map` — namespace-split map (`test` / `style` / `role`). Each namespace maps glob patterns to lists of stems. A file picks up the union of stems from every pattern it matches in the requested namespace. Patterns are matched via [`pathlib.PurePath.full_match`](https://docs.python.org/3/library/pathlib.html#pathlib.PurePath.full_match) against the full relative path — see the Python docs for exact semantics. `**` matches any number of path components, so `**/*.py` matches Python files at any depth and `tests/**/*.py` matches them only under `tests/`. Bare patterns like `Dockerfile` are anchored to the root; use `**/Dockerfile` to match at any depth.

### Resolution order

1. `$SDLC_CONFIG` — if set, the user config is loaded from this absolute path. Useful when you want the file to live somewhere other than `.sdlc/config.json`. Set in `.mcp.json`:

   ```json
   { "mcpServers": { "sdlc": { "env": { "SDLC_CONFIG": "${PWD}/docs/sdlc.json" } } } }
   ```

2. `<cwd>/.sdlc/config.json` — the convention path.
3. No user config — the package default (visible at `sdlc://config/default`) applies.

### Merge semantics

User config merges onto the default per the following rules. Removing or replacing a default pattern requires writing the same pattern key with the desired value (or `[]` to disable):

- **Top level:** `guides-dir` from user replaces default.
- **`guide-map`:** per-namespace deep merge — user's `test` dict updates the default's `test` dict; same for `style` and `role`. Unmentioned namespaces pass through unchanged.
- **Inside a namespace:** pattern keys merge shallowly — a user pattern key replaces the default's same-pattern entry; disjoint pattern keys coexist.

### Skill integration

The `implement`, `test`, and `review` skills do not hardcode guide URIs. Each calls `sdlc_guides_for(paths, kind)` with the relevant file paths and reads every returned URI. To add a guide for a new language or convention, drop the markdown file in `.sdlc/guides/{test,style}/` and (if the file should be picked up for a path that the default map doesn't cover) add an entry to `guide-map` in `.sdlc/config.json`. Review roles follow the same configuration pattern — a markdown file under `.sdlc/guides/role/` plus a `guide-map.role` entry (the `sdlc_role` skill authors both) — but, unlike `test` and `style` guides, are selected by name rather than resolved from paths via `sdlc_guides_for`. When `sdlc_review` runs a role, it does the reverse: a reverse lookup over `guide-map.role` returns the globs mapped to that role, and the changed files those globs match seed the reviewer's scope (which it then extends to related files the PR did not touch — see **Review context and scope** below).

### Review prompt assembly and size

`sdlc_review` returns the review skill in full on every call, so the skill's size is a cost paid per invocation. Two mechanisms keep it down.

**Design rationale is a separate resource.** `skills/review.md` carries the executable protocol, the MUST/SHALL rules and the text the agent emits verbatim; the derivations, the failures that produced each guard, and the claims verified by execution live at `sdlc://review-rationale`, addressed by `§R<n>` id rather than by heading wording. The skill points at it with a deliberately subordinate idiom — italic, leading with `Why:`, and naming an observable trigger — because rationale is read when a block misbehaves, not as a precondition for a step. Guides use the opposite idiom, a bolded unconditional imperative, and the difference is load-bearing: a resource read on the critical path of every run is one an agent under load paraphrases instead of fetching. That is also why the reviewer brief, the phase-2 message and step 11's prompt templates stay in the skill. The rationale carries no rules, and a test enforces it — which is what makes the split verifiable, since a rule can then only be in the skill.

**The prompt is assembled per mode.** About a third of the skill is re-review-only, and the `Re-review:` directive is known at the endpoint before the skill body is concatenated. Re-review spans are fenced in the source with paired `<!-- rereview:begin -->` / `<!-- rereview:end -->` comments and stripped for a fresh round; a re-review assembly is byte-identical to the source minus the fence lines. The fences are blocks rather than per-line tags because roughly three quarters of the re-review material carries no `**(re-review)**` marker of its own — a marked header introduces paragraphs, bullets and command blocks that inherit its mode silently.

Measured on a fresh paths-mode round: the extraction took the assembled prompt from 138,587 to 85,790 bytes; later features brought it back up to 99,431; and removing the git layer — repository resolution, the commit-branch worktree, staging, and the per-mutation commit walk — brought it down to 75,840. `tests/test_prompt_budget.py` budgets the assembled prompt, the rationale's own size, and every other skill. The figures are measurements, not targets: the budget constants are the thing to read for what is actually enforced.

### The `.sdlc/reviews/` convention

`sdlc_review` writes a standardized local review document — it posts nothing to GitHub. It takes **exactly one** target: a PR number (PR mode) or a list of file paths/globs (paths mode); supplying neither or both raises `ValueError`. The review (produce) document is written autonomously as the final step: the skill presents the consolidated findings as informational, then writes the document. There is **one** approval gate, a question only the user can answer: **(re-review)** removing a blocking finding from the termination predicate without the corroboration described under Re-review below. It is stated over the OUTCOME rather than over the disposition vocabulary, so `close`, `reject` and a re-tier to **incidental** are all covered and naming a subset cannot leave a further route open. The write target is the next unused `review-<iteration>.md`, which the tool resolves deterministically (scanning the target directory for the highest existing round) and injects into the skill prompt as an exact `Review document: <dir>/review-<iteration>.md` path alongside the retained `Review document directory:` line — so the skill writes that path verbatim rather than globbing, and a run never overwrites an earlier document.

In **PR mode**, each review round is written to `.sdlc/reviews/issue-#<N>/review-<iteration>.md`, where `<N>` is the first issue the PR closes when several are linked (resolved from `closingIssuesReferences`, falling back to parsing `Closes #N` in the PR body; the connection has no ordering guarantee, so `<N>` is one closing issue, not necessarily the only one) and `<iteration>` is 1-based, one greater than the highest existing `review-*.md` for that issue.

In **paths mode**, there is no PR, no diff, no linked issue, and no `gh` call: the skill expands the supplied literal paths and globs against the working tree and reviews each matched file's whole contents. The round is written to `.sdlc/reviews/<slug>/review-<iteration>.md`, where `<slug>` is computed deterministically by the tool from the raw `paths` strings (no filesystem access) — a single literal file path yields that file's stem (e.g. `src/sdlc/role-guides/aie.md` → `aie`), while a glob or multi-path argument yields a sanitized join of the raw args plus an 8-hex-char SHA-256 suffix over the sorted, newline-joined paths. The slug is stable across argument order, so successive paths-mode reviews of the same target accumulate their `review-*.md` rounds in one directory. The `<iteration>` rule is the same as PR mode.

The document is structured from the bundled template (`sdlc://review-template`): a header (the pass line — `**Pass <k>**` with the open blocking `<B>`, advisory `<A>` and incidental `<I>` counts and this pass's `<c>` closed / `<r>` rejected / `<a>` added / `<u>` carried-unexamined deltas — plus roles used, reviewers per role, the retired-id line, dedup approach, severity legend; in PR mode also the target HEAD sha and branch commit map); findings grouped by severity tier (blocking, then advisory, then incidental) — each with a stable ID, title, severity, a `Reference` (`file:line`, or a file-level / issue-level reference for a line-less finding), an Issue section with evidence, a Remediation checklist where the consolidator pre-selects the recommended option (`[x]`), lists alternatives (`[ ]`), and always offers an `Other: ___` slot, and an optional Tests-to-add section; plus a rejected-in-earlier-passes ledger and a cross-cutting-decisions section. The pass line's `<k>` is the round number, which the endpoint reads off the filenames and injects as `Review round:`; the skill writes it rather than deriving it. **In PR mode** each finding also carries a Touched commit and the document ends with a fixup-mapping section; **in paths mode both are omitted** — there are no commits to attribute findings to or fold fixups into.

**Review context and scope.** Two bounds, not one, and conflating them is what let a PR close an issue it had not satisfied. **Context** is the entire repository: a reviewer MAY read any file at any time, reading is never restricted, and reading alone is never grounds for a finding. **Scope** is what a reviewer is answerable for. In PR mode it is code logically related to the originating issue's expected outcomes — **whether or not this PR touched it**, so a change a criterion required and nobody made is in scope precisely because it is missing — plus code this PR introduced or changed wherever it landed, all intersected with the files the role's `guide-map.role` globs match. In paths mode it is the matched files; the paths the user named are the intent statement and nothing widens them.

`sdlc_role_scope` **seeds** scope; it does not bound it. The call can only ever return files the PR changed, so treating its result as the boundary is what made an omission unraisable: the file is not in the diff, so it is in no reviewer's scope, so the finding cannot be made and the chain terminates with no blocking findings on a PR that does not satisfy the issue. Each reviewer extends the seed to related files its role covers, naming the criterion that admits each one, and the document's Scope line records those extensions so the widening is auditable. The role's globs remain the hard outer bound — relatedness is a judgement and a judgement with no mechanical bound drifts — and step 8 now verifies it per finding rather than trusting the brief: a finding outside the raising role's map is re-attributed to a role that covers it, or kept with a header note, never dropped. A reviewer sweeps each acceptance criterion before finishing, identifying the code that should satisfy it and verifying that it does; a change that should have been made and was not carries `(no commit — omission)` and is grouped in the fixup mapping under a new commit, since there is no sha to fold into.

**Severity tiers.** The three tiers are defined by what a finding **is**, not by what it does to approval — the second says nothing about whether a finding pertains to the issue the PR closes, and for three passes of this tool's own first re-review chain nothing in the pipeline asked. **Blocking** is a correctness defect, or an implementation that does something other than what the originating issue asked for; it gates termination. **Advisory** is on-issue work that adds to technical debt if it is not addressed now. **Incidental** does not pertain to the originating issue at all: a real observation about a file the PR happens to touch, recorded with its id and evidence as a deferral rather than dismissed, and carried as a candidate for a future issue. The raising role's blocking policy decides Blocking against Advisory for on-issue work; relevance to the issue is what separates Incidental from both, and relevance is not role-relative, so a blocking-versus-incidental disagreement is resolved against the acceptance criteria rather than by ranking the tiers — the finding stays blocking until it is. `sdlc_implement --review <#>` walks Tier 1 and Tier 2 and reports Tier 3 as deferrals without proposing work. Incidental is **PR mode only**: paths mode has no originating issue, so there is nothing to test relevance against and an off-issue observation is Advisory there. Documents written before this tier existed carry two tiers and parse unchanged; no migration is required.

The `**(BLOCKING)**` heading marker outranks the tier section a finding sits in, and there is deliberately **no `**(INCIDENTAL)**` counterpart**. The override is monotone toward blocking — it can only promote a finding into the termination predicate — so a marker left behind by a careless re-tier costs a pass the next round recovers. A demoting marker would drop a blocking finding out of the predicate silently, so Tier 3 membership is by section alone.

**Incremental disclosure.** The document is the largest artifact in the pipeline — 108,405 bytes rendered for a 55-finding round, against a ~103,000-byte fresh review prompt — and no consumer needs it whole. `sdlc_review --verify` and `sdlc_implement --review` therefore inject it as an **outline**: the document's own structure with every finding's `Issue` paragraph and `Remediation` checklist replaced by one marker each. Everything else is present verbatim — ids, severities, references, touched commits, full titles, role attributions, both ledgers, the pass header and the current pass's cross-cutting section. Bodies are fetched with `sdlc_review_findings(<document path>, [<ids>])` when a consumer reaches a finding it has to act on.

The enumeration is what makes the elision safe, so it stays whole: a finding absent from the injected block is absent from the round, gets no disposition and leaves no trace, which is the failure every guard in `pr_state` exists for. The outline is also itself a valid review document — parsing it yields the same findings with empty bodies. **The fetch is required, not advisory**, and deliberately the opposite idiom to `sdlc://review-rationale`: rationale is read on a symptom and may be skipped, a finding body is what a disposition or a remediation is judged against, so acting on an unfetched finding is acting on a title. A round carries only its own `## Pass <k> — cross-cutting decisions` section. A document written before rounds were separate files may hold several; any earlier than its header's counter is elided too.

In **PR mode**, this document is the finding source `sdlc_implement` consumes on its feedback path. By default a subsequent `sdlc_implement <N>` (or `sdlc_implement <pr#>`) parses the latest round of the **latest** review for the closing issue, renders its findings, and routes to `implement-feedback` so the agent walks each finding's pre-selected remediation through a per-finding approval gate. `--review <int>` selects a specific review instead, again at its latest round. `sdlc_implement` reads the document straight off disk — `sdlc_review` posts nothing to GitHub, and the dispatcher no longer probes GitHub review threads. A PR's GitHub review feedback can still feed the loop, but only by explicitly converting it first: `--review <pr-url>` fetches that PR's threads and review-body comments and writes them into a fresh local review document (at the next iteration) before consuming it. Paths-mode documents are not keyed to an issue and so are not auto-consumed by `sdlc_implement`; read and apply them directly.

**Re-review (`sdlc_review --verify <review #>`).** Layered on whichever target mode is active, a re-review continues an existing review rather than producing a new one: everything is a review, and `--verify` seeds one with an earlier round's findings. The endpoint loads the **latest round** of review `<#>` for the active target — from `.sdlc/reviews/issue-#<N>/` in PR mode (the closing issue is resolved exactly as for a fresh PR review), or `.sdlc/reviews/<slug>/` in paths mode (the same deterministic slug) — and raises `ValueError` if the target has no such review (a PR that closes no issue, a missing directory, or a missing iteration are all hard errors, consistent with the exactly-one-target guard; a bare `sdlc_review --verify <#>` with no target trips that guard too). It then emits the same directive set a fresh round does, with two differences: the `Review document:` write target is the NEXT round of that review — `review-<#>.<k>.md`, a new file beside the earlier rounds, which are never modified — and the loaded findings are rendered into the prompt as the **seeded** set. Round 1 is `review-<#>.md`, so a document written before rounds were separate files is read as round 1 with no migration.

Each reviewer keeps its role lens and `guide-map.role` confinement and reviews the current files exactly as on a fresh round. The two halves are ordered **structurally**, by dispatching each reviewer twice: the first message carries the ordinary fresh-round brief and no seeded text at all, and only once the reviewer has returned its own findings does a second message deliver the seeded set. A reviewer that reads the prior findings first tends to confirm them rather than review the code — and a remediation that resolves every prior finding while introducing a new one passes that unnoticed — but an instruction not to read ahead cannot prevent it, since a brief is read as one context. Withholding the seeded set is what makes the ordering real. It is paired with a prohibition on reading `.sdlc/reviews/` in the phase-1 brief, since the prior round's document otherwise sits at a guessable path inside the tree under review; together they earn the consolidator's treatment of an independent rediscovery as stronger evidence than agreement. The seeded findings are routed to each reviewer by **every role recorded on them** rather than by matching their `Reference` against a file set, so cross-cutting and issue-level findings are assignable rather than stranded and a finding two roles raised is judged by both; one whose recorded roles are all absent from this pass carries unchanged, with the header recording that it was not re-examined. For each finding in its subset the reviewer returns a disposition: **close** (the remediation the finding called for is present), **reject** (the finding does not hold up as written — a guide rule that is not in the supplied guide text, a wrong symbol or reference, an unsupported severity — so it is corrected in place or withdrawn), or **carry** (the defect remains and the finding still states it correctly). A defect introduced by an earlier pass's remediation is raised as a new finding, not a disposition. The consolidator applies the dispositions (carry beats close on disagreement; reject applies only when no reviewer carried it), folds in the new findings, and writes the next round. A closed finding leaves the tiers and is recorded, with its reason and the remediating text quoted, in that round's **Closed this round** ledger — the only record of why it closed. Removing a **blocking** finding is gated, because `close`, `reject` and a re-tier to **incidental** each take it out of the single predicate termination depends on and `Reviewers per role` defaults to 1: a blocking `reject` — and, on the same reasoning, re-tiering a blocking finding as off-issue — needs either two reviewers agreeing or explicit user confirmation, and a blocking `close` MUST quote the remediating text from the current file and, unless two reviewers that were dispatched that finding returned `close` independently, be confirmed by the user too — a count over the reviewers that judged it, not over the roles whose globs cover its file, since routing is by role and glob coverage can be two while only `Reviewers per role` agents ever saw it. Uncorroborated by any of the three routes, the finding stays as **carry** with the dissent noted. The gate is stated over the outcome rather than over the disposition vocabulary, so naming two dispositions cannot leave the third door open. Blocking `carry` and every advisory disposition stay autonomous. Finding ids are stable across passes — a carried or corrected finding keeps its id, and retired ids are never reused — because they are cited by earlier rounds and by `sdlc_implement --review <#>`. Since closed and rejected findings are deleted from the tiers, "next unused" cannot be computed from the surviving set; the document carries a **retired-id** line, and a new finding takes the next id above the highest ever issued carrying that prefix — across both the surviving findings and the `Retired ids` line, regardless of the tier each now sits in. Rejections are likewise recorded in a **Rejected in earlier passes** ledger, supplied to the phase-2 message only. Without it a rejected finding — whose code was never changed, because the finding did not hold up as written — is re-raised by every later fresh-context pass under a new id, and a rejected blocking finding blocks forever.

There is no separate verdict artifact: a review is the **sequence of its round files**, each a complete document, and together they are the record of how the review evolved. Iteration terminates on one condition — **no blocking findings remain**. Advisory and incidental findings are carried across passes, subject to the same close and reject treatment, and neither gates. They are reported as two numbers rather than one because they are different backlogs: an advisory finding is on-issue debt this PR took on and can still pay, while an incidental one does not pertain to the originating issue at all and is a candidate for a future one. When blocking findings remain, the next step is `sdlc_implement <target> --review <#>` to address them, followed by another `sdlc_review --verify <#> --roles <the roles that round used>`. The roles matter: a seeded finding whose originating role is absent from a pass has no reviewer and carries unexamined, so a re-review under a narrower role list reports progress while looking at nothing. `--roles` is inherited from the seeded document's Composition line when omitted, and an explicit list that fails to cover the seeded roles is warned about. That inheritance is a parse, so the line's shape is a contract: the role stems are read backticked and comma-separated immediately after the literal `role(s)`, up to the first parenthesis or end of line. A line that names no stems that way yields nothing to inherit and the pass falls back to `general-purpose` — which would carry every finding of a round run under another role — so the endpoint emits a coverage warning in that case too, rather than failing silently. Remediation stays with the user-driven implement loop; `sdlc_review` never fixes code. Nothing is posted to GitHub.

**Recorded code state.** A finding cites `file:line` on a branch whose history is routinely rewritten before merge, so the commits a review was performed against do not survive to be pointed at. Each round therefore records the state it reviewed in a small metadata file beside its document — `review-<#>.meta.json` for round 1, `review-<#>.<k>.meta.json` after.

The record holds the mode, the round, the merge-base with the upstream default branch, a content-addressed tree SHA for the working tree as reviewed, the head, whether the tree was dirty, and — in PR mode — whether that state matched the PR head. The anchor ref is resolved explicitly (`git symbolic-ref refs/remotes/<remote>/HEAD`, preferring a distinct `upstream` remote over `origin`, which is the fork when working from one) rather than taken as the PR's base branch, which may be deleted once a stacked PR merges. An anchor that cannot be resolved does not stop the review: the record carries `"vcs": "unanchored"` and a JSON `null` base, and still records the tree. Outside a repository it carries `"vcs": "none"` with a `null` base and tree — `meta["base"] is None` is the correct test.

The tree is hashed through a throwaway `GIT_INDEX_FILE` built from **empty**, so uncommitted and untracked work is included without disturbing the real index, and `.sdlc/reviews` is excluded by a pathspec anchored to the repository top and derived from the working directory's prefix. Without the exclusion the tree SHA would change every round regardless of the code, since each round adds a document. `head_matches_target` is `true` only when the PR-head sha matched **and** the working tree — measured over the same pathspec — was clean; the sha alone is insufficient, because `git rev-parse HEAD` returns the same value however dirty the tree is.

There is no patch. An earlier design stored a full diff from base to tree so the state could be restored byte for byte; at about a megabyte per round it was only affordable while each round overwrote the last. The tree SHA still answers whether what merged is what was reviewed: hash the merged tree the same way and compare.

**No git tracking.** `sdlc_review` commits nothing and resolves no repository. An earlier design committed every round to a repository nested at `.sdlc`, one commit per finding-set mutation; it was removed because the machinery it needed — repository resolution and refusal, ignore checks, a commit-branch worktree, staging and promotion, a mutation-by-mutation walk — was about a third of the skill and the source of most of its defects. Rounds as separate files give the same safety (nothing is ever overwritten) without it, and the reasons for each state change live in the documents. Whether `.sdlc/reviews/` is tracked, and where, is the project's decision.

## Installation & Setup

Configure your MCP client to launch the `sdlc-mcp` server.

**Claude Code** (`.mcp.json` in project root or `~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "sdlc": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/conradbzura/sdlc", "sdlc-mcp"]
    }
  }
}
```

**Development install:**

```bash
git clone https://github.com/conradbzura/sdlc
cd sdlc
pip install -e .
```

Then point your MCP client to the `sdlc-mcp` command.

**Verification:**

```bash
# Test server starts and responds to MCP protocol
mcp dev src/sdlc/server.py
```

### Optional: Token-Efficient Context with Understand-Anything

For large codebases, the `implement`, `test`, and `commit` tools can reference a codebase knowledge graph to gather architectural context without sending entire source files as context. [Understand-Anything](https://github.com/Lum1104/Understand-Anything) analyzes project structure, extracts file relationships, and generates a lightweight JSON knowledge graph that agents can query instead of reading raw source.

Once generated, the tools will automatically use the knowledge graph to answer architectural questions (e.g., "What components import this file?", "What functions call this one?") during planning and review phases. This dramatically reduces token usage on large codebases while improving recommendation quality.

## Directory Layout

```
sdlc/
├── AGENTS.md                        ← symlink → src/sdlc/AGENTS.md
├── pyproject.toml                   ← Python package config
└── src/sdlc/                        ← MCP server package
    ├── __init__.py
    ├── __main__.py
    ├── server.py                    ← FastMCP server, tools, resources
    ├── guides.py                    ← Config loader, guide discovery, resolver
    ├── pr_state.py                  ← gh wrappers and PR-state dispatch for sdlc_implement
    ├── config.json                  ← Package-default config (guide-map)
    ├── role-template.md             ← Bundled role-document template
    ├── review-template.md           ← Bundled consolidated-review-document template
    ├── review-rationale.md          ← Design rationale for the review skill (an MCP resource)
    ├── AGENTS.md                    ← you are here (canonical)
    ├── skills/                      ← Canonical skill definitions (read by server)
    │   ├── issue.md
    │   ├── implement.md
    │   ├── implement-continue.md
    │   ├── implement-feedback.md
    │   ├── test.md
    │   ├── commit.md
    │   ├── pr.md
    │   ├── review.md
    │   ├── role.md
    │   └── understand-chat.md
    ├── test-guides/                 ← Bundled test guides (extend via .sdlc/guides/test/)
    │   └── python.md
    ├── style-guides/                ← Bundled style guides (extend via .sdlc/guides/style/)
    │   └── markdown.md
    └── role-guides/                 ← Bundled review roles (extend via .sdlc/guides/role/)
        ├── general-purpose.md
        └── aie.md                   ← AI-engineering lens; scope set per-project in guide-map.role
```

## Pipeline Overview

The typical development flow follows this sequence. Start by drafting a GitHub issue with acceptance criteria and description. Fetch the issue, create a feature branch, enter planning phase, and design a concrete implementation plan. Execute the plan by writing code and tests, guided by project context and test conventions. Optionally, analyze code changes, evaluate existing test coverage, and generate comprehensive test specifications targeting 100% coverage of public APIs. Analyze the working tree diff, group changes by logical kind, and create disciplined atomic commits with conventional-commit messages. Review the branch diff and create or update a draft pull request linked to the issue. Fetch the PR, review it through one or more role lenses (N reviewers per role), and consolidate the findings into a single local review document under `.sdlc/reviews/` — nothing is posted to GitHub. To act on the findings, re-run `sdlc_implement`: it parses the latest review document (or the `--review`-selected iteration / PR-URL conversion), renders the findings, and routes to `implement-feedback` for a per-finding, approval-gated remediation walk-through.

The `implement`, `test`, and `commit` steps are iterative — you can run them multiple times to refine the implementation based on feedback or additional context. After each change, re-run `sdlc_pr` to update the PR description before final review.

## Tool-Specific Execution

Each skill includes an "Implementation Notes" section that provides tool-specific execution instructions.

**Claude Code:** Skills include explicit instructions for using the `EnterPlanMode` tool, subagent invocation via the `Agent` tool, and other Claude Code-specific features.

**Other LLM assistants:** A generic fallback is provided (output the plan as structured text, wait for explicit approval).

All skills follow this pattern:

```markdown
## Implementation Notes

When instructions reference "enter planning phase," execute it according to your tool:

**Claude Code:**
- MUST invoke the `EnterPlanMode` tool...
- MUST spawn a subagent...

**Other LLM assistants:**
- MUST output the plan as structured text...
- MUST wait for explicit user approval...
```

This keeps skill definitions portable while supporting tool-specific optimizations.

### Pipeline References

The SDLC pipeline is referenced as: `issue` → `implement` → `test` → `commit` → `pr` → `review`
