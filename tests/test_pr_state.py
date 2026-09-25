"""Tests for sdlc.pr_state — gh wrappers and PR-state dispatch."""

import json
import textwrap

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from sdlc import pr_state
from sdlc.server import REVIEW_TEMPLATE_PATH
from sdlc.pr_state import (
    Finding,
    Findings,
    GhUnavailable,
    PrContext,
    ReviewFinding,
    ReviewFindings,
    parse_review_document,
    render_findings,
    render_outline,
    resolve_repo,
)


def _review_document(blocking="", advisory="", incidental=None):
    """Build a minimal review-document markdown body with the given tiers.

    ``blocking``, ``advisory`` and ``incidental`` are pre-rendered finding
    blocks (already dedented); each is dropped under its severity tier
    heading. ``incidental`` defaults to ``None``, which omits the Tier 3
    section entirely — that is the two-tier shape every document written
    before the incidental tier existed carries.
    """
    tier_three = (
        ""
        if incidental is None
        else "## Tier 3 — Incidental\n\n{0}\n\n".format(incidental)
    )
    return textwrap.dedent(
        """\
        # PR #42 — Round 1 Review

        Header prose with branch commit map and severity legend.

        ---

        ## Tier 1 — Blocking

        {blocking}

        ## Tier 2 — Advisory

        {advisory}

        {incidental}## Cross-cutting decisions

        None.
        """
    ).format(blocking=blocking, advisory=advisory, incidental=tier_three)


_BLOCKING_FINDING = textwrap.dedent(
    """\
    ### B1 — Rename foo to bar **(BLOCKING)** — aie (3/10 aie)
    **Reference:** `src/sdlc/server.py:64`

    **Issue:** The symbol `foo` should be `bar` because the convention says so.

    **Remediation:**
    - [x] Rename `foo` to `bar`. *(Recommended — matches the convention.)*
    - [ ] Leave it and add a comment.
    - [ ] Other: ________________________________________________

    **Touched commit:** `abc1234`
    """
)

_ADVISORY_FINDING = textwrap.dedent(
    """\
    ### A1 — Tidy the import block — aie (2/10 aie)
    **Reference:** `src/sdlc/server.py`

    The imports could be grouped more clearly; this is a readability nit.
    - [x] Group stdlib imports first. *(Recommended — readability.)*
    - [ ] Other: ________________________________________________

    **Touched commit:** `def5678`
    """
)

_INCIDENTAL_FINDING = textwrap.dedent(
    """\
    ### I1 — Pre-existing None guard is missing — aie (1/10 aie)
    **Reference:** `src/sdlc/server.py:200`

    The guard predates this PR and no acceptance criterion covers it; recorded as a deferral.
    - [x] File a follow-up issue. *(Recommended — off-issue for this PR.)*
    - [ ] Other: ________________________________________________

    **Touched commit:** `def5678`
    """
)

_ISSUE_LEVEL_FINDING = textwrap.dedent(
    """\
    ### B2 — Acceptance criterion #3 omitted **(BLOCKING)** — aie (1/10 aie)
    **Reference:** issue acceptance criterion #3

    **Issue:** The PR never implements criterion #3 from the issue.

    **Remediation:**
    - [x] Implement criterion #3. *(Recommended — required by the issue.)*
    - [ ] Other: ________________________________________________

    **Touched commit:** `abc1234`
    """
)


def _make_fake_run_gh(responses):
    """Build a fake _run_gh that maps argument tuples to canned outputs.

    Each ``responses`` entry maps a tuple of gh args to one of:
      * a string — returned as the canned stdout.
      * ``None`` — simulates a failing gh command (returns ``None`` to
        callers that pass ``allow_failure=True``; otherwise raises
        ``GhUnavailable``).
      * an ``Exception`` instance — raised directly, regardless of
        ``allow_failure``.
    """

    def fake(args, allow_failure=False):
        key = tuple(args)
        if key not in responses:
            raise AssertionError(f"unexpected gh call: {args}")
        response = responses[key]
        if isinstance(response, Exception):
            raise response
        if response is None:
            if allow_failure:
                return None
            raise GhUnavailable(f"gh {' '.join(args)} failed (canned)")
        return response

    return fake


_REPO_VIEW_FIELDS = "owner,name,isFork,parent"
_REPO_NOT_FORK = json.dumps(
    {
        "owner": {"login": "conradbzura"},
        "name": "sdlc",
        "isFork": False,
        "parent": None,
    }
)
_REPO_FORK = json.dumps(
    {
        "owner": {"login": "fork-owner"},
        "name": "sdlc",
        "isFork": True,
        "parent": {"owner": {"login": "upstream"}, "name": "sdlc"},
    }
)
_PR_VIEW_42 = json.dumps(
    {"number": 42, "headRefName": "feature-x", "url": "https://example/pr/42"}
)
_GRAPHQL_QUERY = (
    "query=query($owner: String!, $repo: String!, $pr: Int!) "
    "{ repository(owner: $owner, name: $repo) { pullRequest(number: $pr) "
    "{ reviewThreads(first: 100) { nodes { isResolved comments(first: 1) "
    "{ nodes { body path line author { login } } } } } } } }"
)


def _graphql_payload(threads):
    return json.dumps(
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {"nodes": threads}
                    }
                }
            }
        }
    )


def _reviews_payload(reviews):
    return json.dumps({"reviews": reviews})


def _graphql_args(owner, repo, pr_number):
    return (
        "api", "graphql",
        "-f", _GRAPHQL_QUERY,
        "-f", f"owner={owner}",
        "-f", f"repo={repo}",
        "-F", f"pr={pr_number}",
    )


_CLOSING_QUERY = (
    "query=query($owner: String!, $repo: String!, $pr: Int!) "
    "{ repository(owner: $owner, name: $repo) { pullRequest(number: $pr) "
    "{ closingIssuesReferences(first: 10) { nodes { number } } } } }"
)


def _closing_graphql_args(owner, repo, pr_number):
    return (
        "api", "graphql",
        "-f", _CLOSING_QUERY,
        "-f", f"owner={owner}",
        "-f", f"repo={repo}",
        "-F", f"pr={pr_number}",
    )


def _closing_payload(numbers):
    return json.dumps(
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "closingIssuesReferences": {
                            "nodes": [{"number": n} for n in numbers]
                        }
                    }
                }
            }
        }
    )


def test_dispatch_with_issue_and_no_linked_pr(tmp_path, monkeypatch):
    """Test dispatch returns None for a fresh issue with no linked PR.

    Given:
        Number 99 classifies as an issue and no PR closes it.
    When:
        dispatch(99) is called.
    Then:
        It should return None to signal the fresh-implementation flow.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
        ("pr", "view", "99", "--json", "number,headRefName,url"): None,
        ("issue", "view", "99"): "issue body",
        (
            "pr", "list", "--search", "Closes #99",
            "--json", "number,headRefName,url", "--jq", ".[0]",
        ): "null\n",
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    result = pr_state.dispatch(99)

    # Assert
    assert result is None


def test_dispatch_with_issue_linked_pr_and_no_local_docs(tmp_path, monkeypatch):
    """Test dispatch returns a PrContext for an issue whose PR has no local docs.

    Given:
        An issue number with no local review document on disk whose linked PR
        is 42.
    When:
        dispatch(99) is called.
    Then:
        It should return a PrContext carrying the linked PR's metadata.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    pr_meta = {
        "number": 42,
        "headRefName": "feature-x",
        "url": "https://example/pr/42",
    }
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
        ("pr", "view", "99", "--json", "number,headRefName,url"): None,
        ("issue", "view", "99"): "issue body",
        (
            "pr", "list", "--search", "Closes #99",
            "--json", "number,headRefName,url", "--jq", ".[0]",
        ): json.dumps(pr_meta),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    result = pr_state.dispatch(99)

    # Assert
    assert result == PrContext(
        pr_number=42, head_ref="feature-x", url="https://example/pr/42"
    )


def test_dispatch_with_pr_number_and_no_local_docs(tmp_path, monkeypatch):
    """Test dispatch returns a PrContext for a PR with no local review docs.

    Given:
        Number 42 classifies as a PR whose closing issue 7 has no local review
        document on disk.
    When:
        dispatch(42) is called with the default review selector.
    Then:
        It should return a PrContext carrying the PR's own metadata, with no
        detour through find_linked_pr.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
        ("pr", "view", "42", "--json", "number,headRefName,url"): _PR_VIEW_42,
        _closing_graphql_args("conradbzura", "sdlc", 42): _closing_payload([7]),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    result = pr_state.dispatch(42)

    # Assert
    assert result == PrContext(
        pr_number=42, head_ref="feature-x", url="https://example/pr/42"
    )


def test_dispatch_should_load_latest_local_review_for_issue(tmp_path, monkeypatch):
    """Test dispatch loads the latest local review document for an issue.

    Given:
        Issue 7 has a local review-1.md with a blocking finding.
    When:
        dispatch(7) is called with the default review selector.
    Then:
        It should return the parsed ReviewFindings without any gh round-trip.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "issue-#7"
    directory.mkdir(parents=True)
    (directory / "review-1.md").write_text(_review_document(blocking=_BLOCKING_FINDING))

    def fail(args, allow_failure=False):
        raise AssertionError(f"dispatch should not call gh: {args}")

    monkeypatch.setattr(pr_state, "_run_gh", fail)

    # Act
    result = pr_state.dispatch(7)

    # Assert
    assert isinstance(result, ReviewFindings)
    assert result.issue_number == 7
    assert result.iteration == 1
    assert result.findings[0].id == "B1"


def test_dispatch_should_load_explicit_iteration_when_review_is_int(
    tmp_path, monkeypatch
):
    """Test dispatch loads the given iteration when review is an int.

    Given:
        Issue 7 has review-1.md and review-2.md.
    When:
        dispatch(7, review=1) is called.
    Then:
        It should return the iteration-1 ReviewFindings, not the latest.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "issue-#7"
    directory.mkdir(parents=True)
    (directory / "review-1.md").write_text(_review_document(blocking=_BLOCKING_FINDING))
    second = _BLOCKING_FINDING.replace("### B1", "### B2")
    (directory / "review-2.md").write_text(_review_document(blocking=second))

    # Act
    result = pr_state.dispatch(7, review=1)

    # Assert
    assert isinstance(result, ReviewFindings)
    assert result.iteration == 1
    assert result.findings[0].id == "B1"


def test_dispatch_should_raise_when_explicit_iteration_missing(tmp_path, monkeypatch):
    """Test dispatch raises ValueError for a missing explicit iteration.

    Given:
        Issue 7 has only review-1.md.
    When:
        dispatch(7, review=9) is called.
    Then:
        It should raise ValueError rather than silently falling back.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "issue-#7"
    directory.mkdir(parents=True)
    (directory / "review-1.md").write_text(_review_document(blocking=_BLOCKING_FINDING))
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
        ("pr", "view", "7", "--json", "number,headRefName,url"): None,
        ("issue", "view", "7"): "issue body",
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act & assert
    with pytest.raises(ValueError, match="iteration 9 not found"):
        pr_state.dispatch(7, review=9)


