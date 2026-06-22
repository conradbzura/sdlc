"""Tests for sdlc.pr_state — gh wrappers and PR-state dispatch."""

import json

import pytest

from sdlc import pr_state
from sdlc.pr_state import Finding, Findings, GhUnavailable, PrContext, resolve_repo


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


def test_dispatch_with_issue_and_no_linked_pr(monkeypatch):
    """Test dispatch returns None for a fresh issue with no linked PR.

    Given:
        Number 99 classifies as an issue and no PR closes it.
    When:
        dispatch(99) is called.
    Then:
        It should return None to signal the fresh-implementation flow.
    """
    # Arrange
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


def test_dispatch_with_issue_linked_pr_and_no_feedback(monkeypatch):
    """Test dispatch returns a PrContext when the linked PR has no feedback.

    Given:
        An issue number whose linked PR has zero unresolved review threads
        and zero non-empty review-body comments.
    When:
        dispatch(99) is called.
    Then:
        It should return a PrContext carrying the PR's metadata.
    """
    # Arrange
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
        _graphql_args("conradbzura", "sdlc", 42): _graphql_payload([]),
        ("pr", "view", "42", "--json", "reviews"): _reviews_payload([]),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    result = pr_state.dispatch(99)

    # Assert
    assert result == PrContext(
        pr_number=42, head_ref="feature-x", url="https://example/pr/42"
    )


def test_dispatch_with_pr_number_and_no_feedback(monkeypatch):
    """Test dispatch returns a PrContext when a PR number is passed directly.

    Given:
        Number 42 classifies as a PR with zero unresolved feedback.
    When:
        dispatch(42) is called.
    Then:
        It should return a PrContext carrying the PR's own metadata, with
        no detour through find_linked_pr.
    """
    # Arrange
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
        ("pr", "view", "42", "--json", "number,headRefName,url"): _PR_VIEW_42,
        _graphql_args("conradbzura", "sdlc", 42): _graphql_payload([]),
        ("pr", "view", "42", "--json", "reviews"): _reviews_payload([]),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    result = pr_state.dispatch(42)

    # Assert
    assert result == PrContext(
        pr_number=42, head_ref="feature-x", url="https://example/pr/42"
    )


def test_dispatch_with_unresolved_threads(monkeypatch):
    """Test dispatch returns Findings when a PR has unresolved review threads.

    Given:
        A PR with one unresolved and one resolved thread.
    When:
        dispatch(42) is called.
    Then:
        It should return Findings containing only the unresolved thread.
    """
    # Arrange
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
        {
            "isResolved": True,
            "comments": {"nodes": [{
                "body": "ignore me — already fixed",
                "path": "src/sdlc/guides.py",
                "line": 10,
                "author": {"login": "bob"},
            }]},
        },
    ]
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
        ("pr", "view", "42", "--json", "number,headRefName,url"): _PR_VIEW_42,
        _graphql_args("conradbzura", "sdlc", 42): _graphql_payload(threads),
        ("pr", "view", "42", "--json", "reviews"): _reviews_payload([]),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    result = pr_state.dispatch(42)

    # Assert
    assert isinstance(result, Findings)
    assert result.pr_number == 42
    assert result.head_ref == "feature-x"
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.kind == "review_thread"
    assert finding.path == "src/sdlc/server.py"
    assert finding.line == 64
    assert "rename foo to bar" in finding.body
    assert finding.author == "alice"


def test_dispatch_with_review_body_comments(monkeypatch):
    """Test dispatch surfaces non-empty review-body comments alongside threads.

    Given:
        A PR with no unresolved threads but one non-empty review body and
        one empty review body (an APPROVED-only review).
    When:
        dispatch(42) is called.
    Then:
        It should return Findings containing only the non-empty review-body
        comment marked with kind="review_body" and no file/line.
    """
    # Arrange
    reviews = [
        {
            "author": {"login": "alice"},
            "body": "Please address the doc gap.",
            "state": "COMMENTED",
        },
        {"author": {"login": "bob"}, "body": "", "state": "APPROVED"},
    ]
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
        ("pr", "view", "42", "--json", "number,headRefName,url"): _PR_VIEW_42,
        _graphql_args("conradbzura", "sdlc", 42): _graphql_payload([]),
        ("pr", "view", "42", "--json", "reviews"): _reviews_payload(reviews),
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act
    result = pr_state.dispatch(42)

    # Assert
    assert isinstance(result, Findings)
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.kind == "review_body"
    assert finding.path is None
    assert finding.line is None
    assert "Please address the doc gap." in finding.body
    assert finding.author == "alice"


def test_dispatch_with_unknown_number(monkeypatch):
    """Test dispatch raises when the number does not name an issue or PR.

    Given:
        Number 999 fails both the pr-view and issue-view probes.
    When:
        dispatch(999) is called.
    Then:
        It should raise GhUnavailable.
    """
    # Arrange
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_NOT_FORK,
        ("pr", "view", "999", "--json", "number,headRefName,url"): None,
        ("issue", "view", "999"): None,
    }
    monkeypatch.setattr(pr_state, "_run_gh", _make_fake_run_gh(responses))

    # Act & assert
    with pytest.raises(GhUnavailable):
        pr_state.dispatch(999)


def test_dispatch_when_repo_view_fails(monkeypatch):
    """Test dispatch raises GhUnavailable when gh repo view fails.

    Given:
        gh repo view returns a non-zero exit (e.g., gh missing or unauth).
    When:
        dispatch(42) is called.
    Then:
        It should raise GhUnavailable.
    """
    # Arrange
    def fake(args, allow_failure=False):
        raise GhUnavailable("gh repo view failed (canned)")

    monkeypatch.setattr(pr_state, "_run_gh", fake)

    # Act & assert
    with pytest.raises(GhUnavailable):
        pr_state.dispatch(42)


def test_dispatch_with_fork_repo(monkeypatch):
    """Test dispatch routes gh calls to upstream when current repo is a fork.

    Given:
        gh repo view reports the repo is a fork of upstream/sdlc.
    When:
        dispatch(42) is called.
    Then:
        Subsequent gh commands should include --repo upstream/sdlc and the
        graphql variables should reference the upstream owner/repo.
    """
    # Arrange
    responses = {
        ("repo", "view", "--json", _REPO_VIEW_FIELDS): _REPO_FORK,
        (
            "pr", "view", "42", "--repo", "upstream/sdlc",
            "--json", "number,headRefName,url",
        ): _PR_VIEW_42,
        _graphql_args("upstream", "sdlc", 42): _graphql_payload([]),
        (
            "pr", "view", "42", "--repo", "upstream/sdlc", "--json", "reviews",
        ): _reviews_payload([]),
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
