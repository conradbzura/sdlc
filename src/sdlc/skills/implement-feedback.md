---
name: implement-feedback
description: >
  Address unresolved PR review feedback for an open pull request.
  Invoked by the `sdlc_implement` MCP endpoint when an open PR has
  unresolved review threads or non-empty review-body comments. Walks
  through findings sequentially with per-finding evaluation, approval,
  and fixup-commit guidance.
subagent:
  support: optional
  type: general-purpose
  artifacts:
    - branch_name
    - pr_url
    - pr_number
    - findings_addressed
---

The key words MUST, MUST NOT, SHALL, SHALL NOT, SHOULD, SHOULD NOT, REQUIRED, RECOMMENDED, MAY, and OPTIONAL in this document are to be interpreted as described in RFC 2119.

# Implement Feedback Skill

Walk through unresolved PR review feedback systematically, one finding at a time, with per-finding evaluation and approval gates. Generate ready-to-execute fixup-commit commands after each remediation; do not auto-commit.

## Pipeline Context

This skill is part of the development workflow pipeline: `issue` → `implement` → `test` → `commit` → `pr` → `review`. The `sdlc_implement` MCP endpoint dispatches between three sibling prompts based on PR state — this skill is returned when an open PR has unresolved review threads or non-empty review-body comments. Fresh-start work is routed to the `implement` skill; mid-implementation continuation is routed to the `implement-continue` skill.

## Implementation Notes

This skill does **not** use the structured planning interface (`EnterPlanMode` for Claude Code, structured-plan-text for other LLM assistants). Instead, each finding gets its own inline mini-plan and approval gate during the sequential walkthrough. Reserve the planning interface for end-to-end implementation tasks; per-finding remediation works better as a conversational loop.

## Invariants

- MUST verify the server-supplied finding enumeration by re-querying both review threads AND review-body comments before walking through findings.
- MUST order findings by the canonical severity sequence (correctness → code quality → integration tests → unit tests → style → docs).
- MUST track findings as a todo list, one task per finding, kept visible to the user.
- MUST present findings sequentially. For each finding the agent MUST restate the finding with `file:line` citation, evaluate correctness/relevance, propose one or more solutions with their implications, recommend one option, and wait for explicit user approval before editing.
- MUST NOT auto-commit. After each approved remediation, MUST emit a copy-paste-able `git commit --fixup=<sha>` block mapping each touched file back to the commit on the branch that owns that surface. The agent MUST NOT execute these commands.
- MUST prompt the user to run `sdlc_commit` when they are ready to commit the accumulated remediations.
- MUST NOT proceed to the next pipeline step autonomously.
- MUST use the `understand-chat` skill to query the knowledge graph for context gathering when `.understand-anything/knowledge-graph.json` exists.

## Arguments

The MCP endpoint supplies the PR number, branch name, PR URL, and an enumerated list of findings (review threads and review-body comments) appended below this skill prompt. The agent MUST treat that enumeration as a starting point and re-query (step 3) to confirm completeness before walking through findings.

## Subagent Execution (Optional)

This skill MAY be executed in an isolated subagent to preserve parent context. When invoked with a `--subagent` flag, execute according to your tool:

**Claude Code:**
- MUST spawn a general-purpose subagent using the Agent tool with this brief:
  > You are executing the **`implement-feedback`** skill from the SDLC pipeline (`issue` → `implement` → `test` → `commit` → `pr` → `review`).
  > 1. Read the project instructions in `AGENTS.md`
  > 2. Read and execute the complete workflow defined in this skill's markdown
  > 3. Follow every step faithfully, especially the Invariants section
  > 4. Return a structured summary: accomplishments, findings addressed, fixup-commit commands emitted, and the next pipeline step prompt from the skill

- When the subagent returns, reproduce its full output to the user exactly as written — do not summarize, condense, paraphrase, or omit sections. The user needs to review the complete output to give informed approval. Do not repeat work or add your own commentary.

**Other LLM assistants:**
- Subagent execution may not be supported in your tool. Execute the skill inline following the normal workflow.

## Workflow

### Checklist

1. Resolve target repository
2. Check out the PR branch
3. Verify findings
4. Order findings by severity
5. Track findings as a todo list
6. Gather context
7. Walk through findings sequentially
8. Emit fixup commands after each remediation
9. Prompt the user to run `sdlc_commit`

### 1. Resolve target repository

```bash
gh repo view --json isFork,parent
```

If `isFork` is `true`, use upstream `<owner>/<name>` as the target. All `gh` commands in subsequent steps that reference issues or PRs MUST include `--repo <target>` when the target repo differs from the current repo.

### 2. Check out the PR branch

The MCP endpoint supplied the branch name. Fetch and check it out:

```bash
git fetch origin <branch> && git checkout <branch>
```

If the working tree has uncommitted changes that would conflict with the checkout, stop and ask the user how to proceed.

### 3. Verify findings

The server-supplied enumeration is the starting point but MUST be verified. Re-query both surfaces:

```bash
gh api graphql -f query='
  query($owner: String!, $repo: String!, $pr: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $pr) {
        reviewThreads(first: 100) {
          nodes { isResolved comments(first: 1) { nodes { body path line author { login } } } }
        }
      }
    }
  }
' -f owner='<owner>' -f repo='<repo>' -F pr=<pr-number>

gh pr view <pr-number> --repo <target> --json reviews
```

