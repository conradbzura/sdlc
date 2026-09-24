"""SDLC MCP server — exposes pipeline skills as MCP tools and guides as resources."""

import hashlib
import re
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from sdlc import git_state, guides, pr_state

PACKAGE_DIR = Path(__file__).resolve().parent
SKILLS_DIR = PACKAGE_DIR / "skills"
AGENTS_MD_PATH = PACKAGE_DIR / "AGENTS.md"
ROLE_TEMPLATE_PATH = PACKAGE_DIR / "role-template.md"
REVIEW_TEMPLATE_PATH = PACKAGE_DIR / "review-template.md"
REVIEW_RATIONALE_PATH = PACKAGE_DIR / "review-rationale.md"

_state = guides.load_state(cwd=Path.cwd(), package_dir=PACKAGE_DIR)

mcp = FastMCP(
    "sdlc",
    instructions=(
        "SDLC pipeline for LLM agents. "
        "Tools follow the pipeline: issue → implement → test → commit → pr → review. "
        "Each tool returns the full workflow instructions for that stage. "
        "The LLM reads these instructions and executes them step-by-step, "
        "respecting human-in-the-loop approval gates."
    ),
)


def _read_skill(name: str) -> str:
    """Read a skill markdown file and return its content."""
    path = SKILLS_DIR / f"{name}.md"
    if not path.is_file():
        return f"Error: skill '{name}' not found at {path}"
    return path.read_text()


# Spans of the review skill that only a re-review needs. The markers are block
# FENCES, not per-line tags: roughly three quarters of the re-review-only text
# carries no `**(re-review)**` marker of its own, because a marked header
# introduces paragraphs, bullets and command blocks that inherit its mode
# silently. Filtering on the literal marker would strip a fifth of the material
# and mangle a dozen shared paragraphs.
_REREVIEW_BEGIN = "<!-- rereview:begin -->"
_REREVIEW_END = "<!-- rereview:end -->"


def _strip_rereview(text: str, keep_body: bool = False) -> str:
    """Return ``text`` with every fenced re-review span removed.

    A fresh round is handed a prompt that never mentions dispositions, seeded
    findings or the pass ledger — material it cannot act on and which competes
    for attention with the steps it must actually run.
    """
    out, depth = [], 0
    for line in text.splitlines(keepends=True):
        marker = line.strip()
        if marker == _REREVIEW_BEGIN:
            depth += 1
            continue
        if marker == _REREVIEW_END:
            depth -= 1
            if depth < 0:
                raise ValueError("review.md: unbalanced re-review fence")
            continue
        if keep_body or depth == 0:
            out.append(line)
    if depth:
        raise ValueError("review.md: re-review fence opened and never closed")
    return "".join(out)


def review_skill(rereview: bool) -> str:
    """Return the review skill assembled for the active mode.

    The `Re-review:` directive is known here, before the skill body is ever
    concatenated, so a fresh round need not carry the re-review protocol. On a
    re-review the fences themselves are dropped and everything else is byte
    identical to the file on disk.

    Both modes go through one pass so they cannot disagree about what a
    marker IS: an earlier form assembled the re-review by exact `str.replace`
    of the marker plus its newline, which required column 0 and no trailing
    whitespace, while the fresh path matched on `line.strip()`. A marker that
    drifted by one space would then have been honoured on one path and
    emitted literally on the other, and only the fresh path ran the balance
    check that catches an unclosed opener — whose failure mode is silently
    deleting the rest of the prompt.
    """
    return _strip_rereview(_read_skill("review"), keep_body=rereview)


def _read_file(path: Path) -> str:
    """Read a file and return its content."""
    if not path.is_file():
        return f"Error: file not found at {path}"
    return path.read_text()


def _target_branch_directive(target: str) -> str:
    """Render the target-branch-override directive for a resolved target.

    The wording is byte-identical across `sdlc_implement` and `sdlc_pr` so the
    skills can reference it uniformly: implement branches FROM this branch and
    pr bases the PR AGAINST it, instead of the resolved default branch.
    """
    return (
        f"Target branch override: {target}\n"
        "Branch from / base against this branch instead of the resolved "
        "default branch."
    )


