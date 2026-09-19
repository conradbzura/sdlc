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
| `sdlc_review` | 6th | Review an open PR (diff) **or** a set of local file paths/globs, writing a consolidated local review document under `.sdlc/reviews/` (no GitHub posting); `--verify <review #>` instead re-reviews an existing `review-<#>.md`, rewriting it in place with findings closed, rejected, or added, and committing each mutation separately |
| `sdlc_understand_chat` | — | Query the codebase knowledge graph |
| `sdlc_guides_for` | — | Resolve which test or style guides apply to a list of file paths |
| `sdlc_roles` | — | List the available review roles as resource URIs |
| `sdlc_role_scope` | — | Reverse-lookup the changed files a role's findings are confined to (over the merged `guide-map.role`) |
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
| `sdlc://review-template` | Bundled consolidated-review-document template (header, severity-tiered findings, cross-cutting decisions, fixup mapping) |
| `sdlc://agents-md` | This file (project-level agent instructions) |
| `sdlc://knowledge-graph` | Codebase knowledge graph (if generated) |

Use the `sdlc_guides_for` tool to discover which `{stem}` values apply to a given set of file paths — see "Project Configuration" below.

## Project Configuration

Projects can extend or override the bundled test-, style-, and role-guides by dropping markdown files under `.sdlc/guides/{test,style,role}/` and (optionally) declaring a glob-to-guides map in `.sdlc/config.json`. The MCP server merges this user config on top of the package default at startup. Review roles use the same `guide-map` mechanism as `test` and `style` guides — a `role` namespace maps globs to role stems — with one difference in how they are consumed: a role is selected explicitly by name, and its `guide-map.role` entries scope which files the selected role's findings apply to (any file may still be read for context).

### Discovery

Guides are discovered from two sources at startup. Within each `kind` namespace (`test`, `style`, `role`), user guides win on stem collision.

1. **Bundled** — `src/sdlc/{test,style,role}-guides/*.md` shipped with the package.
2. **User** — files under the directory named by `guides-dir` (resolved relative to the config file's parent directory), or the convention path `<cwd>/.sdlc/guides/` when `guides-dir` is unset. Must contain `test/`, `style/`, and/or `role/` subdirectories with `*.md` files.

The stem is the filename without `.md`. Each discovered guide is exposed at `sdlc://guides/{kind}/{stem}`.

All three kinds (`test`, `style`, `role`) are configured via `guide-map`. `test` and `style` guides are resolved from changed file paths; `role` guides are listed by name via `sdlc_roles`, read at `sdlc://guides/role/<stem>`, and selected explicitly. A role's `guide-map.role` entries scope which files a reviewer running that role confines its findings to — resolved by a **reverse lookup** over `guide-map.role` (given a role stem, the globs mapped to it; the inverse of `sdlc_guides_for`'s path-to-stems direction). The `sdlc_review` tool consumes selected roles: it runs N reviewers per role, each confined to its role's mapped files (see the Review pipeline below).

### Config file

`.sdlc/config.json` (kebab-case keys, all fields optional):

```json
{
  "guides-dir": ".sdlc/guides",
  "review-branch": "reviews",
  "review-repo": ".",
  "guide-map": {
    "test":  { "**/*.py": ["python", "pytest-patterns"] },
    "style": { "**/*.py": ["python"], "**/*.md": ["markdown"] },
    "role":  { "src/**/*.py": ["architect"] }
  }
}
```

The example above is illustrative: `pytest-patterns`, the `style` `**/*.py` → `python` entry, and the `architect` role are hypothetical user-supplied entries. Only `python` (test), `markdown` (style), and the `general-purpose` and `aie` roles ship by default. The bundled `guide-map.role` maps only `**/*` → `general-purpose`; `aie` ships as a role document but is scoped per-project (its files are project-specific), so a project that wants it adds its own `guide-map.role` entry. See `sdlc://config/default` for the authoritative bundled map.

- `guides-dir` — path to a directory containing `test/`, `style/`, and/or `role/` subdirs of `*.md` guides. Resolved relative to the config file's parent directory. Defaults to the convention path `<cwd>/.sdlc/guides`.
- `review-branch` — the branch `sdlc_review` commits review documents to, overridable per call by the tool's `target` argument. Unset means the checked-out branch, which is the default. Validated against git's ref-format rules at load, since the value reaches a `git` invocation and is interpolated into the directive block the reviewing agent reads.
- `review-repo` — path to the git repository review documents are committed to, resolved relative to the config file's parent exactly as `guides-dir` is. Unset falls back to `.sdlc` when it is already a repository; when it is not, `sdlc_review` reports the repository unresolved and the skill asks the user rather than inferring one.
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