def test_dispatch_should_convert_when_review_is_a_pr_url(tmp_path, monkeypatch):
    """Test dispatch converts a PR URL into a local document when review is a str.

    Given:
        A GitHub PR URL whose PR closes issue 7 and carries review feedback.
    When:
        dispatch with review set to that PR URL is called.
    Then:
        It should write and return the converted ReviewFindings.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    threads = [
        {
            "isResolved": False,
            "comments": {"nodes": [{
                "body": "rename foo to bar",
                "path": "src/sdlc/server.py",
                "line": 64,
                "author": {"login": "alice"},
            }]},
        },
    ]
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
        _closing_graphql_args("conradbzura", "sdlc", 42): _closing_payload([7]),
        _graphql_args("conradbzura", "sdlc", 42): _graphql_payload(threads),
        ("pr", "view", "42", "--json", "reviews"): _reviews_payload([]),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    result = pr_state.dispatch(
        42, review="https://github.com/conradbzura/sdlc/pull/42"
    )

    # Assert
    assert isinstance(result, ReviewFindings)
    assert result.issue_number == 7
    assert (tmp_path / ".sdlc" / "reviews" / "issue-#7" / "review-1.md").is_file()


def test_dispatch_should_raise_for_malformed_pr_url(monkeypatch):
    """Test dispatch raises ValueError when review is a non-PR-URL string.

    Given:
        A numeric string that is not a GitHub PR URL.
    When:
        dispatch(42, review="123") is called.
    Then:
        It should raise ValueError rather than coercing it to an iteration.
    """
    # Arrange
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act & assert
    with pytest.raises(ValueError, match="not a GitHub PR URL"):
        pr_state.dispatch(42, review="123")


def test_dispatch_with_unknown_number(tmp_path, monkeypatch):
    """Test dispatch raises when the number does not name an issue or PR.

    Given:
        Number 999 fails both the pr-view and issue-view probes.
    When:
        dispatch(999) is called.
    Then:
        It should raise GhUnavailable.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
        ("pr", "view", "999", "--json", "number,headRefName,url"): None,
        ("issue", "view", "999"): None,
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act & assert
    with pytest.raises(GhUnavailable):
        pr_state.dispatch(999)


def test_dispatch_when_repo_view_fails(tmp_path, monkeypatch):
    """Test dispatch raises GhUnavailable when gh repo view fails.

    Given:
        gh repo view returns a non-zero exit (e.g., gh missing or unauth).
    When:
        dispatch(42) is called.
    Then:
        It should raise GhUnavailable.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)

    def fake(args, allow_failure=False):
        raise GhUnavailable("gh repo view failed (canned)")

    monkeypatch.setattr(pr_state, "_run_gh", fake)

    # Act & assert
    with pytest.raises(GhUnavailable):
        pr_state.dispatch(42)


def test_dispatch_with_fork_repo(tmp_path, monkeypatch):
    """Test dispatch routes gh calls to upstream when current repo is a fork.

    Given:
        gh repo view reports the repo is a fork of upstream/sdlc and PR 42
        closes issue 7 with no local review document.
    When:
        dispatch(42) is called.
    Then:
        Subsequent gh commands should include --repo upstream/sdlc and the
        graphql variables should reference the upstream owner/repo.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_FORK,
        (
            "pr", "view", "42", "--repo", "upstream/sdlc",
            "--json", "number,headRefName,url",
        ): _PR_VIEW_42,
        _closing_graphql_args("upstream", "sdlc", 42): _closing_payload([7]),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    result = pr_state.dispatch(42)

    # Assert
    assert isinstance(result, PrContext)
    assert result.pr_number == 42


def test_closing_issue_should_resolve_via_closing_references(monkeypatch):
    """Test closing_issue resolves the linked issue from closingIssuesReferences.

    Given:
        PR 42's closingIssuesReferences connection names issue 7.
    When:
        closing_issue(42) is called.
    Then:
        It should return 7 without consulting the PR body.
    """
    # Arrange
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
        _closing_graphql_args("conradbzura", "sdlc", 42): _closing_payload([7]),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    result = pr_state.closing_issue(42)

    # Assert
    assert result == 7


def test_closing_issue_should_fall_back_to_body_keyword_when_references_empty(
    monkeypatch,
):
    """Test closing_issue parses the PR body when the connection is empty.

    Given:
        PR 42 has an empty closingIssuesReferences connection but a body that
        says "Closes #7".
    When:
        closing_issue(42) is called.
    Then:
        It should return 7 from the PR-body keyword fallback.
    """
    # Arrange
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
        _closing_graphql_args("conradbzura", "sdlc", 42): _closing_payload([]),
        (
            "pr", "view", "42", "--json", "body", "--jq", ".body",
        ): "Implements the widget.\n\nCloses #7\n",
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    result = pr_state.closing_issue(42)

    # Assert
    assert result == 7


def test_closing_issue_should_return_none_when_pr_has_no_linked_issue(monkeypatch):
    """Test closing_issue returns None when neither surface names an issue.

    Given:
        PR 42 has an empty closingIssuesReferences connection and a body with
        no closing keyword.
    When:
        closing_issue(42) is called.
    Then:
        It should return None.
    """
    # Arrange
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
        _closing_graphql_args("conradbzura", "sdlc", 42): _closing_payload([]),
        (
            "pr", "view", "42", "--json", "body", "--jq", ".body",
        ): "A standalone change with no linked issue.\n",
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    result = pr_state.closing_issue(42)

    # Assert
    assert result is None


def test_closing_issue_should_route_to_upstream_when_fork(monkeypatch):
    """Test closing_issue queries upstream when the current repo is a fork.

    Given:
        gh repo view reports the repo is a fork of upstream/sdlc and PR 42's
        connection names issue 7.
    When:
        closing_issue(42) is called.
    Then:
        It should resolve 7 using the upstream owner/repo in the graphql call.
    """
    # Arrange
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_FORK,
        _closing_graphql_args("upstream", "sdlc", 42): _closing_payload([7]),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    result = pr_state.closing_issue(42)

    # Assert
    assert result == 7


def test_resolve_repo_should_return_no_flag_when_not_a_fork(monkeypatch):
    """Test resolve_repo signals the current repo when it is not a fork.

    Given:
        gh repo view reports the current repo is not a fork.
    When:
        resolve_repo() is called.
    Then:
        It should return a repo whose repo_flag is None (no --repo needed)
        carrying the current owner and name.
    """
    # Arrange
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    repo = resolve_repo()

    # Assert
    assert repo.repo_flag is None
    assert repo.owner == "conradbzura"
    assert repo.name == "sdlc"


def test_resolve_repo_should_return_upstream_flag_when_a_fork(monkeypatch):
    """Test resolve_repo targets the upstream when the current repo is a fork.

    Given:
        gh repo view reports the current repo is a fork of upstream/sdlc.
    When:
        resolve_repo() is called.
    Then:
        It should return a repo whose repo_flag is the upstream
        "upstream/sdlc" identifier with the upstream owner and name.
    """
    # Arrange
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_FORK,
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    repo = resolve_repo()

    # Assert
    assert repo.repo_flag == "upstream/sdlc"
    assert repo.owner == "upstream"
    assert repo.name == "sdlc"


def test_resolve_repo_should_raise_when_gh_unavailable(monkeypatch):
    """Test resolve_repo propagates GhUnavailable when gh fails.

    Given:
        gh repo view fails (gh missing or unauthenticated).
    When:
        resolve_repo() is called.
    Then:
        It should raise GhUnavailable.
    """
    # Arrange
    def fake(args, allow_failure=False):
        raise GhUnavailable("gh repo view failed (canned)")

    monkeypatch.setattr(pr_state, "_run_gh", fake)

    # Act & assert
    with pytest.raises(GhUnavailable):
        resolve_repo()


def test_resolve_repo_should_raise_when_gh_output_is_malformed(monkeypatch):
    """Test resolve_repo raises GhUnavailable when gh returns malformed JSON.

    Given:
        gh repo view exits 0 but emits output that is not valid JSON.
    When:
        resolve_repo() is called.
    Then:
        It should raise GhUnavailable rather than a JSONDecodeError, so the
        graceful-degradation contract holds.
    """
    # Arrange
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): "not json{",
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act & assert
    with pytest.raises(GhUnavailable):
        resolve_repo()


def test_resolve_repo_should_raise_when_fork_parent_is_null(monkeypatch):
    """Test resolve_repo raises GhUnavailable when a fork has a null parent.

    Given:
        gh repo view reports isFork true but the parent field is null (a
        permissions quirk).
    When:
        resolve_repo() is called.
    Then:
        It should raise GhUnavailable rather than a TypeError/KeyError, so the
        graceful-degradation contract holds.
    """
    # Arrange
    fork_without_parent = json.dumps(
        {
            "owner": {"login": "fork-owner"},
            "name": "sdlc",
            "isFork": True,
            "parent": None,
        }
    )
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): fork_without_parent,
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act & assert
    with pytest.raises(GhUnavailable):
        resolve_repo()


class TestFindings:
    def test_format_with_thread_finding(self):
        """Test Findings.format renders thread findings with file:line citations.

        Given:
            Findings holding one review_thread finding.
        When:
            format() is called.
        Then:
            The output should include file:line, body, and author.
        """
        # Arrange
        findings = Findings(
            pr_number=42,
            head_ref="feature-x",
            url="https://example/pr/42",
            findings=[
                Finding(
                    kind="review_thread",
                    path="src/sdlc/server.py",
                    line=64,
                    body="rename foo to bar",
                    author="alice",
                ),
            ],
        )

        # Act
        rendered = findings.format()

        # Assert
        assert "src/sdlc/server.py:64" in rendered
        assert "rename foo to bar" in rendered
        assert "alice" in rendered

    def test_format_with_review_body_finding(self):
        """Test Findings.format renders review-body comments without file/line.

        Given:
            Findings holding one review_body finding (PR-level comment).
        When:
            format() is called.
        Then:
            The output should include the body and author and MUST NOT include
            a None file/line citation.
        """
        # Arrange
        findings = Findings(
            pr_number=42,
            head_ref="feature-x",
            url="https://example/pr/42",
            findings=[
                Finding(
                    kind="review_body",
                    path=None,
                    line=None,
                    body="Please address the doc gap.",
                    author="alice",
                ),
            ],
        )

        # Act
        rendered = findings.format()

        # Assert
        assert "Please address the doc gap." in rendered
        assert "alice" in rendered
        assert "None:None" not in rendered
        assert ":None" not in rendered