def _review_repo_directive(repo: git_state.ReviewRepo, configured: str | None) -> str:
    """Render the repository directive for `sdlc_review` document commits.

    The repository is declared, never inferred — see `git_state`. An
    unresolved repository is reported as such, with the instruction to ask the
    user, mirroring how PR mode reports an unresolved linked issue rather than
    guessing a path.
    """
    if repo.root is not None:
        return f"Review repository: {repo.root.as_posix()}"
    if repo.reason is not None:
        # A refusal, not a miss. The path IS a repository, so reporting it as
        # "not a git repository" would send the user to initialize something
        # that already exists.
        return f"Review repository: unresolved\n{repo.reason}"
    if configured is not None:
        # NAME the resolved path. `review-repo` resolves against the config
        # file's parent, not the working directory, so the raw value alone
        # cannot show the user what went wrong — and the natural misspelling
        # of this very key produces a message that is FALSE without it:
        # `{"review-repo": ".sdlc"}` in `.sdlc/config.json` resolves to
        # `.sdlc/.sdlc`, and saying ".sdlc is not a git repository" sends the
        # user to initialize a repository that already exists, on every call
        # forever, since step 10(a) records the answer and asks once.
        resolved = (
            f" resolves to {repo.candidate.as_posix()!r} (relative to the config "
            "file's parent), which"
            if repo.candidate is not None
            else ""
        )
        hint = ""
        if (
            repo.candidate is not None
            and repo.candidate.name == repo.candidate.parent.name
        ):
            # The value repeats the directory it is resolved against — the
            # same shape `guides._validate_schema` hints at for camel case.
            hint = (
                f' Did you mean "." — the value that names '
                f"{repo.candidate.parent.as_posix()} itself?"
            )
        return (
            "Review repository: unresolved\n"
            f"The configured review-repo ({configured!r}){resolved} is not a "
            f"git repository.{hint} Tell the user, and ask them to correct "
            "review-repo in .sdlc/config.json or initialize that path as a "
            "repository. Do not commit anywhere else."
        )
    return (
        "Review repository: unresolved\n"
        "No review-repo is configured and .sdlc is not a repository. Before "
        "writing, ask the user either to name an existing repository or to "
        "create one with `git init .sdlc`, then record their answer as "
        '"review-repo" in .sdlc/config.json so this is asked once. Do not guess.'
    )


def _in_repository_directive(
    repo: git_state.ReviewRepo, path: str, label: str
) -> str | None:
    """Render ``path`` addressed from the review repository root, if known.

    The working-directory-relative directives say where the skill writes;
    staging the same files needs them addressed from the repository root
    instead. The two differ whenever the repository is not the working
    directory, which is the normal case when `.sdlc` is its own repository.
    """
    if repo.root is None:
        return None
    resolved = (Path.cwd() / path).resolve()
    try:
        relative = resolved.relative_to(repo.root)
    except ValueError:
        return (
            f"{label}: unresolved\n"
            f"{path} does not lie inside {repo.root.as_posix()}, so it cannot "
            "be committed there. Tell the user their review-repo does not "
            "contain the review documents."
        )
    suffix = "/" if path.endswith("/") else ""
    return f"{label}: {relative.as_posix()}{suffix}"


def _review_branch_directive(target: str | None, configured: str | None) -> str | None:
    """Render the commit-destination branch directive, or ``None``.

    Resolution order is the explicit `target` argument, then the
    `review-branch` config key. When neither is set the result is ``None`` and
    no directive is emitted — the skill commits to whatever branch is checked
    out, which is the documented default. An empty `target` is a malformed
    override, not a request to fall back, so it is rejected rather than
    ignored.

    Deliberately distinct from `_target_branch_directive`: that one names a
    branch to branch FROM or base AGAINST, while this one names the branch
    commits land ON.
    """
    branch = target if target is not None else configured
    if branch is None:
        return None
    git_state.validate_branch_name(branch)
    return (
        f"Review commit branch: {branch}\n"
        "Commit the review document to this branch instead of the checked-out "
        "one. Use a temporary worktree so the tree under review is never "
        "disturbed."
    )


def _review_commit_directives(
    target: str | None, document: str, snapshot: str
) -> list[str]:
    """Render the commit-destination directives shared by every review mode.

    Fresh and re-review rounds, in PR and paths mode alike, all write a
    document, capture the state it was derived from, and commit both, so they
    all carry the same tail. Assembling it once keeps the four paths from
    drifting apart.

    The config is re-read here rather than taken from the import-time `_state`.
    Step 10 of the review skill asks the user to name a repository when none
    resolves and writes their answer into `.sdlc/config.json`, promising the
    question is asked once; without that re-read the write would not be seen
    until the server restarted, and the very next review — the `--verify` pass
    the skill directs the user to run — would ask again.

    The read is deliberately non-mutating. Only `review_repo`, `review_branch`
    and `config_dir` are wanted here, and rebinding the module-global `_state`
    that `sdlc_guides_for`, `sdlc_roles`, `sdlc_role_scope`, `sdlc_role` and
    every guide resource read from would be an invisible side effect of
    rendering a directive.
    """
    state = guides.load_state(cwd=Path.cwd(), package_dir=PACKAGE_DIR)
    repo = git_state.resolve_review_repo(
        state.review_repo, state.config_dir, Path.cwd()
    )
    parts = [f"\n\n{_review_repo_directive(repo, state.review_repo)}"]
    parts.append(f"\n\nReview snapshot directory: {snapshot}")
    for path, label in (
        (document, "Review document in repository"),
        (snapshot, "Review snapshot in repository"),
    ):
        directive = _in_repository_directive(repo, path, label)
        if directive is not None:
            parts.append(f"\n\n{directive}")
    branch_directive = _review_branch_directive(target, state.review_branch)
    if branch_directive is not None:
        parts.append(f"\n\n{branch_directive}")
    return parts


