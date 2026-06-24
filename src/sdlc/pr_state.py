"""GitHub PR state helpers for the ``sdlc_implement`` and ``sdlc_review`` MCP endpoints."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
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
class ReviewFinding:
    """A single finding parsed from a local ``.sdlc/reviews`` review document."""

    id: str
    title: str
    severity: Literal["blocking", "advisory"]
    reference: str
    issue: str
    remediation: str
    touched_commit: str | None


@dataclass(frozen=True)
class ReviewFindings:
    """A parsed local review document: its provenance and its findings."""

    issue_number: int
    iteration: int
    path: str
    findings: list[ReviewFinding]

    def format(self) -> str:
        """Render the review document as a human-readable feedback block.

        The header carries the document's actual path (``self.path``), the
        issue number, and iteration so the agent can re-read the document. The
        path is emitted verbatim rather than reconstructed, so a paths-mode
        ``<slug>/review-<#>.md`` document renders correctly (in the issue-keyed
        case ``self.path`` already equals that reconstruction). Findings are
        emitted blocking first, then advisory, each numbered with its id,
        severity, reference, title, issue, and pre-selected remediation block.
        """
        lines = [f"Review document: {self.path}"]
        if self.issue_number:
            lines.append(f"Issue: #{self.issue_number}")
        lines += [
            f"Iteration: {self.iteration}",
            f"Path: {self.path}",
            f"Findings ({len(self.findings)}):",
        ]
        ordered = [f for f in self.findings if f.severity == "blocking"]
        ordered += [f for f in self.findings if f.severity == "advisory"]
        for index, finding in enumerate(ordered, start=1):
            lines.append("")
            lines.append(
                f"  {index}. [{finding.severity}] {finding.id} — {finding.title}"
            )
            lines.append(f"     Reference: {finding.reference}")
            if finding.issue:
                lines.append(f"     Issue: {finding.issue}")
            lines.append("     Remediation:")
            for remediation_line in finding.remediation.splitlines():
                lines.append(f"       {remediation_line}")
            if finding.touched_commit is not None:
                lines.append(f"     Touched commit: {finding.touched_commit}")
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


# A PR URL passed as the ``--review`` argument: it MUST look like a GitHub PR
# URL (``…github.com/<owner>/<repo>/pull/<n>``) so a numeric string is never
# silently coerced into a local-iteration selector.
_PR_URL = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)",
    re.IGNORECASE,
)

# Finding heading in a local review document, e.g.
# ``### B1 — Title here **(BLOCKING)** — aie (3/10 …)`` or
# ``### A1 — Title here — aie (4/10 …)``. The ``**(BLOCKING)**`` marker is
# optional; the tier section the heading sits under is authoritative for
# severity, with the marker as a secondary signal.
_FINDING_HEADING = re.compile(
    r"^###\s+(?P<id>\S+)\s+—\s+(?P<rest>.*)$",
)
_BLOCKING_MARKER = "**(BLOCKING)**"
_TIER_BLOCKING = re.compile(r"^##\s+Tier\s+1\b.*Blocking", re.IGNORECASE)
_TIER_ADVISORY = re.compile(r"^##\s+Tier\s+2\b.*Advisory", re.IGNORECASE)


def _reviews_dir(issue_number: int) -> Path:
    """Return the review-document directory for ``issue_number``.

    Mirrors the cwd-relative convention `sdlc_review` writes to:
    ``.sdlc/reviews/issue-#<N>``.
    """
    return Path(".sdlc/reviews") / f"issue-#{issue_number}"


def _iterations(
    issue_number: int, directory: Path | None = None
) -> list[int]:
    """Return the sorted iteration numbers present for the review directory.

    Globs ``review-*.md`` in the review directory and parses the trailing
    integer from each filename. When ``directory`` is given, that explicit
    directory is scanned; otherwise the issue-keyed ``_reviews_dir`` applies.
    Returns an empty list when the directory is absent or holds no parseable
    ``review-<int>.md`` file.
    """
    if directory is None:
        directory = _reviews_dir(issue_number)
    if not directory.is_dir():
        return []
    iterations: list[int] = []
    for path in directory.glob("review-*.md"):
        match = re.fullmatch(r"review-(\d+)", path.stem)
        if match:
            iterations.append(int(match.group(1)))
    return sorted(iterations)


def _latest_iteration(
    issue_number: int, directory: Path | None = None
) -> int | None:
    """Return the highest iteration for the review directory, or ``None``."""
    iterations = _iterations(issue_number, directory)
    return iterations[-1] if iterations else None


def _next_iteration(issue_number: int) -> int:
    """Return the next iteration to write for ``issue_number`` (``max + 1``)."""
    iterations = _iterations(issue_number)
    return (iterations[-1] if iterations else 0) + 1


def _extract_field(block: str, label: str) -> str | None:
    """Return the inline value of a ``**Label:** value`` line in ``block``."""
    pattern = re.compile(
        rf"^\*\*{re.escape(label)}:\*\*\s*(?P<value>.*)$", re.MULTILINE
    )
    match = pattern.search(block)
    if match is None:
        return None
    return match.group("value").strip()


def _parse_finding_block(
    finding_id: str,
    rest: str,
    body: str,
    severity: Literal["blocking", "advisory"],
) -> ReviewFinding:
    """Build a ``ReviewFinding`` from one finding heading and its body text.

    ``rest`` is the heading text after the id; ``body`` is everything between
    this heading and the next heading / tier boundary.
    """
    title = rest
    if _BLOCKING_MARKER in title:
        title = title.split(_BLOCKING_MARKER, 1)[0]
    # Drop a trailing `— <role / agreement>` attribution when present.
    title = title.split(" — ", 1)[0].strip()

    reference = _extract_field(body, "Reference") or ""
    touched_commit = _extract_field(body, "Touched commit")

    # The issue text is the labelled `**Issue:**` paragraph for blocking
    # findings; advisory findings carry a bare paragraph between the Reference
    # line and the first remediation checkbox instead.
    issue = _extract_issue(body)
    remediation = _extract_remediation(body)

    return ReviewFinding(
        id=finding_id,
        title=title,
        severity=severity,
        reference=reference,
        issue=issue,
        remediation=remediation,
        touched_commit=touched_commit,
    )


def _extract_issue(body: str) -> str:
    """Return the finding's issue text.

    Prefers an explicit ``**Issue:**`` paragraph; falls back to the bare
    paragraph between the ``**Reference:**`` line and the first remediation
    checkbox (the advisory shape in the review template).
    """
    lines = body.splitlines()
    labelled: list[str] = []
    capturing = False
    for line in lines:
        if line.startswith("**Issue:**"):
            capturing = True
            labelled.append(line[len("**Issue:**"):].strip())
            continue
        if capturing:
            if line.startswith("**") or line.lstrip().startswith("- ["):
                break
            labelled.append(line.strip())
    if any(labelled):
        return "\n".join(labelled).strip()

    # Advisory shape: text after the Reference line, before the first checkbox.
    bare: list[str] = []
    seen_reference = False
    for line in lines:
        if line.startswith("**Reference:**"):
            seen_reference = True
            continue
        if not seen_reference:
            continue
        if line.lstrip().startswith("- ["):
            break
        if line.startswith("**"):
            break
        bare.append(line.strip())
    return "\n".join(bare).strip()


def _extract_remediation(body: str) -> str:
    """Return the remediation checklist block verbatim.

    Captures the contiguous run of ``- [ ]`` / ``- [x]`` checkbox lines
    (and their continuations), preserving the pre-selected option, any
    alternatives, and the ``Other:`` slot.
    """
    lines = body.splitlines()
    captured: list[str] = []
    capturing = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("- ["):
            capturing = True
            captured.append(line.rstrip())
            continue
        if capturing:
            if not stripped:
                continue
            if (
                stripped.startswith("**")
                or stripped.startswith("###")
                or stripped.startswith("---")
            ):
                break
            # A continuation line of the current checkbox item.
            captured.append(line.rstrip())
    return "\n".join(captured).strip()


def parse_review_document(
    path: str | Path, issue_number: int, iteration: int
) -> ReviewFindings:
    """Parse a local review markdown document into a ``ReviewFindings``.

    Splits the document on its severity-tier sections (``## Tier 1 — Blocking``
    / ``## Tier 2 — Advisory``) and on the per-finding ``### <ID> — <title>``
    headings, extracting each finding's reference, issue, remediation block,
    and touched commit. Severity comes from the enclosing tier section, with
    the ``**(BLOCKING)**`` heading marker as a corroborating signal.
    """
    text = Path(path).read_text()
    lines = text.splitlines()

    findings: list[ReviewFinding] = []
    current_severity: Literal["blocking", "advisory"] | None = None
    pending: tuple[str, str, Literal["blocking", "advisory"]] | None = None
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal pending, body_lines
        if pending is not None:
            finding_id, rest, severity = pending
            findings.append(
                _parse_finding_block(
                    finding_id, rest, "\n".join(body_lines), severity
                )
            )
        pending = None
        body_lines = []

    for line in lines:
        if _TIER_BLOCKING.match(line):
            flush()
            current_severity = "blocking"
            continue
        if _TIER_ADVISORY.match(line):
            flush()
            current_severity = "advisory"
            continue
        heading = _FINDING_HEADING.match(line)
        if heading is not None and current_severity is not None:
            flush()
            rest = heading.group("rest")
            severity: Literal["blocking", "advisory"] = current_severity
            if _BLOCKING_MARKER in rest:
                severity = "blocking"
            pending = (heading.group("id"), rest, severity)
            continue
        if line.startswith("## "):
            # A non-tier section heading (e.g. Cross-cutting decisions) ends
            # the findings region.
            flush()
            current_severity = None
            continue
        if pending is not None:
            body_lines.append(line)

    flush()
    return ReviewFindings(
        issue_number=issue_number,
        iteration=iteration,
        path=str(path),
        findings=findings,
    )


def load_review_findings(
    issue_number: int,
    iteration: int | None = None,
    directory: Path | None = None,
) -> ReviewFindings:
    """Load and parse a local review document.

    When ``directory`` is given, ``review-*.md`` is globbed and resolved under
    that explicit directory (the slug-aware paths-mode and PR-mode location the
    server supplies); when ``None``, behavior is exactly as the issue-keyed
    ``_reviews_dir(issue_number)`` location. With ``iteration=None`` the latest
    review round is loaded; with an explicit integer that exact
    ``review-<iteration>.md`` is loaded. Raises ``ValueError`` with a clear
    message naming the actual directory when it is absent, holds no
    ``review-*.md``, or the requested explicit iteration's file does not exist.
    """
    if directory is None:
        directory = _reviews_dir(issue_number)
    if not directory.is_dir():
        raise ValueError(
            f"No review documents found: directory {directory} does not "
            "exist. Run sdlc_review on the target first."
        )
    if iteration is None:
        latest = _latest_iteration(issue_number, directory)
        if latest is None:
            raise ValueError(
                f"No review documents found: {directory} contains no "
                "review-<iteration>.md file. Run sdlc_review on the target "
                "first."
            )
        iteration = latest
    path = directory / f"review-{iteration}.md"
    if not path.is_file():
        available = _iterations(issue_number, directory)
        raise ValueError(
            f"Review iteration {iteration} not found: {path} does not exist. "
            f"Available iterations: {available or 'none'}."
        )
    return parse_review_document(path, issue_number, iteration)


def _render_github_findings_as_document(
    issue_number: int,
    iteration: int,
    pr_url: str,
    threads: list[Finding],
    body_findings: list[Finding],
) -> str:
    """Render GitHub PR ``Finding``s into the local review-document markdown.

    Produces a template-shaped document — header, blocking/advisory tiers, and
    one finding per GitHub comment — so it can be parsed back by
    ``parse_review_document``. GitHub review feedback carries no severity, so
    every converted finding lands in the blocking tier with a generic,
    pre-selected ``[x]`` "address the reviewer's comment" remediation plus an
    ``Other:`` slot.
    """
    all_findings = [*threads, *body_findings]
    header = [
        f"# PR Review (converted) — Round {iteration}",
        "",
        f"Generated by converting the GitHub review feedback on {pr_url} "
        f"(Closes #{issue_number}) into a local review document. GitHub "
        "review comments carry no severity tier, so each is recorded as a "
        "blocking finding with a generic pre-selected remediation; adjust "
        "before applying.",
        "",
        "---",
        "",
        "## Tier 1 — Blocking",
        "",
    ]
    other_slot = "- [ ] Other: ________________________________________________"
    blocks: list[str] = []
    for index, finding in enumerate(all_findings, start=1):
        if finding.path is not None and finding.line is not None:
            reference = f"`{finding.path}:{finding.line}`"
        elif finding.path is not None:
            reference = f"`{finding.path}`"
        else:
            reference = "(cross-cutting — no single line)"
        author = finding.author or "unknown"
        title = finding.body.strip().splitlines()[0] if finding.body.strip() else (
            "Review comment"
        )
        blocks.append(
            "\n".join(
                [
                    f"### C{index} — {title} **(BLOCKING)** — @{author}",
                    f"**Reference:** {reference}",
                    "",
                    f"**Issue:** @{author} ({finding.kind}): {finding.body.strip()}",
                    "",
                    "**Remediation:**",
                    "- [x] Address the reviewer's comment. "
                    "*(Recommended — pre-selected from the GitHub review.)*",
                    other_slot,
                    "",
                ]
            )
        )
    if not blocks:
        blocks.append(
            "_No unresolved GitHub review feedback was found on this PR._\n"
        )
    advisory = ["---", "", "## Tier 2 — Advisory", ""]
    return "\n".join(header) + "\n\n---\n\n".join(blocks) + "\n\n" + "\n".join(
        advisory
    )


def convert_pr_review_to_document(
    pr_url: str, repo: _Repo | None = None
) -> ReviewFindings:
    """Convert a GitHub PR's review feedback into a new local review document.

    Parses ``owner/repo/pr_number`` from ``pr_url`` (which MUST be a GitHub PR
    URL), fetches the PR's unresolved review threads and non-empty review-body
    comments, resolves the closing issue, renders the GitHub findings into a
    template-shaped markdown document at the NEXT iteration (never overwriting),
    writes it, then parses it back and returns the result.

    Raises ``ValueError`` when ``pr_url`` is not a GitHub PR URL, or when the
    PR has no closing issue (there is no issue directory to write under).
    """
    match = _PR_URL.search(pr_url)
    if match is None:
        raise ValueError(
            f"--review {pr_url!r} is not a GitHub PR URL "
            "(expected …github.com/<owner>/<repo>/pull/<number>)."
        )
    pr_number = int(match.group("number"))
    if repo is None:
        repo = resolve_repo()
    issue_number = _find_closing_issue(repo, pr_number)
    if issue_number is None:
        raise ValueError(
            f"PR {pr_url} closes no issue (no closingIssuesReferences entry "
            "and no Closes/Fixes/Resolves keyword in the body); cannot place a "
            "review document under .sdlc/reviews/issue-#<N>/."
        )
    threads, body_findings = _query_review_state(repo, pr_number)
    iteration = _next_iteration(issue_number)
    document = _render_github_findings_as_document(
        issue_number, iteration, pr_url, threads, body_findings
    )
    directory = _reviews_dir(issue_number)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"review-{iteration}.md"
    path.write_text(document)
    return parse_review_document(path, issue_number, iteration)


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


def dispatch(
    number: int,
    repo: _Repo | None = None,
    review: int | str | None = None,
) -> ReviewFindings | PrContext | None:
    """Classify ``number`` and resolve the review work to perform.

    The ``review`` argument is polymorphic and selects the finding source:

    * ``int`` — load that explicit local review iteration for the closing
      issue. A missing iteration raises ``ValueError``.
    * ``str`` — a GitHub PR URL whose review feedback is converted into a NEW
      local review document (at the next iteration) and returned. A
      non-PR-URL string raises ``ValueError``.
    * ``None`` (the default) — load the latest local review document for the
      closing issue when one exists; otherwise preserve the legacy
      classification: a linked PR with no local docs yields ``PrContext``
      (continue flow) and a bare issue with no PR yields ``None`` (fresh flow).

    Args:
      number: An issue number or an open PR number.
      repo: A pre-resolved target repository. When ``None`` (the default),
        the repo is resolved via ``resolve_repo()`` — but only if a ``gh``
        round-trip is actually needed; a local-doc lookup for a bare issue
        with ``review`` ``None``/``int`` needs no ``gh``.
      review: The review-feedback selector described above.

    Returns:
      * ``None`` — fresh-implementation flow.
      * ``PrContext`` — continue flow (a PR is in scope, no local review docs).
      * ``ReviewFindings`` — feedback flow, sourced from a local review document
        (or a freshly converted PR-URL document).

    Raises ``GhUnavailable`` for any ``gh`` error (including ``number`` not
    being a known issue or PR), and ``ValueError`` for a missing requested
    iteration or a malformed PR-URL ``review`` argument.
    """
    # A PR-URL conversion is independent of ``number``'s classification.
    if isinstance(review, str):
        if repo is None:
            repo = resolve_repo()
        return convert_pr_review_to_document(review, repo)

    # Local docs need no ``gh``. ``number`` IS the closing issue when it names
    # an issue, so speculatively try a local lookup keyed on it before paying
    # for classification. A hit returns immediately; a miss falls through and
    # the ``gh`` classification below tells us whether it was a PR after all.
    local = _try_local_review(number, review)
    if local is not None:
        return local

    if repo is None:
        repo = resolve_repo()
    kind, pr_meta = _classify_number(repo, number)
    if kind == "missing":
        raise GhUnavailable(f"#{number} is neither an open issue nor a PR")

    if kind == "issue":
        issue_number: int | None = number
    else:
        issue_number = _find_closing_issue(repo, number)

    if review is not None:
        if issue_number is None:
            raise ValueError(
                f"--review {review} was requested for PR #{number}, but the "
                "PR closes no issue, so there is no .sdlc/reviews/issue-#<N>/ "
                "directory to read review documents from."
            )
        # ``number`` was a PR whose closing issue we only just resolved; retry
        # the local lookup against it, surfacing a missing iteration clearly.
        return load_review_findings(issue_number, review)

    if issue_number is not None:
        local = _try_local_review(issue_number, None)
        if local is not None:
            return local

    if kind == "issue":
        pr_meta = _find_linked_pr(repo, number)
        if pr_meta is None:
            return None
    assert pr_meta is not None
    pr_number = int(pr_meta["number"])
    head_ref = pr_meta["headRefName"]
    url = pr_meta["url"]
    return PrContext(pr_number=pr_number, head_ref=head_ref, url=url)


def _try_local_review(
    issue_number: int, iteration: int | None
) -> ReviewFindings | None:
    """Return the local review document for ``issue_number`` if present.

    Returns ``None`` (rather than raising) when the directory or the requested
    iteration is absent, so callers can fall through to a ``gh``-based path.
    """
    directory = _reviews_dir(issue_number)
    if not directory.is_dir():
        return None
    if iteration is None:
        latest = _latest_iteration(issue_number)
        if latest is None:
            return None
        return parse_review_document(
            directory / f"review-{latest}.md", issue_number, latest
        )
    path = directory / f"review-{iteration}.md"
    if not path.is_file():
        return None
    return parse_review_document(path, issue_number, iteration)


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
