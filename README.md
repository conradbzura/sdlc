# SDLC Pipeline for LLM Agents

A structured, human-in-the-loop software development lifecycle pipeline for working with LLM coding assistants. This repo provides a canonical set of skills and guides that enforce discipline, quality, and collaboration throughout the development process.

You're in control. The agent proposes; you approve. No destructive actions happen without your explicit consent.

## Human-in-the-Loop Philosophy

Building software with LLM agents is powerful but risky without structure. Without guardrails, agents make arbitrary choices about commit structure, testing, and code organization. Autonomous workflows can push broken code or submit PRs without review. Code quality becomes unpredictable.

This pipeline attempts to solve that by keeping you in the loop at every decision point. Issues are drafted before they're filed, code is planned before it's written, tests are specified before implementation, commits are atomic with clear messages, and PRs are reviewed before pushing. The goal is to make the agent's work visible and deliberate. This approach balances agent efficiency (structured planning, bulk changes) with human judgment (approval gates, oversight, pivotal decisions).

## Quick Start (Claude Code)

Install the pipeline into your Claude Code skills directory:

```bash
cd /path/to/sdlc
make install target=~/.claude/skills
```

You now have six skills available: `issue`, `implement`, `test`, `commit`, `pr`, `review`.

### End-to-End Example

Here's what a complete workflow looks like from idea to merged code.

**1. File an Issue**

You discuss a problem or describe the work you want done:

```
I want to add retry logic to the API client. It should retry on 5xx errors, with exponential backoff up to 3 attempts.
```

Run the `issue` skill:

```
/issue [--subagent]
```

The agent drafts the issue, you review it in plan mode, and it gets filed. You get an issue number: #42.

If you have issue templates defined in your `.github` dir, the agent will follow the relevant template.

**2. Implement the Feature**

Start implementation with the issue number:

```
/implement 42 [--subagent]
```

The agent fetches issue #42, creates a branch (`42-add-api-client-retry-logic`), gathers codebase context, enters planning mode with a concrete implementation plan, and waits. You review the plan, approve it, and the code and tests are implemented according to what you approved.

**3. (Optional) Write Additional Tests**

If you want more comprehensive test coverage:

```
/test 42 [--subagent]
```

The agent analyzes what changed in the branch, reads existing tests to avoid duplication, proposes new test cases in plan mode, and waits for your approval. You review and approve, and new tests are added.

**4. Commit with Atomic, Well-Described Commits**

When you're satisfied with the code:

```
/commit [--subagent]
```

The agent analyzes the working tree diff, groups changes by logical kind (refactors, new features, tests, etc.), and presents a plan for how it will commit. You review the plan, approve it, and commits are created with conventional-commit messages.

**5. Create a Draft PR**

Review and open a pull request:

```
/pr 42 [--subagent]
```

The agent reviews the branch diff against main, drafts a PR description based on what was actually implemented, and creates a draft PR—never auto-marked ready for review. You review the description, approve it, and the PR is pushed.

If you have a PR template defined in your `.github` dir, the agent will follow that template.

**6. Review the PR (Optional)**

For additional compliance checks:

```
/review 42 [--subagent]
```

The agent analyzes the PR against project guides (style, testing, architecture), groups findings by severity, and posts inline review comments. You approve or request changes, and the review is posted.

**7. Iterate or Merge**

If review feedback requires changes, re-enter the implementation loop:

```
/implement 42 [--subagent]
```

Address the feedback, then re-run `/test`, `/commit`, `/pr` as needed. When you're satisfied, mark the PR ready for review and merge via GitHub.

## Installation

You can integrate the SDLC pipeline into your project in three ways. Choose based on your team's approach to standardization and customization.

### Git Submodule

Use submodules if you want a canonical, versioned pipeline. All projects share the same pipeline specification, updates are deliberate, and drift is prevented.

**Add the submodule:**

```bash
git submodule add https://github.com/you/sdlc sdlc
cd sdlc
make install target=~/.claude/skills
```

**To update the pipeline to a newer version:**

```bash
cd sdlc
git fetch origin
git checkout main
cd ..
git add sdlc
git commit -m "chore: Update SDLC pipeline to latest"
```

**On a fresh clone:**

```bash
git submodule update --init
cd sdlc && make install target=~/.claude/skills
```

Submodules enforce that you're on a specific version. Changes to the pipeline require an explicit update commit. Your project's history remains separate from the pipeline's history.

### Git Subtree (For customizable, project-specific pipelines)