def _target_repo_directive(repo: pr_state.Repo) -> str:
    """Render the target-repo directive for a resolved repository.

    The wording is identical across every tool whose skill runs `gh` against
    issues or PRs, so the skills consume it uniformly. When the current repo is
    a fork, `repo.repo_flag` is the upstream `<owner>/<name>` and `gh` commands
    that reference issues or PRs MUST pass `--repo <id>`; otherwise the current
    repo applies and `--repo` MUST be omitted.
    """
    if repo.repo_flag is None:
        return (
            "Target repo: current repo — omit --repo on gh commands that "
            "reference issues or PRs."
        )
    return (
        f"Target repo: {repo.repo_flag}\n"
        f"Pass --repo {repo.repo_flag} on gh commands that reference issues "
        "or PRs — unless the user explicitly asked to target the fork, in "
        "which case omit --repo and use the current repo."
    )


def _resolve_target_repo_directive() -> str | None:
    """Resolve the target repo once and render its directive.

    Returns the directive string, or ``None`` when `gh` is unavailable so the
    caller degrades gracefully (the skill falls back to resolving the repo
    itself via its user-prose fork-override note).
    """
    try:
        repo = pr_state.resolve_repo()
    except pr_state.GhUnavailable:
        return None
    return _target_repo_directive(repo)


_GLOB_METACHARS = set("*?[]")


def _paths_slug(paths: list[str]) -> str:
    """Derive a stable directory slug from raw `sdlc_review` path arguments.

    Pure and filesystem-free — the slug is computed from the path/glob STRINGS
    so that successive `paths`-mode reviews of the same target accumulate their
    `review-1/2/3…` rounds under one `.sdlc/reviews/<slug>/` directory.

    A single literal file path (one element with no glob metacharacters
    `*?[]`) yields that file's stem (e.g. ``src/sdlc/role-guides/aie.md`` →
    ``aie``). A glob, or any multi-element list, yields a sanitized join of the
    raw arguments (non-alphanumerics collapsed to ``-``, leading/trailing ``-``
    stripped, truncated to ~40 chars) suffixed with ``-<hash8>``, where
    ``<hash8>`` is the first 8 hex digits of the SHA-256 over the sorted,
    newline-joined raw path strings. Both the label and the hash are taken over
    the sorted paths, so the whole slug is stable and collision-resistant
    regardless of argument order.
    """
    if len(paths) == 1 and not (_GLOB_METACHARS & set(paths[0])):
        return Path(paths[0]).stem
    ordered = sorted(paths)
    digest = hashlib.sha256("\n".join(ordered).encode()).hexdigest()[:8]
    sanitized = (
        re.sub(r"[^a-zA-Z0-9]+", "-", "-".join(ordered)).strip("-")[:40].strip("-")
    )
    return f"{sanitized}-{digest}"


@mcp.tool()
async def sdlc_issue(
    issue_number: int | None = None, context: str | None = None
) -> str:
    """Draft and push a GitHub issue, or update an existing one.

    Use when the user says "issue", "file an issue", "create an issue",
    "open a bug report", or similar. If `.issue.md` exists in the repo root,
    it is used as the source. Otherwise the issue is drafted interactively.
    When an issue number is provided, the existing issue is updated instead of
    a new one being created.

    Args:
        issue_number: Optional GitHub issue number to update. When omitted, a
            new issue is drafted; when provided, enter the update workflow.
        context: Optional description of the problem or feature to file.
    """
    skill = _read_skill("issue")
    parts = [skill]
    repo_directive = _resolve_target_repo_directive()
    if repo_directive is not None:
        parts.append(f"\n---\n\n{repo_directive}")
    if issue_number is not None:
        parts.append(
            f"\n---\n\nTarget issue to update: #{issue_number}\n\n"
            "Enter the update workflow defined in this skill."
        )
    if context:
        parts.append(f"\n---\n\nUser context for this issue:\n\n{context}")
    return "\n".join(parts)


