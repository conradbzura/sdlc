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

You now have seven tools available: `sdlc_issue`, `sdlc_implement`, `sdlc_test`, `sdlc_commit`, `sdlc_pr`, `sdlc_review`, `sdlc_understand_chat`.

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

The agent calls `sdlc_review` with the PR number. It analyzes the PR against project guides (style, testing, architecture), groups findings by severity, and posts inline review comments. You approve or request changes, and the review is posted.

**7. Iterate or Merge**

If review feedback requires changes, re-enter the implementation loop with `sdlc_implement`. Address the feedback, then re-run test, commit, and pr tools as needed. When you're satisfied, mark the PR ready for review and merge via GitHub.

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
        │   └── understand-chat.md
        ├── test-guides/            # Testing conventions (served as MCP resources)
        │   └── python.md
        └── style-guides/           # Style conventions (served as MCP resources)
            └── markdown.md
```

### MCP Tools

| Tool | Purpose |
|------|---------|
| `sdlc_issue` | Draft and push a GitHub issue |
| `sdlc_implement` | Implement a GitHub issue, continue an in-progress PR, or address PR review feedback |
| `sdlc_test` | Analyze coverage and write comprehensive tests |
| `sdlc_commit` | Stage and commit changes with atomic commits |
| `sdlc_pr` | Review changes and create a draft pull request |
| `sdlc_review` | Review an open pull request for compliance and quality |
| `sdlc_understand_chat` | Query the codebase knowledge graph |

### MCP Resources

| URI | Content |
|-----|---------|
| `sdlc://guides/test/python` | Python testing conventions |
| `sdlc://guides/style/markdown` | Markdown style conventions |
| `sdlc://agents-md` | Project-level agent instructions |
| `sdlc://knowledge-graph` | Codebase knowledge graph (if generated) |

## What You Get

The pipeline enforces disciplined commits — atomic, well-structured, with conventional-commit messages that make your history readable. It emphasizes test-first planning, generating comprehensive test specs before implementation. Code quality is enforced through guide-based compliance review with inline comments. Every action is presented for review before execution, so you never have unwanted surprises. When you get PR feedback, you loop back to implementation, refine, and iterate. The system is tool-agnostic — any MCP-compatible client can connect. For large codebases, you can generate lightweight knowledge graphs to give the agent architectural context without shipping megabytes of source code as context.

## Documentation

- **[AGENTS.md](./AGENTS.md)** — Technical reference for agents: implementation notes, skill discovery, tool-specific execution
- **[src/sdlc/skills/issue.md](./src/sdlc/skills/issue.md)** — Issue skill
- **[src/sdlc/skills/implement.md](./src/sdlc/skills/implement.md)** — Implementation skill
- **[src/sdlc/skills/test.md](./src/sdlc/skills/test.md)** — Testing skill
- **[src/sdlc/skills/commit.md](./src/sdlc/skills/commit.md)** — Commit skill
- **[src/sdlc/skills/pr.md](./src/sdlc/skills/pr.md)** — Pull request skill
- **[src/sdlc/skills/review.md](./src/sdlc/skills/review.md)** — Code review skill
- **[src/sdlc/test-guides/python.md](./src/sdlc/test-guides/python.md)** — Python testing conventions
- **[src/sdlc/style-guides/markdown.md](./src/sdlc/style-guides/markdown.md)** — Markdown style conventions

## Pipeline at a Glance

```
issue → implement → [test] → commit → pr → [review [→ implement → ...]]
```

The optional steps are in brackets. The `implement`, `test`, and `commit` steps are iterative — you can cycle through them as many times as needed before the PR goes out.
