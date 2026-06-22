"""Tests for sdlc.server — MCP tools and resources."""

import json

import pytest

from sdlc import pr_state
from sdlc.pr_state import Finding, Findings, GhUnavailable, PrContext
from sdlc.server import (
    agents_md,
    get_default_config,
    get_role_guide,
    get_style_guide,
    get_test_guide,
    knowledge_graph,
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
    monkeypatch.setattr(pr_state, "dispatch", lambda number: None)

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
    monkeypatch.setattr(pr_state, "dispatch", lambda number: context)

    # Act
    result = await sdlc_implement(number=42)

    # Assert
    assert "# Implement Continue Skill" in result
    assert "feature-x" in result
    assert "https://example/pr/42" in result


@pytest.mark.asyncio
async def test_sdlc_implement_with_findings(monkeypatch):
    """Test sdlc_implement returns the feedback skill when findings exist.

    Given:
        pr_state.dispatch returns a Findings instance for the given number.
    When:
        sdlc_implement(number=42) is called.
    Then:
        It should return the feedback skill with formatted findings appended.
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
    monkeypatch.setattr(pr_state, "dispatch", lambda number: findings)

    # Act
    result = await sdlc_implement(number=42)

    # Assert
    assert "# Implement Feedback Skill" in result
    assert "src/sdlc/server.py:64" in result
    assert "rename foo to bar" in result


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
    def raise_unavailable(_number):
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
    monkeypatch.setattr(pr_state, "dispatch", lambda number: None)

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
    monkeypatch.setattr(pr_state, "dispatch", lambda number: None)

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
