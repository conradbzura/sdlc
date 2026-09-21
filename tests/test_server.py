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
    _read_skill,
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
    sdlc_role,
    sdlc_role_scope,
    sdlc_roles,
    sdlc_test,
    sdlc_understand_chat,
)


def _write_config(root, *, repo=None, branch=None):
    """Write a real .sdlc/config.json under root with the given review keys.

    Values resolve relative to the config file's PARENT, so a sibling of the
    working directory is named "../<name>" exactly as a user would have to
    write it.
    """
    config = {}
    if repo is not None:
        config["review-repo"] = repo
    if branch is not None:
        config["review-branch"] = branch
    path = Path(root) / ".sdlc" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))
    return path


@pytest.fixture(autouse=True)
def _isolated_review_config(monkeypatch, tmp_path):
    """Run every test from an empty directory carrying no review config.

    The review directives are rendered from a config read against the process
    working directory, so without this the developer's own checkout — which
    sets review-repo — would decide them and these tests would assert against
    the host's configuration rather than against the code. Tests that need a
    value write a real config with _write_config instead of reaching into
    module state.
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
    return pr_state._Repo(owner="upstream", name="sdlc", repo_flag="upstream/sdlc")


def _current_repo():
    """A resolved repo standing in for a non-fork (current repo applies)."""
    return pr_state._Repo(owner="conradbzura", name="sdlc", repo_flag=None)


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
    body = result[len(_read_skill("review")) :]
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
async def test_sdlc_implement_with_review_findings(monkeypatch):
    """Test sdlc_implement returns the feedback skill when review findings exist.

    Given:
        pr_state.dispatch returns a ReviewFindings instance for the number.
    When:
        sdlc_implement(number=42) is called.
    Then:
        It should return the feedback skill with the rendered review document.
    """
    # Arrange
    review_findings = ReviewFindings(
        issue_number=7,
        iteration=2,
        path=".sdlc/reviews/issue-#7/review-2.md",
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
        It should include the template's blocking and advisory tier headings.
    """
    # Arrange
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)

    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    assert "## Tier 1 — Blocking" in result
    assert "## Tier 2 — Advisory" in result


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
        It should include the template's blocking and advisory tier headings.
    """
    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    assert "## Tier 1 — Blocking" in result
    assert "## Tier 2 — Advisory" in result


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


def _write_review_doc(tmp_path, directory, iteration, finding_id="B1"):
    """Write a minimal one-finding review document under ``directory``.

    Returns the path written. ``directory`` is relative to ``tmp_path`` (the
    cwd the test chdirs into); the document carries a single blocking finding
    whose id is ``finding_id`` so the rendered output is identifiable.
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
    path = target / f"review-{iteration}.md"
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
    """Test a re-review propagates GhUnavailable when gh is down.

    Given:
        closing_issue raises GhUnavailable for PR 10.
    When:
        sdlc_review(pr_number=10, verify=1) is called.
    Then:
        It should raise GhUnavailable — a re-review cannot resolve the issue
        directory and does not degrade like the fresh-review path.
    """

    # Arrange
    def raise_unavailable(pr_number):
        raise GhUnavailable("gh executable not found on PATH")

    monkeypatch.setattr(pr_state, "closing_issue", raise_unavailable)

    # Act / Assert
    with pytest.raises(GhUnavailable):
        await sdlc_review(pr_number=10, verify=1)


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
async def test_sdlc_review_should_seed_findings_and_write_in_place_when_rereviewing_a_pr(
    tmp_path, monkeypatch
):
    """Test re-review PR mode seeds findings and writes the document in place.

    Given:
        Issue 7 has review-1.md with a blocking finding, and PR 10 closes it.
    When:
        sdlc_review(pr_number=10, verify=1) is called.
    Then:
        It should name review-1.md as the write target, seed the rendered
        finding, and carry the PR target with no verify document.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)
    _write_review_doc(tmp_path, ".sdlc/reviews/issue-#7", 1)

    # Act
    result = await sdlc_review(pr_number=10, verify=1)

    # Assert
    assert "Re-review: review-1" in result
    assert "Review document: .sdlc/reviews/issue-#7/review-1.md" in result
    assert "Verify document" not in result
    assert "Rename foo to bar" in result
    assert "Target PR: #10" in result


@pytest.mark.asyncio
async def test_sdlc_review_should_rewrite_the_slug_document_when_rereviewing_paths(
    tmp_path, monkeypatch
):
    """Test re-review paths mode rewrites the slug directory document in place.

    Given:
        A slug directory keyed by the single literal file's stem holds
        review-1.md with a blocking finding.
    When:
        sdlc_review(paths=["src/sdlc/server.py"], verify=1) is called.
    Then:
        It should name that same document as the write target, seed the
        rendered finding, and carry a Target paths block with no PR or
        resolved-issue directive.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], verify=1)

    # Assert
    directive = _review_directive(result)
    assert "Re-review: review-1" in directive
    assert "Review document: .sdlc/reviews/server/review-1.md" in directive
    assert "Verify document" not in directive
    assert "Rename foo to bar" in directive
    assert "Target paths:" in directive
    assert "Target PR:" not in directive
    assert "Resolved issue:" not in directive


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
        It should include the template's blocking and advisory tier headings.
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
async def test_sdlc_implement_should_inject_target_repo_on_feedback_path(monkeypatch):
    """Test sdlc_implement injects the target-repo directive on the feedback path.

    Given:
        pr_state.dispatch returns ReviewFindings and resolve_repo reports a fork.
    When:
        sdlc_implement(number=42) is called.
    Then:
        It should append the target-repo directive alongside the findings.
    """
    # Arrange
    review_findings = ReviewFindings(
        issue_number=7,
        iteration=1,
        path=".sdlc/reviews/issue-#7/review-1.md",
        findings=[
            ReviewFinding(
                id="B1",
                title="Rename foo to bar",
                severity="blocking",
                reference="`src/sdlc/server.py:64`",
                issue="The symbol foo should be bar.",
                remediation="- [x] Rename foo to bar.",
                touched_commit="`abc1234`",
            ),
        ],
    )
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
        It should return the blocking and advisory severity-tier headings.
    """
    # Act
    result = await review_template()

    # Assert
    assert "## Tier 1 — Blocking" in result
    assert "## Tier 2 — Advisory" in result


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
async def test_sdlc_review_should_name_the_configured_repository(
    tmp_path, monkeypatch
):
    """Test the declared review repository is named as an absolute path.

    Given:
        review-repo names .sdlc/reviews, a git repository beneath the config
        directory and distinct from the bare .sdlc fallback.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        It should name that repository by its absolute path.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".sdlc" / "reviews" / ".git").mkdir(parents=True)
    _write_config(tmp_path, repo="reviews")

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    expected = (tmp_path / ".sdlc" / "reviews").resolve().as_posix()
    assert f"Review repository: {expected}" in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_name_sdlc_when_it_is_a_repository(
    tmp_path, monkeypatch
):
    """Test .sdlc is used as the convention fallback when it is a repository.

    Given:
        No configured review-repo and a .sdlc directory holding a .git.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        It should name .sdlc by its absolute path.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".sdlc" / ".git").mkdir(parents=True)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    expected = (tmp_path / ".sdlc").resolve().as_posix()
    assert f"Review repository: {expected}" in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_report_unresolved_when_no_repository_is_declared(
    tmp_path, monkeypatch
):
    """Test an undeclared repository is reported as a question for the user.

    Given:
        No configured review-repo and a .sdlc that is not a repository.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        It should report the repository unresolved and direct the skill to ask
        the user rather than inferring one.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    assert "Review repository: unresolved" in directive
    assert "git init .sdlc" in directive
    assert "Do not guess." in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_report_unresolved_when_the_configured_repo_is_invalid(
    tmp_path, monkeypatch
):
    """Test a misconfigured review-repo is surfaced, not silently replaced.

    Given:
        review-repo names a directory that is not a repository, while .sdlc
        itself is one.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        It should report the configured path unresolved rather than falling
        back to the .sdlc repository the user did not name.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / ".sdlc" / ".git").mkdir(parents=True)
    _write_config(tmp_path, repo="../elsewhere")

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    assert "Review repository: unresolved" in directive
    assert "elsewhere" in directive
    assert (tmp_path / ".sdlc").resolve().as_posix() not in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_emit_the_document_path_relative_to_the_repository(
    tmp_path, monkeypatch
):
    """Test the staging path is rebased onto the review repository root.

    Given:
        .sdlc is the review repository, so the document lies below it.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        It should emit the document path relative to .sdlc, which is what git
        add can address, alongside the working-directory path it is written to.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".sdlc" / ".git").mkdir(parents=True)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    assert "Review document: .sdlc/reviews/server/review-1.md" in directive
    assert "Review document in repository: reviews/server/review-1.md" in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_refuse_a_review_repo_at_the_reviewed_root(
    tmp_path, monkeypatch
):
    """Test a review repo naming the reviewed root is refused, not resolved.

    Given:
        review-repo names the working directory itself, which is a repository.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        It should report the repository unresolved, because excluding the
        review repository from the snapshot would exclude the whole tree and
        abort the capture at step 2.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    _write_config(tmp_path, repo="..")

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    assert "Review repository: unresolved" in directive
    assert "Review document in repository:" not in directive


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
async def test_sdlc_review_should_emit_the_branch_directive_when_target_given(
    tmp_path, monkeypatch
):
    """Test an explicit target branch is emitted as the commit destination.

    Given:
        A target branch is supplied to sdlc_review.
    When:
        sdlc_review(paths=[...], target="reviews") is called.
    Then:
        It should name that branch as the review commit branch and call for a
        worktree so the reviewed tree is undisturbed.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], target="reviews")

    # Assert
    directive = _review_directive(result)
    assert "Review commit branch: reviews" in directive
    assert "worktree" in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_fall_back_to_the_configured_branch(
    tmp_path, monkeypatch
):
    """Test the review-branch config key supplies the branch when no target is given.

    Given:
        The loaded state carries a configured review branch and no target is
        supplied.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        It should name the configured branch as the review commit branch.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, branch="from-config")

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    assert "Review commit branch: from-config" in _review_directive(result)


@pytest.mark.asyncio
async def test_sdlc_review_should_prefer_the_target_over_the_configured_branch(
    tmp_path, monkeypatch
):
    """Test an explicit target outranks the configured review branch.

    Given:
        The loaded state carries a configured review branch and a different
        target is supplied.
    When:
        sdlc_review(paths=[...], target="explicit") is called.
    Then:
        It should name the supplied target, not the configured branch.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, branch="from-config")

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], target="explicit")

    # Assert
    directive = _review_directive(result)
    assert "Review commit branch: explicit" in directive
    assert "from-config" not in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_emit_commit_directives_when_rereviewing(
    tmp_path, monkeypatch
):
    """Test a re-review carries the same commit directives a fresh round does.

    Given:
        A slug directory holds review-1.md and a target branch is supplied.
    When:
        sdlc_review(paths=[...], verify=1, target="reviews") is called.
    Then:
        It should emit both the review repository and the commit branch
        directives.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1)

    # Act
    result = await sdlc_review(
        paths=["src/sdlc/server.py"], verify=1, target="reviews"
    )

    # Assert
    directive = _review_directive(result)
    assert "Review repository:" in directive
    assert "Review commit branch: reviews" in directive


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fresh_pr", "fresh_paths", "rereview_pr", "rereview_paths"])
async def test_sdlc_review_should_emit_one_commit_directive_set_in_every_mode(
    mode, tmp_path, monkeypatch
):
    """Test every review shape carries exactly one set of commit directives.

    Given:
        A review repository and a target branch, in each of the four shapes a
        review can take.
    When:
        sdlc_review is called in that shape.
    Then:
        It should emit exactly one Review repository line and exactly one
        Review commit branch line.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".sdlc" / ".git").mkdir(parents=True)
    _write_config(tmp_path, branch="reviews")
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)
    if mode.startswith("rereview"):
        directory = ".sdlc/reviews/issue-#7" if "pr" in mode else ".sdlc/reviews/server"
        _write_review_doc(tmp_path, directory, 1)
    kwargs = {"pr_number": 10} if "pr" in mode else {"paths": ["src/sdlc/server.py"]}
    if mode.startswith("rereview"):
        kwargs["verify"] = 1

    # Act
    result = await sdlc_review(**kwargs)

    # Assert
    directive = _review_directive(result)
    lines = directive.splitlines()
    assert sum(1 for line in lines if line.startswith("Review repository:")) == 1
    assert sum(1 for line in lines if line.startswith("Review commit branch:")) == 1
    assert sum(1 for line in lines if line.startswith("Review snapshot directory:")) == 1
    assert (
        sum(1 for line in lines if line.startswith("Review snapshot in repository:"))
        == 1
    )