@mcp.tool()
async def sdlc_implement(
    number: int, target: str | None = None, review: int | str | None = None
) -> str:
    """Implement a GitHub issue or address local review feedback on a PR.

    Use when the user says "implement", "implement #N", or similar.
    Pass an issue number for a fresh start; pass a PR number to continue
    work on an in-progress PR or to address review feedback.

    The endpoint inspects the GitHub state for ``number`` and the ``review``
    selector, then returns one of three skill prompts: the fresh-implementation
    prompt, the continue-on-existing-branch prompt, or the feedback-remediation
    prompt sourced from a local review document under
    ``.sdlc/reviews/issue-#<N>/``. If ``gh`` is unavailable, falls back to the
    fresh prompt with a diagnostic note.

    Args:
        number: An issue number or an open PR number.
        target: Optional branch to override the resolved default. When set,
            a fresh implementation creates its branch from this branch instead
            of the repo default. Ignored on the continue and feedback paths,
            which operate on an existing branch.
        review: Polymorphic review-feedback selector.
            * ``None`` (default) — load the latest local review document for
              the closing issue when one exists; otherwise route to the
              continue (linked PR) or fresh (bare issue) prompt.
            * ``int`` — load that exact local review iteration. A missing
              iteration returns a clear diagnostic string.
            * ``str`` — a GitHub PR URL whose review feedback is converted into
              a new local review document (next iteration) and consumed. A
              non-PR-URL string returns a clear diagnostic string.
    """
    try:
        repo = pr_state.resolve_repo()
    except pr_state.GhUnavailable:
        repo = None
    repo_suffix = (
        f"\n\n{_target_repo_directive(repo)}" if repo is not None else ""
    )
    try:
        state = pr_state.dispatch(number, repo=repo, review=review)
    except pr_state.GhUnavailable as exc:
        skill = _read_skill("implement")
        parts = [
            f"{skill}\n---\n\nTarget: #{number}\n\n"
            f"<!-- diagnostic: PR state could not be determined ({exc}); "
            "falling back to fresh-implementation prompt. -->"
        ]
        if target:
            parts.append(f"\n{_target_branch_directive(target)}")
        parts.append(repo_suffix)
        return "".join(parts)
    except ValueError as exc:
        return (
            f"Could not load the requested review feedback for #{number}: "
            f"{exc}"
        )
    if state is None:
        skill = _read_skill("implement")
        parts = [f"{skill}\n---\n\nTarget issue: #{number}"]
        if target:
            parts.append(f"\n{_target_branch_directive(target)}")
        parts.append(repo_suffix)
        return "".join(parts)
    if isinstance(state, pr_state.ReviewFindings):
        skill = _read_skill("implement-feedback")
        return (
            f"{skill}\n---\n\nTarget: #{number}\n"
            f"{state.disclose()}{repo_suffix}"
        )
    skill = _read_skill("implement-continue")
    return (
        f"{skill}\n---\n\n"
        f"Target PR: #{state.pr_number} ({state.url})\n"
        f"Branch: {state.head_ref}{repo_suffix}"
    )


@mcp.tool()
async def sdlc_test(issue_number: int) -> str:
    """Analyze code changes and write comprehensive tests.

    Use when the user says "test", "test #N", "write tests for #N",
    or similar. Analyzes what changed, evaluates existing coverage,
    and plans new tests targeting 100% coverage of public APIs.

    Args:
        issue_number: The GitHub issue number to write tests for.
    """
    skill = _read_skill("test")
    parts = [f"{skill}\n---\n\nTarget issue: #{issue_number}"]
    repo_directive = _resolve_target_repo_directive()
    if repo_directive is not None:
        parts.append(f"\n\n{repo_directive}")
    return "".join(parts)


@mcp.tool()
async def sdlc_commit() -> str:
    """Stage and commit changes with atomic, well-described commits.

    Use when the user says "commit", "commit my changes", "stage and commit",
    or similar. Analyzes the working tree diff, groups changes by logical kind,
    and creates disciplined atomic commits with conventional-commit messages.
    """
    skill = _read_skill("commit")
    repo_directive = _resolve_target_repo_directive()
    if repo_directive is None:
        return skill
    return f"{skill}\n---\n\n{repo_directive}"


@mcp.tool()
async def sdlc_pr(issue_number: int, target: str | None = None) -> str:
    """Review changes and create a draft pull request.

    Use when the user says "pr", "create a PR for #N", "open a PR",
    or similar. Reviews the branch diff and drafts a PR description
    based on what was actually implemented.

    Args:
        issue_number: The GitHub issue number to create a PR for.
        target: Optional branch to override the resolved default. When set,
            the PR is based against this branch instead of the repo default.
    """
    skill = _read_skill("pr")
    parts = [f"{skill}\n---\n\nTarget issue: #{issue_number}"]
    if target:
        parts.append(f"\n{_target_branch_directive(target)}")
    repo_directive = _resolve_target_repo_directive()
    if repo_directive is not None:
        parts.append(f"\n\n{repo_directive}")
    return "".join(parts)


