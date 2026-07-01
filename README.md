# SDLC Pipeline for LLM Agents

A structured, human-in-the-loop software development lifecycle pipeline for working with LLM coding assistants. This repo provides a canonical set of skills and guides that enforce discipline, quality, and collaboration throughout the development process, served as an MCP (Model Context Protocol) server.

You're in control. The agent proposes; you approve. No destructive actions happen without your explicit consent.

## Human-in-the-Loop Philosophy

Building software with LLM agents is powerful but risky without structure. Without guardrails, agents make arbitrary choices about commit structure, testing, and code organization. Autonomous workflows can push broken code or submit PRs without review. Code quality becomes unpredictable.

This pipeline attempts to solve that by keeping you in the loop at every decision point. Issues are drafted before they're filed, code is planned before it's written, tests are specified before implementation, commits are atomic with clear messages, and PRs are reviewed before pushing. The goal is to make the agent's work visible and deliberate. This approach balances agent efficiency (structured planning, bulk changes) with human judgment (approval gates, oversight, pivotal decisions).

## Quick Start

Install and run the MCP server. Any MCP-compatible client (Claude Code, VS Code, JetBrains, etc.) can connect.

### Claude Code

Add to your project's `.mcp.json`:

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

Or install locally and point to the entry point:

```json
{
  "mcpServers": {
    "sdlc": {
      "command": "sdlc-mcp"
    }
  }
}
```

### VS Code / JetBrains

Configure your IDE's MCP settings to launch the `sdlc-mcp` command via stdio transport. Refer to your IDE's MCP documentation for the exact configuration format.

### Development Install

```bash
git clone https://github.com/conradbzura/sdlc
cd sdlc
pip install -e .
```

You now have eleven tools available: the pipeline stages `sdlc_issue`, `sdlc_implement`, `sdlc_test`, `sdlc_commit`, `sdlc_pr`, and `sdlc_review`, plus the supporting tools `sdlc_understand_chat`, `sdlc_guides_for`, `sdlc_roles`, `sdlc_role_scope`, and `sdlc_role`.

### End-to-End Example

Here's what a complete workflow looks like from idea to merged code.

**1. File an Issue**

You discuss a problem or describe the work you want done:

```
I want to add retry logic to the API client. It should retry on 5xx errors, with exponential backoff up to 3 attempts.
```

The agent calls the `sdlc_issue` tool, drafts the issue, you review it, and it gets filed. You get an issue number: #42.

If you have issue templates defined in your `.github` dir, the agent will follow the relevant template.

**2. Implement the Feature**

The agent calls `sdlc_implement` with issue number 42. It fetches the issue, creates a branch (`42-add-api-client-retry-logic`), gathers codebase context, enters planning mode with a concrete implementation plan, and waits. You review the plan, approve it, and the code and tests are implemented according to what you approved.

**3. (Optional) Write Additional Tests**

If you want more comprehensive test coverage, the agent calls `sdlc_test` with issue number 42. It analyzes what changed in the branch, reads existing tests to avoid duplication, proposes new test cases, and waits for your approval. You review and approve, and new tests are added.

**4. Commit with Atomic, Well-Described Commits**

When you're satisfied with the code, the agent calls `sdlc_commit`. It analyzes the working tree diff, groups changes by logical kind (refactors, new features, tests, etc.), and presents a plan for how it will commit. You review the plan, approve it, and commits are created with conventional-commit messages.

**5. Create a Draft PR**

The agent calls `sdlc_pr` with issue number 42. It reviews the branch diff against main, drafts a PR description based on what was actually implemented, and creates a draft PR — never auto-marked ready for review. You review the description, approve it, and the PR is pushed.

If you have a PR template defined in your `.github` dir, the agent will follow that template.

**6. Review the PR (Optional)**

The agent calls `sdlc_review` with either the PR number or a set of local file paths/globs (exactly one). It runs one or more reviewer roles (N reviewers per role) over the target — the PR diff in PR mode, or the named files' whole contents in paths mode — each confined to the files its role is mapped to, then consolidates their findings — deduped, merged across roles, highest severity wins — into a single local document. In PR mode that document lives at `.sdlc/reviews/issue-#<N>/review-<iteration>.md`; in paths mode it lives at `.sdlc/reviews/<slug>/review-<iteration>.md`, where `<slug>` is derived deterministically from the paths so repeated reviews of the same target accumulate together. The document groups findings by severity (blocking first), gives each a stable ID and a `Reference`, and pre-selects a recommended remediation per finding with alternatives and an `Other` slot (PR-mode documents also map each finding to its touched commit for fixups; paths-mode documents omit commit attribution). The document is written automatically as the final step — the consolidated findings are presented for visibility, then written without an approval gate; each run lands at the next unused `review-<iteration>.md` (resolved deterministically by the tool), so an earlier round is never overwritten. Nothing is posted to GitHub. In PR mode this document is exactly what `sdlc_implement` consumes to drive fixups — see the next step.

**7. Iterate or Merge**

If review feedback requires changes, re-enter the implementation loop with `sdlc_implement`. By default it parses the latest review document for the closing issue, renders its findings, and walks you through each one's pre-selected remediation behind a per-finding approval gate; `--review <iteration>` selects an earlier round, and `--review <pr-url>` first converts that PR's GitHub review comments into a fresh local review document. Address the feedback, then re-run test, commit, and pr tools as needed.