@pytest.mark.asyncio
async def test_sdlc_review_should_emit_commit_directives_when_reviewing_a_pr(
    tmp_path, monkeypatch
):
    """Test the fresh PR path carries the commit directives, not only paths mode.

    Given:
        A PR closing issue 7, a .sdlc repository, and a target branch.
    When:
        sdlc_review(pr_number=10, target="reviews") is called.
    Then:
        It should emit the repository, repository-relative document, and commit
        branch directives.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".sdlc" / ".git").mkdir(parents=True)
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: 7)

    # Act
    result = await sdlc_review(pr_number=10, target="reviews")

    # Assert
    directive = _review_directive(result)
    assert "Review repository:" in directive
    assert (
        "Review document in repository: reviews/issue-#7/review-1.md" in directive
    )
    assert "Review commit branch: reviews" in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_omit_commit_directives_when_the_issue_is_unresolved(
    tmp_path, monkeypatch
):
    """Test no commit directives are emitted when no document will be written.

    Given:
        A PR that closes no issue, so the skill is told to stop and ask.
    When:
        sdlc_review(pr_number=10, target="reviews") is called.
    Then:
        It should emit no commit directives, since there is no document to
        write or commit on that branch.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pr_state, "closing_issue", lambda pr_number: None)

    # Act
    result = await sdlc_review(pr_number=10, target="reviews")

    # Assert
    directive = _review_directive(result)
    assert "Resolved issue: unresolved" in directive
    assert "Review repository:" not in directive
    assert "Review commit branch:" not in directive


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
async def test_sdlc_review_should_label_the_seeded_block_distinctly_from_the_target(
    tmp_path, monkeypatch
):
    """Test the write target cannot be confused with the seeded provenance line.

    Given:
        A slug directory holding review-1.md.
    When:
        sdlc_review(paths=[...], verify=1) is called.
    Then:
        It should emit exactly one Review document line, with the seeded block's
        provenance carried under a distinct Seeded from label.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], verify=1)

    # Assert
    directive = _review_directive(result)
    lines = directive.splitlines()
    assert sum(1 for line in lines if line.startswith("Review document:")) == 1
    assert "Review document: .sdlc/reviews/server/review-1.md" in directive
    assert "Seeded from: .sdlc/reviews/server/review-1.md" in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_rewrite_the_requested_iteration_in_place(
    tmp_path, monkeypatch
):
    """Test a re-review targets the requested round, never the next one.

    Given:
        A slug directory holding both review-1.md and review-2.md.
    When:
        sdlc_review(paths=[...], verify=1) is called.
    Then:
        It should name review-1.md as the write target and never advance the
        iteration.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 2, finding_id="B9")

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], verify=1)

    # Assert
    directive = _review_directive(result)
    assert "Review document: .sdlc/reviews/server/review-1.md" in directive
    assert "review-3.md" not in directive
    assert "B9" not in directive


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
@pytest.mark.parametrize(
    "target",
    ["", "   ", "main\nReview repository: /etc", "a b", "-lead", "..", "x.lock"],
)
async def test_sdlc_review_should_raise_when_the_target_branch_is_invalid(
    target, tmp_path, monkeypatch
):
    """Test a malformed target branch is rejected before it reaches a directive.

    Given:
        A target branch that git would reject, or that carries a newline able
        to forge a second directive line.
    When:
        sdlc_review is called with it.
    Then:
        It should raise ValueError.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act & assert
    with pytest.raises(ValueError):
        await sdlc_review(paths=["src/sdlc/server.py"], target=target)


@pytest.mark.asyncio
@pytest.mark.parametrize("closing", [7, None])
async def test_sdlc_review_should_raise_on_an_invalid_target_in_pr_mode(
    closing, tmp_path, monkeypatch
):
    """Test a malformed target is rejected in PR mode whether an issue links.

    Given:
        A PR target and a branch name carrying a newline, with and without a
        closing issue.
    When:
        sdlc_review is called with it.
    Then:
        It should raise in both cases. The branch directive is not rendered at
        all when no issue links, so validating only there would silently drop
        the user's explicit override on exactly that branch.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pr_state, "resolve_repo", _current_repo)
    monkeypatch.setattr(pr_state, "closing_issue", lambda _n: closing)

    # Act & assert
    with pytest.raises(ValueError):
        await sdlc_review(pr_number=10, target="main\nReview repository: /etc")


