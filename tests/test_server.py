"""Tests for sdlc.server — MCP tools and resources."""

import json
import re
from pathlib import Path

import pytest

from sdlc import pr_state, server
from sdlc.pr_state import (
    GhUnavailable,
    PrContext,
    ReviewFinding,
    ReviewFindings,
)
from sdlc.server import (
    review_skill,
    agents_md,
    get_default_config,
    get_role_guide,
    get_style_guide,
    get_test_guide,
    knowledge_graph,
    review_rationale,
    review_template,
    role_template,
    sdlc_commit,
    sdlc_guides_for,
    sdlc_implement,
    sdlc_issue,
    sdlc_pr,
    sdlc_review,
    sdlc_review_findings,
    sdlc_role,
    sdlc_role_scope,
    sdlc_roles,
    sdlc_test,
    sdlc_understand_chat,
)


@pytest.fixture(autouse=True)
def _isolated_review_config(monkeypatch, tmp_path):
    """Run every test from an empty directory carrying no review documents.

    The review directives are resolved by listing ``.sdlc/reviews`` under the
    process working directory, so without this the developer's own checkout —
    which holds real reviews — would decide the review number and round, and
    these tests would assert against the host's files rather than the code.
    """
    monkeypatch.delenv("SDLC_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _stub_gh_unavailable(monkeypatch):
    """Default resolve_repo to GhUnavailable so tools degrade deterministically.

    Tools whose skills run gh against issues/PRs resolve the target repo at
    call time. Without this stub the resolution would shell out to the real
    gh on the host, making output environment-dependent. Tests that exercise
    the injection override this with their own resolve_repo patch.
    """

    def raise_unavailable():
        raise GhUnavailable("gh stubbed unavailable in tests")

    monkeypatch.setattr(pr_state, "resolve_repo", raise_unavailable)


def _fork_repo():
    """A resolved repo standing in for a fork whose upstream is upstream/sdlc."""
    return pr_state.Repo(owner="upstream", name="sdlc", repo_flag="upstream/sdlc")


def _current_repo():
    """A resolved repo standing in for a non-fork (current repo applies)."""
    return pr_state.Repo(owner="conradbzura", name="sdlc", repo_flag=None)


def _patch_resolve_repo(monkeypatch, repo):
    """Patch pr_state.resolve_repo to return ``repo`` for the duration of a test."""
    monkeypatch.setattr(pr_state, "resolve_repo", lambda: repo)


def _patch_resolve_repo_unavailable(monkeypatch):
    """Patch pr_state.resolve_repo to raise GhUnavailable."""

    def raise_unavailable():
        raise GhUnavailable("gh executable not found on PATH")

    monkeypatch.setattr(pr_state, "resolve_repo", raise_unavailable)


def _review_directive(result):
    """Return the directive block sdlc_review appends after the skill prose.

    The skill markdown documents both review modes, so substrings like
    ``Target repo:`` or ``--repo`` legitimately appear in its body. The
    mode-specific contract is about what the tool APPENDS, so isolate that
    block by stripping the inlined skill prefix and the trailing template.
    """
    # The skill is assembled per mode, so strip whichever assembly this result
    # actually carries rather than assuming the whole file is present.
    for rereview in (False, True):
        skill = review_skill(rereview=rereview)
        if result.startswith(skill):
            body = result[len(skill):]
            break
    else:
        raise AssertionError("result does not begin with either skill assembly")
    head, separator, tail = body.partition("\n\nReview document template:")
    if not separator:
        return body
    # On a re-review the template sits BETWEEN the directives and the trailing
    # seeded block, which is deliberately last: it is bulk context, not a
    # directive, and burying the commit-destination directives behind it is
    # what the ordering exists to prevent. Drop the template, keep both spans.
    seeded = tail.find("\n\nSeeded findings —")
    return head + (tail[seeded:] if seeded != -1 else "")


@pytest.mark.asyncio
async def test_sdlc_issue_should_return_skill_when_no_arguments():
    """Test sdlc_issue returns skill content when called with no arguments.

    Given:
        No issue number and no context argument.
    When:
        sdlc_issue() is called.
    Then:
        It should return the issue skill content with no update directive.
    """
    # Act
    result = await sdlc_issue()

    # Assert
    assert "# Issue Skill" in result
    assert "User context" not in result
    assert "Target issue to update" not in result


@pytest.mark.asyncio
async def test_sdlc_issue_should_append_context_when_provided():
    """Test sdlc_issue appends user context when provided.

    Given:
        A context string is provided.
    When:
        sdlc_issue(context="Add retry logic") is called.
    Then:
        It should return skill content with user context appended.
    """
    # Act
    result = await sdlc_issue(context="Add retry logic")

    # Assert
    assert "# Issue Skill" in result
    assert "Add retry logic" in result
    assert "Target issue to update" not in result


@pytest.mark.asyncio
async def test_sdlc_issue_should_append_update_directive_when_issue_number_given():
    """Test sdlc_issue appends an update directive when an issue number is given.

    Given:
        An issue number is provided.
    When:
        sdlc_issue(issue_number=42) is called.
    Then:
        It should return skill content with the update directive and #42.
    """
    # Act
    result = await sdlc_issue(issue_number=42)

    # Assert
    assert "# Issue Skill" in result
    assert "Target issue to update: #42" in result
    assert "User context" not in result


@pytest.mark.asyncio
async def test_sdlc_issue_should_append_directive_and_context_when_both_given():
    """Test sdlc_issue appends both the update directive and the context.

    Given:
        An issue number and a context string are provided.
    When:
        sdlc_issue(issue_number=42, context="Add retry logic") is called.
    Then:
        It should return skill content with both the update directive and context.
    """
    # Act
    result = await sdlc_issue(issue_number=42, context="Add retry logic")

    # Assert
    assert "# Issue Skill" in result
    assert "Target issue to update: #42" in result
    assert "Add retry logic" in result


@pytest.mark.asyncio
async def test_sdlc_implement_with_no_pr(monkeypatch):
    """Test sdlc_implement returns the fresh skill when no PR is linked.

    Given:
        pr_state.dispatch returns None for the given number.
    When:
        sdlc_implement(number=42) is called.
    Then:
        It should return the fresh implement skill with #42 appended.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "dispatch", lambda number, repo=None, review=None: None)

    # Act
    result = await sdlc_implement(number=42)

    # Assert
    assert "# Implement Skill" in result
    assert "# Implement Continue Skill" not in result
    assert "# Implement Feedback Skill" not in result
    assert "#42" in result


@pytest.mark.asyncio
async def test_sdlc_implement_with_no_feedback_pr(monkeypatch):
    """Test sdlc_implement returns the continue skill for a PR with no feedback.

    Given:
        pr_state.dispatch returns a PrContext for the given number.
    When:
        sdlc_implement(number=42) is called.
    Then:
        It should return the continue skill with the PR metadata appended.
    """
    # Arrange
    context = PrContext(pr_number=42, head_ref="feature-x", url="https://example/pr/42")
    monkeypatch.setattr(pr_state, "dispatch", lambda number, repo=None, review=None: context)

    # Act
    result = await sdlc_implement(number=42)

    # Assert
    assert "# Implement Continue Skill" in result
    assert "feature-x" in result
    assert "https://example/pr/42" in result


@pytest.mark.asyncio
async def test_sdlc_implement_with_review_findings(tmp_path, monkeypatch):
    """Test sdlc_implement returns the feedback skill when review findings exist.

    Given:
        pr_state.dispatch returns a ReviewFindings instance for the number.
    When:
        sdlc_implement(number=42) is called.
    Then:
        It should return the feedback skill with the document disclosed as an
        outline — every finding named, each body held back for a fetch.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    path = _write_review_doc(tmp_path, ".sdlc/reviews/issue-#7", 2)
    review_findings = pr_state.parse_review_document(path, issue_number=7, iteration=2)
    monkeypatch.setattr(
        pr_state, "dispatch", lambda number, repo=None, review=None: review_findings
    )

    # Act
    result = await sdlc_implement(number=42)

    # Assert
    assert "# Implement Feedback Skill" in result
    assert "src/sdlc/server.py:64" in result
    assert "Rename foo to bar" in result
    assert "Iteration: 2" in result
    assert "sdlc_review_findings" in result
    assert "The symbol `foo` should be `bar`." not in result


@pytest.mark.asyncio
async def test_sdlc_implement_should_thread_int_review_to_dispatch(monkeypatch):
    """Test sdlc_implement passes an int review selector through to dispatch.

    Given:
        A captured dispatch spy and review=3.
    When:
        sdlc_implement(number=7, review=3) is called.
    Then:
        dispatch should receive review=3.
    """
    # Arrange
    captured = {}

    def fake_dispatch(number, repo=None, review=None):
        captured["review"] = review
        return None

    monkeypatch.setattr(pr_state, "dispatch", fake_dispatch)

    # Act
    await sdlc_implement(number=7, review=3)

    # Assert
    assert captured["review"] == 3


@pytest.mark.asyncio
async def test_sdlc_implement_should_thread_pr_url_review_to_dispatch(monkeypatch):
    """Test sdlc_implement passes a PR-URL review selector through to dispatch.

    Given:
        A captured dispatch spy and a PR-URL review argument.
    When:
        sdlc_implement(number=7, review=<pr-url>) is called.
    Then:
        dispatch should receive the PR URL unchanged.
    """
    # Arrange
    captured = {}
    url = "https://github.com/conradbzura/sdlc/pull/42"

    def fake_dispatch(number, repo=None, review=None):
        captured["review"] = review
        return None

    monkeypatch.setattr(pr_state, "dispatch", fake_dispatch)

    # Act
    await sdlc_implement(number=7, review=url)

    # Assert
    assert captured["review"] == url


@pytest.mark.asyncio
async def test_sdlc_implement_should_report_missing_iteration(monkeypatch):
    """Test sdlc_implement returns a diagnostic when dispatch raises ValueError.

    Given:
        pr_state.dispatch raises ValueError for a missing review iteration.
    When:
        sdlc_implement(number=7, review=9) is called.
    Then:
        It should return a clear diagnostic string rather than propagating.
    """
    # Arrange
    def raise_value_error(number, repo=None, review=None):
        raise ValueError("Review iteration 9 not found for issue #7")

    monkeypatch.setattr(pr_state, "dispatch", raise_value_error)

    # Act
    result = await sdlc_implement(number=7, review=9)

    # Assert
    assert "Could not load the requested review feedback" in result
    assert "iteration 9 not found" in result


@pytest.mark.asyncio
async def test_sdlc_implement_should_resolve_repo_exactly_once(tmp_path, monkeypatch):
    """Test sdlc_implement resolves the target repo exactly once per call.

    Given:
        A non-fork repo and a PR number whose closing issue has no local review
        document, with the real dispatch running against a canned gh and a
        counting spy wrapping resolve_repo.
    When:
        sdlc_implement(number=42) is called.
    Then:
        resolve_repo should be invoked exactly once — the single resolution is
        threaded through dispatch rather than recomputed for the PR-state
        classification.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    call_count = 0

    def counting_resolve_repo():
        nonlocal call_count
        call_count += 1
        return _current_repo()

    pr_view = json.dumps(
        {"number": 42, "headRefName": "feature-x", "url": "https://example/pr/42"}
    )
    closing_query = (
        "query=query($owner: String!, $repo: String!, $pr: Int!) "
        "{ repository(owner: $owner, name: $repo) { pullRequest(number: $pr) "
        "{ closingIssuesReferences(first: 10) { nodes { number } } } } }"
    )
    closing_payload = json.dumps(
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "closingIssuesReferences": {"nodes": [{"number": 7}]}
                    }
                }
            }
        }
    )
    responses = {
        ("pr", "view", "42", "--json", "number,headRefName,url"): pr_view,
        (
            "api", "graphql",
            "-f", closing_query,
            "-f", "owner=conradbzura",
            "-f", "repo=sdlc",
            "-F", "pr=42",
        ): closing_payload,
    }

    def fake_run_gh(args, allow_failure=False):
        return responses[tuple(args)]

    monkeypatch.setattr(pr_state, "_run_gh", fake_run_gh)
    monkeypatch.setattr(pr_state, "resolve_repo", counting_resolve_repo)

    # Act
    result = await sdlc_implement(number=42)

    # Assert
    assert call_count == 1
    assert "# Implement Continue Skill" in result


@pytest.mark.asyncio
async def test_sdlc_implement_when_gh_unavailable(monkeypatch):
    """Test sdlc_implement falls back to the fresh skill when gh is unavailable.

    Given:
        pr_state.dispatch raises GhUnavailable.
    When:
        sdlc_implement(number=42) is called.
    Then:
        It should return the fresh skill with a diagnostic comment appended.
    """
    # Arrange
    def raise_unavailable(_number, repo=None, review=None):
        raise GhUnavailable("gh executable not found on PATH")

    monkeypatch.setattr(pr_state, "dispatch", raise_unavailable)

    # Act
    result = await sdlc_implement(number=42)

    # Assert
    assert "# Implement Skill" in result
    assert "diagnostic" in result
    assert "gh executable not found" in result


@pytest.mark.asyncio
async def test_sdlc_implement_should_omit_target_directive_when_no_target(monkeypatch):
    """Test sdlc_implement omits the override directive when no target is given.

    Given:
        pr_state.dispatch returns None and no target argument is provided.
    When:
        sdlc_implement(number=42) is called.
    Then:
        It should return fresh implement skill content without an override directive.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "dispatch", lambda number, repo=None, review=None: None)

    # Act
    result = await sdlc_implement(number=42)

    # Assert
    assert "Branch from / base against this branch" not in result