class TestReviewFindings:
    def test_format_should_render_header_and_finding_details(self):
        """Test ReviewFindings.format renders the header and each finding.

        Given:
            ReviewFindings carrying one blocking finding.
        When:
            format() is called.
        Then:
            The output should include the issue/iteration header and the
            finding's id, severity, reference, title, and remediation.
        """
        # Arrange
        review = ReviewFindings(
            issue_number=42,
            iteration=3,
            path=".sdlc/reviews/issue-#42/review-3.md",
            findings=[
                ReviewFinding(
                    id="B1",
                    title="Rename foo to bar",
                    severity="blocking",
                    reference="`src/sdlc/server.py:64`",
                    issue="The symbol foo should be bar.",
                    remediation="- [x] Rename foo to bar. *(Recommended.)*",
                    touched_commit="`abc1234`",
                ),
            ],
        )

        # Act
        rendered = review.format()

        # Assert
        assert "Issue: #42" in rendered
        assert "Iteration: 3" in rendered
        assert "B1" in rendered
        assert "blocking" in rendered
        assert "src/sdlc/server.py:64" in rendered
        assert "Rename foo to bar" in rendered
        assert "- [x] Rename foo to bar" in rendered

    def test_format_should_order_blocking_findings_before_advisory(self):
        """Test ReviewFindings.format emits blocking findings before advisory.

        Given:
            ReviewFindings whose list holds an advisory finding before a
            blocking one.
        When:
            format() is called.
        Then:
            The blocking finding should appear before the advisory finding in
            the rendered output.
        """
        # Arrange
        review = ReviewFindings(
            issue_number=42,
            iteration=1,
            path=".sdlc/reviews/issue-#42/review-1.md",
            findings=[
                ReviewFinding(
                    id="A1",
                    title="Advisory item",
                    severity="advisory",
                    reference="`a.py`",
                    issue="advisory issue",
                    remediation="- [x] tidy",
                    touched_commit=None,
                ),
                ReviewFinding(
                    id="B1",
                    title="Blocking item",
                    severity="blocking",
                    reference="`b.py:1`",
                    issue="blocking issue",
                    remediation="- [x] fix",
                    touched_commit=None,
                ),
            ],
        )

        # Act
        rendered = review.format()

        # Assert
        assert rendered.index("Blocking item") < rendered.index("Advisory item")

    def test_format_should_order_incidental_findings_last(self):
        """Test ReviewFindings.format emits the three tiers in gate order.

        Given:
            ReviewFindings whose list holds an incidental finding first, then
            an advisory one, then a blocking one.
        When:
            format() is called.
        Then:
            The rendered order should be blocking, advisory, incidental — the
            order in which a consumer should spend attention, since only the
            first gates and only the last is a deferral.
        """
        # Arrange
        review = ReviewFindings(
            issue_number=42,
            iteration=1,
            path=".sdlc/reviews/issue-#42/review-1.md",
            findings=[
                ReviewFinding(
                    id="I1",
                    title="Incidental item",
                    severity="incidental",
                    reference="`c.py`",
                    issue="incidental issue",
                    remediation="- [x] defer",
                    touched_commit=None,
                ),
                ReviewFinding(
                    id="A1",
                    title="Advisory item",
                    severity="advisory",
                    reference="`a.py`",
                    issue="advisory issue",
                    remediation="- [x] tidy",
                    touched_commit=None,
                ),
                ReviewFinding(
                    id="B1",
                    title="Blocking item",
                    severity="blocking",
                    reference="`b.py:1`",
                    issue="blocking issue",
                    remediation="- [x] fix",
                    touched_commit=None,
                ),
            ],
        )

        # Act
        rendered = review.format()

        # Assert
        assert (
            rendered.index("Blocking item")
            < rendered.index("Advisory item")
            < rendered.index("Incidental item")
        )
        assert "[incidental] I1" in rendered

    def test_format_should_emit_the_documents_actual_path(self):
        """Test ReviewFindings.format emits self.path verbatim in the header.

        Given:
            ReviewFindings whose path is a paths-mode `<slug>/review-<#>.md`
            that does not match the issue-keyed reconstruction.
        When:
            format() is called.
        Then:
            The header should carry the document's actual path verbatim, not a
            reconstructed `.sdlc/reviews/issue-#<N>/review-<#>.md`.
        """
        # Arrange
        review = ReviewFindings(
            issue_number=7,
            iteration=1,
            path=".sdlc/reviews/server/review-1.md",
            findings=[],
        )

        # Act
        rendered = review.format()

        # Assert
        assert ".sdlc/reviews/server/review-1.md" in rendered
        assert ".sdlc/reviews/issue-#7/review-1.md" not in rendered

    def test_format_should_label_the_header_with_the_document_default(self):
        """Test ReviewFindings.format labels the header line by default.

        Given:
            ReviewFindings and no label argument.
        When:
            format() is called.
        Then:
            The header line should read `Review document: <path>`.
        """
        # Arrange
        review = ReviewFindings(
            issue_number=7,
            iteration=1,
            path=".sdlc/reviews/issue-#7/review-1.md",
            findings=[],
        )

        # Act
        rendered = review.format()

        # Assert
        assert rendered.startswith(
            "Review document: .sdlc/reviews/issue-#7/review-1.md"
        )

    def test_format_should_label_the_header_when_a_label_is_given(self):
        """Test ReviewFindings.format honors an explicit header label.

        Given:
            ReviewFindings and the label the re-review seeding block uses.
        When:
            format(label="Seeded from") is called.
        Then:
            The header line should carry that label instead of the default,
            so the seeded block cannot be mistaken for the write target.
        """
        # Arrange
        review = ReviewFindings(
            issue_number=7,
            iteration=1,
            path=".sdlc/reviews/issue-#7/review-1.md",
            findings=[],
        )

        # Act
        rendered = review.format(label="Seeded from")

        # Assert
        assert rendered.startswith(
            "Seeded from: .sdlc/reviews/issue-#7/review-1.md"
        )
        assert "Review document:" not in rendered

    def test_disclose_should_carry_the_enumeration_without_the_bodies(
        self,
        tmp_path, monkeypatch
    ):
        """Test the injected block names every finding and elides every body.

        Given:
            A parsed review document with findings in three tiers.
        When:
            disclose is called, as both endpoints now call it.
        Then:
            It should keep the provenance header, carry every finding's heading
            and reference, and elide the issue text — so the enumeration a pass
            depends on is inline while the bulk is not.
        """
        # Arrange
        monkeypatch.chdir(tmp_path)
        path = _reviews_document(
            tmp_path,
            _review_document(
                blocking=_BLOCKING_FINDING,
                advisory=_ADVISORY_FINDING,
                incidental=_INCIDENTAL_FINDING,
            ),
        )
        parsed = parse_review_document(path, issue_number=42, iteration=1)

        # Act
        block = parsed.disclose()

        # Assert
        assert f"Review document: {path}" in block
        assert "Issue: #42" in block
        assert "Findings (3)" in block
        for heading in ("### B1 —", "### A1 —", "### I1 —"):
            assert heading in block, heading
        assert "**Issue:**" not in block
        assert "The symbol `foo` should be `bar`" not in block
        assert block.count("sdlc_review_findings") >= 3


    def test_disclose_should_carry_what_format_drops(self, tmp_path, monkeypatch):
        """Test the outline block preserves the fields the rendered one loses.

        Given:
            `format` re-renders parsed fields, so role attribution, the ledgers
            and the cross-cutting section never reach a consumer through it.
        When:
            Both renderings of the same document are compared.
        Then:
            disclose should carry the role attribution and the trailing
            sections that format does not — which is what removes the
            read-back obligation, not just the token cost.
        """
        # Arrange
        monkeypatch.chdir(tmp_path)
        path = _reviews_document(tmp_path, _review_document(blocking=_BLOCKING_FINDING))
        parsed = parse_review_document(path, issue_number=42, iteration=1)

        # Act
        block = parsed.disclose()
        rendered = parsed.format()

        # Assert
        assert "aie (3/10 aie)" in block
        assert "aie (3/10 aie)" not in rendered
        assert "## Cross-cutting decisions" in block
        assert "## Cross-cutting decisions" not in rendered


    def test_disclose_should_label_the_header_when_a_label_is_given(
        self,
        tmp_path, monkeypatch
    ):
        """Test a re-review's provenance line cannot be read as a write target.

        Given:
            A re-review injects both a `Review document:` write-target directive
            and the seeded document's provenance.
        When:
            disclose is called with the seeded label.
        Then:
            The header should use that label, keeping the two apart exactly as
            the full rendering does.
        """
        # Arrange
        monkeypatch.chdir(tmp_path)
        path = _reviews_document(tmp_path, _review_document(blocking=_BLOCKING_FINDING))
        parsed = parse_review_document(path, issue_number=42, iteration=1)

        # Act
        block = parsed.disclose(label="Seeded from")

        # Assert
        assert block.startswith(f"Seeded from: {path}")


def test_parse_review_document_should_extract_a_blocking_finding(tmp_path):
    """Test parse_review_document extracts a blocking finding's fields.

    Given:
        A review document with one blocking finding under Tier 1.
    When:
        parse_review_document is called.
    Then:
        It should return a ReviewFindings whose finding carries the id, title
        (with the BLOCKING marker stripped), blocking severity, reference,
        issue, remediation, and touched commit.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(_review_document(blocking=_BLOCKING_FINDING))

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    assert result.issue_number == 42
    assert result.iteration == 1
    assert result.path == str(path)
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.id == "B1"
    assert finding.title == "Rename foo to bar"
    assert finding.severity == "blocking"
    assert finding.reference == "`src/sdlc/server.py:64`"
    assert "should be `bar`" in finding.issue
    assert "- [x] Rename `foo` to `bar`." in finding.remediation
    assert "- [ ] Other:" in finding.remediation
    assert finding.touched_commit == "`abc1234`"


def test_parse_review_document_should_extract_an_advisory_finding(tmp_path):
    """Test parse_review_document extracts an advisory finding without labels.

    Given:
        A review document whose Tier 2 advisory finding states its issue as a
        bare paragraph (no **Issue:** label) and lists its remediation without
        a **Remediation:** label.
    When:
        parse_review_document is called.
    Then:
        It should classify the finding as advisory and still capture the bare
        issue text and the remediation checklist.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(_review_document(advisory=_ADVISORY_FINDING))

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.id == "A1"
    assert finding.severity == "advisory"
    assert "readability nit" in finding.issue
    assert "- [x] Group stdlib imports first." in finding.remediation


def test_parse_review_document_should_handle_an_issue_level_reference(tmp_path):
    """Test parse_review_document preserves a line-less issue-level reference.

    Given:
        A blocking finding whose Reference is an issue acceptance criterion
        rather than a file:line citation.
    When:
        parse_review_document is called.
    Then:
        It should preserve the issue-level reference verbatim.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(_review_document(blocking=_ISSUE_LEVEL_FINDING))

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    finding = result.findings[0]
    assert finding.reference == "issue acceptance criterion #3"
    assert finding.severity == "blocking"


def test_parse_review_document_should_group_findings_by_tier(tmp_path):
    """Test parse_review_document assigns severity from the enclosing tier.

    Given:
        A review document with one finding under each of the three severity
        tiers.
    When:
        parse_review_document is called.
    Then:
        It should return every finding with the severity of its tier.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(
        _review_document(
            blocking=_BLOCKING_FINDING,
            advisory=_ADVISORY_FINDING,
            incidental=_INCIDENTAL_FINDING,
        )
    )

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    by_id = {f.id: f.severity for f in result.findings}
    assert by_id == {"B1": "blocking", "A1": "advisory", "I1": "incidental"}


def test_parse_review_document_should_extract_an_incidental_finding(tmp_path):
    """Test parse_review_document extracts a Tier 3 finding's fields.

    Given:
        A review document whose Tier 3 finding states its issue as a bare
        paragraph, in the same shape Tier 2 uses.
    When:
        parse_review_document is called.
    Then:
        It should classify the finding as incidental and capture the bare
        issue text, the remediation checklist and the touched commit.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(_review_document(incidental=_INCIDENTAL_FINDING))

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.id == "I1"
    assert finding.title == "Pre-existing None guard is missing"
    assert finding.severity == "incidental"
    assert finding.reference == "`src/sdlc/server.py:200`"
    assert "no acceptance criterion covers it" in finding.issue
    assert "- [x] File a follow-up issue." in finding.remediation
    assert finding.touched_commit == "`def5678`"


def test_parse_review_document_should_read_a_two_tier_document_unchanged(tmp_path):
    """Test a document written before the incidental tier still parses.

    Given:
        A review document carrying only Tier 1 and Tier 2 — the shape every
        document written before the incidental tier existed has.
    When:
        parse_review_document is called.
    Then:
        It should return exactly the two findings with their original
        severities, so no migration is required of existing chains.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    document = _review_document(
        blocking=_BLOCKING_FINDING, advisory=_ADVISORY_FINDING
    )
    assert "Tier 3" not in document
    path.write_text(document)

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    assert [(f.id, f.severity) for f in result.findings] == [
        ("B1", "blocking"),
        ("A1", "advisory"),
    ]