@pytest.mark.asyncio
async def test_sdlc_review_should_not_fall_back_to_config_when_the_target_is_empty(
    tmp_path, monkeypatch
):
    """Test an empty target is a malformed override, not a request to fall back.

    Given:
        A configured review branch and an empty explicit target.
    When:
        sdlc_review(paths=[...], target="") is called.
    Then:
        It should raise rather than silently using the configured branch.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, branch="from-config")

    # Act & assert
    with pytest.raises(ValueError):
        await sdlc_review(paths=["src/sdlc/server.py"], target="")


@pytest.mark.asyncio
async def test_sdlc_review_should_use_config_written_to_disk(tmp_path, monkeypatch):
    """Test a config file on disk reaches the rendered directives.

    Given:
        A .sdlc/config.json setting review-repo and review-branch, and the
        real reload path restored.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        It should name both the configured repository and branch, having
        re-read the config itself rather than relying on the import-time bind.
    """
    # Arrange
    sdlc_dir = tmp_path / ".sdlc"
    (sdlc_dir / ".git").mkdir(parents=True)
    (sdlc_dir / "config.json").write_text(
        json.dumps({"review-repo": ".", "review-branch": "from-disk"})
    )

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    assert "Review commit branch: from-disk" in directive
    assert f"Review repository: {sdlc_dir.resolve().as_posix()}" in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_not_emit_the_base_branch_override_directive(
    tmp_path, monkeypatch
):
    """Test the review target is a commit destination, not a base branch.

    Given:
        A target branch supplied to sdlc_review.
    When:
        sdlc_review(paths=[...], target="reviews") is called.
    Then:
        It should emit the commit-branch directive and never the base-branch
        override wording used by implement and pr.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], target="reviews")

    # Assert
    directive = _review_directive(result)
    assert "Review commit branch: reviews" in directive
    assert "Target branch override" not in directive


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
async def test_sdlc_review_should_rereview_a_hashed_slug_directory(
    tmp_path, monkeypatch
):
    """Test a re-review resolves the hashed slug a multi-path round wrote to.

    Given:
        A glob-and-multi-path target whose hashed slug directory holds
        review-1.md.
    When:
        sdlc_review is called over the same paths with verify=1.
    Then:
        It should name that same hashed directory's document as the write
        target.
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
    assert f"Review document: .sdlc/reviews/{slug}/review-1.md" in directive
    assert f"Seeded from: .sdlc/reviews/{slug}/review-1.md" in directive


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
async def test_sdlc_review_should_pair_the_snapshot_directory_with_the_document(
    tmp_path, monkeypatch
):
    """Test the snapshot directory carries the same round number as the document.

    Given:
        A slug directory holding review-1.md and review-2.md.
    When:
        sdlc_review is called with verify=1.
    Then:
        It should name snapshot-1 beside review-1.md, never the round the
        document is not being rewritten at.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".sdlc" / ".git").mkdir(parents=True)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 2, finding_id="B9")

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], verify=1)

    # Assert
    directive = _review_directive(result)
    assert "Review document: .sdlc/reviews/server/review-1.md" in directive
    assert "Review snapshot directory: .sdlc/reviews/server/snapshot-1/" in directive
    assert "snapshot-2" not in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_rebase_the_snapshot_onto_the_review_repository(
    tmp_path, monkeypatch
):
    """Test the snapshot's staging path is relative to the review repository.

    Given:
        .sdlc is the review repository, so the snapshot lies below it.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        It should emit the snapshot directory relative to .sdlc for staging,
        alongside the working-directory path it is written to.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".sdlc" / ".git").mkdir(parents=True)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    assert "Review snapshot directory: .sdlc/reviews/server/snapshot-1/" in directive
    assert "Review snapshot in repository: reviews/server/snapshot-1/" in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_refuse_a_repo_containing_the_reviewed_tree(
    tmp_path, monkeypatch
):
    """Test a review repository above the reviewed tree is refused, not rebased.

    Given:
        A repository two levels above the working directory, named by
        review-repo, so it contains the tree under review.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        It should report the repository unresolved and say why, rather than
        rebasing the review paths onto it — no top-anchored relative pathspec
        can exclude a directory that contains the reviewed tree, so the
        capture would embed the review repository in the snapshot of the code
        it reviews and the tree SHA would churn every pass unnoticed.
    """
    # Arrange
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    (tmp_path / ".git").mkdir()
    _write_config(work, repo="../..")

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    assert "Review repository: unresolved" in directive
    assert "contains the tree under review" in directive
    assert "is not a git repository" not in directive
    assert "Review snapshot in repository:" not in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_omit_the_snapshot_staging_path_when_unresolved(
    tmp_path, monkeypatch
):
    """Test no staging path is offered when there is no repository to stage into.

    Given:
        No review-repo and a .sdlc that is not a repository.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        It should still name where the snapshot is written, but offer no
        repository-relative path, since no repository is resolved.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    assert "Review snapshot directory: .sdlc/reviews/server/snapshot-1/" in directive
    assert "Review snapshot in repository:" not in directive
    assert "Review document in repository:" not in directive


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
async def test_sdlc_review_should_pick_up_a_review_repo_recorded_mid_session(
    tmp_path, monkeypatch
):
    """Test a review-repo written after an unresolved round is honored next call.

    Given:
        A working directory with no review repository, reviewed once, after
        which .sdlc/reviews is recorded as review-repo. That path is
        deliberately NOT the one the bare .sdlc fallback would produce, so
        only a genuine config re-read can name it.
    When:
        sdlc_review is called a second time.
    Then:
        The first round should report unresolved and the second should name
        the recorded repository, without the server being restarted.
    """
    # Arrange
    store = tmp_path / ".sdlc" / "reviews"
    (store / ".git").mkdir(parents=True)

    # Act
    first = _review_directive(await sdlc_review(paths=["src/sdlc/server.py"]))
    _write_config(tmp_path, repo="reviews")
    second = _review_directive(await sdlc_review(paths=["src/sdlc/server.py"]))

    # Assert
    assert "Review repository: unresolved" in first
    assert f"Review repository: {store.resolve().as_posix()}" in second


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
async def test_sdlc_review_should_report_the_document_unresolved_when_outside(
    tmp_path, monkeypatch
):
    """Test a document symlinked out of the repository reports unresolved.

    Given:
        A resolvable review repository at .sdlc, with the review directory
        inside it symlinked to a location outside it — the one arrangement
        that still puts a document outside a repository resolution accepted,
        since resolve_review_repo now refuses any configured repository that
        cannot contain .sdlc/reviews.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        Both repository-relative directives should read unresolved with the
        explanation, while the repository itself is still named — the two are
        deliberately independent, and step 10 of the review skill builds a
        STOP gate on exactly this string.
    """
    # Arrange
    sdlc = tmp_path / ".sdlc"
    (sdlc / ".git").mkdir(parents=True)
    outside = tmp_path / "outside"
    (outside / "server").mkdir(parents=True)
    (sdlc / "reviews").mkdir()
    (sdlc / "reviews" / "server").symlink_to(outside / "server")

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    expected = sdlc.resolve().as_posix()
    assert f"Review repository: {expected}" in directive
    assert "Review document in repository: unresolved" in directive
    assert "Review snapshot in repository: unresolved" in directive
    assert f"does not lie inside {expected}" in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_refuse_a_repository_that_cannot_hold_the_document(
    tmp_path, monkeypatch
):
    """Test a sibling review repository is refused at resolution.

    Given:
        review-repo names a sibling repository outside the reviewed tree,
        which can never contain the hardcoded .sdlc/reviews document path.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        The repository directive should read unresolved and carry the reason,
        so the user is told at the point the configuration is read rather
        than being handed a named repository the document directives then
        contradict.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs" / ".git").mkdir(parents=True)
    _write_config(tmp_path, repo="../docs")

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    assert "Review repository: unresolved" in directive
    assert "does not contain" in directive
    assert (tmp_path / "docs").resolve().as_posix() in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_resolve_a_symlinked_sdlc(tmp_path, monkeypatch):
    """Test a symlinked .sdlc yields a real repository-relative document path.

    Given:
        No configured review-repo and a .sdlc that is a symlink to a sibling
        repository.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        The document should be addressed from the link's target as a real
        path, rather than reported outside a repository that contains it —
        which would STOP step 10(a) on every pass and never commit a round.
    """
    # Arrange
    store = tmp_path / "review-store"
    (store / ".git").mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    (work / ".sdlc").symlink_to(store)
    monkeypatch.chdir(work)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    assert f"Review repository: {store.resolve().as_posix()}" in directive
    assert "Review document in repository: reviews/server/review-1.md" in directive
    assert "Review document in repository: unresolved" not in directive


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
        "Review repository:"
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
async def test_sdlc_review_should_name_the_resolved_path_when_the_repo_is_missing(
    tmp_path, monkeypatch
):
    """Test the unresolved directive names where the configured value landed.

    Given:
        A real .sdlc repository and `review-repo` set to ".sdlc" — the
        intuitive spelling, which resolves against the config file's parent to
        .sdlc/.sdlc and finds nothing.
    When:
        sdlc_review(paths=[...]) is called.
    Then:
        It should name the resolved path and suggest "." rather than claiming
        .sdlc is not a git repository, which is false and would send the user
        to initialize a repository that already exists on every call.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".sdlc" / ".git").mkdir(parents=True)
    _write_config(tmp_path, repo=".sdlc")

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    directive = _review_directive(result)
    nested = (tmp_path / ".sdlc" / ".sdlc").resolve().as_posix()
    assert "Review repository: unresolved" in directive
    assert nested in directive
    assert 'Did you mean "."' in directive


@pytest.mark.asyncio
async def test_sdlc_review_should_place_the_seeded_block_after_the_template(
    tmp_path, monkeypatch
):
    """Test the largest distractor trails every directive it could bury.

    Given:
        A re-review, whose seeded block is a dump of a whole prior document.
    When:
        The prompt is rendered.
    Then:
        Every commit-destination directive should precede the template, and
        the seeded block should follow it.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    _write_review_doc(tmp_path, ".sdlc/reviews/server", 1)

    # Act
    result = await sdlc_review(paths=["src/sdlc/server.py"], verify=1)

    # Assert
    template = result.index("\n\nReview document template:")
    assert result.index("Review snapshot directory:") < template
    assert result.index("Review document:") < template
    assert template < result.index("\n\nSeeded findings —")