def _render_rereview(
    pr_number: int | None,
    paths: list[str] | None,
    roles: list[str] | None,
    subagents: int,
    verify: int,
    target: str | None,
) -> str:
    """Render the `sdlc_review` re-review directive block.

    A re-review is an ordinary review seeded with an existing round's findings.
    It loads `review-<verify>.md` for the active target (an issue-keyed
    directory in PR mode, a slug directory in paths mode) and renders the same
    directive set a fresh review does, with two differences: the write target is
    that existing document rather than a new iteration, and its findings are
    appended for the reviewers to close, reject, or carry.

    Raises ``ValueError`` when a PR target closes no issue, or when the target
    has no `review-<verify>.md` (surfaced by `load_review_findings`).
    """
    skill = review_skill(rereview=True)
    template = _read_file(REVIEW_TEMPLATE_PATH)
    if paths is not None:
        slug = _paths_slug(paths)
        directory = Path(".sdlc/reviews") / slug
        findings = pr_state.load_review_findings(
            0, iteration=verify, directory=directory
        )
        paths_block = "\n".join(paths)
        target_directive = f"Target paths:\n{paths_block}"
        mode_note = (
            "Paths mode: no PR, no diff, and no linked issue — expand the "
            "literal paths and globs above against the working tree and review "
            "each matched file's whole contents. Run no gh and post nothing."
        )
        repo_directive = None
    else:
        issue_number = pr_state.closing_issue(pr_number)
        if issue_number is None:
            raise ValueError(
                f"--verify {verify} was requested for PR #{pr_number}, but the "
                "PR closes no issue, so there is no .sdlc/reviews/issue-#<N>/ "
                "directory to read the review document from."
            )
        directory = Path(".sdlc/reviews") / f"issue-#{issue_number}"
        findings = pr_state.load_review_findings(
            issue_number, iteration=verify, directory=directory
        )
        target_directive = (
            f"Target PR: #{pr_number}\n"
            f"Resolved issue: #{issue_number}"
        )
        mode_note = None
        repo_directive = _resolve_target_repo_directive()
    directory_str = directory.as_posix()
    document = f"{directory_str}/review-{verify}.md"
    snapshot = f"{directory_str}/snapshot-{verify}/"
    # Inherit the seeded document's roles. A seeded finding whose originating
    # role is absent from this pass has no reviewer at all and carries
    # unexamined, so a re-review that silently fell back to `general-purpose`
    # would carry EVERY finding of a round run under another role, forever,
    # while still reporting progress. The document is already parsed here, so
    # the list is free.
    seeded_roles = pr_state.parse_composition_roles(findings.path)
    coverage_note = None
    # An explicit empty list is an omission, not a request for no roles: it
    # would otherwise render a bare `Roles:` line AND suppress inheritance
    # while warning against every seeded role, which is the worst of both.
    if not roles:
        roles = None
    if roles is None:
        roles = seeded_roles or ["general-purpose"]
        if not seeded_roles:
            # The inheritance failed rather than being declined. This is
            # strictly worse than a user narrowing the roles — which IS warned
            # about below — because nobody chose it and nothing else says so.
            coverage_note = (
                "Seeded-role coverage warning: the seeded document's "
                "Composition line could not be read, so no roles were "
                "inherited and this pass runs general-purpose only. Every "
                "seeded finding raised by another role will carry unexamined. "
                "Check the Composition line names its roles as backticked, "
                "comma-separated stems immediately after the literal "
                "`role(s)`, or pass --roles explicitly."
            )
    elif not seeded_roles:
        # An explicit list against a Composition line that could not be read.
        # Coverage is LEAST knowable here and was, until this arm existed, the
        # one case that reported nothing: the warning below is guarded on a
        # non-empty seeded set, and the inheritance warning above is guarded on
        # `roles is None`.
        coverage_note = (
            "Seeded-role coverage warning: the seeded document's Composition "
            "line could not be read, so the roles this pass runs "
            f"({', '.join(roles)}) could not be checked against the roles the "
            "seeded findings were raised by. Any finding raised by a role not "
            "in this pass will carry unexamined. Check the Composition line "
            "names its roles as backticked, comma-separated stems immediately "
            "after the literal `role(s)`."
        )
    else:
        uncovered = [role for role in seeded_roles if role not in roles]
        if uncovered:
            coverage_note = (
                "Seeded-role coverage warning: this pass runs "
                f"{', '.join(roles)}, but the seeded findings were raised by "
                f"{', '.join(uncovered)}, which no reviewer in this pass "
                "carries. Every finding from those roles will carry "
                "unexamined — record that in the pass header, or re-run with "
                # The UNION. `seeded_roles` alone fixes the seeded coverage by
                # discarding whatever lens the caller deliberately added this
                # pass, turning one coverage gap into the opposite one.
                f"--roles {' '.join(sorted(set(roles) | set(seeded_roles)))}."
            )
    roles_line = ", ".join(roles)
    # The target directive selects the mode, and in paths mode a miss means
    # running `gh` in a mode that forbids it. It therefore leads, as on a fresh
    # round, rather than trailing the seeded block — a rendered dump of an
    # entire prior review document, routinely thousands of tokens, and exactly
    # the kind of long distractor-dense span that buries what follows it.
    parts = [
        f"{skill}\n---\n\n"
        f"{target_directive}\n"
        f"Roles: {roles_line}\n"
        f"Reviewers per role: {subagents}\n"
        f"Re-review: review-{verify}\n"
        f"Review document directory: {directory_str}/\n"
        f"Review document: {document}"
    ]
    if mode_note is not None:
        parts.append(f"\n{mode_note}")
    if coverage_note is not None:
        parts.append(f"\n\n{coverage_note}")
    if repo_directive is not None:
        parts.append(f"\n\n{repo_directive}")
    parts.extend(_review_commit_directives(target, document, snapshot))
    parts.append(f"\n\nReview document template:\n\n{template}")
    # The seeded block goes LAST. It is a rendered dump of an entire prior
    # review document — routinely thousands of tokens — and it is bulk context
    # rather than a directive: nothing above it depends on it, while the
    # commit-destination directives above ARE consumed by step 2 and by step
    # 10's validation gate, and their failure mode is a quiet commit to the
    # wrong place. Keeping every directive in the leading span and the largest
    # distractor in the trailing one is the whole point of the ordering.
    parts.append(
        "\n\nSeeded findings — the authoritative FINDING-SET enumeration for "
        "this pass: a finding absent here is absent from this pass, and the "
        "set is not re-derived from the file. This is the document's own "
        "structure with each finding's issue text and remediation checklist "
        "elided: headings, references, touched commits, both ledgers, the "
        "cross-cutting sections and the pass header are all present verbatim, "
        "so there is nothing to read back for them. Fetch the bodies you act "
        "on with `sdlc_review_findings` — a disposition is judged against a "
        "body, so applying one to a finding you have not fetched is applying "
        "it to text you never read.\n"
        f"{findings.disclose(label='Seeded from')}"
    )
    return "".join(parts)