To confirm a round was actually addressed, run `sdlc_review --verify <review #>` against the same target. It re-reads that `review-<#>.md`, fans the same per-role reviewers out as verifiers, and judges each finding **Resolved** or **Unresolved** against your current files — writing a `verify-<#>.md` report with an unresolved count rather than a new review. If any findings remain unresolved, it points you back to `sdlc_implement <target> --review <#>`; when zero remain, the round is verified complete. When you're satisfied, mark the PR ready for review and merge via GitHub.

## Project Structure

```
sdlc/
├── README.md                       # This file
├── AGENTS.md                       # Symlink → src/sdlc/AGENTS.md
├── pyproject.toml                  # Python package config (MCP SDK dependency)
└── src/
    └── sdlc/                       # MCP server package
        ├── __init__.py             # Package entry point
        ├── __main__.py             # python -m sdlc support
        ├── server.py               # FastMCP server, tool & resource registrations
        ├── pr_state.py             # gh wrappers and PR-state dispatch for sdlc_implement
        ├── AGENTS.md               # Technical reference for agent implementations
        ├── skills/                 # Canonical skill definitions (read by server)
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
        ├── role-template.md        # Bundled role-document template
        ├── review-template.md      # Bundled consolidated-review-document template
        ├── test-guides/            # Testing conventions (served as MCP resources)
        │   └── python.md
        ├── style-guides/           # Style conventions (served as MCP resources)
        │   └── markdown.md
        └── role-guides/            # Review roles (served as MCP resources)
            ├── general-purpose.md
            └── aie.md              # AI-engineering lens; scope set per-project in guide-map.role
```

### MCP Tools

| Tool | Purpose |
|------|---------|
| `sdlc_issue` | Draft and push a GitHub issue |
| `sdlc_implement` | Implement a GitHub issue, continue an in-progress PR, or address a local review document's findings (`--review` selects an iteration or a PR URL to convert) |
| `sdlc_test` | Analyze coverage and write comprehensive tests |
| `sdlc_commit` | Stage and commit changes with atomic commits |
| `sdlc_pr` | Review changes and create a draft pull request |
| `sdlc_review` | Review an open PR (diff) or a set of local file paths/globs, writing a consolidated local review document under `.sdlc/reviews/`; `--verify <review #>` instead verifies an existing review, judging each finding resolved/unresolved against the current files |
| `sdlc_understand_chat` | Query the codebase knowledge graph |
| `sdlc_roles` | List the available review roles |
| `sdlc_role_scope` | Reverse-lookup the changed files a role's findings are confined to |
| `sdlc_role` | Author a review role document |

### MCP Resources

| URI | Content |
|-----|---------|
| `sdlc://guides/test/python` | Python testing conventions |
| `sdlc://guides/style/markdown` | Markdown style conventions |
| `sdlc://guides/role/general-purpose` | Default review role |
| `sdlc://guides/role/aie` | AI-engineering review role (agent-facing prompt and skill content) |
| `sdlc://role-template` | Role-document template |
| `sdlc://review-template` | Consolidated-review-document template |
| `sdlc://agents-md` | Project-level agent instructions |
| `sdlc://knowledge-graph` | Codebase knowledge graph (if generated) |

## What You Get

The pipeline enforces disciplined commits — atomic, well-structured, with conventional-commit messages that make your history readable. It emphasizes test-first planning, generating comprehensive test specs before implementation. Code quality is enforced through guide-based, role-driven review that produces a consolidated local review document — an actionable, option-per-finding remediation plan you keep under `.sdlc/reviews/`, which `sdlc_implement` then consumes to walk you through the fixups one finding at a time. Every action is presented for review before execution, so you never have unwanted surprises. When you get review feedback, you loop back to implementation, refine, and iterate. The system is tool-agnostic — any MCP-compatible client can connect. For large codebases, you can generate lightweight knowledge graphs to give the agent architectural context without shipping megabytes of source code as context.

## Documentation

- **[AGENTS.md](./AGENTS.md)** — Technical reference for agents: implementation notes, skill discovery, tool-specific execution
- **[src/sdlc/skills/issue.md](./src/sdlc/skills/issue.md)** — Issue skill
- **[src/sdlc/skills/implement.md](./src/sdlc/skills/implement.md)** — Implementation skill
- **[src/sdlc/skills/test.md](./src/sdlc/skills/test.md)** — Testing skill
- **[src/sdlc/skills/commit.md](./src/sdlc/skills/commit.md)** — Commit skill
- **[src/sdlc/skills/pr.md](./src/sdlc/skills/pr.md)** — Pull request skill
- **[src/sdlc/skills/review.md](./src/sdlc/skills/review.md)** — Code review skill
- **[src/sdlc/skills/role.md](./src/sdlc/skills/role.md)** — Review-role authoring skill
- **[src/sdlc/test-guides/python.md](./src/sdlc/test-guides/python.md)** — Python testing conventions
- **[src/sdlc/style-guides/markdown.md](./src/sdlc/style-guides/markdown.md)** — Markdown style conventions

## Pipeline at a Glance

```
issue → implement → [test] → commit → pr → [review [→ implement → ...]]
```

The optional steps are in brackets. The `implement`, `test`, and `commit` steps are iterative — you can cycle through them as many times as needed before the PR goes out.