@pytest.mark.asyncio
async def test_sdlc_implement_should_append_target_directive_when_target_given(monkeypatch):
    """Test sdlc_implement appends the override directive when a target is given.

    Given:
        pr_state.dispatch returns None and a target branch of "stable".
    When:
        sdlc_implement(number=42, target="stable") is called.
    Then:
        It should return content with the override directive naming "stable".
    """
    # Arrange
    monkeypatch.setattr(pr_state, "dispatch", lambda number, repo=None, review=None: None)

    # Act
    result = await sdlc_implement(number=42, target="stable")

    # Assert
    assert "Target branch override: stable" in result
    assert "Branch from / base against this branch" in result


@pytest.mark.asyncio
async def test_sdlc_test_should_interpolate_issue_number():
    """Test sdlc_test returns skill content with interpolated issue number.

    Given:
        An issue number.
    When:
        sdlc_test(issue_number=42) is called.
    Then:
        It should return test skill content with #42 appended.
    """
    # Act
    result = await sdlc_test(issue_number=42)

    # Assert
    assert "# Test Skill" in result
    assert "#42" in result


@pytest.mark.asyncio
async def test_sdlc_commit_should_return_skill_content():
    """Test sdlc_commit returns the commit skill content.

    Given:
        No arguments.
    When:
        sdlc_commit() is called.
    Then:
        It should return the commit skill content.
    """
    # Act
    result = await sdlc_commit()

    # Assert
    assert "# Commit Skill" in result


@pytest.mark.asyncio
async def test_sdlc_pr_should_interpolate_issue_number():
    """Test sdlc_pr returns skill content with interpolated issue number.

    Given:
        An issue number.
    When:
        sdlc_pr(issue_number=42) is called.
    Then:
        It should return pr skill content with #42 appended.
    """
    # Act
    result = await sdlc_pr(issue_number=42)

    # Assert
    assert "# PR Skill" in result
    assert "#42" in result


@pytest.mark.asyncio
async def test_sdlc_pr_should_omit_target_directive_when_no_target():
    """Test sdlc_pr omits the override directive when no target is given.

    Given:
        No target argument.
    When:
        sdlc_pr(issue_number=42) is called.
    Then:
        It should return pr skill content without an override directive.
    """
    # Act
    result = await sdlc_pr(issue_number=42)

    # Assert
    assert "Branch from / base against this branch" not in result


@pytest.mark.asyncio
async def test_sdlc_pr_should_append_target_directive_when_target_given():
    """Test sdlc_pr appends the override directive when a target is given.

    Given:
        A target branch of "master".
    When:
        sdlc_pr(issue_number=42, target="master") is called.
    Then:
        It should return content with the override directive naming "master".
    """
    # Act
    result = await sdlc_pr(issue_number=42, target="master")

    # Assert
    assert "Target branch override: master" in result
    assert "Branch from / base against this branch" in result


@pytest.mark.asyncio
async def test_sdlc_review_should_interpolate_pr_number(monkeypatch):
    """Test sdlc_review returns skill content with interpolated PR number.

    Given:
        A PR number.
    When:
        sdlc_review(pr_number=10) is called.
    Then:
        It should return review skill content with #10 appended.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)

    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    assert "# Review Skill" in result
    assert "#10" in result


@pytest.mark.asyncio
async def test_sdlc_review_should_default_to_general_purpose_role_when_roles_omitted(
    monkeypatch,
):
    """Test sdlc_review applies the general-purpose role default when roles omitted.

    Given:
        A PR number and no roles argument.
    When:
        sdlc_review(pr_number=10) is called.
    Then:
        It should name the general-purpose role in the appended composition.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)

    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    assert "Roles: general-purpose" in result


@pytest.mark.asyncio
async def test_sdlc_review_should_default_reviewers_per_role_to_one(monkeypatch):
    """Test sdlc_review defaults the per-role reviewer count to one.

    Given:
        A PR number and no subagents argument.
    When:
        sdlc_review(pr_number=10) is called.
    Then:
        It should report one reviewer per role.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)

    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    assert "Reviewers per role: 1" in result


@pytest.mark.asyncio
async def test_sdlc_review_should_list_all_roles_when_multiple_given(monkeypatch):
    """Test sdlc_review renders every supplied role in the composition.

    Given:
        A PR number and a roles list of two roles.
    When:
        sdlc_review(pr_number=10, roles=["architect", "security"]) is called.
    Then:
        It should name both roles in the appended composition.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)

    # Act
    result = await sdlc_review(pr_number=10, roles=["architect", "security"])

    # Assert
    assert "Roles: architect, security" in result


@pytest.mark.asyncio
async def test_sdlc_review_should_report_subagent_count_when_given(monkeypatch):
    """Test sdlc_review reports the requested per-role reviewer count.

    Given:
        A PR number and subagents=5.
    When:
        sdlc_review(pr_number=10, subagents=5) is called.
    Then:
        It should report five reviewers per role.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)

    # Act
    result = await sdlc_review(pr_number=10, subagents=5)

    # Assert
    assert "Reviewers per role: 5" in result


@pytest.mark.asyncio
async def test_sdlc_review_should_inline_review_template(monkeypatch):
    """Test sdlc_review inlines the consolidated-review-document template.

    Given:
        A PR number.
    When:
        sdlc_review(pr_number=10) is called.
    Then:
        It should include all three of the template's severity-tier headings.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)

    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    assert "## Tier 1 — Blocking" in result
    assert "## Tier 2 — Advisory" in result
    assert "## Tier 3 — Incidental" in result


@pytest.mark.asyncio
async def test_sdlc_review_should_append_resolved_issue_directive_when_linked(
    monkeypatch,
):
    """Test sdlc_review appends the resolved issue and its document directory.

    Given:
        closing_issue resolves PR 10 to linked issue 7.
    When:
        sdlc_review(pr_number=10) is called.
    Then:
        It should append the resolved issue number and the issue's review
        document directory.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)

    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    assert "Resolved issue: #7" in result
    assert "Review document directory: .sdlc/reviews/issue-#7/" in result


@pytest.mark.asyncio
async def test_sdlc_review_should_note_unresolved_when_no_linked_issue(monkeypatch):
    """Test sdlc_review notes an unresolved issue when the PR has no link.

    Given:
        closing_issue returns None for PR 10.
    When:
        sdlc_review(pr_number=10) is called.
    Then:
        It should append an unresolved notice instead of a document directory.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: None)

    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    directive = (
        result.split("Reviewers per role: 1\n", 1)[1]
        .split("\n\nReview document template:", 1)[0]
    )
    assert directive.startswith("Resolved issue: unresolved")
    assert "Review document directory:" not in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_degrade_when_issue_resolution_unavailable(
    monkeypatch,
):
    """Test sdlc_review degrades gracefully when gh resolution fails.

    Given:
        closing_issue raises GhUnavailable for PR 10.
    When:
        sdlc_review(pr_number=10) is called.
    Then:
        It should still return the review skill with an unresolved-issue notice
        rather than propagating the error.
    """
    # Arrange
    def raise_unavailable(pr_number):
        raise GhUnavailable("gh missing")

    monkeypatch.setattr(pr_state, "closing_issue", raise_unavailable)

    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    assert "# Review Skill" in result
    assert "Resolved issue: unresolved" in result


@pytest.mark.asyncio
async def test_sdlc_review_should_raise_when_no_target_given():
    """Test sdlc_review rejects a call naming neither a PR nor paths.

    Given:
        Neither pr_number nor paths is supplied.
    When:
        sdlc_review() is called.
    Then:
        It should raise ValueError, before any skill read or gh call.
    """
    # Act / Assert
    with pytest.raises(ValueError):
        await sdlc_review()


