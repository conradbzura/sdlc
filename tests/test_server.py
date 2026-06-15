"""Tests for sdlc.server — MCP tools and resources."""

import json

import pytest

from sdlc import pr_state
from sdlc.pr_state import Finding, Findings, GhUnavailable, PrContext
from sdlc.server import (
    agents_md,
    get_default_config,
    get_style_guide,
    get_test_guide,
    knowledge_graph,
    sdlc_commit,
    sdlc_guides_for,
    sdlc_implement,
    sdlc_issue,
    sdlc_pr,
    sdlc_review,
    sdlc_test,
    sdlc_understand_chat,
)


@pytest.mark.asyncio
async def test_sdlc_issue_should_return_skill_when_no_context():
    """Test sdlc_issue returns skill content when called with no arguments.

    Given:
        No context argument.
    When:
        sdlc_issue() is called.
    Then:
        It should return the issue skill content.
    """
    # Act
    result = await sdlc_issue()

    # Assert
    assert "# Issue Skill" in result
    assert "User context" not in result


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
async def test_sdlc_review_should_interpolate_pr_number():
    """Test sdlc_review returns skill content with interpolated PR number.

    Given:
        A PR number.
    When:
        sdlc_review(pr_number=10) is called.
    Then:
        It should return review skill content with #10 appended.
    """
    # Act
    result = await sdlc_review(pr_number=10)

    # Assert
    assert "# Review Skill" in result
    assert "#10" in result


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
