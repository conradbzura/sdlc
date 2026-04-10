# SDLC Pipeline for LLM Agents

This document describes the skill definitions and guides that form a structured software development lifecycle (SDLC) pipeline for LLM agents. It is the canonical source for all pipeline behaviour.

## Architecture

The SDLC pipeline is an MCP (Model Context Protocol) server. Skills are exposed as MCP tools and guides as MCP resources. Any MCP-compatible client (Claude Code, VS Code, JetBrains, etc.) can connect via stdio transport.

### MCP Tools

Each tool returns the full workflow instructions for its pipeline stage. The LLM reads these instructions and executes them step-by-step, respecting human-in-the-loop approval gates.

| Tool | Stage | Purpose |
|------|-------|---------|
| `sdlc_issue` | 1st | Draft and push a GitHub issue |
| `sdlc_implement` | 2nd | Implement a GitHub issue with planning and code changes |
| `sdlc_test` | 3rd | Analyze coverage and write comprehensive tests |
| `sdlc_commit` | 4th | Stage and commit changes with atomic commits |
| `sdlc_pr` | 5th | Review changes and create a draft pull request |
| `sdlc_review` | 6th | Review an open pull request for compliance and quality |
| `sdlc_understand_chat` | — | Query the codebase knowledge graph |

The `implement`, `test`, and `commit` tools are iterative — they can be invoked multiple times for a given issue to address PR feedback or refine implementation.

### MCP Resources

| URI | Content |
|-----|---------|
| `sdlc://guides/test/python` | Python testing conventions (pytest, pytest-mock, Hypothesis) |
| `sdlc://guides/style/markdown` | Markdown authoring style guide |
| `sdlc://agents-md` | This file (project-level agent instructions) |
| `sdlc://knowledge-graph` | Codebase knowledge graph (if generated) |

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
    ├── AGENTS.md                    ← you are here (canonical)
    ├── skills/                      ← Canonical skill definitions (read by server)
    │   ├── issue.md
    │   ├── implement.md
    │   ├── test.md
    │   ├── commit.md
    │   ├── pr.md
    │   ├── review.md
    │   └── understand-chat.md
    ├── test-guides/
    │   └── python.md
    └── style-guides/
        └── markdown.md
```

## Pipeline Overview

The typical development flow follows this sequence. Start by drafting a GitHub issue with acceptance criteria and description. Fetch the issue, create a feature branch, enter planning phase, and design a concrete implementation plan. Execute the plan by writing code and tests, guided by project context and test conventions. Optionally, analyze code changes, evaluate existing test coverage, and generate comprehensive test specifications targeting 100% coverage of public APIs. Analyze the working tree diff, group changes by logical kind, and create disciplined atomic commits with conventional-commit messages. Review the branch diff and create or update a draft pull request linked to the issue. Fetch the PR, analyze it against project guides, and post inline review comments with findings.

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