**Definition of "unresolved review comment":** A review comment is unresolved when its thread is literally marked as unresolved in GitHub's review UI (i.e., the thread has not been clicked "Resolve conversation"). This is a binary GitHub state, not a judgment call. Use the `isResolved` field on review-thread nodes to determine this. An unresolved thread means the reviewer intentionally left it open — the skill MUST read each unresolved comment, understand what the reviewer is asking for, and plan changes to address it. Do not dismiss unresolved comments as already handled without verifying the reviewer's intent.

Findings come from two surfaces and BOTH MUST be enumerated:

- **Review threads** — inline comments left on specific lines of the diff. The correctness review in particular often carries its findings here rather than in the PR-level review body.
- **Review-body comments** — PR-level comments left as part of a review summary. Skip empty bodies (an APPROVED review with no body is not a finding).

If the verification surfaces findings the server's enumeration missed, add them to the working set. If it surfaces fewer (e.g., a reviewer resolved a thread between the server query and now), drop them.

### 4. Order findings by severity

Sort the verified findings by the canonical severity sequence so downstream remediations may be obviated by upstream fixes:

1. Correctness bugs in source
2. Code quality / hygiene in source
3. Test issues — integration tests
4. Test issues — unit tests
5. Stylistic issues
6. Documentation issues

**Rationale:** A correctness fix may rewrite the surface a quality finding targeted, and a source-code rename may invalidate a doc finding verbatim. Front-loading impact prevents wasted churn.

### 5. Track findings as a todo list

Create one task per finding so the user can see progress. The task description SHOULD include the finding's `file:line` citation and a short summary so each task is self-contained when read out of context.

### 6. Gather context

Before walking through findings, MUST read enough of the codebase to evaluate them confidently:

- MUST check whether `.understand-anything/knowledge-graph.json` exists. If it does, MUST use the `understand-chat` skill with a query synthesized from the highest-severity finding to gather architectural context. If the graph does not exist, skip this bullet and continue.
- MUST read source files referenced in any finding's `file:line` citation.
- MUST read existing tests for the affected modules.
- MUST resolve applicable test guides by calling `sdlc_guides_for` with the candidate or referenced source-file paths and `kind="test"`, then read every returned URI to internalize the relevant testing conventions.
- MUST read project-level instructions (`AGENTS.md`) for build tooling, documentation style, and architecture context.

### 7. Walk through findings sequentially

For each finding, in severity order:

1. **Restate the finding** with its `file:line` citation, the reviewer's name, and the exact body text. Mark the corresponding todo as in-progress.
2. **Evaluate correctness/relevance.** Reviewers can be wrong or out of date. Read the code at the cited location. State whether the finding is valid, partially valid, or stale, and explain why.
3. **Propose one or more solutions** with their implications. Call out a recommended option grounded in the PR's objectives.
4. **Wait for explicit user approval** before editing. Allow the user to push back, ask clarifying questions, or pick a different option. The agent MUST NOT edit any file before approval is given.
5. **Implement the approved option.** Edit only the files in scope of the approved option.
6. **Mark the todo complete** after the user confirms the remediation looks right (or after step 8's fixup-command block has been emitted, whichever the user prefers).

### 8. Emit fixup commands after each remediation

After each approved remediation, map every touched file back to the commit on the branch that owns that surface, and emit a copy-paste-able block of `git commit --fixup=<sha>` commands. To find the owning commit:

```bash
git log --oneline main..HEAD -- <touched-file>
```

The most recent commit touching the file is usually the right target. Include the target commit's subject as a trailing comment so the user can sanity-check the mapping:

```bash
git add path/to/touched/file.py
git commit --fixup=<sha>      # <commit subject as appears in git log>
```

**Fixup vs new commit:** Prefer `git commit --fixup=<sha>` when the remediation touches code that already belongs to an existing commit on the branch. An autosquash rebase later folds these in cleanly. Net-new commits are warranted ONLY when the remediation introduces an entirely new subsystem, feature, or concept. If the remediation *replaces* something already in a prior commit, fixup that prior commit instead.

The agent MUST NOT execute these commands. The user reviews and runs them.

### 9. Prompt the user to run `sdlc_commit`

Once all findings have been remediated (or the user chooses to stop early), do NOT auto-commit. Prompt the user with the next pipeline step:

> Ready to commit the remediations? Run the `commit` skill (`sdlc_commit`) to stage and commit the changes; an autosquash rebase against `main` will fold the fixups into their owning commits. Then re-run `sdlc_pr` to update the PR description.

DO NOT proceed on your own.

## Edge Cases

- **Branch checkout fails (uncommitted changes):** Stop and ask the user how to handle the conflict.
- **Branch checkout fails (missing remote ref):** Stop and report the situation; the supplied branch name may be stale.
- **Reviewer's intent is ambiguous:** Ask the user to clarify before proposing solutions; do not guess.
- **Finding is already addressed by an earlier remediation in this session:** Mark the corresponding todo complete with a note (e.g., "obviated by remediation of finding #1") and move on.
- **Finding has been resolved in GitHub between the server query and the verification re-query:** Drop the finding from the working set with a note.
- **No file owns the touched surface (entirely new code):** A net-new commit is appropriate. Emit `git commit -m "<subject>"` instead of a fixup, with a recommended subject in the conventional-commit style.