@pytest.mark.asyncio
async def test_sdlc_review_should_raise_when_both_targets_given():
    """Test sdlc_review rejects a call naming both a PR and paths.

    Given:
        Both pr_number and paths are supplied.
    When:
        sdlc_review(pr_number=10, paths=["src/sdlc/server.py"]) is called.
    Then:
        It should raise ValueError, before any skill read or gh call.
    """
    # Act / Assert
    with pytest.raises(ValueError):
        await sdlc_review(pr_number=10, paths=["src/sdlc/server.py"])


@pytest.mark.asyncio
async def test_sdlc_review_paths_mode_should_emit_target_paths_and_skill_header():
    """Test sdlc_review in paths mode names the paths and inlines the skill.

    Given:
        A paths list with a single literal file.
    When:
        sdlc_review(paths=["src/sdlc/server.py"]) is called.
    Then:
        It should return the review skill and a Target paths directive naming
        the path verbatim.
    """
    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    assert "# Review Skill" in result
    assert "Target paths:" in result
    assert "src/sdlc/server.py" in result


@pytest.mark.asyncio
async def test_sdlc_review_paths_mode_should_omit_target_repo_even_for_fork(
    monkeypatch,
):
    """Test sdlc_review in paths mode never injects a target-repo directive.

    Given:
        resolve_repo reports the current repo is a fork of upstream/sdlc.
    When:
        sdlc_review(paths=["src/sdlc/server.py"]) is called.
    Then:
        It should omit the Target repo directive and any --repo flag, because
        paths mode runs no gh.
    """
    # Arrange
    _patch_resolve_repo(monkeypatch, _fork_repo())

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    assert "Target repo:" not in directive
    assert "--repo" not in directive


@pytest.mark.asyncio
async def test_sdlc_review_paths_mode_should_omit_pr_and_issue_directives():
    """Test sdlc_review in paths mode emits no PR or resolved-issue directives.

    Given:
        A paths list with a single literal file.
    When:
        sdlc_review(paths=["src/sdlc/server.py"]) is called.
    Then:
        It should omit both the Target PR directive and the Resolved issue
        directive.
    """
    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    assert "Target PR:" not in directive
    assert "Resolved issue:" not in directive


@pytest.mark.asyncio
async def test_sdlc_review_paths_mode_should_default_to_general_purpose_role():
    """Test sdlc_review in paths mode defaults the role to general-purpose.

    Given:
        A paths list and no roles argument.
    When:
        sdlc_review(paths=["src/sdlc/server.py"]) is called.
    Then:
        It should name the general-purpose role in the appended composition.
    """
    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    assert "Roles: general-purpose" in result


@pytest.mark.asyncio
async def test_sdlc_review_paths_mode_should_render_explicit_roles():
    """Test sdlc_review in paths mode renders an explicit role list.

    Given:
        A paths list and roles=["aie"].
    When:
        sdlc_review(paths=["src/sdlc/server.py"], roles=["aie"]) is called.
    Then:
        It should name the aie role in the appended composition.
    """
    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], roles=["aie"])

    # Assert
    assert "Roles: aie" in result


@pytest.mark.asyncio
async def test_sdlc_review_paths_mode_should_report_subagent_count():
    """Test sdlc_review in paths mode reports the per-role reviewer count.

    Given:
        A paths list and subagents=4.
    When:
        sdlc_review(paths=["src/sdlc/server.py"], subagents=4) is called.
    Then:
        It should report four reviewers per role.
    """
    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], subagents=4)

    # Assert
    assert "Reviewers per role: 4" in result


@pytest.mark.asyncio
async def test_sdlc_review_paths_mode_should_inline_review_template():
    """Test sdlc_review in paths mode inlines the review-document template.

    Given:
        A paths list with a single literal file.
    When:
        sdlc_review(paths=["src/sdlc/server.py"]) is called.
    Then:
        It should include all three of the template's severity-tier headings.
    """
    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    assert "## Tier 1 — Blocking" in result
    assert "## Tier 2 — Advisory" in result
    assert "## Tier 3 — Incidental" in result


@pytest.mark.asyncio
async def test_sdlc_review_paths_mode_should_emit_stem_directory_for_single_literal():
    """Test sdlc_review derives a stem-based document directory for one file.

    Given:
        A paths list with a single literal file path.
    When:
        sdlc_review(paths=["src/sdlc/role-guides/aie.md"]) is called.
    Then:
        It should emit a review document directory keyed by the file's stem.
    """
    # Act
    result = await sdlc_review(paths=["src/sdlc/role-guides/aie.md"])

    # Assert
    assert "Review document directory: .sdlc/reviews/aie/" in result


@pytest.mark.asyncio
async def test_sdlc_review_paths_mode_should_emit_hashed_directory_for_glob():
    """Test sdlc_review derives a sanitized, hashed directory for a glob.

    Given:
        A paths list whose single element is a glob.
    When:
        sdlc_review(paths=["src/sdlc/**/*.py"]) is called.
    Then:
        It should emit a review document directory whose slug is the sanitized
        join of the args plus an 8-hex-char hash suffix.
    """
    # Act
    result = await sdlc_review(paths=["src/sdlc/**/*.py"])

    # Assert — the slug is PINNED, not recomputed. It is the directory
    # successive rounds of one target accumulate under, so its stability across
    # releases is the contract; deriving the expectation from the code under
    # test would assert that code against itself and pass through any change.
    expected = "src-sdlc-py-59843563"
    assert f"Review document directory: .sdlc/reviews/{expected}/" in result
    suffix = expected.rsplit("-", 1)[1]
    assert len(suffix) == 8
    assert all(ch in "0123456789abcdef" for ch in suffix)


@pytest.mark.asyncio
async def test_sdlc_review_pr_mode_should_inject_first_iteration_review_path(
    tmp_path, monkeypatch
):
    """Test sdlc_review injects the first review path for an empty issue dir.

    Given:
        closing_issue resolves PR 10 to issue 7 and the issue's review
        directory does not yet exist.
    When:
        sdlc_review(pr_number=10) is called.
    Then:
        It should inject the exact next-unused review path at iteration 1
        alongside the retained review document directory line.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)

    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    assert "Review document directory: .sdlc/reviews/issue-#7/" in result
    assert "Review document: .sdlc/reviews/issue-#7/review-1.md" in result


@pytest.mark.asyncio
async def test_sdlc_review_pr_mode_should_inject_next_iteration_without_overwrite(
    tmp_path, monkeypatch
):
    """Test sdlc_review injects the next iteration and leaves prior rounds intact.

    Given:
        Issue 7 already has review-1.md and closing_issue resolves PR 10 to it.
    When:
        sdlc_review(pr_number=10) is called.
    Then:
        It should inject review-2.md as the write target and leave the seeded
        review-1.md unmodified.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)
    directory = tmp_path / ".sdlc" / "reviews" / "issue-#7"
    directory.mkdir(parents=True)
    seeded = directory / "review-1.md"
    seeded.write_text("existing round one")

    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    assert "Review document: .sdlc/reviews/issue-#7/review-2.md" in result
    assert seeded.read_text() == "existing round one"


@pytest.mark.asyncio
async def test_sdlc_review_paths_mode_should_inject_first_iteration_review_path(
    tmp_path, monkeypatch
):
    """Test sdlc_review injects the first review path for an empty slug dir.

    Given:
        A single literal path whose slug directory does not yet exist.
    When:
        sdlc_review(paths=["src/sdlc/server.py"]) is called.
    Then:
        It should inject the exact next-unused review path at iteration 1 under
        the slug directory.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    assert "Review document directory: .sdlc/reviews/server/" in result
    assert "Review document: .sdlc/reviews/server/review-1.md" in result


@pytest.mark.asyncio
async def test_sdlc_review_paths_mode_should_inject_next_iteration_without_overwrite(
    tmp_path, monkeypatch
):
    """Test sdlc_review injects the next iteration for a seeded slug directory.

    Given:
        The slug directory for a single literal path already holds review-1.md.
    When:
        sdlc_review(paths=["src/sdlc/server.py"]) is called.
    Then:
        It should inject review-2.md as the write target and leave the seeded
        review-1.md unmodified.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / ".sdlc" / "reviews" / "server"
    directory.mkdir(parents=True)
    seeded = directory / "review-1.md"
    seeded.write_text("existing round one")

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    assert "Review document: .sdlc/reviews/server/review-2.md" in result
    assert seeded.read_text() == "existing round one"


def _write_review_doc(tmp_path, directory, iteration, finding_id="B1", round=1):
    """Write a minimal one-finding review document under ``directory``.

    Returns the path written. ``directory`` is relative to ``tmp_path`` (the
    cwd the test chdirs into); the document carries a single blocking finding
    whose id is ``finding_id`` so the rendered output is identifiable.
    ``round`` selects the file: round 1 is ``review-<N>.md`` and every later
    round is ``review-<N>.<round>.md``.
    """
    target = tmp_path / directory
    target.mkdir(parents=True, exist_ok=True)
    document = (
        "# PR #10 — Round 1 Review\n\n"
        "Header prose.\n\n"
        "---\n\n"
        "## Tier 1 — Blocking\n\n"
        f"### {finding_id} — Rename foo to bar **(BLOCKING)** — aie (1/1 aie)\n"
        "**Reference:** `src/sdlc/server.py:64`\n\n"
        "**Issue:** The symbol `foo` should be `bar`.\n\n"
        "**Remediation:**\n"
        "- [x] Rename `foo` to `bar`. *(Recommended.)*\n"
        "- [ ] Other: ________________________________________________\n\n"
        "**Touched commit:** `abc1234`\n\n"
        "## Tier 2 — Advisory\n\n"
        "## Cross-cutting decisions\n\nNone.\n"
    )
    name = f"review-{iteration}.md" if round == 1 else f"review-{iteration}.{round}.md"
    path = target / name
    path.write_text(document)
    return path


@pytest.mark.asyncio
async def test_sdlc_review_should_raise_when_rereviewing_with_no_target():
    """Test sdlc_review with verify but no target raises ValueError.

    Given:
        verify is set but neither pr_number nor paths is supplied.
    When:
        sdlc_review(verify=1) is called.
    Then:
        It should raise ValueError via the exactly-one-target guard.
    """
    # Act / Assert
    with pytest.raises(ValueError):
        await sdlc_review(verify=1)