@mcp.tool()
async def sdlc_review(
    pr_number: int | None = None,
    paths: list[str] | None = None,
    roles: list[str] | None = None,
    subagents: int = 1,
    verify: int | None = None,
    target: str | None = None,
) -> str:
    """Review an open PR, or a set of local paths, into a consolidated document.

    Use when the user says "review", "review PR #N", "review this PR",
    "review these files", or similar. Exactly one target MUST be supplied:

    - **PR mode** (`pr_number`): review the PR diff. Spawns `subagents`
      reviewer(s) per role across `roles` (`subagents × len(roles)` reviewer
      subagents total), each reviewing the diff through its role's lens and
      confined to that role's `guide-map.role` files. The main session agent
      consolidates their findings into a single
      `.sdlc/reviews/issue-#<N>/review-<iteration>.md`. The linked issue `<N>`
      is resolved here via the `closingIssuesReferences` relationship (with a
      PR-body fallback) and supplied to the skill.
    - **PATHS mode** (`paths`): review the literal file paths and globs as they
      stand in the working tree — no PR, no diff, no linked issue, and no `gh`.
      The skill expands the globs and reviews each matched file's whole
      contents. Reviewers and consolidation work the same way, but the document
      lives at `.sdlc/reviews/<slug>/review-<iteration>.md`, where `<slug>` is
      derived deterministically from the raw `paths` strings (see
      `_paths_slug`) so successive runs of the same target accumulate together.

    `verify` makes the run a **re-review** rather than a fresh one: it loads
    the existing `review-<verify>.md` for the active target, seeds the
    reviewers with its findings, and rewrites that same document in place. Each
    pass may close a finding whose remediation is present, reject one that does
    not hold up, or add one the current state newly exposes. The chain
    terminates when no blocking findings remain; advisory and incidental
    findings carry forward and neither gates.

    Every finding-set mutation is committed separately, with a message
    justifying the state change, to the repository named by the `review-repo`
    config key, falling back to `.sdlc` only when that key is unset and `.sdlc`
    is itself a repository (see `git_state.resolve_review_repo`).

    Nothing is posted to GitHub in any mode.

    Args:
        pr_number: The PR number to review. Mutually exclusive with `paths`.
        paths: Literal file paths and/or globs to review in place. Mutually
            exclusive with `pr_number`.
        roles: Review-role stems to run, one reviewer set per role. On a
            fresh round, defaults to ["general-purpose"] when omitted. On a
            re-review, defaults to the roles named on the seeded document's
            Composition line, falling back to ["general-purpose"] only when
            none are recorded — a seeded finding whose originating role is
            absent from a pass has no reviewer and carries unexamined, so
            passing an explicit list that does not cover the seeded roles
            narrows coverage rather than widening it.
        subagents: Number of independent reviewers to run per role. Defaults
            to 1.
        verify: When set, re-review the existing `review-<verify>.md` for the
            active target instead of starting a fresh chain, rewriting it in
            place. Raises `ValueError` when no target is supplied (the
            exactly-one-target guard), when a PR target closes no issue (no
            issue directory to read from), or when the target has no
            `review-<verify>.md`. An explicit `roles` list that fails to cover
            the seeded document's roles emits a coverage warning naming the
            uncovered ones, as does a Composition line that cannot be read.
        target: Optional branch the review-document commits land on, overriding
            the `review-branch` config key. When neither is set, commits go to
            the checked-out branch. Note this is a commit destination, unlike
            the `target` of `sdlc_implement` and `sdlc_pr`, which names a
            branch to branch from or base against.
    """
    if (pr_number is None) == (paths is None):
        raise ValueError(
            "sdlc_review requires exactly one target: pass either pr_number "
            "(PR mode) or paths (paths mode), not both and not neither."
        )
    if target is not None:
        # Validated here rather than where the directive is rendered. That
        # render is skipped entirely on the PR path when the PR closes no
        # issue, which would otherwise drop the user's explicit override
        # without a word and leave the one argument that reaches a `git`
        # invocation unchecked on exactly one branch.
        git_state.validate_branch_name(target)
    if verify is not None:
        # `roles` stays None here on purpose: a re-review inherits the roles the
        # seeded document was produced under, and only an explicit list overrides
        # that. Defaulting to `general-purpose` first would erase the distinction.
        return _render_rereview(
            pr_number, paths, roles, subagents, verify, target
        )
    if not roles:
        roles = ["general-purpose"]
    skill = review_skill(rereview=False)
    template = _read_file(REVIEW_TEMPLATE_PATH)
    roles_line = ", ".join(roles)
    if paths is not None:
        slug = _paths_slug(paths)
        paths_block = "\n".join(paths)
        directory = Path(".sdlc/reviews") / slug
        iteration = pr_state._next_iteration(0, directory=directory)
        document = f".sdlc/reviews/{slug}/review-{iteration}.md"
        snapshot = f".sdlc/reviews/{slug}/snapshot-{iteration}/"
        parts = [
            f"{skill}\n---\n\n"
            f"Roles: {roles_line}\n"
            f"Reviewers per role: {subagents}\n"
            f"Target paths:\n{paths_block}\n"
            f"Review document directory: .sdlc/reviews/{slug}/\n"
            f"Review document: {document}\n"
            "Paths mode: no PR, no diff, and no linked issue — expand the "
            "literal paths and globs above against the working tree and review "
            "each matched file's whole contents. Run no gh and post nothing.",
        ]
        parts.extend(_review_commit_directives(target, document, snapshot))
        parts.append(f"\n\nReview document template:\n\n{template}")
        return "".join(parts)
    try:
        issue_number = pr_state.closing_issue(pr_number)
    except pr_state.GhUnavailable:
        issue_number = None
    if issue_number is not None:
        directory = Path(".sdlc/reviews") / f"issue-#{issue_number}"
        iteration = pr_state._next_iteration(issue_number, directory=directory)
        document = (
            f".sdlc/reviews/issue-#{issue_number}/review-{iteration}.md"
        )
        snapshot = (
            f".sdlc/reviews/issue-#{issue_number}/snapshot-{iteration}/"
        )
        issue_line = (
            f"Resolved issue: #{issue_number}\n"
            f"Review document directory: .sdlc/reviews/issue-#{issue_number}/\n"
            f"Review document: {document}"
        )
    else:
        document = None
        snapshot = None
        issue_line = (
            "Resolved issue: unresolved -- the PR has no linked issue via the "
            "closingIssuesReferences relationship or a Closes/Fixes/Resolves "
            "keyword; ask the user which issue it addresses before writing the "
            "review document."
        )
    parts = [
        f"{skill}\n---\n\n"
        f"Target PR: #{pr_number}\n"
        f"Roles: {roles_line}\n"
        f"Reviewers per role: {subagents}\n"
        f"{issue_line}"
    ]
    repo_directive = _resolve_target_repo_directive()
    if repo_directive is not None:
        parts.append(f"\n\n{repo_directive}")
    if document is not None:
        parts.extend(_review_commit_directives(target, document, snapshot))
    parts.append(f"\n\nReview document template:\n\n{template}")
    return "".join(parts)