def test_parse_review_document_should_promote_a_marked_finding_in_the_incidental_tier(
    tmp_path,
):
    """Test the blocking marker still outranks a Tier 3 section heading.

    Given:
        A finding carrying the BLOCKING marker that sits under Tier 3 —
        a re-tier that moved the finding but not its marker.
    When:
        parse_review_document is called.
    Then:
        It should classify the finding as blocking. The marker override is
        monotone toward blocking, so a stale marker costs a wasted pass
        rather than dropping a finding out of the termination predicate.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    stale = _BLOCKING_FINDING.replace("### B1", "### B4")
    path.write_text(_review_document(incidental=stale))

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    assert result.findings[0].id == "B4"
    assert result.findings[0].severity == "blocking"


def test_parse_review_document_should_separate_adjacent_findings(tmp_path):
    """Test parse_review_document splits two findings joined by a separator.

    Given:
        Two blocking findings under Tier 1 separated by a --- horizontal rule.
    When:
        parse_review_document is called.
    Then:
        It should return both findings, and neither remediation should absorb
        the --- separator.
    """
    # Arrange
    second = _BLOCKING_FINDING.replace("### B1", "### B3").replace(
        "Rename foo to bar", "Tighten the guard"
    )
    blocking = f"{_BLOCKING_FINDING}\n---\n\n{second}"
    path = tmp_path / "review-1.md"
    path.write_text(_review_document(blocking=blocking))

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    assert [f.id for f in result.findings] == ["B1", "B3"]
    for finding in result.findings:
        assert "---" not in finding.remediation


_CONTINUED_REMEDIATION = textwrap.dedent(
    """\
    ### B1 — Replace the blocklist **(BLOCKING)** — aie (1/1 aie)
    **Reference:** `src/sdlc/git_state.py:35`

    **Issue:** The guard enumerates what it rejects.

    **Remediation:**
    - [x] Replace the blocklist with an allowlist. *(Recommended.)*

    **Note that** this rejects names git itself would accept, which is the
    intended trade.

    - [ ] Extend the blocklist by the characters named above.
    - [ ] Other: ________________________________________________

    **Touched commit:** `abc1234`
    """
)


def test_parse_review_document_should_keep_options_after_a_bold_continuation(
    tmp_path,
):
    """Test a bolded continuation does not truncate the remediation checklist.

    Given:
        A finding whose remediation carries a paragraph opening with a bold
        span between its first option and the two below it.
    When:
        parse_review_document is called.
    Then:
        It should return all three options and the Other: slot. Terminating on
        any line opening `**` cannot tell a label from a bolded continuation,
        which is the defect `_FIELD_LABELS` was introduced to close for the
        issue text and had not been applied to the checklist.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(_review_document(blocking=_CONTINUED_REMEDIATION))

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    remediation = result.findings[0].remediation
    assert remediation.count("- [") == 3, remediation
    assert "Other:" in remediation
    assert "Extend the blocklist" in remediation
    assert "**Touched commit:**" not in remediation


_FENCED_FINDING = textwrap.dedent(
    """\
    ### B1 — Quote the guide **(BLOCKING)** — aie (1/1 aie)
    **Reference:** `src/sdlc/style-guides/markdown.md`

    **Issue:** The guide states the rule as:

    ```markdown
    ### Do

        Indented sample.

    ### Don't
    ```

    and a reviewer may quote a whole finding heading to discuss it:

    ```markdown
    ### B9 — Phantom finding **(BLOCKING)** — aie (1/1 aie)
    ## Tier 2 — Advisory
    ```

    which is prose, not structure.

    **Remediation:**
    - [x] Track fenced state while scanning. *(Recommended.)*
    - [ ] Other: ________________________________________________

    **Touched commit:** `abc1234`
    """
)


def test_parse_review_document_should_keep_a_fenced_heading_in_the_issue_text(
    tmp_path,
):
    """Test a `###` line inside a fence stays issue text instead of aborting.

    Given:
        A blocking finding whose Issue quotes a fenced Markdown sample
        containing `### Do` and an indented line.
    When:
        parse_review_document is called.
    Then:
        It should return the finding rather than raising, with the fenced
        sample preserved verbatim including its indentation.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(_review_document(blocking=_FENCED_FINDING))

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    assert [f.id for f in result.findings] == ["B1"]
    issue = result.findings[0].issue
    assert "### Do" in issue
    assert "### Don't" in issue
    assert "    Indented sample." in issue


def test_parse_review_document_should_ignore_a_finding_heading_inside_a_fence(
    tmp_path,
):
    """Test a quoted finding heading does not become a second finding.

    Given:
        A blocking finding whose Issue quotes `### B9 — … **(BLOCKING)**`
        inside a fenced block.
    When:
        parse_review_document is called.
    Then:
        Only the real finding should be returned, and the quoted heading
        should survive as issue text.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(_review_document(blocking=_FENCED_FINDING))

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    assert [f.id for f in result.findings] == ["B1"]
    assert "B9 — Phantom finding" in result.findings[0].issue


def test_parse_review_document_should_ignore_a_tier_heading_inside_a_fence(
    tmp_path,
):
    """Test a fenced tier heading does not end the findings region.

    Given:
        A blocking finding quoting `## Tier 2 — Advisory` inside a fence, and
        a real advisory finding under the real Tier 2 heading below it.
    When:
        parse_review_document is called.
    Then:
        The advisory finding should still be parsed, and be tiered advisory.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(
        _review_document(blocking=_FENCED_FINDING, advisory=_ADVISORY_FINDING)
    )

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    assert [f.id for f in result.findings] == ["B1", "A1"]
    assert result.findings[1].severity == "advisory"


_FENCED_FIELD_FINDING = textwrap.dedent(
    """\
    ### B1 — Quote the template **(BLOCKING)** — aie (1/1 aie)
    **Reference:** `src/sdlc/pr_state.py:331`

    **Issue:** A template-conformant finding carries its fields like this:

    ```markdown
    **Reference:** `made/up.py:999`
    **Touched commit:** `deadbee`
    ```

    which is a sample, not this finding's own attribution.

    **Remediation:**
    - [x] Make the extractor fence-aware. *(Recommended.)*
    - [ ] Other: ________________________________________________

    **Touched commit:** `abc1234`
    """
)


def test_parse_review_document_should_ignore_a_reference_inside_a_fence(
    tmp_path,
):
    """Test a fenced `**Reference:**` sample does not become the reference.

    Given:
        A blocking finding that quotes a fenced template sample carrying its
        own `**Reference:**` line ABOVE the finding's real Reference, so the
        template's usual ordering cannot be what protects the parse.
    When:
        parse_review_document is called.
    Then:
        The finding's reference should be the real one outside the fence, so
        the in-place re-review cannot write a fabricated citation back into
        the document.
    """
    # Arrange
    leading_fence = textwrap.dedent(
        """\
        ### B1 — Quote the template first **(BLOCKING)** — aie (1/1 aie)

        A finding may quote the shape before stating its own:

        ```markdown
        **Reference:** `made/up.py:999`
        ```

        **Reference:** `src/sdlc/pr_state.py:331`

        **Issue:** The extractor took the leftmost match.

        **Remediation:**
        - [x] Make the extractor fence-aware. *(Recommended.)*
        - [ ] Other: ________________________________________________

        **Touched commit:** `abc1234`
        """
    )
    path = tmp_path / "review-1.md"
    path.write_text(_review_document(blocking=leading_fence))

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    assert result.findings[0].reference == "`src/sdlc/pr_state.py:331`"


def test_parse_review_document_should_ignore_a_touched_commit_inside_a_fence(
    tmp_path,
):
    """Test a fenced `**Touched commit:**` sample does not become the sha.

    Given:
        A blocking finding whose Issue quotes a fenced template sample
        carrying its own `**Touched commit:**` line above the real trailing
        one.
    When:
        parse_review_document is called.
    Then:
        The finding's touched commit should be the real trailing sha, since
        the value drives `git commit --fixup` through the fixup mapping.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(_review_document(blocking=_FENCED_FIELD_FINDING))

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    assert result.findings[0].touched_commit == "`abc1234`"


def test_parse_review_document_should_raise_when_a_fence_is_never_closed(
    tmp_path,
):
    """Test an unbalanced fence is reported instead of swallowing findings.

    Given:
        A two-finding document whose first finding quotes a fenced block that
        is never closed, so every later line reads as fenced.
    When:
        parse_review_document is called.
    Then:
        It should raise, naming the line the fence was opened on, rather than
        returning a short enumeration the in-place rewrite would then delete
        the missing findings from.
    """
    # Arrange
    unclosed = _BLOCKING_FINDING.replace(
        "**Issue:** The symbol `foo` should be `bar` because the convention "
        "says so.",
        "**Issue:** Consider:\n\n```python\ndef f():\n    pass\n",
    )
    path = tmp_path / "review-1.md"
    path.write_text(
        _review_document(blocking=unclosed, advisory=_ADVISORY_FINDING)
    )

    # Act & assert
    with pytest.raises(ValueError, match="unclosed code fence opened at line"):
        parse_review_document(path, issue_number=42, iteration=1)


def test_parse_review_document_should_keep_an_em_dash_inside_a_blocking_title(
    tmp_path,
):
    """Test a blocking title containing an em dash is not truncated.

    Given:
        A blocking heading whose title itself contains ` — ` ahead of the
        `**(BLOCKING)**` marker and the role attribution.
    When:
        parse_review_document is called.
    Then:
        The whole title should survive and the attribution should be dropped.
    """
    # Arrange
    heading = (
        "### B1 — Empty patch claim is false — the usual case "
        "**(BLOCKING)** — aie (1/5 aie)"
    )
    blocking = _BLOCKING_FINDING.replace(
        "### B1 — Rename foo to bar **(BLOCKING)** — aie (3/10 aie)", heading
    )
    path = tmp_path / "review-1.md"
    path.write_text(_review_document(blocking=blocking))

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    assert result.findings[0].title == (
        "Empty patch claim is false — the usual case"
    )



def test_render_outline_should_keep_the_enumeration_and_drop_the_bodies(tmp_path):
    """Test the outline carries every finding but none of their prose.

    Given:
        A review document with a finding in each severity tier.
    When:
        render_outline is called.
    Then:
        It should keep every heading and single-line labelled field and drop
        every Issue paragraph and remediation checkbox, so the finding-set
        enumeration survives while the bulk does not.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(
        _review_document(
            blocking=_BLOCKING_FINDING,
            advisory=_ADVISORY_FINDING,
            incidental=_INCIDENTAL_FINDING,
        )
    )

    # Act
    outline = render_outline(path)

    # Assert
    for heading in ("### B1 —", "### A1 —", "### I1 —"):
        assert heading in outline, heading
    assert outline.count("**Reference:**") == 3
    assert outline.count("**Touched commit:**") == 3
    assert "**Issue:**" not in outline
    assert "- [x]" not in outline
    assert "The symbol `foo` should be `bar`" not in outline


def test_render_outline_should_mark_each_elided_body_once(tmp_path):
    """Test a removed body leaves a visible, countable gap.

    Given:
        Three findings whose bodies are elided.
    When:
        render_outline is called.
    Then:
        It should emit exactly one marker per finding, naming the fetch. A
        silent gap is what would let a consumer work from the outline and
        invent a body it never read.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(
        _review_document(
            blocking=_BLOCKING_FINDING,
            advisory=_ADVISORY_FINDING,
            incidental=_INCIDENTAL_FINDING,
        )
    )

    # Act
    outline = render_outline(path)

    # Assert
    assert outline.count("sdlc_review_findings") == 3


def test_render_outline_should_pass_the_non_finding_sections_through(tmp_path):
    """Test the ledgers and cross-cutting decisions survive verbatim.

    Given:
        A document whose header and trailing sections carry the state a
        re-review must preserve across an in-place rewrite.
    When:
        render_outline is called.
    Then:
        Those regions should appear byte-for-byte, since the outline exists
        partly to stop a consumer having to read them back from disk.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    document = _review_document(blocking=_BLOCKING_FINDING)
    path.write_text(document)
    header = document.split("## Tier 1")[0]

    # Act
    outline = render_outline(path)

    # Assert
    assert outline.startswith(header)
    assert "## Cross-cutting decisions" in outline
    assert "## Tier 1 — Blocking" in outline
    assert "## Tier 2 — Advisory" in outline


def test_render_outline_should_round_trip_as_a_review_document(tmp_path):
    """Test the outline is itself parseable, with the same enumeration.

    Given:
        A review document with three findings.
    When:
        The outline is parsed as a review document in its own right.
    Then:
        It should yield the same ids, severities, references and titles with
        empty issues AND empty remediations — the property every consumer of
        the outline depends on, since a lost id is a finding deleted with no
        disposition, and a marker captured as issue text is a body a consumer
        can mistake for one it has read.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(
        _review_document(
            blocking=_BLOCKING_FINDING,
            advisory=_ADVISORY_FINDING,
            incidental=_INCIDENTAL_FINDING,
        )
    )
    outline_path = tmp_path / "outline.md"
    outline_path.write_text(render_outline(path))

    # Act
    original = parse_review_document(path, issue_number=42, iteration=1)
    echoed = parse_review_document(outline_path, issue_number=42, iteration=1)

    # Assert
    fields = lambda r: [
        (f.id, f.severity, f.reference, f.title, f.touched_commit) for f in r.findings
    ]
    assert fields(echoed) == fields(original)
    assert all(not f.remediation.strip() for f in echoed.findings)
    assert all(not f.issue.strip() for f in echoed.findings)


