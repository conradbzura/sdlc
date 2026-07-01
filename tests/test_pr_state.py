"""Tests for sdlc.pr_state — gh wrappers and PR-state dispatch."""

import json
import textwrap

import pytest

from sdlc import pr_state
from sdlc.pr_state import (
    Finding,
    Findings,
    GhUnavailable,
    PrContext,
    ReviewFinding,
    ReviewFindings,
    parse_review_document,
    resolve_repo,
)


def _review_document(blocking="", advisory=""):
    """Build a minimal review-document markdown body with the given tiers.

    ``blocking`` and ``advisory`` are pre-rendered finding blocks (already
    dedented); each is dropped under its severity tier heading.
    """
    return textwrap.dedent(
        """\
        # PR #42 — Round 1 Review

        Header prose with branch commit map and severity legend.

        ---

        ## Tier 1 — Blocking

        {blocking}

        ## Tier 2 — Advisory

        {advisory}

        ## Cross-cutting decisions

        None.
        """
    ).format(blocking=blocking, advisory=advisory)


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
        A review document with one finding under each severity tier.
    When:
        parse_review_document is called.
    Then:
        It should return both findings with the severity of their tier.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(
        _review_document(blocking=_BLOCKING_FINDING, advisory=_ADVISORY_FINDING)
    )

    # Act
    result = parse_review_document(path, issue_number=42, iteration=1)

    # Assert
    by_id = {f.id: f.severity for f in result.findings}
    assert by_id == {"B1": "blocking", "A1": "advisory"}


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
    repo = pr_state._Repo(owner="conradbzura", name="sdlc", repo_flag=None)

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
    repo = pr_state._Repo(owner="conradbzura", name="sdlc", repo_flag=None)

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
    repo = pr_state._Repo(owner="conradbzura", name="sdlc", repo_flag=None)

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
    repo = pr_state._Repo(owner="conradbzura", name="sdlc", repo_flag=None)

    # Act
    result = pr_state.convert_pr_review_to_document(
        "https://github.com/conradbzura/sdlc/pull/42", repo=repo
    )

    # Assert
    assert len(result.findings) == 2
    for finding in result.findings:
        assert "---" not in finding.remediation