@mcp.tool()
async def sdlc_understand_chat(query: str) -> str:
    """Answer questions about the codebase using the knowledge graph.

    Use to gather architectural context — component summaries, relationships,
    and layer assignments — that informs planning, scoping, and review.

    Args:
        query: The question about the codebase to answer.
    """
    skill = _read_skill("understand-chat")
    return f"{skill}\n---\n\nQuery: {query}"


@mcp.tool()
async def sdlc_guides_for(
    paths: list[str], kind: Literal["test", "style"]
) -> list[str]:
    """Resolve which guides apply to a set of file paths.

    Returns a deduplicated list of `sdlc://guides/{kind}/{stem}` URIs whose
    glob patterns match any of the given paths. Read each returned URI to
    obtain the guide content.

    Args:
        paths: File paths (relative to project root) to resolve guides for.
        kind: Guide namespace — "test" or "style".
    """
    stems = guides.resolve_guides(paths, kind, _state.guide_map, _state.discovered)
    return [f"sdlc://guides/{kind}/{stem}" for stem in stems]


@mcp.tool()
async def sdlc_roles() -> list[str]:
    """List the available review roles as resource URIs.

    Returns a list of `sdlc://guides/role/{stem}` URIs, one per discovered
    role (bundled or user-supplied). Read each URI to obtain the role's lens,
    blocking policy, and focus globs.
    """
    return [
        f"sdlc://guides/role/{stem}" for stem in guides.list_roles(_state.discovered)
    ]


