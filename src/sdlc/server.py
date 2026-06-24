"""SDLC MCP server — exposes pipeline skills as MCP tools and guides as resources."""

import hashlib
import re
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from sdlc import guides, pr_state

PACKAGE_DIR = Path(__file__).resolve().parent
SKILLS_DIR = PACKAGE_DIR / "skills"
AGENTS_MD_PATH = PACKAGE_DIR / "AGENTS.md"
ROLE_TEMPLATE_PATH = PACKAGE_DIR / "role-template.md"
REVIEW_TEMPLATE_PATH = PACKAGE_DIR / "review-template.md"

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


def _target_repo_directive(repo: pr_state._Repo) -> str:
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
        return f"{skill}\n---\n\nTarget: #{number}\n{state.format()}{repo_suffix}"
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


def _render_verify(
    pr_number: int | None,
    paths: list[str] | None,
    roles: list[str],
    subagents: int,
    verify: int,
) -> str:
    """Render the `sdlc_review` verify-mode directive block.

    Loads the existing `review-<verify>.md` for the active target (an
    issue-keyed directory in PR mode, a slug directory in paths mode), renders
    its findings, and assembles the verify directive: the inlined review skill,
    the composition lines, the `Verify mode` / `Verify document` write-target
    lines, the pre-rendered findings, the mode's target directive, and the
    inlined review-document template.

    Raises ``ValueError`` when a PR target closes no issue, or when the target
    has no `review-<verify>.md` (surfaced by `load_review_findings`).
    """
    skill = _read_skill("review")
    template = _read_file(REVIEW_TEMPLATE_PATH)
    roles_line = ", ".join(roles)
    if paths is not None:
        slug = _paths_slug(paths)
        directory = Path(".sdlc/reviews") / slug
        findings = pr_state.load_review_findings(
            0, iteration=verify, directory=directory
        )
        paths_block = "\n".join(paths)
        target_directive = (
            f"Target paths:\n{paths_block}\n"
            "Paths mode: no PR, no diff, and no linked issue — capture each "
            "matched file's current contents and judge resolution against "
            "them. Run no gh and post nothing."
        )
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
        target_directive = f"Target PR: #{pr_number}"
        repo_directive = _resolve_target_repo_directive()
        if repo_directive is not None:
            target_directive = f"{target_directive}\n\n{repo_directive}"
    directory_str = directory.as_posix()
    return (
        f"{skill}\n---\n\n"
        f"Roles: {roles_line}\n"
        f"Reviewers per role: {subagents}\n"
        f"Verify mode: review-{verify}\n"
        f"Review document directory: {directory_str}/\n"
        f"Verify document: {directory_str}/verify-{verify}.md\n"
        f"{findings.format()}\n\n"
        f"{target_directive}\n\n"
        f"Review document template:\n\n{template}"
    )


@mcp.tool()
async def sdlc_review(
    pr_number: int | None = None,
    paths: list[str] | None = None,
    roles: list[str] | None = None,
    subagents: int = 1,
    verify: int | None = None,
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

    `verify` layers a **verification pass** on top of the active target mode:
    it loads the existing `review-<verify>.md` for that target, fans per-role
    verifiers out to judge each finding Resolved/Unresolved against the current
    files, and writes the verdicts to `verify-<verify>.md` beside the review
    document. The unresolved set feeds the next `sdlc_implement`.

    Nothing is posted to GitHub in any mode.

    Args:
        pr_number: The PR number to review. Mutually exclusive with `paths`.
        paths: Literal file paths and/or globs to review in place. Mutually
            exclusive with `pr_number`.
        roles: Review-role stems to run, one reviewer set per role. Defaults
            to ["general-purpose"] when omitted (every mode).
        subagents: Number of independent reviewers to run per role. Defaults
            to 1.
        verify: When set, verify the existing `review-<verify>.md` for the
            active target instead of producing a new review. Raises
            `ValueError` when no target is supplied (the exactly-one-target
            guard), when a PR target closes no issue (no issue directory to
            read from), or when the target has no `review-<verify>.md`.
    """
    if (pr_number is None) == (paths is None):
        raise ValueError(
            "sdlc_review requires exactly one target: pass either pr_number "
            "(PR mode) or paths (paths mode), not both and not neither."
        )
    if roles is None:
        roles = ["general-purpose"]
    if verify is not None:
        return _render_verify(pr_number, paths, roles, subagents, verify)
    skill = _read_skill("review")
    template = _read_file(REVIEW_TEMPLATE_PATH)
    roles_line = ", ".join(roles)
    if paths is not None:
        slug = _paths_slug(paths)
        paths_block = "\n".join(paths)
        parts = [
            f"{skill}\n---\n\n"
            f"Roles: {roles_line}\n"
            f"Reviewers per role: {subagents}\n"
            f"Target paths:\n{paths_block}\n"
            f"Review document directory: .sdlc/reviews/{slug}/\n"
            "Paths mode: no PR, no diff, and no linked issue — expand the "
            "literal paths and globs above against the working tree and review "
            "each matched file's whole contents. Run no gh and post nothing.",
            f"\n\nReview document template:\n\n{template}",
        ]
        return "".join(parts)
    try:
        issue_number = pr_state.closing_issue(pr_number)
    except pr_state.GhUnavailable:
        issue_number = None
    if issue_number is not None:
        issue_line = (
            f"Resolved issue: #{issue_number}\n"
            f"Review document directory: .sdlc/reviews/issue-#{issue_number}/"
        )
    else:
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
    """Return the subset of `paths` a role's findings are confined to.

    Performs the reverse lookup over the server's already-merged
    `guide-map.role` (default config deep-merged with `.sdlc/config.json`) and
    intersects the role's globs with `paths` using the same
    `pathlib.PurePath.full_match` semantics `sdlc_guides_for` uses. The
    `sdlc_review` skill calls this to scope each reviewer to its role's files
    instead of re-deriving the merge and glob match by hand. An empty list
    means the role maps to none of the given paths (a role with no
    `guide-map.role` entry, or a real role whose globs match no changed file);
    callers MUST distinguish those cases (see the review skill). The bundled
    `general-purpose` role maps to `**/*`, so every path is in scope.

    Args:
        paths: File paths (relative to project root) to scope — typically the
            PR's changed files.
        role: The review-role stem to scope `paths` for.
    """
    return guides.files_for_role(paths, role, _state.guide_map)


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