Use subtrees if your project needs to customize the pipeline or diverge from the canonical version. The full pipeline history merges into your project, allowing local modifications and optional upstream syncs.

**Add the subtree:**

```bash
git subtree add --prefix sdlc https://github.com/you/sdlc main
cd sdlc && make install target=~/.claude/skills
```

**To pull upstream updates (optional):**

```bash
git subtree pull --prefix sdlc https://github.com/you/sdlc main
```

**To push customizations back upstream (optional):**

```bash
git subtree push --prefix sdlc https://github.com/you/sdlc feature-branch
```

Subtrees blur the line between your project and the pipeline. You can fork the pipeline and make it project-specific. The full history is merged, so `git blame` and `git log` show everything together.

### Standalone Installation (for single tools)

If you're using Claude Code standalone without a larger project repo, simply clone and install directly:

```bash
git clone https://github.com/you/sdlc ~/sdlc
cd ~/sdlc
make install target=~/.claude/skills
```

**To uninstall:**

```bash
cd ~/sdlc
make uninstall target=~/.claude/skills
```

## Project Structure

```
sdlc/
├── README.md                   # This file
├── AGENTS.md                   # Technical reference for agent implementations
├── makefile                    # Install/uninstall targets (delegates to scripts/)
├── .gitignore
├── scripts/
│   ├── install.sh              # Installation script (creates symlinks)
│   └── uninstall.sh            # Uninstallation script (removes symlinks)
└── agents/
    ├── skills/                 # Canonical skill implementations
    │   ├── issue/              # Issue filing skill
    │   ├── implement/          # Feature implementation skill
    │   ├── test/               # Test coverage planning skill
    │   ├── commit/             # Atomic commit skill
    │   ├── pr/                 # Pull request creation skill
    │   ├── review/             # Code review skill
    │   └── understand-chat/    # Knowledge graph Q&A skill
    ├── test-guides/            # Testing conventions (generated as symlinks in skills)
    │   └── python.md
    └── style-guides/           # Style conventions (generated as symlinks in skills)
        └── markdown.md
```

### Installation Behavior

The `make install` and `make uninstall` commands delegate to shell scripts in `scripts/`:

- **`scripts/install.sh`** creates symlinks for:
  - Skill directories at the target location
  - Guide directories (test-guides, style-guides) inside each skill for easy reference

- **`scripts/uninstall.sh`** removes:
  - Skill symlinks from the target
  - Guide symlinks from the source skill directories
  - Guide symlinks from the target

Guide symlinks are intentionally **not committed to git**; they're generated dynamically during installation. See `.gitignore` for the exclusion patterns.

## For Other LLM Assistants

See [AGENTS.md](./AGENTS.md) for tool-specific setup instructions beyond Claude Code.

## What You Get

The pipeline enforces disciplined commits—atomic, well-structured, with conventional-commit messages that make your history readable. It emphasizes test-first planning, generating comprehensive test specs before implementation. Code quality is enforced through guide-based compliance review with inline comments. Every action is presented for review before execution, so you never have unwanted surprises. When you get PR feedback, you loop back to implementation, refine, and iterate. The entire system is tool-agnostic—it works with Claude Code and can be adapted for other LLM assistants. For large codebases, you can generate lightweight knowledge graphs to give the agent architectural context without shipping megabytes of source code as context.

## Documentation

- **[AGENTS.md](./AGENTS.md)** — Technical reference for agents: implementation notes, skill discovery, tool-specific execution
- **[agents/skills/issue/SKILL.md](./agents/skills/issue/SKILL.md)** — Issue skill
- **[agents/skills/implement/SKILL.md](./agents/skills/implement/SKILL.md)** — Implementation skill
- **[agents/skills/test/SKILL.md](./agents/skills/test/SKILL.md)** — Testing skill
- **[agents/skills/commit/SKILL.md](./agents/skills/commit/SKILL.md)** — Commit skill
- **[agents/skills/pr/SKILL.md](./agents/skills/pr/SKILL.md)** — Pull request skill
- **[agents/skills/review/SKILL.md](./agents/skills/review/SKILL.md)** — Code review skill
- **[agents/test-guides/python.md](./agents/test-guides/python.md)** — Python testing conventions
- **[agents/style-guides/markdown.md](./agents/style-guides/markdown.md)** — Markdown style conventions

## Pipeline at a Glance

```
issue → implement → [test] → commit → pr → [review [→ implement → ...]]
```

The optional steps are in brackets. The `implement`, `test`, and `commit` steps are iterative—you can cycle through them as many times as needed before the PR goes out.