def test_render_outline_should_mark_an_elided_body_that_is_entirely_fenced(tmp_path):
    """Test a body with nothing outside a fence still announces its elision.

    Given:
        A finding whose whole body is a fenced sample, with no unfenced prose
        and no remediation checklist to stand in for one.
    When:
        The outline is rendered.
    Then:
        It should still carry exactly one marker for that finding. The marker
        is the mechanism: a body dropped without one reads as a finding that
        simply has no body, so nothing tells a consumer to fetch it.
    """
    # Arrange
    fenced = (
        "### A1 — a fenced-only body — reviewer (1/1)\n"
        "**Reference:** `b.py:2`\n"
        "\n"
        "```python\n"
        'offending = "code"\n'
        "```\n"
        "\n"
        "**Touched commit:** `def5678`\n"
    )
    path = tmp_path / "review-1.md"
    path.write_text(_review_document(blocking=_BLOCKING_FINDING, advisory=fenced))

    # Act
    outline = render_outline(path)

    # Assert
    parsed = parse_review_document(path, issue_number=42, iteration=1)
    assert outline.count("body elided") == len(parsed.findings)
    assert 'offending = "code"' not in outline


def test_parse_review_document_should_keep_a_body_opening_with_a_bold_span(tmp_path):
    """Test prose that begins in bold is not mistaken for a field label.

    Given:
        A finding whose body opens with `**Criterion #15**` and continues in
        a later paragraph opening `**(a) …**` — ordinary emphasis, not a
        labelled field.
    When:
        The document is parsed.
    Then:
        The whole body should survive. Terminating on any bold-leading line
        drops evidence out of the body that the mandatory fetch serves, and
        it does so silently.
    """
    # Arrange
    bold = (
        "### A1 — a body that opens in bold — reviewer (1/1)\n"
        "**Reference:** `b.py:2`\n"
        "\n"
        "**Criterion #15** says the non-repository case writes a null base.\n"
        "\n"
        "**(a) The third door.** The gate names two dispositions, not three.\n"
        "\n"
        "- [x] Emit `null` for the absent fields.\n"
        "\n"
        "**Touched commit:** `def5678`\n"
    )
    path = tmp_path / "review-1.md"
    path.write_text(_review_document(blocking=_BLOCKING_FINDING, advisory=bold))

    # Act
    parsed = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    issue = next(f.issue for f in parsed.findings if f.id == "A1")
    assert "Criterion #15" in issue
    assert "The third door" in issue


def test_render_outline_should_ignore_a_finding_heading_inside_a_fence(tmp_path):
    """Test a quoted heading is not treated as a finding to elide.

    Given:
        A finding whose Issue text quotes a heading in a fenced block — which
        this project's own review documents routinely do, since the artifacts
        under review are review documents.
    When:
        render_outline is called.
    Then:
        It should elide the whole body including the fence, and emit one
        marker rather than treating the quoted heading as a second finding.
    """
    # Arrange
    finding = textwrap.dedent(
        """\
        ### B1 — Quoting a heading **(BLOCKING)** — aie (1/10 aie)
        **Reference:** `src/sdlc/server.py:64`

        **Issue:** The document renders this:

        ```
        ### B9 — A quoted finding **(BLOCKING)** — aie
        **Reference:** `nowhere.py:1`
        ```

        **Remediation:**
        - [x] Fence it. *(Recommended — the parser skips fenced headings.)*
        - [ ] Other: ________________________________________________

        **Touched commit:** `abc1234`
        """
    )
    path = tmp_path / "review-1.md"
    path.write_text(_review_document(blocking=finding))

    # Act
    outline = render_outline(path)

    # Assert
    assert outline.count("sdlc_review_findings") == 1
    assert "### B9" not in outline
    assert "`nowhere.py:1`" not in outline
    assert outline.count("**Reference:**") == 1


def _reviews_document(tmp_path, body):
    """Write a review document at the containment-approved location."""
    directory = tmp_path / ".sdlc" / "reviews" / "issue-#42"
    directory.mkdir(parents=True)
    path = directory / "review-1.md"
    path.write_text(body)
    return path


def test_render_findings_should_return_only_the_requested_bodies(
    tmp_path, monkeypatch
):
    """Test a fetch serves the named findings and nothing else.

    Given:
        A document with three findings and a request for one of them.
    When:
        render_findings is called with that id.
    Then:
        It should return that finding's full body and omit the others, so a
        consumer pays only for what it asked for.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    path = _reviews_document(
        tmp_path,
        _review_document(
            blocking=_BLOCKING_FINDING,
            advisory=_ADVISORY_FINDING,
            incidental=_INCIDENTAL_FINDING,
        ),
    )

    # Act
    result = render_findings(path, ["A1"])

    # Assert
    assert "A1" in result
    assert "readability nit" in result
    assert "Group stdlib imports first." in result
    assert "B1" not in result
    assert "I1" not in result


def test_render_findings_should_order_the_result_by_severity(tmp_path, monkeypatch):
    """Test a batch fetch comes back in the order a consumer spends attention.

    Given:
        A request naming an incidental finding before a blocking one.
    When:
        render_findings is called.
    Then:
        The blocking finding should come first, matching the order the
        seeded block and the implement walk both use.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    path = _reviews_document(
        tmp_path,
        _review_document(
            blocking=_BLOCKING_FINDING,
            advisory=_ADVISORY_FINDING,
            incidental=_INCIDENTAL_FINDING,
        ),
    )

    # Act
    result = render_findings(path, ["I1", "A1", "B1"])

    # Assert
    assert result.index("B1") < result.index("A1") < result.index("I1")


def test_render_findings_should_name_an_id_it_could_not_find(tmp_path, monkeypatch):
    """Test an unknown id is reported rather than silently dropped.

    Given:
        A request naming a finding that is not in the document.
    When:
        render_findings is called.
    Then:
        It should name the missing id in the result. Silently returning a
        short answer is how a consumer ends up dispositioning a finding it
        was never shown.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    path = _reviews_document(tmp_path, _review_document(blocking=_BLOCKING_FINDING))

    # Act
    result = render_findings(path, ["B1", "B9"])

    # Assert
    assert "B9" in result
    assert "not found" in result.lower()


def test_render_findings_should_refuse_a_path_outside_the_reviews_directory(
    tmp_path, monkeypatch
):
    """Test the fetch cannot be pointed at an arbitrary file.

    Given:
        A path outside `.sdlc/reviews/`, which is where every review
        document lives.
    When:
        render_findings is called with it.
    Then:
        It should raise, naming the path. The argument reaches the
        filesystem and arrives from a prompt, so the location is checked
        rather than assumed.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    outside = tmp_path / "secrets.md"
    outside.write_text(_review_document(blocking=_BLOCKING_FINDING))

    # Act & assert
    with pytest.raises(ValueError, match="secrets.md"):
        render_findings(outside, ["B1"])


def test_render_findings_should_match_the_full_render_for_the_same_finding(
    tmp_path, monkeypatch
):
    """Test a fetched body is the body the full render would have carried.

    Given:
        The same document rendered in full and fetched one finding at a
        time.
    When:
        Both renderings of a finding are compared.
    Then:
        The fetched text should carry the same issue and remediation, so
        disclosure changes when a consumer reads a body and never what it
        reads.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    path = _reviews_document(
        tmp_path, _review_document(blocking=_BLOCKING_FINDING, advisory=_ADVISORY_FINDING)
    )
    parsed = parse_review_document(path, issue_number=42, iteration=1)
    expected = next(f for f in parsed.findings if f.id == "B1")

    # Act
    result = render_findings(path, ["B1"])

    # Assert
    assert expected.issue in result
    for line in expected.remediation.splitlines():
        assert line in result


def test_the_bundled_template_should_head_cross_cutting_sections_with_a_pass(
    tmp_path,
):
    """Test a document built from the shipped template can be elided.

    Given:
        The template is appended verbatim to every review prompt and the
        skill tells the consolidator to follow it exactly, so its heading is
        the one an agent copies.
    When:
        A two-pass document is built using that heading and rendered.
    Then:
        The superseded section's body should go and the operative one should
        stay. An unnumbered heading matches nothing, so no section is ever
        elided and they accumulate for the life of the chain — while three
        documents claim the opposite.
    """
    # Arrange
    template = (REVIEW_TEMPLATE_PATH).read_text()
    heading = next(
        line
        for line in template.splitlines()
        if line.startswith("## ") and "cross-cutting" in line.lower()
    )
    path = tmp_path / "review-1.md"
    document = _review_document(blocking=_BLOCKING_FINDING).replace(
        "# PR #42 — Round 1 Review\n",
        "# PR #42 — Round 1 Review\n\n**Pass 2** — 1 blocking, 0 advisory, 0 incidental open.\n",
        1,
    )
    path.write_text(
        document
        + f"\n{heading.replace('<k>', '1')}\n\nSuperseded reasoning.\n"
        + f"\n{heading.replace('<k>', '2')}\n\nOperative reasoning.\n"
    )

    # Act
    outline = render_outline(path)

    # Assert
    assert "Superseded reasoning." not in outline
    assert "Operative reasoning." in outline


def test_render_outline_should_elide_a_superseded_cross_cutting_section(tmp_path):
    """Test a past pass's decisions do not ride along on every later pass.

    Given:
        A pass-4 document carrying its own cross-cutting section and those
        of passes 2 and 3, which accumulate and roughly double each round.
    When:
        render_outline is called.
    Then:
        It should keep the current pass's section and elide the earlier
        numbered ones, naming the document to read them in. Only the
        current pass's decisions are operative; the rest are history.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(
        _review_document(blocking=_BLOCKING_FINDING).replace(
            "## Cross-cutting decisions\n\nNone.",
            "## Cross-cutting decisions\n\nThe original theme.\n\n"
            "## Pass 2 — cross-cutting decisions\n\nSuperseded theme two.\n\n"
            "## Pass 3 — cross-cutting decisions\n\nSuperseded theme three.\n\n"
            "## Pass 4 — cross-cutting decisions\n\nThe operative theme.",
        ).replace("# PR #42 — Round 1 Review", "# PR #42 — Round 1 Review\n\n**Pass 4** — 1 blocking open."),
    )

    # Act
    outline = render_outline(path)

    # Assert
    assert "The operative theme." in outline
    assert "Superseded theme two." not in outline
    assert "Superseded theme three." not in outline
    # The headings stay, so the elision is visible and the history findable.
    assert "## Pass 2 — cross-cutting decisions" in outline
    assert "## Pass 3 — cross-cutting decisions" in outline
    assert outline.count("superseded") >= 2


def test_render_outline_should_keep_an_unnumbered_cross_cutting_section(tmp_path):
    """Test only a section that names an earlier pass is treated as history.

    Given:
        A document whose cross-cutting section carries no pass number, so
        nothing establishes that a later pass superseded it.
    When:
        render_outline is called.
    Then:
        It should keep the section. Eliding by position would drop an
        operative section on any document that orders them differently.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(
        _review_document(blocking=_BLOCKING_FINDING).replace(
            "None.", "A theme with no pass number."
        )
    )

    # Act
    outline = render_outline(path)

    # Assert
    assert "A theme with no pass number." in outline


def test_iterations_should_be_empty_when_no_review_dir(tmp_path, monkeypatch):
    """Test the iteration helper returns nothing when no review dir exists.

    Given:
        A working directory with no .sdlc/reviews/issue-#7 directory.
    When:
        load_review_findings(7) is called.
    Then:
        It should raise ValueError naming the missing directory.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act & assert
    with pytest.raises(ValueError, match="does not exist"):
        pr_state.load_review_findings(7)


