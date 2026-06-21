# SDLC Pipeline for LLM Agents

This document describes the skill definitions and guides that form a structured software development lifecycle (SDLC) pipeline for LLM agents. It is the canonical source for all pipeline behaviour.

## Architecture

The SDLC pipeline is an MCP (Model Context Protocol) server. Skills are exposed as MCP tools and guides as MCP resources. Any MCP-compatible client (Claude Code, VS Code, JetBrains, etc.) can connect via stdio transport.

### MCP Tools

Each tool returns the full workflow instructions for its pipeline stage. The LLM reads these instructions and executes them step-by-step, respecting human-in-the-loop approval gates.

| Tool | Stage | Purpose |
|------|-------|---------|
| `sdlc_issue` | 1st | Draft and push a GitHub issue |
| `sdlc_implement` | 2nd | Implement a GitHub issue, continue an in-progress PR, or address PR review feedback |
| `sdlc_test` | 3rd | Analyze coverage and write comprehensive tests |
| `sdlc_commit` | 4th | Stage and commit changes with atomic commits |
| `sdlc_pr` | 5th | Review changes and create a draft pull request |
| `sdlc_review` | 6th | Review an open PR and write a consolidated local review document under `.sdlc/reviews/` (no GitHub posting) |
| `sdlc_understand_chat` | — | Query the codebase knowledge graph |
| `sdlc_guides_for` | — | Resolve which test or style guides apply to a list of file paths |
| `sdlc_roles` | — | List the available review roles as resource URIs |
| `sdlc_role_scope` | — | Reverse-lookup the changed files a role's findings are confined to (over the merged `guide-map.role`) |
| `sdlc_role` | — | Author a review role document (lens, blocking policy, focus globs) |

The `implement`, `test`, and `commit` tools are iterative — they can be invoked multiple times for a given issue to address PR feedback or refine implementation. `sdlc_implement` accepts either an issue number or a PR number and dispatches between three sibling skill prompts based on PR state: `implement` (fresh start, no PR yet), `implement-continue` (PR exists, no review feedback yet), and `implement-feedback` (PR has unresolved review threads or review-body comments).

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
  "guide-map": {
    "test":  { "**/*.py": ["python", "pytest-patterns"] },
    "style": { "**/*.py": ["python"], "**/*.md": ["markdown"] },
    "role":  { "src/**/*.py": ["architect"] }
  }
}
```

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

The `implement`, `test`, and `review` skills do not hardcode guide URIs. Each calls `sdlc_guides_for(paths, kind)` with the relevant file paths and reads every returned URI. To add a guide for a new language or convention, drop the markdown file in `.sdlc/guides/{test,style}/` and (if the file should be picked up for a path that the default map doesn't cover) add an entry to `guide-map` in `.sdlc/config.json`. Review roles follow the same configuration pattern — a markdown file under `.sdlc/guides/role/` plus a `guide-map.role` entry (the `sdlc_role` skill authors both) — but, unlike `test` and `style` guides, are selected by name rather than resolved from paths via `sdlc_guides_for`. When `sdlc_review` runs a role, it does the reverse: a reverse lookup over `guide-map.role` returns the globs mapped to that role, and the reviewer confines its findings to the changed files those globs match (any file may still be read for context).

### The `.sdlc/reviews/` convention

`sdlc_review` writes a standardized local review document — it posts nothing to GitHub. Each review round is written to `.sdlc/reviews/issue-#<N>/review-<iteration>.md`, where `<N>` is the first issue the PR closes when several are linked (resolved from `closingIssuesReferences`, falling back to parsing `Closes #N` in the PR body; the connection has no ordering guarantee, so `<N>` is one closing issue, not necessarily the only one) and `<iteration>` is 1-based, one greater than the highest existing `review-*.md` for that issue. The document is structured from the bundled template (`sdlc://review-template`): a header (roles used, reviewers per role, target HEAD sha, dedup approach, severity legend, branch commit map); findings grouped by severity tier (blocking first) — each with a stable ID, title, severity, a `Reference` (`file:line`, or a file-level / issue-level reference for a line-less finding), an Issue section with evidence, a Remediation checklist where the consolidator pre-selects the recommended option (`[x]`), lists alternatives (`[ ]`), and always offers an `Other: ___` slot, an optional Tests-to-add section, and a Touched commit; plus cross-cutting-decisions and fixup-mapping sections. The document is a local artifact: the user or agent reads it and applies each finding's pre-selected remediation and fixup-mapping entry as a manual work list. It is NOT auto-consumed by `sdlc_implement` — because nothing is posted to GitHub, a subsequent `sdlc_implement` call routes to `implement-continue` (not `implement-feedback`) unless the user separately surfaces the findings.

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

The typical development flow follows this sequence. Start by drafting a GitHub issue with acceptance criteria and description. Fetch the issue, create a feature branch, enter planning phase, and design a concrete implementation plan. Execute the plan by writing code and tests, guided by project context and test conventions. Optionally, analyze code changes, evaluate existing test coverage, and generate comprehensive test specifications targeting 100% coverage of public APIs. Analyze the working tree diff, group changes by logical kind, and create disciplined atomic commits with conventional-commit messages. Review the branch diff and create or update a draft pull request linked to the issue. Fetch the PR, review it through one or more role lenses (N reviewers per role), and consolidate the findings into a single local review document under `.sdlc/reviews/` — nothing is posted to GitHub. The document is a local artifact the user or agent reads to drive fixups manually; `sdlc_implement` does not ingest it.

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
