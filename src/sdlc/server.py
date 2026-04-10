"""SDLC MCP server — exposes pipeline skills as MCP tools and guides as resources."""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

PACKAGE_DIR = Path(__file__).resolve().parent
SKILLS_DIR = PACKAGE_DIR / "skills"
TEST_GUIDES_DIR = PACKAGE_DIR / "test-guides"
STYLE_GUIDES_DIR = PACKAGE_DIR / "style-guides"
AGENTS_MD_PATH = PACKAGE_DIR / "AGENTS.md"

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


@mcp.tool()
async def sdlc_issue(context: str | None = None) -> str:
    """Draft and push a GitHub issue.

    Use when the user says "issue", "file an issue", "create an issue",
    "open a bug report", or similar. If `.issue.md` exists in the repo root,
    it is used as the source. Otherwise the issue is drafted interactively.

    Args:
        context: Optional description of the problem or feature to file.
    """
    skill = _read_skill("issue")
    parts = [skill]
    if context:
        parts.append(f"\n---\n\nUser context for this issue:\n\n{context}")
    return "\n".join(parts)


@mcp.tool()
async def sdlc_implement(issue_number: int) -> str:
    """Implement a GitHub issue with planning and code changes.

    Use when the user says "implement", "implement #N", or similar.
    Fetches the issue, creates a branch, gathers context, and enters
    planning phase before writing code. On re-invocation after a PR
    exists, addresses unresolved review feedback.

    Args:
        issue_number: The GitHub issue number to implement.
    """
    skill = _read_skill("implement")
    return f"{skill}\n---\n\nTarget issue: #{issue_number}"


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
    return f"{skill}\n---\n\nTarget issue: #{issue_number}"


@mcp.tool()
async def sdlc_commit() -> str:
    """Stage and commit changes with atomic, well-described commits.

    Use when the user says "commit", "commit my changes", "stage and commit",
    or similar. Analyzes the working tree diff, groups changes by logical kind,
    and creates disciplined atomic commits with conventional-commit messages.
    """
    return _read_skill("commit")


@mcp.tool()
async def sdlc_pr(issue_number: int) -> str:
    """Review changes and create a draft pull request.

    Use when the user says "pr", "create a PR for #N", "open a PR",
    or similar. Reviews the branch diff and drafts a PR description
    based on what was actually implemented.

    Args:
        issue_number: The GitHub issue number to create a PR for.
    """
    skill = _read_skill("pr")
    return f"{skill}\n---\n\nTarget issue: #{issue_number}"


@mcp.tool()
async def sdlc_review(pr_number: int) -> str:
    """Review an open pull request for compliance and quality.

    Use when the user says "review", "review PR #N", "review this PR",
    or similar. Analyzes the PR diff against project guides, categorizes
    findings by severity, and posts an inline review.

    Args:
        pr_number: The PR number to review.
    """
    skill = _read_skill("review")
    return f"{skill}\n---\n\nTarget PR: #{pr_number}"


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


@mcp.resource("sdlc://guides/test/python")
async def test_guide_python() -> str:
    """Python testing conventions guide (pytest, pytest-mock, Hypothesis)."""
    return _read_file(TEST_GUIDES_DIR / "python.md")


@mcp.resource("sdlc://guides/style/markdown")
async def style_guide_markdown() -> str:
    """Markdown authoring style guide."""
    return _read_file(STYLE_GUIDES_DIR / "markdown.md")


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