@mcp.tool()
async def sdlc_role_scope(paths: list[str], role: str) -> list[str]:
    """Return the subset of `paths` that seeds a role's review scope.

    Performs the reverse lookup over the server's already-merged
    `guide-map.role` (default config deep-merged with `.sdlc/config.json`) and
    intersects the role's globs with `paths` using the same
    `pathlib.PurePath.full_match` semantics `sdlc_guides_for` uses. The
    `sdlc_review` skill calls this to seed each reviewer's scope instead of
    re-deriving the merge and glob match by hand. The result is a SEED, not a
    boundary: it can only contain paths that were passed in, so a review whose
    scope is defined by an issue rather than by a diff extends it (see the
    skill's "Context and scope" section). The role's globs remain the outer
    bound, and the skill re-calls this per finding to enforce it. An empty list
    means the role maps to none of the given paths (a role with no
    `guide-map.role` entry, or a real role whose globs match no changed file);
    callers MUST distinguish those cases (see the review skill). The bundled
    `general-purpose` role maps to `**/*`, so every path is in scope.

    Args:
        paths: File paths (relative to project root) to scope — the PR's
            changed files when seeding, or a single finding's file when the
            skill validates which role that finding belongs to.
        role: The review-role stem to scope `paths` for.
    """
    return guides.files_for_role(paths, role, _state.guide_map)


@mcp.tool()
async def sdlc_review_findings(document: str, ids: list[str]) -> str:
    """Return the full text of specific findings from a review document.

    The endpoints inject a review document as an OUTLINE — every finding's
    heading, reference and touched commit, with the issue text and remediation
    checklist elided behind a marker. Call this when you reach a finding you
    have to act on: composing a reviewer's phase-2 message, applying a
    disposition, or walking a remediation with the user.

    Unlike `sdlc://review-rationale`, which is read on a symptom and may be
    skipped, this fetch is REQUIRED at the point of use. A finding's body is
    what a disposition or a remediation is judged against; acting on an
    elided finding means acting on a body you never read.

    Args:
        document: The review document path, taken verbatim from the injected
            `Review document:` or `Seeded from:` directive. Must resolve
            inside `.sdlc/reviews/`.
        ids: Finding ids to fetch, e.g. `["B1", "B4", "A7"]`. Batch a whole
            role's subset in one call rather than fetching one at a time. An
            id the document does not hold is named in the result. Pass an
            EMPTY list to get the enumeration instead — every finding as one
            `id / severity / reference / title` line with no bodies, plus a
            trailing `Ids:` line for comparing id sets. Use that to reconcile
            a seeded block against the file, or to order a remediation walk,
            without paying for a body you are not going to read.
    """
    try:
        return pr_state.render_findings(document, ids)
    except (ValueError, OSError) as exc:
        return f"Error: {exc}"


@mcp.tool()
async def sdlc_role(name: str) -> str:
    """Author a review role document.

    Use when the user says "role", "create a role", "add a review role",
    or similar. Drafts a role document (lens, blocking policy, focus globs)
    and, on approval, writes it to `.sdlc/guides/role/<name>.md`.

    Args:
        name: The role name (stem) to author, e.g. "architect".
    """
    skill = _read_skill("role")
    template = _read_file(ROLE_TEMPLATE_PATH)
    return (
        f"{skill}\n---\n\n"
        f"Target role: {name}\n\n"
        f"Role document template:\n\n{template}"
    )


@mcp.resource("sdlc://guides/test/{stem}")
async def get_test_guide(stem: str) -> str:
    """Return the test guide identified by `stem` (e.g. "python")."""
    return guides.read_guide("test", stem, _state.discovered)


@mcp.resource("sdlc://guides/style/{stem}")
async def get_style_guide(stem: str) -> str:
    """Return the style guide identified by `stem` (e.g. "markdown")."""
    return guides.read_guide("style", stem, _state.discovered)


@mcp.resource("sdlc://guides/role/{stem}")
async def get_role_guide(stem: str) -> str:
    """Return the role guide identified by `stem` (e.g. "general-purpose")."""
    return guides.read_guide("role", stem, _state.discovered)


@mcp.resource("sdlc://config/default")
async def get_default_config() -> str:
    """Return the package-default config.json content."""
    return _read_file(guides.DEFAULT_CONFIG_PATH)


@mcp.resource("sdlc://role-template")
async def role_template() -> str:
    """Return the bundled role-document template."""
    return _read_file(ROLE_TEMPLATE_PATH)


@mcp.resource("sdlc://review-template")
async def review_template() -> str:
    """Return the bundled consolidated-review-document template."""
    return _read_file(REVIEW_TEMPLATE_PATH)


@mcp.resource("sdlc://review-rationale")
async def review_rationale() -> str:
    """Return the review skill's design rationale.

    Read on demand by an agent executing `sdlc_review` — when a command block
    misbehaves, or before deviating from an instruction whose reason is not
    obvious. Deliberately NOT concatenated into the tool's return: the whole
    point is that the skill carries the protocol and this carries the why.
    """
    return _read_file(REVIEW_RATIONALE_PATH)


@mcp.resource("sdlc://agents-md")
async def agents_md() -> str:
    """Project-level instructions for agent implementations (AGENTS.md)."""
    return _read_file(AGENTS_MD_PATH)


@mcp.resource("sdlc://knowledge-graph")
async def knowledge_graph() -> str:
    """Codebase knowledge graph (if available)."""
    kg_path = Path.cwd() / ".understand-anything" / "knowledge-graph.json"
    if kg_path.exists():
        return _read_file(kg_path)
    return "No knowledge graph found. Run /understand to generate one."


def main() -> None:
    """Run the SDLC MCP server."""
    mcp.run()