@pytest.mark.asyncio
async def test_sdlc_review_should_raise_when_rereviewing_a_pr_that_closes_no_issue(
    monkeypatch,
):
    """Test re-review PR mode raises when the PR closes no issue.

    Given:
        closing_issue returns None for PR 10.
    When:
        sdlc_review(pr_number=10, verify=1) is called.
    Then:
        It should raise ValueError — there is no issue directory to read from.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: None)

    # Act / Assert
    with pytest.raises(ValueError):
        await sdlc_review(pr_number=10, verify=1)


@pytest.mark.asyncio
async def test_sdlc_review_should_raise_when_rereviewing_a_pr_and_gh_is_unavailable(
    monkeypatch,
):
    """Test a re-review fails as ValueError, not GhUnavailable, when gh is down.

    Given:
        closing_issue raises GhUnavailable for PR 10.
    When:
        sdlc_review(pr_number=10, verify=1) is called.
    Then:
        It should raise ValueError naming gh and the document it could not
        locate. Stopping is correct — a re-review cannot resolve the issue
        directory and does not degrade like the fresh-review path — but the
        failure has to match the contract `sdlc_review`'s docstring and
        AGENTS.md both state, which enumerates ValueError only.
    """

    # Arrange
    def raise_unavailable(pr_number):
        raise GhUnavailable("gh executable not found on PATH")

    monkeypatch.setattr(pr_state, "closing_issue", raise_unavailable)

    # Act / Assert
    with pytest.raises(ValueError, match="gh executable not found") as raised:
        await sdlc_review(pr_number=10, verify=1)
    assert "review-1.md" in str(raised.value)
    assert not isinstance(raised.value, GhUnavailable)


@pytest.mark.asyncio
async def test_sdlc_review_should_raise_when_rereviewing_a_pr_with_no_review_document(
    tmp_path, monkeypatch
):
    """Test re-review PR mode raises when the target has no review document.

    Given:
        closing_issue resolves PR 10 to issue 7, but no issue-#7 review
        directory exists on disk.
    When:
        sdlc_review(pr_number=10, verify=1) is called.
    Then:
        It should raise ValueError surfaced by load_review_findings.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)

    # Act / Assert
    with pytest.raises(ValueError):
        await sdlc_review(pr_number=10, verify=1)


@pytest.mark.asyncio
async def test_sdlc_review_should_raise_when_rereviewing_a_missing_iteration(
    tmp_path, monkeypatch
):
    """Test re-review PR mode raises when the requested iteration is absent.

    Given:
        Issue 7 has only review-1.md but verify=5 is requested.
    When:
        sdlc_review(pr_number=10, verify=5) is called.
    Then:
        It should raise ValueError naming the missing iteration.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)
    _write_review_doc(tmp_path, ".sdlc/reviews/issue-#7", 1)

    # Act / Assert
    with pytest.raises(ValueError, match="iteration 5 not found"):
        await sdlc_review(pr_number=10, verify=5)


@pytest.mark.asyncio
async def test_sdlc_review_should_raise_when_rereviewing_paths_with_no_document(
    tmp_path, monkeypatch
):
    """Test re-review paths mode raises when no review doc exists for the slug.

    Given:
        No slug directory exists for the single literal file.
    When:
        sdlc_review(paths=["src/sdlc/server.py"], verify=1) is called.
    Then:
        It should raise ValueError surfaced by load_review_findings.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act / Assert
    with pytest.raises(ValueError):
        await sdlc_review(paths=["src/sdlc/server.py"], verify=1)


@pytest.mark.asyncio
async def test_sdlc_review_should_inline_the_template_when_rereviewing(
    tmp_path, monkeypatch
):
    """Test a re-review still inlines the consolidated-review-document template.

    Given:
        Issue 7 has review-1.md and PR 10 closes it.
    When:
        sdlc_review(pr_number=10, verify=1) is called.
    Then:
        It should include all three of the template's severity-tier headings.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)
    _write_review_doc(tmp_path, ".sdlc/reviews/issue-#7", 1)

    # Act
    result = await sdlc_review(pr_number=10, verify=1)

    # Assert
    assert "## Tier 1 — Blocking" in result
    assert "## Tier 2 — Advisory" in result
    assert "## Tier 3 — Incidental" in result


@pytest.mark.asyncio
async def test_sdlc_review_should_omit_the_rereview_directive_when_verify_is_unset(
    tmp_path, monkeypatch
):
    """Test sdlc_review without verify emits no re-review or seeded block.

    Given:
        closing_issue resolves PR 10 to issue 7 and verify is omitted.
    When:
        sdlc_review(pr_number=10) is called.
    Then:
        It should carry neither the re-review directive nor a seeded
        findings block.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)

    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    directive = _review_directive(result)
    assert "Re-review" not in directive
    assert "Verify" not in directive
    assert "Seeded findings" not in directive
    assert "Seeded from" not in directive


def _document_directory(result):
    """Return the slug directory sdlc_review resolved for a paths-mode call."""
    marker = "Review document directory: .sdlc/reviews/"
    directive = _review_directive(result)
    assert marker in directive, "no review document directory in the directive"
    return directive.split(marker, 1)[1].split("/", 1)[0]


@pytest.mark.asyncio
async def test_sdlc_review_should_name_the_file_stem_for_one_literal_path():
    """Test a single literal path resolves to that file's stem.

    Given:
        A paths-mode review of one literal file path with no glob
        metacharacters.
    When:
        sdlc_review is called with it.
    Then:
        The review document directory should be the file's stem, with no hash
        suffix — the readable case the slug rule exists to preserve.
    """
    # Act
    result = await sdlc_review(paths=["src/sdlc/role-guides/aie.md"])

    # Assert
    assert _document_directory(result) == "aie"


@pytest.mark.asyncio
async def test_sdlc_review_should_resolve_one_directory_regardless_of_path_order():
    """Test the slug is stable and order-independent for a multi-path target.

    Given:
        The same two file paths supplied in each order.
    When:
        sdlc_review is called with both orderings, and twice with the same
        glob.
    Then:
        Every call should resolve the same directory, sanitized of glob
        metacharacters and path separators. Successive rounds of one target
        accumulate under that directory, so an unstable slug would scatter a
        review chain across directories and a re-review would find nothing.
    """
    # Act
    forward = await sdlc_review(paths=["src/a.py", "src/b.py"])
    reversed_order = await sdlc_review(paths=["src/b.py", "src/a.py"])
    glob_first = await sdlc_review(paths=["src/sdlc/**/*.py"])
    glob_again = await sdlc_review(paths=["src/sdlc/**/*.py"])

    # Assert
    assert _document_directory(forward) == _document_directory(reversed_order)
    glob_slug = _document_directory(glob_first)
    assert glob_slug == _document_directory(glob_again)
    assert "*" not in glob_slug
    assert "/" not in glob_slug
    suffix = glob_slug.rsplit("-", 1)[1]
    assert len(suffix) == 8
    assert all(ch in "0123456789abcdef" for ch in suffix)


@pytest.mark.asyncio
async def test_sdlc_understand_chat_should_interpolate_query():
    """Test sdlc_understand_chat returns skill content with interpolated query.

    Given:
        A query string.
    When:
        sdlc_understand_chat(query="How does auth work?") is called.
    Then:
        It should return understand-chat skill content with the query appended.
    """
    # Act
    result = await sdlc_understand_chat(query="How does auth work?")

    # Assert
    assert "# Understand Chat Skill" in result
    assert "How does auth work?" in result


@pytest.mark.asyncio
async def test_sdlc_issue_should_inject_upstream_target_repo_when_fork(monkeypatch):
    """Test sdlc_issue injects the upstream target-repo directive for a fork.

    Given:
        pr_state.resolve_repo reports the current repo is a fork of upstream/sdlc.
    When:
        sdlc_issue() is called.
    Then:
        It should append a "Target repo: upstream/sdlc" directive.
    """
    # Arrange
    _patch_resolve_repo(monkeypatch, _fork_repo())

    # Act
    result = await sdlc_issue()

    # Assert
    assert "Target repo: upstream/sdlc" in result
    assert "--repo upstream/sdlc" in result


@pytest.mark.asyncio
async def test_sdlc_issue_should_inject_current_repo_directive_when_not_fork(monkeypatch):
    """Test sdlc_issue injects the current-repo directive when not a fork.

    Given:
        pr_state.resolve_repo reports the current repo is not a fork.
    When:
        sdlc_issue() is called.
    Then:
        It should append a current-repo directive instructing to omit --repo.
    """
    # Arrange
    _patch_resolve_repo(monkeypatch, _current_repo())

    # Act
    result = await sdlc_issue()

    # Assert
    assert "omit --repo on gh commands that reference issues or PRs" in result


@pytest.mark.asyncio
async def test_sdlc_issue_should_omit_target_repo_when_gh_unavailable(monkeypatch):
    """Test sdlc_issue appends no target-repo directive when gh is unavailable.

    Given:
        pr_state.resolve_repo raises GhUnavailable.
    When:
        sdlc_issue() is called.
    Then:
        It should still return the skill content with no "Target repo" directive.
    """
    # Arrange
    _patch_resolve_repo_unavailable(monkeypatch)

    # Act
    result = await sdlc_issue()

    # Assert
    assert "# Issue Skill" in result
    assert "Target repo: upstream/sdlc" not in result
    assert "omit --repo on gh commands that reference issues or PRs" not in result


@pytest.mark.asyncio
async def test_sdlc_implement_should_inject_upstream_target_repo_when_fork(monkeypatch):
    """Test sdlc_implement injects the upstream target-repo directive for a fork.

    Given:
        pr_state.dispatch returns None and resolve_repo reports a fork.
    When:
        sdlc_implement(number=42) is called.
    Then:
        It should append a "Target repo: upstream/sdlc" directive.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "dispatch", lambda number, repo=None, review=None: None)
    _patch_resolve_repo(monkeypatch, _fork_repo())

    # Act
    result = await sdlc_implement(number=42)

    # Assert
    assert "Target repo: upstream/sdlc" in result


@pytest.mark.asyncio
async def test_sdlc_implement_should_inject_target_repo_on_continue_path(monkeypatch):
    """Test sdlc_implement injects the target-repo directive on the continue path.

    Given:
        pr_state.dispatch returns a PrContext and resolve_repo reports a fork.
    When:
        sdlc_implement(number=42) is called.
    Then:
        It should append the target-repo directive alongside the PR metadata.
    """
    # Arrange
    context = PrContext(pr_number=42, head_ref="feature-x", url="https://example/pr/42")
    monkeypatch.setattr(pr_state, "dispatch", lambda number, repo=None, review=None: context)
    _patch_resolve_repo(monkeypatch, _fork_repo())

    # Act
    result = await sdlc_implement(number=42)

    # Assert
    assert "# Implement Continue Skill" in result
    assert "Target repo: upstream/sdlc" in result


@pytest.mark.asyncio
async def test_sdlc_implement_should_inject_target_repo_on_feedback_path(
    tmp_path, monkeypatch
):
    """Test sdlc_implement injects the target-repo directive on the feedback path.

    Given:
        pr_state.dispatch returns ReviewFindings and resolve_repo reports a fork.
    When:
        sdlc_implement(number=42) is called.
    Then:
        It should append the target-repo directive alongside the findings.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    path = _write_review_doc(tmp_path, ".sdlc/reviews/issue-#7", 1)
    review_findings = pr_state.parse_review_document(path, issue_number=7, iteration=1)
    monkeypatch.setattr(
        pr_state, "dispatch", lambda number, repo=None, review=None: review_findings
    )
    _patch_resolve_repo(monkeypatch, _fork_repo())

    # Act
    result = await sdlc_implement(number=42)

    # Assert
    assert "# Implement Feedback Skill" in result
    assert "Target repo: upstream/sdlc" in result


