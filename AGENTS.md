# SDLC Pipeline for LLM Agents

This document describes the skill definitions and guides that form a structured software development lifecycle (SDLC) pipeline for LLM agents. It is the canonical source for all pipeline behaviour.

## Skill Naming Convention

Skills are referred to by their backticked names (`issue`, `implement`, `test`, `commit`, `pr`, `review`) throughout documentation. These are tool-agnostic identifiers that work across Claude Code (CLI, desktop, web, IDE extensions) and other LLM assistants. In Claude Code, skills are invoked with a `/` prefix (e.g., `/test`, `/implement`). In other tools, invocation syntax may differ; refer to the tool's documentation.

The backtick notation makes skills portable and tool-independent.

### Writing User Prompts

When transitioning users between skills, use the command invocation semantics native to your platform. If your environment supports direct command invocation (e.g., `/commit`, `@commit`, or equivalent), use it. Say "Ready for the next stage? Run `/commit` to continue." or "Run the test skill with issue #103" or "Address the findings with `@implement` and re-run the test skill." Let the native semantics of your platform determine how skills are invoked, ensuring skill transitions are explicit and actionable within your own execution context.

### Pipeline References

The SDLC pipeline is referenced as: `issue` → `implement` → `test` → `commit` → `pr` → `review`

## Skill Descriptions

| Skill | Stage | Purpose |
|-------|-------|---------|
| `issue` | 1st | Draft and push a GitHub issue |
| `implement` | 2nd | Implement a GitHub issue with planning and code changes |
| `test` | 3rd | Analyze coverage and write comprehensive tests |
| `commit` | 4th | Stage and commit changes with atomic commits |
| `pr` | 5th | Review changes and create a draft pull request |
| `review` | 6th | Review an open pull request for compliance and quality |

The `implement`, `test`, and `commit` skills are iterative—they can be invoked multiple times for a given issue to address PR feedback or refine implementation.

## Installation & Setup

Claude Code users should use the `install` make target to symlink skills into their Claude Code `.claude/skills/` directory:

```bash
cd /path/to/sdlc
make install target=~/.claude/skills
```

Verify installation with:

```bash
ls -lh ~/.claude/skills/
```

To uninstall, use the corresponding `uninstall` target:

```bash
make uninstall target=~/.claude/skills
```

For other LLM assistants, the skill definitions in `agents/skills/` are portable and tool-agnostic. Start by discovering your tool's skill discovery mechanism—typically an environment variable, config file, or dedicated directory. Then use the `install` make target to symlink skills: `make install target=<your-tool-skills-dir>`. Ensure the tool has access to project context files: `AGENTS.md`, `.understand-anything/knowledge-graph.json` (if present), and any referenced guides.

Each skill includes "Implementation Notes" sections with tool-specific execution instructions. Claude Code uses `EnterPlanMode` and the `Agent` tool for structured workflows. Other tools use a generic fallback (output the plan as structured text, wait for explicit approval).

### Optional: Token-Efficient Context with Understand-Anything

For large codebases, the `implement`, `test`, and `commit` skills can reference a codebase knowledge graph to gather architectural context without sending entire source files as context. [Understand-Anything](https://github.com/Lum1104/Understand-Anything) analyzes project structure, extracts file relationships, and generates a lightweight JSON knowledge graph that agents can query instead of reading raw source.

Once generated, the skills will automatically use the knowledge graph to answer architectural questions (e.g., "What components import this file?", "What functions call this one?") during planning and review phases. This dramatically reduces token usage on large codebases while improving recommendation quality.

## Directory Layout

```
agents/
├── AGENTS.md                    ← you are here
├── skills/                      ← LLM-agnostic skill definitions (portable)
│   ├── issue/
│   │   └── SKILL.md
│   ├── implement/
│   │   └── SKILL.md
│   ├── test/
│   │   └── SKILL.md
│   ├── commit/
│   │   └── SKILL.md
│   ├── pr/
│   │   └── SKILL.md
│   ├── review/
│   │   └── SKILL.md
│   └── understand-chat/
│       └── SKILL.md
├── guides/
│   ├── testguide-python.md
│   └── styleguide-markdown.md
```

## Pipeline Overview

The typical development flow follows this sequence. Start by drafting a GitHub issue with acceptance criteria and description. Fetch the issue, create a feature branch, enter planning phase, and design a concrete implementation plan. Execute the plan by writing code and tests, guided by project context and test conventions. Optionally, analyze code changes, evaluate existing test coverage, and generate comprehensive test specifications targeting 100% coverage of public APIs. Analyze the working tree diff, group changes by logical kind, and create disciplined atomic commits with conventional-commit messages. Review the branch diff and create or update a draft pull request linked to the issue. Fetch the PR, analyze it against project guides, and post inline review comments with findings.

The `implement`, `test`, and `commit` steps are iterative—you can run them multiple times to refine the implementation based on feedback or additional context. After each change, re-run `pr <number>` to update the PR description before final review.

## Tool-Specific Execution

Each skill includes an "Implementation Notes" section that provides tool-specific execution instructions.

**Claude Code:** Skills include explicit instructions for using the `EnterPlanMode` tool, subagent invocation via the `Agent` tool, and other Claude Code-specific features.

**Other LLM assistants:** A generic fallback is provided (output the plan as structured text, wait for explicit user approval).

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

## Skill Discovery & Registration

Each coding assistant tool has its own convention for discovering skills. Identify your tool's skill discovery location—typically an environment variable, config file, or dedicated directory (e.g., `.claude/skills/` for Claude Code). Run the install target to symlink all skills at once: `make install target=<your-tool-skills-dir>`. Verify context access to ensure your tool can read `AGENTS.md`, `.understand-anything/knowledge-graph.json` (if present), and test/style guides.

For Claude Code specifically:

```bash
cd /path/to/sdlc
make install target=~/.claude/skills
```

To uninstall:

```bash
make uninstall target=~/.claude/skills
```