- **Top level:** `guides-dir`, `review-branch` and `review-repo` from user replace default.
- **`guide-map`:** per-namespace deep merge — user's `test` dict updates the default's `test` dict; same for `style` and `role`. Unmentioned namespaces pass through unchanged.
- **Inside a namespace:** pattern keys merge shallowly — a user pattern key replaces the default's same-pattern entry; disjoint pattern keys coexist.

### Skill integration

The `implement`, `test`, and `review` skills do not hardcode guide URIs. Each calls `sdlc_guides_for(paths, kind)` with the relevant file paths and reads every returned URI. To add a guide for a new language or convention, drop the markdown file in `.sdlc/guides/{test,style}/` and (if the file should be picked up for a path that the default map doesn't cover) add an entry to `guide-map` in `.sdlc/config.json`. Review roles follow the same configuration pattern — a markdown file under `.sdlc/guides/role/` plus a `guide-map.role` entry (the `sdlc_role` skill authors both) — but, unlike `test` and `style` guides, are selected by name rather than resolved from paths via `sdlc_guides_for`. When `sdlc_review` runs a role, it does the reverse: a reverse lookup over `guide-map.role` returns the globs mapped to that role, and the reviewer confines its findings to the changed files those globs match (any file may still be read for context).

### The `.sdlc/reviews/` convention

`sdlc_review` writes a standardized local review document — it posts nothing to GitHub. It takes **exactly one** target: a PR number (PR mode) or a list of file paths/globs (paths mode); supplying neither or both raises `ValueError`. The review (produce) document is written autonomously as the final step: the skill presents the consolidated findings as informational, then writes the document without an approval gate. The write target is the next unused `review-<iteration>.md`, which the tool resolves deterministically (scanning the target directory for the highest existing round) and injects into the skill prompt as an exact `Review document: <dir>/review-<iteration>.md` path alongside the retained `Review document directory:` line — so the skill writes that path verbatim rather than globbing, and a run never overwrites an earlier round.

In **PR mode**, each review round is written to `.sdlc/reviews/issue-#<N>/review-<iteration>.md`, where `<N>` is the first issue the PR closes when several are linked (resolved from `closingIssuesReferences`, falling back to parsing `Closes #N` in the PR body; the connection has no ordering guarantee, so `<N>` is one closing issue, not necessarily the only one) and `<iteration>` is 1-based, one greater than the highest existing `review-*.md` for that issue.

In **paths mode**, there is no PR, no diff, no linked issue, and no `gh` call: the skill expands the supplied literal paths and globs against the working tree and reviews each matched file's whole contents. The round is written to `.sdlc/reviews/<slug>/review-<iteration>.md`, where `<slug>` is computed deterministically by the tool from the raw `paths` strings (no filesystem access) — a single literal file path yields that file's stem (e.g. `src/sdlc/role-guides/aie.md` → `aie`), while a glob or multi-path argument yields a sanitized join of the raw args plus an 8-hex-char SHA-256 suffix over the sorted, newline-joined paths. The slug is stable across argument order, so successive paths-mode reviews of the same target accumulate their `review-*.md` rounds in one directory. The `<iteration>` rule is the same as PR mode.

The document is structured from the bundled template (`sdlc://review-template`): a header (roles used, reviewers per role, dedup approach, severity legend; in PR mode also the target HEAD sha and branch commit map); findings grouped by severity tier (blocking first) — each with a stable ID, title, severity, a `Reference` (`file:line`, or a file-level / issue-level reference for a line-less finding), an Issue section with evidence, a Remediation checklist where the consolidator pre-selects the recommended option (`[x]`), lists alternatives (`[ ]`), and always offers an `Other: ___` slot, and an optional Tests-to-add section; plus a cross-cutting-decisions section. **In PR mode** each finding also carries a Touched commit and the document ends with a fixup-mapping section; **in paths mode both are omitted** — there are no commits to attribute findings to or fold fixups into.

In **PR mode**, this document is the finding source `sdlc_implement` consumes on its feedback path. By default a subsequent `sdlc_implement <N>` (or `sdlc_implement <pr#>`) parses the **latest** `review-<iteration>.md` for the closing issue, renders its findings, and routes to `implement-feedback` so the agent walks each finding's pre-selected remediation through a per-finding approval gate. `--review <int>` selects a specific earlier iteration instead. `sdlc_implement` reads the document straight off disk — `sdlc_review` posts nothing to GitHub, and the dispatcher no longer probes GitHub review threads. A PR's GitHub review feedback can still feed the loop, but only by explicitly converting it first: `--review <pr-url>` fetches that PR's threads and review-body comments and writes them into a fresh local review document (at the next iteration) before consuming it. Paths-mode documents are not keyed to an issue and so are not auto-consumed by `sdlc_implement`; read and apply them directly.

**Re-review (`sdlc_review --verify <review #>`).** Layered on whichever target mode is active, a re-review continues an existing review rather than producing a new one: everything is a review, and `--verify` seeds one with an earlier round's findings. The endpoint loads the existing `review-<#>.md` for the active target — `.sdlc/reviews/issue-#<N>/review-<#>.md` in PR mode (the closing issue is resolved exactly as for a fresh PR review), or `.sdlc/reviews/<slug>/review-<#>.md` in paths mode (the same deterministic slug) — and raises `ValueError` if the target has no such document (a PR that closes no issue, a missing directory, or a missing iteration are all hard errors, consistent with the exactly-one-target guard; a bare `sdlc_review --verify <#>` with no target trips that guard too). It then emits the same directive set a fresh round does, with two differences: the `Review document:` write target is that existing `review-<#>.md` rather than a new iteration, and the loaded findings are rendered into the prompt as the **seeded** set.

Each reviewer keeps its role lens and `guide-map.role` confinement and reviews the current files exactly as on a fresh round. On top of that it receives the seeded findings whose `Reference` falls in its in-scope files and returns a disposition for each: **close** (the remediation the finding called for is present), **reject** (the finding does not hold up as written — a guide rule that is not in the supplied guide text, a wrong symbol or reference, an unsupported severity — so it is corrected in place or withdrawn), or **carry** (the defect remains and the finding still states it correctly). A defect introduced by an earlier pass's remediation is raised as a new finding, not a disposition. The consolidator applies the dispositions (carry beats close on disagreement; reject applies only when no reviewer carried it), folds in the new findings, and rewrites `review-<#>.md` in place. Finding ids are stable across passes — a carried or corrected finding keeps its id, new findings take the next unused id in their tier, and retired ids are never reused — because they are cited in the commit history and by `sdlc_implement --review <#>`.

There is no separate verdict artifact: `review-<#>.md` is a **living document** whose git history is the record of how the review evolved. Iteration terminates on one condition — **no blocking findings remain**. Advisory findings are carried across passes, subject to the same close and reject treatment, but never gate. When blocking findings remain, the next step is `sdlc_implement <target> --review <#>` to address them, followed by another `sdlc_review --verify <#>`. Remediation stays with the user-driven implement loop; `sdlc_review` never fixes code. Nothing is posted to GitHub.

**Git tracking.** Every round is committed, and in a re-review each finding-set mutation is its own commit whose message justifies that state change (`review: Close B2 — nil guard now present at server.py:318`). Mutations are applied in the order close → reject → add, and each commit leaves the document internally consistent, header counts included. Review-document commits take a `review:` type prefix, which is never used for code commits; the other subject rules are the `commit` skill's.

The repository is **declared, not inferred**. `git_state.resolve_review_repo` reads the `review-repo` config key — resolved relative to the config file's parent, as `guides-dir` is — and falls back to `.sdlc` only when that directory is already a repository. It is pure filesystem work; nothing in this package runs `git` (`pr_state._run_gh` shells out to `gh` only, and every git operation in the pipeline is performed by the agent following the skill markdown). The endpoint injects `Review repository: <absolute path>`, plus `Review document in repository: <path>` giving the same document addressed from that root — the path every `git` command in step 10 takes, as distinct from the working-directory-relative `Review document:` the file is written to. The two differ whenever the repository is not the working directory, which is the normal case when `.sdlc` is its own repository.

When neither the config key nor the `.sdlc` fallback yields a repository, the directive reads `Review repository: unresolved` and the skill stops to ask the user — either name an existing repository or `git init .sdlc` — then records the answer as `review-repo` so the question is asked once. This mirrors how PR mode reports an unresolved linked issue instead of guessing a path. An earlier design walked from the working directory up to the filesystem root looking for a `.git`; it could silently select a repository the user never intended (a home directory managed as a dotfiles repo, say), so the search was removed rather than bounded. A configured path that is not a repository is likewise reported, never quietly replaced by a fallback, and an ignored review path is an error the user resolves rather than something to force-add.

An optional `Review commit branch:` directive names the branch the commits land on, resolved as the explicit `target` argument, then the `review-branch` config key, then — when the directive is absent entirely — the checked-out branch. The endpoint cannot read the current branch without running `git`, so "default to the working branch" is expressed by emitting no directive at all. When the named branch differs from the one checked out, the skill commits through a temporary `git worktree` so the tree under review is never disturbed. Note that this `target` is a commit destination, unlike the same-named parameter of `sdlc_implement` and `sdlc_pr`, which names a branch to branch from or base against.

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
    ├── git_state.py                 ← resolves the repository review documents are committed to
    ├── config.json                  ← Package-default config (guide-map)
    ├── role-template.md             ← Bundled role-document template
    ├── review-template.md           ← Bundled consolidated-review-document template
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