def test_load_review_findings_should_load_the_latest_iteration(tmp_path, monkeypatch):
    """Test load_review_findings loads the highest iteration when none is given.

    Given:
        Issue 7 has review-1.md and review-2.md, the latter naming finding B2.
    When:
        load_review_findings(7) is called with no explicit iteration.
    Then:
        It should load review-2.md (the latest) and report iteration 2.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "issue-#7"
    directory.mkdir(parents=True)
    (directory / "review-1.md").write_text(_review_document(blocking=_BLOCKING_FINDING))
    second = _BLOCKING_FINDING.replace("### B1", "### B2")
    (directory / "review-2.md").write_text(_review_document(blocking=second))

    # Act
    result = pr_state.load_review_findings(7)

    # Assert
    assert result.iteration == 2
    assert result.findings[0].id == "B2"


def test_load_review_findings_should_load_an_explicit_iteration(tmp_path, monkeypatch):
    """Test load_review_findings loads the exact iteration requested.

    Given:
        Issue 7 has review-1.md and review-2.md.
    When:
        load_review_findings(7, iteration=1) is called.
    Then:
        It should load review-1.md regardless of the later iteration.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "issue-#7"
    directory.mkdir(parents=True)
    (directory / "review-1.md").write_text(_review_document(blocking=_BLOCKING_FINDING))
    second = _BLOCKING_FINDING.replace("### B1", "### B2")
    (directory / "review-2.md").write_text(_review_document(blocking=second))

    # Act
    result = pr_state.load_review_findings(7, iteration=1)

    # Assert
    assert result.iteration == 1
    assert result.findings[0].id == "B1"


def test_load_review_findings_should_raise_when_explicit_iteration_missing(
    tmp_path, monkeypatch
):
    """Test load_review_findings raises when the requested iteration is absent.

    Given:
        Issue 7 has only review-1.md.
    When:
        load_review_findings(7, iteration=5) is called.
    Then:
        It should raise ValueError naming the missing iteration.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "issue-#7"
    directory.mkdir(parents=True)
    (directory / "review-1.md").write_text(_review_document(blocking=_BLOCKING_FINDING))

    # Act & assert
    with pytest.raises(ValueError, match="iteration 5 not found"):
        pr_state.load_review_findings(7, iteration=5)


def test_load_review_findings_should_raise_when_dir_has_no_reviews(
    tmp_path, monkeypatch
):
    """Test load_review_findings raises when the dir holds no review files.

    Given:
        Issue 7's review directory exists but contains no review-<n>.md file.
    When:
        load_review_findings(7) is called.
    Then:
        It should raise ValueError noting the directory has no review document.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "issue-#7"
    directory.mkdir(parents=True)
    (directory / "notes.txt").write_text("not a review")

    # Act & assert
    with pytest.raises(ValueError, match="no review-<iteration>.md"):
        pr_state.load_review_findings(7)


def test_load_review_findings_should_load_from_an_explicit_directory(
    tmp_path, monkeypatch
):
    """Test load_review_findings reads from an explicit directory when given.

    Given:
        A slug directory `.sdlc/reviews/server/` holding review-1.md, with no
        issue-#7 directory present.
    When:
        load_review_findings(7, directory=<slug dir>) is called.
    Then:
        It should load review-1.md from the explicit directory and carry that
        directory's path in the result.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "server"
    directory.mkdir(parents=True)
    (directory / "review-1.md").write_text(_review_document(blocking=_BLOCKING_FINDING))

    # Act
    result = pr_state.load_review_findings(7, directory=directory)

    # Assert
    assert result.findings[0].id == "B1"
    assert result.path == str(directory / "review-1.md")


def test_load_review_findings_should_load_an_explicit_iteration_from_directory(
    tmp_path, monkeypatch
):
    """Test load_review_findings reads an explicit iteration from a directory.

    Given:
        A slug directory holding review-1.md and review-2.md.
    When:
        load_review_findings(7, iteration=1, directory=<slug dir>) is called.
    Then:
        It should load review-1.md from the explicit directory regardless of
        the later iteration.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "server"
    directory.mkdir(parents=True)
    (directory / "review-1.md").write_text(_review_document(blocking=_BLOCKING_FINDING))
    second = _BLOCKING_FINDING.replace("### B1", "### B2")
    (directory / "review-2.md").write_text(_review_document(blocking=second))

    # Act
    result = pr_state.load_review_findings(7, iteration=1, directory=directory)

    # Assert
    assert result.iteration == 1
    assert result.findings[0].id == "B1"


def test_load_review_findings_should_load_latest_from_directory(
    tmp_path, monkeypatch
):
    """Test load_review_findings reads the latest iteration from a directory.

    Given:
        A slug directory holding review-1.md and review-2.md, the latter naming
        finding B2.
    When:
        load_review_findings(7, directory=<slug dir>) is called with no explicit
        iteration.
    Then:
        It should load review-2.md (the latest) and report iteration 2.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "server"
    directory.mkdir(parents=True)
    (directory / "review-1.md").write_text(_review_document(blocking=_BLOCKING_FINDING))
    second = _BLOCKING_FINDING.replace("### B1", "### B2")
    (directory / "review-2.md").write_text(_review_document(blocking=second))

    # Act
    result = pr_state.load_review_findings(7, directory=directory)

    # Assert
    assert result.iteration == 2
    assert result.findings[0].id == "B2"


def test_load_review_findings_should_raise_when_directory_missing(
    tmp_path, monkeypatch
):
    """Test load_review_findings raises when the explicit directory is absent.

    Given:
        A slug directory that does not exist on disk.
    When:
        load_review_findings(7, directory=<missing dir>) is called.
    Then:
        It should raise ValueError naming the missing directory.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "server"

    # Act & assert
    with pytest.raises(ValueError, match="server"):
        pr_state.load_review_findings(7, directory=directory)


def test_load_review_findings_should_raise_when_iteration_missing_in_directory(
    tmp_path, monkeypatch
):
    """Test load_review_findings raises when an iteration is absent in the dir.

    Given:
        A slug directory holding only review-1.md.
    When:
        load_review_findings(7, iteration=5, directory=<slug dir>) is called.
    Then:
        It should raise ValueError naming the missing iteration.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "server"
    directory.mkdir(parents=True)
    (directory / "review-1.md").write_text(_review_document(blocking=_BLOCKING_FINDING))

    # Act & assert
    with pytest.raises(ValueError, match="iteration 5 not found"):
        pr_state.load_review_findings(7, iteration=5, directory=directory)


def test_convert_pr_review_to_document_should_write_and_round_trip(
    tmp_path, monkeypatch
):
    """Test convert_pr_review_to_document writes a doc and parses it back.

    Given:
        A GitHub PR URL whose review feedback resolves to one thread and one
        review-body comment, and whose closing issue is 7.
    When:
        convert_pr_review_to_document is called.
    Then:
        It should write review-1.md under issue-#7 and return ReviewFindings
        carrying both converted findings.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    threads = [
        {
            "isResolved": False,
            "comments": {"nodes": [{
                "body": "rename foo to bar",
                "path": "src/sdlc/server.py",
                "line": 64,
                "author": {"login": "alice"},
            }]},
        },
    ]
    reviews = [{"author": {"login": "bob"}, "body": "Fix the doc gap."}]
    responses = {
        _closing_graphql_args("conradbzura", "sdlc", 42): _closing_payload([7]),
        _graphql_args("conradbzura", "sdlc", 42): _graphql_payload(threads),
        ("pr", "view", "42", "--json", "reviews"): _reviews_payload(reviews),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))
    repo = pr_state.Repo(owner="conradbzura", name="sdlc", repo_flag=None)

    # Act
    result = pr_state.convert_pr_review_to_document(
        "https://github.com/conradbzura/sdlc/pull/42", repo=repo
    )

    # Assert
    written = tmp_path / ".sdlc" / "reviews" / "issue-#7" / "review-1.md"
    assert written.is_file()
    assert result.issue_number == 7
    assert result.iteration == 1
    bodies = " ".join(f.issue for f in result.findings)
    assert "rename foo to bar" in bodies
    assert "Fix the doc gap." in bodies


def test_convert_pr_review_to_document_should_carry_the_header_a_rereview_reads(
    tmp_path, monkeypatch
):
    """Test a converted document carries the three load-bearing header lines.

    Given:
        A GitHub PR URL whose review feedback converts into a local document.
    When:
        convert_pr_review_to_document is called.
    Then:
        The written document should carry a pass line, a Retired ids line and
        a Composition line naming at least one role. It is a first-class
        `review-<iteration>.md` that `sdlc_review --verify` will seed from,
        and without these three step 2 cannot read `<k>`, step 10(c) has
        nothing to bump, `max(retired ∪ open) + 1` has half its input, and the
        role inheritance falls back without saying so. Nothing raises on their
        absence, so the document would degrade silently.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    threads = [
        {
            "isResolved": False,
            "comments": {"nodes": [{
                "body": "rename foo to bar",
                "path": "src/sdlc/server.py",
                "line": 64,
                "author": {"login": "alice"},
            }]},
        },
    ]
    responses = {
        _closing_graphql_args("conradbzura", "sdlc", 42): _closing_payload([7]),
        _graphql_args("conradbzura", "sdlc", 42): _graphql_payload(threads),
        ("pr", "view", "42", "--json", "reviews"): _reviews_payload([]),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))
    repo = pr_state.Repo(owner="conradbzura", name="sdlc", repo_flag=None)

    # Act
    pr_state.convert_pr_review_to_document(
        "https://github.com/conradbzura/sdlc/pull/42", repo=repo
    )

    # Assert
    written = tmp_path / ".sdlc" / "reviews" / "issue-#7" / "review-1.md"
    document = written.read_text()
    assert "**Pass 1** — 1 blocking," in document
    assert "**Retired ids** — none." in document
    assert pr_state.parse_composition_roles(written) == ["general-purpose"]


def test_convert_pr_review_to_document_should_carry_an_empty_incidental_tier(
    tmp_path, monkeypatch
):
    """Test a converted document carries all three tier sections.

    Given:
        A GitHub PR URL whose review feedback converts into a local document.
    When:
        convert_pr_review_to_document is called.
    Then:
        The written document should carry an empty Tier 3 section, so a later
        re-review can re-tier a finding into it without hand-editing the
        document into a shape the parser has to guess at.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    reviews = [{"author": {"login": "bob"}, "body": "Fix the doc gap."}]
    responses = {
        _closing_graphql_args("conradbzura", "sdlc", 42): _closing_payload([7]),
        _graphql_args("conradbzura", "sdlc", 42): _graphql_payload([]),
        ("pr", "view", "42", "--json", "reviews"): _reviews_payload(reviews),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))
    repo = pr_state.Repo(owner="conradbzura", name="sdlc", repo_flag=None)

    # Act
    pr_state.convert_pr_review_to_document(
        "https://github.com/conradbzura/sdlc/pull/42", repo=repo
    )

    # Assert
    written = tmp_path / ".sdlc" / "reviews" / "issue-#7" / "review-1.md"
    text = written.read_text()
    assert "## Tier 2 — Advisory" in text
    assert "## Tier 3 — Incidental" in text
    assert text.index("## Tier 2 — Advisory") < text.index("## Tier 3 — Incidental")