@pytest.mark.asyncio
async def test_sdlc_implement_should_inject_target_repo_when_gh_state_unavailable(monkeypatch):
    """Test sdlc_implement still injects the target repo on the diagnostic path.

    Given:
        pr_state.dispatch raises GhUnavailable but resolve_repo succeeds for a fork.
    When:
        sdlc_implement(number=42) is called.
    Then:
        It should return the fresh skill with the diagnostic note and the
        target-repo directive both appended.
    """
    # Arrange
    def raise_unavailable(_number, repo=None, review=None):
        raise GhUnavailable("gh state probe failed")

    monkeypatch.setattr(pr_state, "dispatch", raise_unavailable)
    _patch_resolve_repo(monkeypatch, _fork_repo())

    # Act
    result = await sdlc_implement(number=42)

    # Assert
    assert "# Implement Skill" in result
    assert "diagnostic" in result
    assert "Target repo: upstream/sdlc" in result


@pytest.mark.asyncio
async def test_sdlc_implement_should_omit_target_repo_when_resolve_unavailable(monkeypatch):
    """Test sdlc_implement omits the target-repo directive when resolve fails.

    Given:
        pr_state.dispatch returns None and resolve_repo raises GhUnavailable.
    When:
        sdlc_implement(number=42) is called.
    Then:
        It should return the fresh skill with no "Target repo" directive.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "dispatch", lambda number, repo=None, review=None: None)
    _patch_resolve_repo_unavailable(monkeypatch)

    # Act
    result = await sdlc_implement(number=42)

    # Assert
    assert "# Implement Skill" in result
    assert "Target repo: upstream/sdlc" not in result
    assert "omit --repo on gh commands that reference issues or PRs" not in result


@pytest.mark.asyncio
async def test_sdlc_test_should_inject_target_repo_directive(monkeypatch):
    """Test sdlc_test injects the upstream target-repo directive for a fork.

    Given:
        pr_state.resolve_repo reports the current repo is a fork.
    When:
        sdlc_test(issue_number=42) is called.
    Then:
        It should append a "Target repo: upstream/sdlc" directive.
    """
    # Arrange
    _patch_resolve_repo(monkeypatch, _fork_repo())

    # Act
    result = await sdlc_test(issue_number=42)

    # Assert
    assert "# Test Skill" in result
    assert "Target repo: upstream/sdlc" in result


@pytest.mark.asyncio
async def test_sdlc_test_should_omit_target_repo_when_gh_unavailable(monkeypatch):
    """Test sdlc_test appends no target-repo directive when gh is unavailable.

    Given:
        pr_state.resolve_repo raises GhUnavailable.
    When:
        sdlc_test(issue_number=42) is called.
    Then:
        It should return the skill content with no "Target repo" directive.
    """
    # Arrange
    _patch_resolve_repo_unavailable(monkeypatch)

    # Act
    result = await sdlc_test(issue_number=42)

    # Assert
    assert "# Test Skill" in result
    assert "Target repo: upstream/sdlc" not in result
    assert "omit --repo on gh commands that reference issues or PRs" not in result


@pytest.mark.asyncio
async def test_sdlc_commit_should_inject_target_repo_directive(monkeypatch):
    """Test sdlc_commit injects the upstream target-repo directive for a fork.

    Given:
        pr_state.resolve_repo reports the current repo is a fork.
    When:
        sdlc_commit() is called.
    Then:
        It should append a "Target repo: upstream/sdlc" directive.
    """
    # Arrange
    _patch_resolve_repo(monkeypatch, _fork_repo())

    # Act
    result = await sdlc_commit()

    # Assert
    assert "# Commit Skill" in result
    assert "Target repo: upstream/sdlc" in result


@pytest.mark.asyncio
async def test_sdlc_commit_should_omit_target_repo_when_gh_unavailable(monkeypatch):
    """Test sdlc_commit appends no target-repo directive when gh is unavailable.

    Given:
        pr_state.resolve_repo raises GhUnavailable.
    When:
        sdlc_commit() is called.
    Then:
        It should return the skill content with no "Target repo" directive.
    """
    # Arrange
    _patch_resolve_repo_unavailable(monkeypatch)

    # Act
    result = await sdlc_commit()

    # Assert
    assert "# Commit Skill" in result
    assert "Target repo: upstream/sdlc" not in result
    assert "omit --repo on gh commands that reference issues or PRs" not in result


@pytest.mark.asyncio
async def test_sdlc_pr_should_inject_target_repo_directive(monkeypatch):
    """Test sdlc_pr injects the upstream target-repo directive for a fork.

    Given:
        pr_state.resolve_repo reports the current repo is a fork.
    When:
        sdlc_pr(issue_number=42) is called.
    Then:
        It should append a "Target repo: upstream/sdlc" directive.
    """
    # Arrange
    _patch_resolve_repo(monkeypatch, _fork_repo())

    # Act
    result = await sdlc_pr(issue_number=42)

    # Assert
    assert "# PR Skill" in result
    assert "Target repo: upstream/sdlc" in result


@pytest.mark.asyncio
async def test_sdlc_pr_should_inject_target_repo_alongside_target_branch(monkeypatch):
    """Test sdlc_pr injects the target repo together with the branch override.

    Given:
        pr_state.resolve_repo reports a fork and a target branch is given.
    When:
        sdlc_pr(issue_number=42, target="master") is called.
    Then:
        It should append both the target-branch override and the target-repo
        directive.
    """
    # Arrange
    _patch_resolve_repo(monkeypatch, _fork_repo())

    # Act
    result = await sdlc_pr(issue_number=42, target="master")

    # Assert
    assert "Target branch override: master" in result
    assert "Target repo: upstream/sdlc" in result


@pytest.mark.asyncio
async def test_sdlc_pr_should_omit_target_repo_when_gh_unavailable(monkeypatch):
    """Test sdlc_pr appends no target-repo directive when gh is unavailable.

    Given:
        pr_state.resolve_repo raises GhUnavailable.
    When:
        sdlc_pr(issue_number=42) is called.
    Then:
        It should return the skill content with no "Target repo" directive.
    """
    # Arrange
    _patch_resolve_repo_unavailable(monkeypatch)

    # Act
    result = await sdlc_pr(issue_number=42)

    # Assert
    assert "# PR Skill" in result
    assert "Target repo: upstream/sdlc" not in result
    assert "omit --repo on gh commands that reference issues or PRs" not in result


@pytest.mark.asyncio
async def test_sdlc_review_should_inject_target_repo_directive(monkeypatch):
    """Test sdlc_review injects the upstream target-repo directive for a fork.

    Given:
        pr_state.resolve_repo reports the current repo is a fork.
    When:
        sdlc_review(pr_number=10) is called.
    Then:
        It should append a "Target repo: upstream/sdlc" directive.
    """
    # Arrange
    _patch_resolve_repo(monkeypatch, _fork_repo())

    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    assert "# Review Skill" in result
    assert "Target repo: upstream/sdlc" in result


@pytest.mark.asyncio
async def test_sdlc_review_should_omit_target_repo_when_gh_unavailable(monkeypatch):
    """Test sdlc_review appends no target-repo directive when gh is unavailable.

    Given:
        pr_state.resolve_repo raises GhUnavailable.
    When:
        sdlc_review(pr_number=10) is called.
    Then:
        It should return the skill content with no "Target repo" directive.
    """
    # Arrange
    _patch_resolve_repo_unavailable(monkeypatch)

    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    assert "# Review Skill" in result
    assert "Target repo: upstream/sdlc" not in result
    assert "omit --repo on gh commands that reference issues or PRs" not in result


@pytest.mark.asyncio
async def test_get_test_guide_should_return_bundled_python_guide():
    """Test the test/python URI serves the bundled Python testing guide.

    Given:
        The package bundles src/sdlc/test-guides/python.md.
    When:
        test_guide(stem="python") is called.
    Then:
        It should return the Python test guide content.
    """
    # Act
    result = await get_test_guide(stem="python")

    # Assert
    assert "# Python Test Guide" in result


@pytest.mark.asyncio
async def test_get_test_guide_should_return_error_when_stem_unknown():
    """Test an unknown test guide stem returns an error message.

    Given:
        A stem with no corresponding guide file.
    When:
        test_guide(stem="nonexistent") is called.
    Then:
        It should return a "not found" message.
    """
    # Act
    result = await get_test_guide(stem="nonexistent")

    # Assert
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_get_style_guide_should_return_bundled_markdown_guide():
    """Test the style/markdown URI serves the bundled Markdown style guide.

    Given:
        The package bundles src/sdlc/style-guides/markdown.md.
    When:
        style_guide(stem="markdown") is called.
    Then:
        It should return the Markdown style guide content.
    """
    # Act
    result = await get_style_guide(stem="markdown")

    # Assert
    assert "# Markdown style guide" in result


@pytest.mark.asyncio
async def test_get_default_config_should_return_shipped_json():
    """Test default_config returns the package config.json content.

    Given:
        The package ships src/sdlc/config.json.
    When:
        default_config() is called.
    Then:
        It should return parseable JSON containing the kebab-case guide-map.
    """
    # Act
    result = await get_default_config()

    # Assert
    parsed = json.loads(result)
    assert "guide-map" in parsed
    assert "test" in parsed["guide-map"]
    assert "style" in parsed["guide-map"]
    assert "role" in parsed["guide-map"]


@pytest.mark.asyncio
async def test_get_role_guide_should_return_bundled_general_purpose_role():
    """Test the role/general-purpose URI serves the bundled default role.

    Given:
        The package bundles src/sdlc/role-guides/general-purpose.md.
    When:
        get_role_guide(stem="general-purpose") is called.
    Then:
        It should return the general-purpose role content.
    """
    # Act
    result = await get_role_guide(stem="general-purpose")

    # Assert
    assert "# Role: general-purpose" in result


@pytest.mark.asyncio
async def test_get_role_guide_should_return_bundled_aie_role():
    """Test the role/aie URI serves the bundled AI-engineering role.

    Given:
        The package bundles src/sdlc/role-guides/aie.md.
    When:
        get_role_guide(stem="aie") is called.
    Then:
        It should return the aie role content with its lens and blocking policy.
    """
    # Act
    result = await get_role_guide(stem="aie")

    # Assert
    assert "# Role: aie" in result
    assert "## Lens / identity" in result
    assert "## Blocking policy" in result


@pytest.mark.asyncio
async def test_get_role_guide_should_return_error_when_stem_unknown():
    """Test an unknown role guide stem returns an error message.

    Given:
        A stem with no corresponding role file.
    When:
        get_role_guide(stem="nonexistent") is called.
    Then:
        It should return a "not found" message.
    """
    # Act
    result = await get_role_guide(stem="nonexistent")

    # Assert
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_role_template_should_return_template_content():
    """Test the role-template resource serves the bundled role template.

    Given:
        The package bundles src/sdlc/role-template.md.
    When:
        role_template() is called.
    Then:
        It should return the two required body section headings.
    """
    # Act
    result = await role_template()

    # Assert
    assert "## Lens / identity" in result
    assert "## Blocking policy" in result


@pytest.mark.asyncio
async def test_review_rationale_should_return_document_content():
    """Test the rationale resource serves the review skill's design reasoning.

    Given:
        The bundled review-rationale document.
    When:
        The sdlc://review-rationale resource is read.
    Then:
        It should return the document, carrying its no-rules disclaimer. The
        disclaimer is the safety property the whole split rests on: a rule can
        only be in the skill, because a normative sentence here is forbidden.
    """
    # Act
    result = await review_rationale()

    # Assert
    assert "# Review skill \u2014 design rationale" in result
    assert "**This document carries NO rules.**" in result
    assert "## R10. Step 10" in result


@pytest.mark.asyncio
async def test_review_template_should_return_template_content():
    """Test the review-template resource serves the bundled review template.

    Given:
        The package bundles src/sdlc/review-template.md.
    When:
        review_template() is called.
    Then:
        It should return all three severity-tier headings.
    """
    # Act
    result = await review_template()

    # Assert
    assert "## Tier 1 — Blocking" in result
    assert "## Tier 2 — Advisory" in result
    assert "## Tier 3 — Incidental" in result


@pytest.mark.asyncio
async def test_sdlc_roles_should_include_general_purpose_uri():
    """Test sdlc_roles lists the bundled general-purpose role as a URI.

    Given:
        The package bundles the general-purpose role.
    When:
        sdlc_roles() is called.
    Then:
        The general-purpose role URI is present in the result.
    """
    # Act
    result = await sdlc_roles()

    # Assert
    assert "sdlc://guides/role/general-purpose" in result


@pytest.mark.asyncio
async def test_sdlc_roles_should_include_aie_uri():
    """Test sdlc_roles lists the bundled aie role as a URI.

    Given:
        The package bundles the aie role alongside general-purpose.
    When:
        sdlc_roles() is called.
    Then:
        The aie role URI is present in the result.
    """
    # Act
    result = await sdlc_roles()

    # Assert
    assert "sdlc://guides/role/aie" in result


@pytest.mark.asyncio
async def test_sdlc_roles_should_return_role_uris():
    """Test every entry sdlc_roles returns is a role resource URI.

    Given:
        The discovered roles (at least the bundled general-purpose).
    When:
        sdlc_roles() is called.
    Then:
        Every returned entry is an sdlc://guides/role/ URI.
    """
    # Act
    result = await sdlc_roles()

    # Assert
    assert all(uri.startswith("sdlc://guides/role/") for uri in result)


@pytest.mark.asyncio
async def test_sdlc_role_scope_should_return_all_paths_for_general_purpose():
    """Test sdlc_role_scope scopes the whole diff to the general-purpose role.

    Given:
        The bundled default guide-map maps general-purpose to '**/*'.
    When:
        sdlc_role_scope(paths, role="general-purpose") is called.
    Then:
        Every supplied path is returned in scope.
    """
    # Arrange
    paths = ["src/sdlc/server.py", "README.md"]

    # Act
    result = await sdlc_role_scope(paths=paths, role="general-purpose")

    # Assert
    assert result == paths


@pytest.mark.asyncio
async def test_sdlc_role_scope_should_return_empty_for_unknown_role():
    """Test sdlc_role_scope returns no files for a role with no guide-map entry.

    Given:
        A role stem not mapped to any glob in the bundled guide-map.role.
    When:
        sdlc_role_scope(paths, role="nonexistent") is called.
    Then:
        It should return an empty list regardless of the supplied paths.
    """
    # Act
    result = await sdlc_role_scope(paths=["src/sdlc/server.py"], role="nonexistent")

    # Assert
    assert result == []


@pytest.mark.asyncio
async def test_sdlc_role_should_return_skill_with_target_role():
    """Test sdlc_role returns the role skill with the target role appended.

    Given:
        A role name.
    When:
        sdlc_role(name="architect") is called.
    Then:
        It should return the role skill content with "Target role: architect".
    """
    # Act
    result = await sdlc_role(name="architect")

    # Assert
    assert "# Role Skill" in result
    assert "Target role: architect" in result


@pytest.mark.asyncio
async def test_sdlc_role_should_inline_role_template():
    """Test sdlc_role inlines the role-document template into the prompt.

    Given:
        A role name.
    When:
        sdlc_role(name="architect") is called.
    Then:
        It should include the template's two required body section headings.
    """
    # Act
    result = await sdlc_role(name="architect")

    # Assert
    assert "## Lens / identity" in result
    assert "## Blocking policy" in result


@pytest.mark.asyncio
async def test_sdlc_guides_for_should_return_python_uri_for_py_path():
    """Test sdlc_guides_for resolves a Python source path to the python guide URI.

    Given:
        Default guide-map maps '**/*.py' to ['python'].
    When:
        sdlc_guides_for(['src/foo.py'], 'test') is called.
    Then:
        It should return ['sdlc://guides/test/python'].
    """
    # Act
    result = await sdlc_guides_for(paths=["src/foo.py"], kind="test")

    # Assert
    assert result == ["sdlc://guides/test/python"]


@pytest.mark.asyncio
async def test_sdlc_guides_for_should_return_markdown_uri_for_md_path():
    """Test sdlc_guides_for resolves a Markdown path to the markdown style guide.

    Given:
        Default guide-map maps '**/*.md' to ['markdown'] under 'style'.
    When:
        sdlc_guides_for(['README.md'], 'style') is called.
    Then:
        It should return ['sdlc://guides/style/markdown'].
    """
    # Act
    result = await sdlc_guides_for(paths=["README.md"], kind="style")

    # Assert
    assert result == ["sdlc://guides/style/markdown"]


@pytest.mark.asyncio
async def test_sdlc_guides_for_should_return_empty_when_path_unmatched():
    """Test sdlc_guides_for returns an empty list when no pattern matches.

    Given:
        Default guide-map has no entry for files of arbitrary extension '.xyz'.
    When:
        sdlc_guides_for(['foo.xyz'], 'test') is called.
    Then:
        It should return [].
    """
    # Act
    result = await sdlc_guides_for(paths=["foo.xyz"], kind="test")

    # Assert
    assert result == []


@pytest.mark.asyncio
async def test_sdlc_guides_for_should_union_matches_across_paths():
    """Test sdlc_guides_for unions matches across multiple input paths.

    Given:
        Multiple paths with different extensions.
    When:
        sdlc_guides_for is called with a Python and a Markdown path under 'style'.
    Then:
        Only the markdown guide is returned (default style map only knows .md).
    """
    # Act
    result = await sdlc_guides_for(paths=["foo.py", "README.md"], kind="style")

    # Assert
    assert result == ["sdlc://guides/style/markdown"]


@pytest.mark.asyncio
async def test_sdlc_guides_for_should_return_empty_when_paths_empty():
    """Test sdlc_guides_for returns an empty list when no paths are supplied.

    Given:
        An empty list of paths.
    When:
        sdlc_guides_for(paths=[], kind="test") is called.
    Then:
        It should return [].
    """
    # Act
    result = await sdlc_guides_for(paths=[], kind="test")

    # Assert
    assert result == []


@pytest.mark.asyncio
async def test_agents_md_should_return_file_content():
    """Test agents_md returns the AGENTS.md content.

    Given:
        The repo has AGENTS.md.
    When:
        agents_md() is called.
    Then:
        It should return the AGENTS.md content.
    """
    # Act
    result = await agents_md()

    # Assert
    assert "# SDLC Pipeline for LLM Agents" in result


@pytest.mark.asyncio
async def test_agents_md_should_carry_only_loadable_json_examples():
    """Test every fenced json block in AGENTS.md parses as JSON.

    Given:
        AGENTS.md, whose config example is the only worked example of
        .sdlc/config.json and which review.md directs agents to edit.
    When:
        Each ```json block is parsed.
    Then:
        All should load. JSON has no comments, and guides.load_user_config
        raises on a malformed file at import and on every review — so an
        annotated example that gets copied takes down every sdlc_* call for
        that project, not just the review.
    """
    # Arrange
    content = await agents_md()

    # Act
    blocks = re.findall(r"```json\n(.*?)```", content, re.DOTALL)

    # Assert
    assert blocks, "AGENTS.md carries no json examples to check"
    for block in blocks:
        json.loads(block)


@pytest.mark.asyncio
async def test_knowledge_graph_should_return_content_when_file_exists(monkeypatch, tmp_path):
    """Test knowledge_graph returns graph content when the file exists.

    Given:
        The knowledge graph file exists in the working directory.
    When:
        knowledge_graph() is called.
    Then:
        It should return the knowledge graph JSON content.
    """
    # Arrange
    kg_dir = tmp_path / ".understand-anything"
    kg_dir.mkdir()
    kg_file = kg_dir / "knowledge-graph.json"
    kg_file.write_text('{"project": "test"}')
    monkeypatch.chdir(tmp_path)

    # Act
    result = await knowledge_graph()

    # Assert
    assert '"project"' in result


@pytest.mark.asyncio
async def test_knowledge_graph_should_return_not_found_when_file_missing(monkeypatch, tmp_path):
    """Test knowledge_graph returns not-found message when file is missing.

    Given:
        The knowledge graph file does not exist in the working directory.
    When:
        knowledge_graph() is called.
    Then:
        It should return a "not found" message.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act
    result = await knowledge_graph()

    # Assert
    assert "No knowledge graph found" in result


@pytest.mark.asyncio
async def test_sdlc_review_should_omit_the_branch_directive_when_nothing_sets_one(
    tmp_path, monkeypatch
):
    """Test no branch directive is emitted when neither argument nor config sets one.

    Given:
        No target argument and no configured review branch.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        It should emit no review commit branch directive, leaving the skill to
        commit to the checked-out branch.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    assert "Review commit branch" not in _review_directive(result)


@pytest.mark.asyncio
async def test_sdlc_review_should_emit_the_resolved_issue_when_rereviewing_a_pr(
    tmp_path, monkeypatch
):
    """Test a PR-mode re-review names the linked issue like a fresh round does.

    Given:
        Issue 7 has review-1.md and PR 10 closes it.
    When:
        sdlc_review(pr_number=10, verify=1) is called.
    Then:
        It should emit the Resolved issue directive the skill is told to
        consume rather than re-derive.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)
    _write_review_doc(tmp_path, ".sdlc/reviews/issue-#7", 1)

    # Act
    result = await sdlc_review(pr_number=10, verify=1)

    # Assert
    assert "Resolved issue: #7" in _review_directive(result)


@pytest.mark.asyncio
async def test_sdlc_review_should_raise_when_the_requested_iteration_is_zero(
    tmp_path, monkeypatch
):
    """Test verify=0 is treated as a requested iteration, not as unset.

    Given:
        A slug directory holding review-1.md.
    When:
        sdlc_review(paths=[...], verify=0) is called.
    Then:
        It should raise ValueError for the missing round rather than silently
        running a fresh review.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1)

    # Act & assert
    with pytest.raises(ValueError):
        await sdlc_review(paths=["src/sdlc/server.py"], verify=0)


@pytest.mark.asyncio
async def test_sdlc_review_should_never_reference_a_verify_document(
    tmp_path, monkeypatch
):
    """Test the removed verdict artifact is absent from the whole prompt.

    Given:
        A slug directory holding review-1.md.
    When:
        sdlc_review(paths=[...], verify=1) is called.
    Then:
        No verify- filename fragment should appear anywhere in the returned
        prompt, inlined skill and template included.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], verify=1)

    # Assert
    assert "verify-" not in result
    assert "Verify document" not in result


@pytest.mark.asyncio
async def test_sdlc_review_should_omit_the_issue_line_when_rereviewing_paths(
    tmp_path, monkeypatch
):
    """Test a paths-mode seeded block is not keyed to an issue.

    Given:
        A slug directory holding review-1.md, reviewed in paths mode where no
        issue applies.
    When:
        sdlc_review(paths=[...], verify=1) is called.
    Then:
        The seeded block should carry no issue line, rather than the sentinel
        issue zero the endpoint passes internally.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], verify=1)

    # Assert
    directive = _review_directive(result)
    assert "Issue: #0" not in directive
    assert "Resolved issue:" not in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_lead_with_the_target_directive_when_rereviewing_a_pr(
    tmp_path, monkeypatch
):
    """Test the mode-selecting directive precedes the seeded findings block.

    Given:
        Issue 7 has review-1.md and PR 10 closes it.
    When:
        sdlc_review(pr_number=10, verify=1) is called.
    Then:
        Target PR should appear before the seeded-findings header, so the
        directive deciding whether gh runs is not buried behind a rendered
        dump of an entire prior review document.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)
    _write_review_doc(tmp_path, ".sdlc/reviews/issue-#7", 1)

    # Act
    directive = _review_directive(await sdlc_review(pr_number=10, verify=1))

    # Assert
    assert directive.index("Target PR: #10") < directive.index("Seeded findings —")


@pytest.mark.asyncio
async def test_sdlc_review_should_lead_with_the_target_directive_when_rereviewing_paths(
    tmp_path, monkeypatch
):
    """Test paths mode also puts its target directive ahead of the seeding.

    Given:
        A slug directory holding review-1.md for the requested paths.
    When:
        sdlc_review(paths=[...], verify=1) is called.
    Then:
        Target paths and its paths-mode note should both precede the
        seeded-findings header, since a missed note means running gh in the
        one mode that forbids it.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    slug = "server"
    _write_review_doc(tmp_path, f".sdlc/reviews/{slug}", 1)

    # Act
    directive = _review_directive(
        await sdlc_review(paths=["src/sdlc/server.py"], verify=1)
    )

    # Assert
    seeded = directive.index("Seeded findings —")
    assert directive.index("Target paths:") < seeded
    assert directive.index("Paths mode: no PR") < seeded


@pytest.mark.asyncio
async def test_sdlc_review_should_inherit_the_seeded_roles_when_rereviewing(
    tmp_path, monkeypatch
):
    """Test a re-review runs the roles the seeded document was produced under.

    Given:
        A review document whose Composition line names a non-default role.
    When:
        sdlc_review is re-run with --verify and no explicit roles.
    Then:
        It should dispatch that role rather than falling back to
        general-purpose, which would carry every seeded finding unexamined.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = ".sdlc/reviews/server"
    path = _write_review_doc(tmp_path, directory, 1)
    path.write_text(
        path.read_text().replace(
            "Header prose.",
            "Composition: 5 reviewer(s) per role across role(s) `aie` "
            "(5 × 1 = 5 reviewer subagents total).",
        )
    )

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], verify=1)

    # Assert
    directive = _review_directive(result)
    assert "Roles: aie" in directive
    assert "Roles: general-purpose" not in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_inherit_roles_from_the_elided_composition(
    tmp_path, monkeypatch
):
    """Test the template's own elided Composition shape still yields its roles.

    Given:
        A seeded document whose Composition line lists its roles followed by
        an ellipsis before the parenthetical, which is the shape the bundled
        template models and the skill tells the writing agent to follow.
    When:
        sdlc_review is re-run with --verify and no explicit roles.
    Then:
        Both roles should be inherited, and no coverage warning emitted.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = ".sdlc/reviews/server"
    path = _write_review_doc(tmp_path, directory, 1)
    path.write_text(
        path.read_text().replace(
            "Header prose.",
            "Composition: 3 reviewer(s) per role across role(s) `aie`, "
            "`general-purpose`, … (`3 × 2` reviewer subagents total).",
        )
    )

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], verify=1)

    # Assert
    directive = _review_directive(result)
    assert "Roles: aie, general-purpose" in directive
    assert "Seeded-role coverage warning" not in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_warn_when_the_seeded_roles_cannot_be_read(
    tmp_path, monkeypatch
):
    """Test a failed role inheritance is announced rather than silent.

    Given:
        A seeded document whose Composition line names its roles in prose,
        with no backticked stems to collect.
    When:
        sdlc_review is re-run with --verify and no explicit roles.
    Then:
        It should fall back to general-purpose AND say so. Narrowing chosen by
        the user is already warned about, so the strictly worse case — nobody
        chose it and every seeded finding from another role carries unexamined
        — must not be the quiet one.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = ".sdlc/reviews/server"
    path = _write_review_doc(tmp_path, directory, 1)
    path.write_text(
        path.read_text().replace(
            "Header prose.",
            "Composition: three reviewers per role across role(s) aie and "
            "general-purpose, six reviewer subagents total.",
        )
    )

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], verify=1)

    # Assert
    directive = _review_directive(result)
    assert "Roles: general-purpose" in directive
    assert "Seeded-role coverage warning" in directive
    assert "Composition line could not be read" in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_treat_an_empty_role_list_as_omitted(
    tmp_path, monkeypatch
):
    """Test roles=[] falls back rather than rendering a bare Roles line.

    Given:
        An explicit empty role list on a fresh round and on a re-review whose
        seeded document names a role.
    When:
        sdlc_review is called.
    Then:
        The fresh round should default to general-purpose and the re-review
        should still inherit, instead of emitting `Roles: ` and — on the
        re-review — warning against every seeded role at once.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = ".sdlc/reviews/server"
    path = _write_review_doc(tmp_path, directory, 1)
    path.write_text(
        path.read_text().replace(
            "Header prose.",
            "Composition: 5 reviewer(s) per role across role(s) `aie` "
            "(5 × 1 = 5 reviewer subagents total).",
        )
    )

    # Act
    fresh = _review_directive(
        await sdlc_review(paths=["src/sdlc/server.py"], roles=[])
    )
    rereview = _review_directive(
        await sdlc_review(paths=["src/sdlc/server.py"], roles=[], verify=1)
    )

    # Assert
    assert "Roles: general-purpose" in fresh
    assert "Roles: aie" in rereview
    assert "Seeded-role coverage warning" not in rereview


@pytest.mark.asyncio
async def test_sdlc_review_should_warn_when_roles_miss_the_seeded_set(
    tmp_path, monkeypatch
):
    """Test an explicit role list that cannot cover the seeded set is flagged.

    Given:
        A seeded document raised by `aie`, re-reviewed with a different role.
    When:
        sdlc_review is called with that explicit role list.
    Then:
        It should warn that the uncovered role's findings will carry without
        re-examination, and the roles it names to re-run with should be the
        UNION of the seeded and requested roles — naming the seeded roles
        alone would cure the gap by discarding the lens the caller chose.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = ".sdlc/reviews/server"
    path = _write_review_doc(tmp_path, directory, 1)
    path.write_text(
        path.read_text().replace(
            "Header prose.",
            "Composition: 1 reviewer(s) per role across role(s) `aie` "
            "(1 × 1 = 1 reviewer subagents total).",
        )
    )

    # Act
    result = await sdlc_review(
        paths=["src/sdlc/server.py"], verify=1, roles=["general-purpose"]
    )

    # Assert
    directive = _review_directive(result)
    assert "Seeded-role coverage warning" in directive
    assert "--roles aie general-purpose" in directive


@pytest.mark.asyncio
async def test_sdlc_review_rereview_should_emit_the_target_repo_directive(
    tmp_path, monkeypatch
):
    """Test a PR-mode re-review injects the target-repo directive too.

    Given:
        A seeded review document and a fork whose upstream is upstream/sdlc.
    When:
        sdlc_review is re-run with --verify in PR mode.
    Then:
        It should emit the directive, and emit it BEFORE the repository
        directive. Step 1 of the skill STOPs when the directive is absent, so
        a re-review that silently dropped it would halt every PR-mode pass —
        and the ordering is what keeps it in the leading span ahead of the
        seeded dump, which the surrounding comment block argues for and
        nothing asserted.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = ".sdlc/reviews/issue-#7"
    _write_review_doc(tmp_path, directory, 1)
    _patch_resolve_repo(monkeypatch, _fork_repo())
    monkeypatch.setattr(
        pr_state, "_find_closing_issue", lambda repo, number: 7
    )

    # Act
    result = await sdlc_review(pr_number=42, verify=1)

    # Assert — isolate the appended block; the skill prose documents both names
    directive = _review_directive(result)
    assert "Target repo: upstream/sdlc" in directive
    assert directive.index("Target repo: upstream/sdlc") < directive.index(
        "Review round:"
    )


@pytest.mark.asyncio
async def test_sdlc_review_should_warn_when_the_composition_line_is_unreadable_and_roles_are_explicit(
    tmp_path, monkeypatch
):
    """Test an explicit role list against an unreadable Composition line warns.

    Given:
        A seeded document whose Composition line names no backticked stems,
        re-reviewed with an explicit role list.
    When:
        sdlc_review is called with that list.
    Then:
        It should still emit a coverage warning. This is the case where
        coverage is least knowable — nothing is known about what raised the
        seeded findings — so reporting nothing is the worst available answer,
        and the tool docstring promises a warning here.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    directory = ".sdlc/reviews/server"
    path = _write_review_doc(tmp_path, directory, 1)
    path.write_text(
        path.read_text().replace(
            "Header prose.",
            "Composition: 1 reviewer(s) per role across role(s) aie, "
            "unbackticked and therefore unreadable.",
        )
    )

    # Act
    result = await sdlc_review(
        paths=["src/sdlc/server.py"], verify=1, roles=["general-purpose"]
    )

    # Assert
    directive = _review_directive(result)
    assert "Seeded-role coverage warning" in directive
    assert "could not be read" in directive
    assert "general-purpose" in directive


@pytest.mark.asyncio
async def test_sdlc_review_findings_should_return_the_requested_body(
    tmp_path, monkeypatch
):
    """Test the fetch serves a finding the outline elided.

    Given:
        A review document whose outline carries B1's heading but not its
        issue text.
    When:
        sdlc_review_findings is called for B1.
    Then:
        It should return the issue text and remediation, which is what a
        disposition or a remediation is judged against.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    path = _write_review_doc(tmp_path, ".sdlc/reviews/issue-#7", 1)

    # Act
    result = await sdlc_review_findings(str(path), ["B1"])

    # Assert
    assert "The symbol `foo` should be `bar`." in result
    assert "Rename `foo` to `bar`." in result


@pytest.mark.asyncio
async def test_sdlc_review_findings_should_report_a_path_outside_the_reviews_dir(
    tmp_path, monkeypatch
):
    """Test a misdirected fetch is refused as a message, not an exception.

    Given:
        A document path outside `.sdlc/reviews/`.
    When:
        sdlc_review_findings is called with it.
    Then:
        It should return an error string naming the refusal. A tool that
        raises here would surface as a transport failure rather than as
        something the agent can read and correct.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    outside = tmp_path / "elsewhere.md"
    outside.write_text("# not a review document\n")

    # Act
    result = await sdlc_review_findings(str(outside), ["B1"])

    # Assert
    assert result.startswith("Error:")
    assert "elsewhere.md" in result


@pytest.mark.asyncio
async def test_sdlc_review_findings_should_name_an_id_the_document_lacks(
    tmp_path, monkeypatch
):
    """Test a missing id comes back named rather than as a short answer.

    Given:
        A request for a finding the document does not hold.
    When:
        sdlc_review_findings is called.
    Then:
        It should name the id and say the document does not hold it, so the
        caller cannot mistake absence for a finding it already understood.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    path = _write_review_doc(tmp_path, ".sdlc/reviews/issue-#7", 1)

    # Act
    result = await sdlc_review_findings(str(path), ["B4"])

    # Assert
    assert "B4" in result
    assert "NOT FOUND" in result


@pytest.mark.asyncio
async def test_sdlc_implement_should_say_so_when_the_document_cannot_be_reread(
    tmp_path, monkeypatch
):
    """Test a document that vanished degrades loudly, not silently.

    Given:
        A parsed review document whose file is gone by the time the block is
        rendered.
    When:
        sdlc_implement renders it.
    Then:
        It should fall back to the full rendering and SAY the outline was
        unavailable, naming what the fallback does not carry. A consumer that
        believes it holds the ledgers when it does not will rewrite the
        document over them.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    path = _write_review_doc(tmp_path, ".sdlc/reviews/issue-#7", 1)
    review_findings = pr_state.parse_review_document(path, issue_number=7, iteration=1)
    path.unlink()
    monkeypatch.setattr(
        pr_state, "dispatch", lambda number, repo=None, review=None: review_findings
    )

    # Act
    result = await sdlc_implement(number=42)

    # Assert
    assert "could not be re-read" in result
    assert "ledgers" in result
    # The full rendering is what arrived, so the body IS present.
    assert "The symbol `foo` should be `bar`." in result


@pytest.mark.asyncio
async def test_sdlc_review_should_write_round_one_when_the_review_is_fresh(
    tmp_path, monkeypatch
):
    """Test a fresh review names round 1 and its metadata file.

    Given:
        A paths-mode target with no review documents on disk.
    When:
        sdlc_review is called without verify.
    Then:
        It should name review-1.md as the write target, round 1, and a
        metadata file beside the document.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    assert "Review document: .sdlc/reviews/server/review-1.md" in directive
    assert "Review round: 1" in directive
    assert "Review metadata: .sdlc/reviews/server/review-1.meta.json" in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_write_the_next_round_when_rereviewing_paths(
    tmp_path, monkeypatch
):
    """Test a paths-mode re-review writes a new round beside the seeded one.

    Given:
        A slug directory holding only round 1 of review 1.
    When:
        sdlc_review is called with verify=1 over the same paths.
    Then:
        It should seed from review-1.md and name review-1.2.md as the write
        target, leaving the seeded document as a read-only source.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], verify=1)

    # Assert
    directive = _review_directive(result)
    lines = directive.splitlines()
    assert "Re-review: review-1" in directive
    assert sum(1 for line in lines if line.startswith("Review document:")) == 1
    assert "Review document: .sdlc/reviews/server/review-1.2.md" in directive
    assert "Seeded document: .sdlc/reviews/server/review-1.md" in directive
    assert "Seeded from: .sdlc/reviews/server/review-1.md" in directive
    assert "Review round: 2" in directive
    assert "Review metadata: .sdlc/reviews/server/review-1.2.meta.json" in directive
    assert "Rename foo to bar" in directive
    assert "Target PR:" not in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_write_the_next_round_when_rereviewing_a_pr(
    tmp_path, monkeypatch
):
    """Test a PR-mode re-review writes a new round in the issue directory.

    Given:
        Issue 7's directory holding only round 1 of review 1.
    When:
        sdlc_review is called with a PR number and verify=1.
    Then:
        It should name review-1.2.md under issue-#7 as the write target and
        render the seeded finding.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)
    _write_review_doc(tmp_path, ".sdlc/reviews/issue-#7", 1)

    # Act
    result = await sdlc_review(pr_number=10, verify=1)

    # Assert
    directive = _review_directive(result)
    assert "Target PR: #10" in directive
    assert "Review document: .sdlc/reviews/issue-#7/review-1.2.md" in directive
    assert "Review round: 2" in directive
    assert "Rename foo to bar" in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_seed_from_the_latest_round(tmp_path, monkeypatch):
    """Test a re-review seeds from the highest round on disk.

    Given:
        Review 1 with rounds 1, 2 and 3 on disk, each naming a different
        finding id.
    When:
        sdlc_review is called with verify=1.
    Then:
        It should seed from round 3 alone and name round 4 as the write
        target.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1, finding_id="B1")
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1, finding_id="B2", round=2)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1, finding_id="B3", round=3)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], verify=1)

    # Assert
    directive = _review_directive(result)
    assert "Seeded document: .sdlc/reviews/server/review-1.3.md" in directive
    assert "Review document: .sdlc/reviews/server/review-1.4.md" in directive
    assert "Review round: 4" in directive
    assert "### B3 — " in directive
    assert "### B1 — " not in directive
    assert "### B2 — " not in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_keep_to_the_requested_review_when_rereviewing(
    tmp_path, monkeypatch
):
    """Test a re-review stays on the review it was asked for.

    Given:
        Reviews 1 and 2 of one target, review 2 naming finding B9.
    When:
        sdlc_review is called with verify=1.
    Then:
        It should write the next round of review 1 and neither start review
        3 nor seed review 2's finding.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 2, finding_id="B9")

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], verify=1)

    # Assert
    directive = _review_directive(result)
    assert "Review document: .sdlc/reviews/server/review-1.2.md" in directive
    assert "review-3.md" not in directive
    assert "B9" not in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_not_count_a_later_round_as_a_new_review(
    tmp_path, monkeypatch
):
    """Test a fresh review numbers itself past reviews, not past rounds.

    Given:
        Review 1 with rounds 1 and 2 on disk and no review 2.
    When:
        sdlc_review is called without verify.
    Then:
        It should name review-2.md as the write target.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1, round=2)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    assert "Review document: .sdlc/reviews/server/review-2.md" in directive
    assert "Review round: 1" in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_rereview_a_hashed_slug_directory(
    tmp_path, monkeypatch
):
    """Test a re-review resolves a glob target's hashed slug directory.

    Given:
        A multi-glob target whose review lives under its hashed slug.
    When:
        sdlc_review is called with verify=1 over the same globs.
    Then:
        It should seed from and write beside the document in that slug
        directory.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    paths = ["src/**/*.py", "tests/*.py"]
    slug = "src-py-tests-py-b174fbb7"
    _write_review_doc(tmp_path, f".sdlc/reviews/{slug}", 1)

    # Act
    result = await sdlc_review(paths=paths, verify=1)

    # Assert
    directive = _review_directive(result)
    assert f"Review document: .sdlc/reviews/{slug}/review-1.2.md" in directive
    assert f"Seeded from: .sdlc/reviews/{slug}/review-1.md" in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_place_the_seeded_block_after_the_template(
    tmp_path, monkeypatch
):
    """Test the seeded block trails every directive and the template.

    Given:
        A target with round 1 of review 1 on disk.
    When:
        sdlc_review is called with verify=1.
    Then:
        It should emit the write-target and round directives before the
        template and the seeded block after it.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], verify=1)

    # Assert
    template = result.index("\n\nReview document template:")
    assert result.index("\n\nReview round:") < template
    assert result.index("\n\nReview metadata:") < template
    assert template < result.index("\n\nSeeded findings —")


@pytest.mark.asyncio
async def test_sdlc_review_should_omit_the_round_directives_when_the_issue_is_unresolved(
    monkeypatch,
):
    """Test an unresolved linked issue yields no write-target directives.

    Given:
        A PR that closes no issue.
    When:
        sdlc_review is called in PR mode.
    Then:
        It should emit neither a round nor a metadata directive, since no
        document will be written.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: None)

    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    directive = _review_directive(result)
    assert "Resolved issue: unresolved" in directive
    assert "Review round:" not in directive
    assert "Review metadata:" not in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_reject_a_commit_branch_argument():
    """Test sdlc_review no longer accepts a commit-destination branch.

    Given:
        A caller passing the removed target argument.
    When:
        sdlc_review is called.
    Then:
        It should raise TypeError rather than silently ignore it.
    """
    # Act & assert
    with pytest.raises(TypeError):
        await sdlc_review(paths=["src/sdlc/server.py"], target="reviews")

