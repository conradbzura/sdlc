"""GitHub PR state helpers for the ``sdlc_implement`` and ``sdlc_review`` MCP endpoints."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Literal


class GhUnavailable(Exception):
    """Raised when ``gh`` is missing, unauthenticated, or returns an unexpected error.

    The dispatcher in ``server.py`` catches this and falls back to the
    fresh-implementation prompt with a diagnostic comment so the LLM can
    proceed manually.
    """


@dataclass(frozen=True)
class Finding:
    """A single piece of unresolved PR review feedback."""

    kind: Literal["review_thread", "review_body"]
    path: str | None
    line: int | None
    body: str
    author: str | None


@dataclass(frozen=True)
class PrContext:
    """PR metadata for the no-feedback (continue) flow."""

    pr_number: int
    head_ref: str
    url: str


@dataclass(frozen=True)
class Findings:
    """PR metadata plus the enumerated review feedback."""

    pr_number: int
    head_ref: str
    url: str
    findings: list[Finding]

    def format(self) -> str:
        """Render the findings as a human-readable block for the skill prompt."""
        lines = [
            f"PR: #{self.pr_number} ({self.url})",
            f"Branch: {self.head_ref}",
            f"Findings ({len(self.findings)}):",
        ]
        for index, finding in enumerate(self.findings, start=1):
            if finding.path is not None and finding.line is not None:
                citation = f"{finding.path}:{finding.line}"
            elif finding.path is not None:
                citation = finding.path
            else:
                citation = "(PR-level review)"
            author = finding.author or "unknown"
            lines.append(
                f"  {index}. [{finding.kind}] {citation} — @{author}: {finding.body}"
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class _Repo:
    owner: str
    name: str
    repo_flag: str | None


_GRAPHQL_REVIEW_THREADS = (
    "query($owner: String!, $repo: String!, $pr: Int!) "
    "{ repository(owner: $owner, name: $repo) { pullRequest(number: $pr) "
    "{ reviewThreads(first: 100) { nodes { isResolved comments(first: 1) "
    "{ nodes { body path line author { login } } } } } } } }"
)

_GRAPHQL_CLOSING_ISSUES = (
    "query($owner: String!, $repo: String!, $pr: Int!) "
    "{ repository(owner: $owner, name: $repo) { pullRequest(number: $pr) "
    "{ closingIssuesReferences(first: 10) { nodes { number } } } } }"
)

# Closing keywords GitHub honors in a PR body: close/closes/closed,
# fix/fixes/fixed, resolve/resolves/resolved — each followed by `#<number>`.
_CLOSING_KEYWORD = re.compile(
    r"\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\s+#(\d+)",
    re.IGNORECASE,
)


def _run_gh(args: list[str], allow_failure: bool = False) -> str | None:
    """Invoke ``gh`` and return stdout.

    Raises ``GhUnavailable`` when the binary is missing or the command exits
    non-zero (unless ``allow_failure`` is set, in which case the function
    returns ``None`` on non-zero exits).
    """
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GhUnavailable("gh executable not found on PATH") from exc
    if result.returncode != 0:
        if allow_failure:
            return None
        stderr = result.stderr.strip() or f"exit code {result.returncode}"
        raise GhUnavailable(f"gh {' '.join(args)} failed: {stderr}")
    return result.stdout


def resolve_repo() -> _Repo:
    """Resolve the target repository for ``gh`` commands.

    Returns a ``_Repo`` whose ``repo_flag`` is the ``--repo`` value
    (``"<owner>/<name>"``) when the current repo is a fork — so that issues
    and PRs are addressed against the upstream — and ``None`` otherwise (the
    current repo applies and no ``--repo`` flag is needed).

    Raises ``GhUnavailable`` when ``gh`` is missing, unauthenticated, or
    returns an unexpected error.
    """
    out = _run_gh(["repo", "view", "--json", "owner,name,isFork,parent"])
    try:
        data = json.loads(out)
        if data.get("isFork"):
            parent = data["parent"]
            owner = parent["owner"]["login"]
            name = parent["name"]
            return _Repo(owner=owner, name=name, repo_flag=f"{owner}/{name}")
        return _Repo(
            owner=data["owner"]["login"], name=data["name"], repo_flag=None
        )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise GhUnavailable(f"gh repo view returned unexpected output: {exc}") from exc


def _with_repo(args: list[str], repo_flag: str | None) -> list[str]:
    if repo_flag is None:
        return args
    return [*args, "--repo", repo_flag]


def _classify_number(
    repo: _Repo, number: int
) -> tuple[Literal["pr", "issue", "missing"], dict | None]:
    pr_args = ["pr", "view", str(number)]
    pr_args = _with_repo(pr_args, repo.repo_flag)
    pr_args += ["--json", "number,headRefName,url"]
    pr_out = _run_gh(pr_args, allow_failure=True)
    if pr_out is not None:
        return "pr", json.loads(pr_out)
    issue_args = _with_repo(["issue", "view", str(number)], repo.repo_flag)
    issue_out = _run_gh(issue_args, allow_failure=True)
    if issue_out is not None:
        return "issue", None
    return "missing", None


def _find_linked_pr(repo: _Repo, issue_number: int) -> dict | None:
    args = ["pr", "list"]
    args = _with_repo(args, repo.repo_flag)
    args += [
        "--search", f"Closes #{issue_number}",
        "--json", "number,headRefName,url",
        "--jq", ".[0]",
    ]
    out = _run_gh(args)
    stripped = out.strip() if out else ""
    if not stripped or stripped == "null":
        return None
    return json.loads(stripped)


def _find_closing_issue(repo: _Repo, pr_number: int) -> int | None:
    """Return the issue number PR ``pr_number`` closes, or ``None``.

    Queries GitHub's ``closingIssuesReferences`` connection — the authoritative
    set of issues that close when the PR merges, regardless of whether they were
    linked via a ``Closes #N`` keyword or through the GitHub UI. This is the
    correct relationship check: it is deterministic and does not depend on
    parsing prose. Falls back to scanning the PR body for a
    ``Closes`` / ``Fixes`` / ``Resolves #N`` keyword only when the connection is
    empty, and returns ``None`` when neither surface yields a linked issue.
    """
    graphql_args = [
        "api", "graphql",
        "-f", f"query={_GRAPHQL_CLOSING_ISSUES}",
        "-f", f"owner={repo.owner}",
        "-f", f"repo={repo.name}",
        "-F", f"pr={pr_number}",
    ]
    graphql_out = _run_gh(graphql_args)
    nodes = (
        json.loads(graphql_out)
        .get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("closingIssuesReferences", {})
        .get("nodes", [])
    )
    if nodes:
        return int(nodes[0]["number"])

    body_args = _with_repo(["pr", "view", str(pr_number)], repo.repo_flag)
    body_args += ["--json", "body", "--jq", ".body"]
    body = _run_gh(body_args) or ""
    match = _CLOSING_KEYWORD.search(body)
    if match:
        return int(match.group(1))
    return None


def _query_review_state(
    repo: _Repo, pr_number: int
) -> tuple[list[Finding], list[Finding]]:
    graphql_args = [
        "api", "graphql",
        "-f", f"query={_GRAPHQL_REVIEW_THREADS}",
        "-f", f"owner={repo.owner}",
        "-f", f"repo={repo.name}",
        "-F", f"pr={pr_number}",
    ]
    graphql_out = _run_gh(graphql_args)
    graphql_data = json.loads(graphql_out)
    raw_threads = (
        graphql_data.get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
        .get("nodes", [])
    )
    threads: list[Finding] = []
    for thread in raw_threads:
        if thread.get("isResolved"):
            continue
        comments = thread.get("comments", {}).get("nodes", [])
        if not comments:
            continue
        comment = comments[0]
        author = (comment.get("author") or {}).get("login")
        threads.append(
            Finding(
                kind="review_thread",
                path=comment.get("path"),
                line=comment.get("line"),
                body=comment.get("body", ""),
                author=author,
            )
        )

    reviews_args = ["pr", "view", str(pr_number)]
    reviews_args = _with_repo(reviews_args, repo.repo_flag)
    reviews_args += ["--json", "reviews"]
    reviews_out = _run_gh(reviews_args)
    reviews_data = json.loads(reviews_out)
    body_findings: list[Finding] = []
    for review in reviews_data.get("reviews", []):
        body = (review.get("body") or "").strip()
        if not body:
            continue
        author = (review.get("author") or {}).get("login")
        body_findings.append(
            Finding(
                kind="review_body",
                path=None,
                line=None,
                body=body,
                author=author,
            )
        )
    return threads, body_findings


def dispatch(number: int, repo: _Repo | None = None) -> Findings | PrContext | None:
    """Classify ``number`` and gather PR feedback if applicable.

    Args:
      number: An issue number or an open PR number.
      repo: A pre-resolved target repository. When ``None`` (the default),
        the repo is resolved via ``resolve_repo()``. Callers that already
        resolved the repo (e.g. to build the target-repo directive) SHOULD
        pass it to avoid a redundant ``gh repo view`` round-trip.

    Returns:
      * ``None`` — ``number`` is an issue with no linked PR (fresh flow).
      * ``PrContext`` — a PR is in scope but has no unresolved feedback (continue flow).
      * ``Findings`` — a PR is in scope with unresolved feedback (feedback flow).

    Raises ``GhUnavailable`` for any error, including ``number`` not being
    a known issue or PR in the target repo.
    """
    if repo is None:
        repo = resolve_repo()
    kind, pr_meta = _classify_number(repo, number)
    if kind == "missing":
        raise GhUnavailable(f"#{number} is neither an open issue nor a PR")
    if kind == "issue":
        pr_meta = _find_linked_pr(repo, number)
        if pr_meta is None:
            return None
    assert pr_meta is not None
    pr_number = int(pr_meta["number"])
    head_ref = pr_meta["headRefName"]
    url = pr_meta["url"]
    threads, body_findings = _query_review_state(repo, pr_number)
    findings = [*threads, *body_findings]
    if not findings:
        return PrContext(pr_number=pr_number, head_ref=head_ref, url=url)
    return Findings(
        pr_number=pr_number, head_ref=head_ref, url=url, findings=findings
    )


def closing_issue(pr_number: int) -> int | None:
    """Resolve the issue that PR ``pr_number`` closes.

    Resolves the target repository (routing to upstream when the current repo is
    a fork), then performs the ``closingIssuesReferences`` relationship check
    with a PR-body keyword fallback. Returns the linked issue number, or ``None``
    when the PR has no linked issue. Raises ``GhUnavailable`` when ``gh`` is
    missing, unauthenticated, or errors.
    """
    repo = resolve_repo()
    return _find_closing_issue(repo, pr_number)