def test_convert_pr_review_to_document_should_use_the_next_iteration(
    tmp_path, monkeypatch
):
    """Test convert_pr_review_to_document writes the next iteration, never over.

    Given:
        Issue 7 already has review-1.md, and PR 42 (closing issue 7) has
        review feedback.
    When:
        convert_pr_review_to_document is called.
    Then:
        It should write review-2.md and leave review-1.md untouched.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "issue-#7"
    directory.mkdir(parents=True)
    (directory / "review-1.md").write_text("existing round one")
    responses = {
        _closing_graphql_args("conradbzura", "sdlc", 42): _closing_payload([7]),
        _graphql_args("conradbzura", "sdlc", 42): _graphql_payload([]),
        ("pr", "view", "42", "--json", "reviews"): _reviews_payload([]),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))
    repo = pr_state.Repo(owner="conradbzura", name="sdlc", repo_flag=None)

    # Act
    result = pr_state.convert_pr_review_to_document(
        "https://github.com/conradbzura/sdlc/pull/42", repo=repo
    )

    # Assert
    assert result.iteration == 2
    assert (directory / "review-2.md").is_file()
    assert (directory / "review-1.md").read_text() == "existing round one"


def test_next_iteration_should_be_one_for_empty_issue_directory(tmp_path, monkeypatch):
    """Test _next_iteration returns 1 when the issue directory has no rounds.

    Given:
        A working directory with no .sdlc/reviews/issue-#7 directory.
    When:
        _next_iteration(7) is called.
    Then:
        It should return 1 — the first, unused iteration.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act
    result = pr_state._next_iteration(7)

    # Assert
    assert result == 1


def test_next_iteration_should_follow_the_highest_issue_round(tmp_path, monkeypatch):
    """Test _next_iteration returns max + 1 over an issue directory's rounds.

    Given:
        Issue 7 already has review-1.md and review-2.md.
    When:
        _next_iteration(7) is called.
    Then:
        It should return 3 — one past the highest existing round.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "issue-#7"
    directory.mkdir(parents=True)
    (directory / "review-1.md").write_text("round one")
    (directory / "review-2.md").write_text("round two")

    # Act
    result = pr_state._next_iteration(7)

    # Assert
    assert result == 3


def test_next_iteration_should_be_one_for_empty_explicit_directory(
    tmp_path, monkeypatch
):
    """Test _next_iteration returns 1 for an empty explicit slug directory.

    Given:
        An explicit slug directory that does not yet exist.
    When:
        _next_iteration(0, directory=<slug dir>) is called.
    Then:
        It should return 1 — the first, unused iteration for that directory.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "server"

    # Act
    result = pr_state._next_iteration(0, directory=directory)

    # Assert
    assert result == 1


def test_next_iteration_should_follow_the_highest_explicit_directory_round(
    tmp_path, monkeypatch
):
    """Test _next_iteration returns max + 1 over an explicit slug directory.

    Given:
        A slug directory that already holds review-1.md and review-2.md.
    When:
        _next_iteration(0, directory=<slug dir>) is called.
    Then:
        It should return 3, scanning the explicit directory rather than the
        issue-keyed location for issue 0.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "server"
    directory.mkdir(parents=True)
    (directory / "review-1.md").write_text("round one")
    (directory / "review-2.md").write_text("round two")

    # Act
    result = pr_state._next_iteration(0, directory=directory)

    # Assert
    assert result == 3


def test_convert_pr_review_to_document_should_raise_for_non_pr_url(monkeypatch):
    """Test convert_pr_review_to_document rejects a non-PR-URL argument.

    Given:
        A string that is not a GitHub PR URL.
    When:
        convert_pr_review_to_document is called with it.
    Then:
        It should raise ValueError without touching gh.
    """
    # Arrange
    repo = pr_state.Repo(owner="conradbzura", name="sdlc", repo_flag=None)

    # Act & assert
    with pytest.raises(ValueError, match="not a GitHub PR URL"):
        pr_state.convert_pr_review_to_document("not-a-url", repo=repo)


def test_convert_pr_review_to_document_should_not_leak_separators(
    tmp_path, monkeypatch
):
    """Test the converted document's remediation excludes the tier separator.

    Given:
        A PR with two review-thread findings whose rendered document separates
        each finding block with a horizontal rule.
    When:
        convert_pr_review_to_document parses the document back.
    Then:
        No finding's remediation should capture the trailing --- separator.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    threads = [
        {
            "isResolved": False,
            "comments": {"nodes": [{
                "body": "first comment",
                "path": "a.py",
                "line": 1,
                "author": {"login": "alice"},
            }]},
        },
        {
            "isResolved": False,
            "comments": {"nodes": [{
                "body": "second comment",
                "path": "b.py",
                "line": 2,
                "author": {"login": "bob"},
            }]},
        },
    ]
    responses = {
        _closing_graphql_args("conradbzura", "sdlc", 42): _closing_payload([7]),
        _graphql_args("conradbzura", "sdlc", 42): _graphql_payload(threads),
        ("pr", "view", "42", "--json", "reviews"): _reviews_payload([]),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))
    repo = pr_state.Repo(owner="conradbzura", name="sdlc", repo_flag=None)

    # Act
    result = pr_state.convert_pr_review_to_document(
        "https://github.com/conradbzura/sdlc/pull/42", repo=repo
    )

    # Assert
    assert len(result.findings) == 2
    for finding in result.findings:
        assert "---" not in finding.remediation


def test_convert_pr_review_to_document_should_round_trip_a_fenced_heading(
    tmp_path, monkeypatch
):
    """Test a reviewer comment quoting a Markdown heading still converts.

    Given:
        A GitHub review comment whose body quotes a fenced block containing
        `### Do`, which is ordinary prose in a style-guide discussion.
    When:
        convert_pr_review_to_document is called.
    Then:
        It should return the converted findings rather than raising on its own
        read-back, since the document has already been written to disk by then
        and a retry would only advance the iteration and fail again.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    threads = [
        {
            "isResolved": False,
            "comments": {"nodes": [{
                "body": "The guide says:\n\n```markdown\n### Do\n```\n\nFollow it.",
                "path": "src/sdlc/server.py",
                "line": 64,
                "author": {"login": "alice"},
            }]},
        },
    ]
    responses = {
        _closing_graphql_args("conradbzura", "sdlc", 42): _closing_payload([7]),
        _graphql_args("conradbzura", "sdlc", 42): _graphql_payload(threads),
        ("pr", "view", "42", "--json", "reviews"): _reviews_payload([]),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))
    repo = pr_state.Repo(owner="conradbzura", name="sdlc", repo_flag=None)

    # Act
    result = pr_state.convert_pr_review_to_document(
        "https://github.com/conradbzura/sdlc/pull/42", repo=repo
    )

    # Assert
    assert len(result.findings) == 1
    assert "### Do" in result.findings[0].issue


def test_parse_composition_roles_should_ignore_a_finding_that_quotes_the_literal(
    tmp_path,
):
    """Test a finding body quoting `role(s)` cannot shadow the header.

    Given:
        A review document whose header line is malformed, followed by a
        finding whose prose quotes the literal `role(s)` with a backticked
        stem — the shape any review discussing this contract produces.
    When:
        parse_composition_roles is called on it.
    Then:
        It should return an empty list rather than the quoted stem, so the
        caller emits its coverage warning instead of dispatching a role the
        round never ran.
    """
    # Arrange
    document = tmp_path / "review-1.md"
    document.write_text(
        "# PR #1 — Round 1 Review\n\n"
        "Composition: 5 reviewer(s) per role across roles `aie`.\n\n"
        "## Tier 1 — Blocking\n\n"
        "### B1 — The contract **(BLOCKING)** — aie (1/1 aie)\n"
        "**Reference:** `src/sdlc/AGENTS.md:1`\n\n"
        "**Issue:** The stems are read after the literal role(s) `wrong-role` "
        "up to the first parenthesis.\n"
    )

    # Act
    result = pr_state.parse_composition_roles(document)

    # Assert
    assert result == []


def test_parse_composition_roles_should_return_empty_when_the_line_ends_at_the_literal(
    tmp_path,
):
    """Test a Composition line truncated at `role(s)` names nothing.

    Given:
        A review document whose Composition line ends exactly at the literal
        `role(s)`, with no stems after it.
    When:
        parse_composition_roles is called on it.
    Then:
        It should return an empty list, which the caller reports as a
        coverage warning rather than inheriting a role.
    """
    # Arrange
    document = tmp_path / "review-1.md"
    document.write_text(
        "# PR #1 — Round 1 Review\n\n"
        "Composition: 1 reviewer(s) per role across role(s)\n"
    )

    # Act
    result = pr_state.parse_composition_roles(document)

    # Assert
    assert result == []


def test_convert_pr_review_to_document_should_round_trip_an_unfenced_heading(
    tmp_path, monkeypatch
):
    """Test a reviewer comment containing a bare Markdown heading converts.

    Given:
        A GitHub review comment whose body contains an unfenced `### Do` line
        and a line shaped like a finding heading — ordinary prose in a
        style-guide discussion, and text this package did not write.
    When:
        convert_pr_review_to_document is called.
    Then:
        It should return exactly the converted finding, neither raising on its
        own read-back nor admitting the quoted heading as a second finding.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    threads = [
        {
            "isResolved": False,
            "comments": {"nodes": [{
                "body": (
                    "The guide says:\n\n### Do\n\nUse long lines.\n\n"
                    "### C9 — Phantom **(BLOCKING)** — @bob"
                ),
                "path": "src/sdlc/server.py",
                "line": 64,
                "author": {"login": "alice"},
            }]},
        },
    ]
    responses = {
        _closing_graphql_args("conradbzura", "sdlc", 42): _closing_payload([7]),
        _graphql_args("conradbzura", "sdlc", 42): _graphql_payload(threads),
        ("pr", "view", "42", "--json", "reviews"): _reviews_payload([]),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))
    repo = pr_state.Repo(owner="conradbzura", name="sdlc", repo_flag=None)

    # Act
    result = pr_state.convert_pr_review_to_document(
        "https://github.com/conradbzura/sdlc/pull/42", repo=repo
    )

    # Assert
    assert [f.id for f in result.findings] == ["C1"]
    assert "### Do" in result.findings[0].issue
    assert "C9 — Phantom" in result.findings[0].issue


def test_parse_composition_roles_should_return_the_documented_roles(tmp_path):
    """Test the roles a round ran under are recovered from the header.

    Given:
        A review document whose Composition line names two roles.
    When:
        parse_composition_roles is called on it.
    Then:
        It should return both stems in order.
    """
    # Arrange
    document = tmp_path / "review-1.md"
    document.write_text(
        "# PR #1 — Round 1 Review\n\n"
        "Generated from a `5`-reviewer review. Composition: 5 reviewer(s) "
        "per role across role(s) `aie`, `architect` (5 × 2 = 10 reviewer "
        "subagents total). Findings are deduped.\n"
    )

    # Act
    result = pr_state.parse_composition_roles(document)

    # Assert
    assert result == ["aie", "architect"]

def test_parse_composition_roles_should_return_empty_without_the_line(tmp_path):
    """Test a document predating the Composition line yields nothing.

    Given:
        A review document with no Composition line.
    When:
        parse_composition_roles is called on it.
    Then:
        It should return an empty list rather than raising, so the caller
        can fall back instead of failing an older document.
    """
    # Arrange
    document = tmp_path / "review-1.md"
    document.write_text("# PR #1 — Round 1 Review\n\nNo composition here.\n")

    # Act
    result = pr_state.parse_composition_roles(document)

    # Assert
    assert result == []

def test_parse_composition_roles_should_return_empty_when_unbackticked(tmp_path):
    """Test a paraphrased Composition line names no roles.

    Given:
        A review document whose Composition line names its roles in prose,
        with no backticked stems for the parser to collect.
    When:
        parse_composition_roles is called on it.
    Then:
        It should return an empty list. The caller treats that as nothing
        to inherit, so this is the branch a re-review's silent fallback to
        general-purpose runs through.
    """
    # Arrange
    document = tmp_path / "review-1.md"
    document.write_text(
        "# PR #1 — Round 1 Review\n\n"
        "Composition: 3 reviewer(s) per role across role(s) aie and "
        "general-purpose, six reviewers in total.\n"
    )

    # Act
    result = pr_state.parse_composition_roles(document)

    # Assert
    assert result == []


def _titles_document(heading: str) -> str:
    return (
        "# PR #1 — Round 1 Review\n\n"
        "## Tier 2 — Advisory\n\n"
        f"### {heading}\n"
        "**Reference:** `src/a.py:1`\n\n"
        "Something is off.\n\n"
        "**Remediation:**\n"
        "- [x] Fix it. *(Recommended.)*\n"
    )


