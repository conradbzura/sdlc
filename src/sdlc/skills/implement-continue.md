---
name: implement-continue
description: >
  Continue an in-progress GitHub PR that has no review feedback yet.
  Invoked by the `sdlc_implement` MCP endpoint when a PR is in scope and
  has zero unresolved review threads and zero non-empty review-body
  comments. Checks out the PR branch, identifies remaining work against
  the linked issue, and enters planning phase to design the next slice
  of execution.
subagent:
  support: optional
  type: general-purpose
  artifacts:
    - branch_name
    - pr_url
    - pr_number
---

The key words MUST, MUST NOT, SHALL, SHALL NOT, SHOULD, SHOULD NOT, REQUIRED, RECOMMENDED, MAY, and OPTIONAL in this document are to be interpreted as described in RFC 2119.

# Implement Continue Skill

Pick up an in-progress PR that has no review feedback yet. Check out the PR branch, identify what remains to be done against the linked issue, and enter planning phase to design the next slice of execution.

## Pipeline Context

This skill is part of the development workflow pipeline: `issue` → `implement` → `test` → `commit` → `pr` → `review`. The `sdlc_implement` MCP endpoint dispatches between three sibling prompts based on PR state — this skill is returned when a PR is in scope but has zero unresolved review threads and zero non-empty review-body comments. Fresh-start work is routed to the `implement` skill; PR review feedback is routed to the `implement-feedback` skill.

## Implementation Notes

**Planning phase** is a structured approval workflow. When instructions reference "enter planning phase," execute it according to your coding assistant tool:

**Claude Code:**
- MUST invoke the `EnterPlanMode` tool to present the plan in the planning interface.
- MUST wait for the tool to collect user approval before returning control to you.
- After approval, MUST implement exactly as specified in the approved plan.

**Other LLM assistants:**
- MUST output the plan as clearly structured text with explicit sections (Overview, Files to Modify, Implementation Steps, Testing Strategy, Verification Command).
- MUST append an explicit approval request: "Does this plan look good? Please approve to proceed, request changes, or reject."
- MUST wait for the user's explicit approval before implementing.
- MUST NOT proceed without clear user confirmation.

## Invariants

- MUST check out the PR branch before any other action; never start work from `main` or an unrelated branch.
- MUST identify the linked issue (parse the PR body for `Closes #N`) and read its body to scope the remaining work.
- MUST enter planning phase and receive user approval before writing any code.
- MUST NOT create or modify files outside the scope of the approved plan.
- MUST NOT proceed to the next pipeline step autonomously -- always prompt the user.
- MUST use the `understand-chat` skill to query the knowledge graph for context gathering when `.understand-anything/knowledge-graph.json` exists.

## Arguments

The MCP endpoint supplies the PR number, branch name, and PR URL appended below this skill prompt. The agent MUST consume those values rather than re-deriving them.

## Subagent Execution (Optional)

This skill MAY be executed in an isolated subagent to preserve parent context. When invoked with a `--subagent` flag, execute according to your tool:

**Claude Code:**
- MUST spawn a general-purpose subagent using the Agent tool with this brief:
  > You are executing the **`implement-continue`** skill from the SDLC pipeline (`issue` → `implement` → `test` → `commit` → `pr` → `review`).
  > 1. Read the project instructions in `AGENTS.md`
  > 2. Read and execute the complete workflow defined in this skill's markdown
  > 3. Follow every step faithfully, especially the Invariants section
  > 4. Return a structured summary: accomplishments, key artifacts (branch name, PR URL, remaining work), and the next pipeline step prompt from the skill

- When the subagent returns, reproduce its full output to the user exactly as written — do not summarize, condense, paraphrase, or omit sections. Do not repeat work or add your own commentary.

**Other LLM assistants:**
- Subagent execution may not be supported in your tool. Execute the skill inline following the normal workflow.

## Workflow

### Checklist

1. Resolve target repository
2. Check out the PR branch
3. Identify the linked issue
4. Diff the issue against the current branch state
5. Gather context
6. Enter planning phase
7. Execute after approval
8. Prompt the user to move onto the test or commit step

### 1. Resolve target repository

```bash
gh repo view --json isFork,parent
```

If `isFork` is `true`, extract `parent.owner.login` and `parent.name` to form the upstream repo identifier (`<owner>/<name>`). This upstream identifier becomes the **target repo** for all subsequent `gh` commands that reference issues or pull requests. If the repo is not a fork, the target repo is the current repo and no `--repo` flag is needed.

All `gh` commands in subsequent steps that reference issues or PRs MUST include `--repo <target>` when the target repo differs from the current repo.

### 2. Check out the PR branch

The MCP endpoint supplied the branch name. Fetch and check it out:

```bash
git fetch origin <branch> && git checkout <branch>
```

If the working tree has uncommitted changes that would conflict with the checkout, stop and ask the user how to proceed (stash, discard, or commit first).

### 3. Identify the linked issue

Read the PR body and extract the issue referenced by `Closes #N` (or `Fixes #N`, `Resolves #N`):

```bash
gh pr view <pr-number> --repo <target> --json body --jq '.body'
```

Then fetch the issue body so the remaining work can be scoped against it:

```bash
gh issue view <issue-number> --repo <target>
```

If the PR body has no `Closes` reference, ask the user which issue the PR is implementing.

### 4. Diff the issue against the current branch state

Compare the issue's expected outcome against what is already implemented on the branch. Read the diff between the branch and `main` to see what has been done so far:

```bash
git log --oneline main..HEAD
git diff main...HEAD --stat
```

The remaining work is whatever the issue's expected outcome calls for that is NOT yet present on the branch.

### 5. Gather context

Before entering planning phase, MUST read enough of the codebase to plan confidently:

- MUST check whether `.understand-anything/knowledge-graph.json` exists. If it does, MUST use the `understand-chat` skill with a query synthesized from the issue title and the remaining work to gather architectural context. If the graph does not exist, skip this bullet and continue.
- MUST read source files referenced in the issue's description and any new files added on the branch.
- MUST read existing tests for the affected modules.
- MUST resolve applicable test guides by calling `sdlc_guides_for` with the candidate or referenced source-file paths and `kind="test"`, then read every returned URI to internalize the relevant testing conventions.
- MUST read project-level instructions (`AGENTS.md`) for build tooling, documentation style, and architecture context.

### 6. Enter planning phase

The execution plan must be presented to the user for approval. It:

- MUST map the *remaining* work (not the work already done on the branch) to concrete code changes: exact files, functions, classes, and the nature of each modification.
- SHOULD prefer test-first ordering when applicable.
- MUST follow the testing conventions in the test guides resolved via `sdlc_guides_for` (kind=`test`).
- MUST include a verification section with the exact command(s) to run the test suite.

### 7. Execute after approval

Once the user approves the plan, implement each step sequentially.

### 8. Prompt the user to move onto the test or commit step

The user MUST be prompted with the next pipeline step: "Ready to generate tests? Run the `test` skill with the issue number to analyze coverage and write tests. Or ready to commit? Run the `commit` skill to stage and commit the changes." DO NOT proceed on your own.

## Edge Cases

- **Branch checkout fails (uncommitted changes):** Stop and ask the user how to handle the conflict.
- **Branch checkout fails (missing remote ref):** Stop and report the situation; the supplied branch name may be stale.
- **PR body has no `Closes` reference:** Ask the user which issue the PR addresses; do not guess.
- **Linked issue is closed:** Surface the discrepancy and ask the user whether the work should still proceed.
- **Branch is fully caught up to the issue's expected outcome:** Inform the user, recommend running `sdlc_test` or `sdlc_pr` next, and stop.