def test_parse_review_document_should_keep_an_em_dash_inside_a_title(tmp_path):
    """Test only the trailing attribution is stripped from a title.

    Given:
        An advisory finding whose own title contains a spaced em dash,
        followed by the usual role attribution.
    When:
        The document is parsed.
    Then:
        The full title should survive, since the parsed title is written
        back to the document on the next in-place re-review.
    """
    # Arrange
    document = tmp_path / "review-1.md"
    document.write_text(
        _titles_document("A1 — Empty patch claim is false — the usual case — aie (1/5)")
    )

    # Act
    result = pr_state.parse_review_document(document, 1, 1)

    # Assert
    assert result.findings[0].title == (
        "Empty patch claim is false — the usual case"
    )

def test_parse_review_document_should_raise_on_an_unparsed_heading(tmp_path):
    """Test a malformed finding heading is surfaced, not silently dropped.

    Given:
        A finding heading using a hyphen where the em dash belongs.
    When:
        The document is parsed.
    Then:
        It should raise, because a dropped finding is deleted from the
        document with no disposition on the next in-place re-review.
    """
    # Arrange
    document = tmp_path / "review-1.md"
    document.write_text(_titles_document("A1 - Hyphen where an em dash belongs"))

    # Act & assert
    with pytest.raises(ValueError, match="unparsed finding heading"):
        pr_state.parse_review_document(document, 1, 1)


def test_parse_review_document_should_refuse_a_duplicate_finding_id(tmp_path):
    """Test two findings sharing an id are refused rather than both returned.

    Given:
        Two findings under Tier 1 whose headings carry the same id.
    When:
        The document is parsed.
    Then:
        It should raise, naming the id and both line numbers. Ids are cited in
        the commit history and by `sdlc_implement --review <#>`, and a repeat
        lets one reviewer disposition remove whichever entry a `{f.id: f}`
        collapse happened to keep.
    """
    # Arrange
    second = _BLOCKING_FINDING.replace("Rename foo to bar", "Tighten the guard")
    document = tmp_path / "review-1.md"
    document.write_text(
        _review_document(blocking=f"{_BLOCKING_FINDING}\n---\n\n{second}")
    )

    # Act & assert
    with pytest.raises(ValueError, match="duplicate finding id 'B1'"):
        pr_state.parse_review_document(document, 1, 1)


def test_parse_review_document_should_report_a_heading_outside_every_tier(
    tmp_path,
):
    """Test a finding heading below the tiers is reported rather than dropped.

    Given:
        A document carrying a well-formed finding heading under a non-tier
        section, where the parser's severity is None.
    When:
        The document is parsed.
    Then:
        It should keep it out of `findings`, since it has no severity and so
        nothing to disposition, and name it on `orphaned_ids`. Silently
        skipping it is what made step 7(0) compare this parser against itself:
        the heading was absent from both sides, so the gate could never fire
        on the one failure it exists for, and an in-place re-review then
        rewrites the document without it.
    """
    # Arrange
    document = tmp_path / "review-1.md"
    document.write_text(
        _review_document(blocking=_BLOCKING_FINDING)
        + "\n### B9 — Drifted below the tiers — aie (1/3)\n"
        "**Reference:** `src/mod.py:9`\n\n**Issue:** Nobody will see this.\n"
    )

    # Act
    result = pr_state.parse_review_document(document, 1, 1)

    # Assert
    assert [f.id for f in result.findings] == ["B1"]
    assert result.orphaned_ids == ["B9"]


# --- Property-based coverage for the outline ------------------------------
#
# `render_outline` is all three cases the test guide names a MUST for property
# testing: it states invariants, it round-trips, and its input domain is
# arbitrary Markdown. Every defect this module has carried was found by
# reading rather than by a test — a body terminated on ANY line opening `**`,
# costing 6 of 36 findings on a real document; an elision marker skipped when
# a body opened with a fence; a stray tier heading that made a document's
# visible structure disagree with its parse. Fixed examples missed all three.

_ID_PREFIX = {"blocking": "B", "advisory": "A", "incidental": "I"}


@st.composite
def _review_documents(draw):
    """Draw a review document over the shapes that have actually broken it."""
    counts = {
        tier: draw(st.integers(min_value=0, max_value=3))
        for tier in ("blocking", "advisory", "incidental")
    }
    assume(sum(counts.values()) > 0)

    bodies = []
    for tier, count in counts.items():
        rendered = []
        for index in range(1, count + 1):
            finding_id = f"{_ID_PREFIX[tier]}{index}"
            # A blocking marker may appear on any tier's finding; on a
            # non-blocking tier it re-tiers the finding, which is legal and is
            # how a re-tier is recorded.
            marker = " **(BLOCKING)**" if draw(st.booleans()) else ""
            issue = draw(
                st.sampled_from(
                    [
                        "Plain prose that says what is wrong.",
                        "**Reference:** is a label, this is prose opening bold.",
                        "Quoting a sample:\n\n```markdown\n### B99 — Phantom\n```",
                        "The template heads findings like this:\n\n"
                        "````markdown\n```\n### B98 — Nested phantom\n```\n````",
                    ]
                )
            )
            commit = draw(st.sampled_from(["`abc1234`", "(no commit — omission)"]))
            # A checklist is not a contiguous run of checkboxes in practice: a
            # consolidator routinely writes a note between two options, and a
            # note routinely opens with a bold span. That shape is what a
            # `**`-prefix terminator could not tell from a field label.
            note = draw(
                st.sampled_from(
                    [
                        "",
                        "\n**Note that** this changes behaviour for callers.\n",
                        "\n*Weaker, and it is a second rule.*\n",
                        "\n**Measured:** 6 of 36 findings on a real document.\n",
                    ]
                )
            )
            # The evidence fields a gate is judged on. They are single-line
            # labels like `**Reference:**`, and they were reachable through
            # neither the outline nor the fetch until `_OUTLINE_KEEP` grew.
            evidence = draw(
                st.sampled_from(
                    [
                        "",
                        "**Corroboration:** two reviewers closed independently.\n\n",
                        "**Severity dissent:** general-purpose rated this advisory.\n\n",
                        "**Relevance dissent:** aie read this as off-issue.\n\n",
                    ]
                )
            )
            rendered.append(
                f"### {finding_id} — Title {index}{marker} — aie (1/3)\n"
                f"**Reference:** `src/mod.py:{index}`\n\n"
                f"{evidence}"
                f"**Issue:** {issue}\n\n"
                f"**Remediation:**\n- [x] Fix it.\n"
                f"{note}"
                f"- [ ] Do it the other way.\n"
                f"- [ ] Other: ____\n\n"
                f"**Touched commit:** {commit}\n"
            )
        bodies.append("\n".join(rendered))

    return _review_document(
        blocking=bodies[0],
        advisory=bodies[1],
        incidental=bodies[2] if counts["incidental"] else None,
    )


@settings(max_examples=75, deadline=None)
@given(document=_review_documents())
def test_render_outline_should_preserve_every_finding_identity(
    document, tmp_path_factory
):
    """Test the outline enumerates exactly what the document does.

    Given:
        Any review document over the shapes that have broken this parser —
        fenced bodies, nested fences, paragraphs opening with a bold span,
        blocking markers on any tier, and an absent incidental tier.
    When:
        The document is rendered as an outline and both are parsed.
    Then:
        Each finding's identity tuple should be unchanged. The outline is what
        every endpoint injects, so a finding it drops or re-tiers is a finding
        the consumer never learns exists.
    """
    # Arrange
    directory = tmp_path_factory.mktemp("outline")
    source = directory / "review-1.md"
    source.write_text(document)

    # Act
    outline = directory / "outline.md"
    outline.write_text(render_outline(source))

    # Assert
    def identity(path):
        return [
            (f.id, f.severity, f.reference, f.title, f.touched_commit)
            for f in parse_review_document(path, issue_number=1, iteration=1).findings
        ]

    assert identity(outline) == identity(source)


@settings(max_examples=75, deadline=None)
@given(document=_review_documents())
def test_render_outline_should_leave_every_body_empty(document, tmp_path_factory):
    """Test the outline holds back every body it claims to hold back.

    Given:
        Any review document over the same generated domain.
    When:
        The outline is parsed.
    Then:
        Every finding should carry an empty issue and an empty remediation. A
        body that survives is the saving silently not taken; one that survives
        PARTLY is worse, because the consumer cannot tell it is reading a
        fragment.
    """
    # Arrange
    directory = tmp_path_factory.mktemp("outline")
    source = directory / "review-1.md"
    source.write_text(document)

    # Act
    outline = directory / "outline.md"
    outline.write_text(render_outline(source))

    # Assert
    parsed = parse_review_document(outline, issue_number=1, iteration=1)
    assert parsed.findings
    for finding in parsed.findings:
        assert not finding.issue.strip(), finding.id
        assert not finding.remediation.strip(), finding.id


@settings(max_examples=50, deadline=None)
@given(
    document=_review_documents(),
    tier=st.sampled_from(
        ["## Tier 1 — Blocking", "## Tier 2 — Advisory", "## Tier 3 — Incidental"]
    ),
)
def test_parse_review_document_should_refuse_a_duplicate_tier_heading(
    document, tier, tmp_path_factory
):
    """Test a second heading for one tier is refused rather than absorbed.

    Given:
        Any review document, with one tier heading appended a second time.
    When:
        It is parsed.
    Then:
        It should raise. A stray second heading files its findings under the
        wrong tier for every human reader while this parser, which prefers the
        `**(BLOCKING)**` marker, reports them correctly — so no check that
        goes through the parser can see the divergence. A real pass shipped 6
        blocking findings under an Advisory heading this way.
    """
    # Arrange
    assume(tier in document)
    directory = tmp_path_factory.mktemp("dup")
    source = directory / "review-1.md"
    source.write_text(document + f"\n\n{tier}\n\n")

    # Act & assert
    with pytest.raises(ValueError, match="duplicate tier heading"):
        parse_review_document(source, issue_number=1, iteration=1)


@settings(max_examples=75, deadline=None)
@given(document=_review_documents())
def test_parse_review_document_should_keep_every_remediation_option(
    document, tmp_path_factory
):
    """Test no remediation loses an option, whatever precedes or follows it.

    Given:
        Any review document, whose findings carry a three-option checklist
        that may be interrupted by a note opening with a bold span.
    When:
        It is parsed.
    Then:
        Every finding should return all three options and its Other: slot, and
        none should absorb the `**Touched commit:**` label below it. The
        checklist is what a remediation is judged against and the fetch that
        serves it is mandatory, so a truncated one is evidence the consumer
        never learns is missing.
    """
    # Arrange
    directory = tmp_path_factory.mktemp("options")
    source = directory / "review-1.md"
    source.write_text(document)

    # Act
    result = parse_review_document(source, issue_number=1, iteration=1)

    # Assert
    for finding in result.findings:
        assert finding.remediation.count("- [") == 3, finding.remediation
        assert "Other:" in finding.remediation
        assert "**Touched commit:**" not in finding.remediation


@settings(max_examples=50, deadline=None)
@given(document=_review_documents())
def test_parse_review_document_should_refuse_any_repeated_id(
    document, tmp_path_factory
):
    """Test a repeated id is refused wherever in a tier the repeat falls.

    Given:
        Any review document, with its first finding heading duplicated
        immediately below itself — inside the tier, where the parser reads it
        as a finding rather than skipping it.
    When:
        It is parsed.
    Then:
        It should raise. Appending the repeat at the end of the document would
        land it after `## Cross-cutting decisions`, where no finding parses at
        all and the assertion would hold vacuously.
    """
    # Arrange
    assume(document.count("### ") >= 1)
    lines = document.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("### "))
    lines.insert(index + 1, lines[index])
    directory = tmp_path_factory.mktemp("dupid")
    source = directory / "review-1.md"
    source.write_text("\n".join(lines))

    # Act & assert
    with pytest.raises(ValueError, match="duplicate finding id"):
        parse_review_document(source, issue_number=1, iteration=1)
