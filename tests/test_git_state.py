"""Tests for sdlc.git_state — review-repository resolution and branch validity."""

import dataclasses
import os

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sdlc.git_state import ReviewRepo, resolve_review_repo, validate_branch_name


def _make_repo(directory):
    """Create ``directory`` and give it a .git directory, returning the path."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".git").mkdir(exist_ok=True)
    return directory


class TestReviewRepo:
    """Tests for the ReviewRepo value object."""

    def test___init___should_expose_the_root_and_configured_flag(self, tmp_path):
        """Test a ReviewRepo carries the values it was constructed with.

        Given:
            A repository root and a configured flag.
        When:
            A ReviewRepo is instantiated with them.
        Then:
            It should expose both on its public attributes.
        """
        # Act
        repo = ReviewRepo(root=tmp_path, configured=True)

        # Assert
        assert repo.root == tmp_path
        assert repo.configured is True

    def test___setattr___should_raise_when_an_attribute_is_assigned(self, tmp_path):
        """Test a ReviewRepo cannot be mutated after construction.

        Given:
            A constructed ReviewRepo.
        When:
            One of its attributes is assigned.
        Then:
            It should raise FrozenInstanceError.
        """
        # Arrange
        repo = ReviewRepo(root=tmp_path, configured=False)

        # Act & assert
        with pytest.raises(dataclasses.FrozenInstanceError):
            repo.root = tmp_path / "other"

    def test___eq___should_compare_by_value(self, tmp_path):
        """Test two ReviewRepo values with identical fields are equal.

        Given:
            Two ReviewRepo values built from the same root and flag, and a third
            differing in one field.
        When:
            They are compared.
        Then:
            It should report the matching pair equal and the differing one not.
        """
        # Arrange
        one = ReviewRepo(root=tmp_path, configured=True)
        same = ReviewRepo(root=tmp_path, configured=True)
        other = ReviewRepo(root=tmp_path, configured=False)

        # Act & assert
        assert one == same
        assert one != other


def test_resolve_review_repo_should_resolve_relative_to_the_config_dir(tmp_path):
    """Test a configured path is resolved against the config file's parent.

    Given:
        A repository beside the .sdlc directory and review-repo set to '..'.
    When:
        resolve_review_repo is called with .sdlc as the config directory.
    Then:
        It should return the sibling repository, flagged as configured.
    """
    # Arrange
    _make_repo(tmp_path)
    config_dir = tmp_path / ".sdlc"
    config_dir.mkdir()

    # Act
    result = resolve_review_repo("..", config_dir, tmp_path)

    # Assert
    assert result == ReviewRepo(root=tmp_path.resolve(), configured=True)


def test_resolve_review_repo_should_return_sdlc_when_unset_and_sdlc_is_a_repo(tmp_path):
    """Test .sdlc is used as the convention fallback when it is a repository.

    Given:
        No configured review-repo and a .sdlc directory holding a .git.
    When:
        resolve_review_repo is called.
    Then:
        It should return .sdlc, flagged as not configured.
    """
    # Arrange
    sdlc_dir = _make_repo(tmp_path / ".sdlc")

    # Act
    result = resolve_review_repo(None, None, tmp_path)

    # Assert
    assert result == ReviewRepo(root=sdlc_dir.resolve(), configured=False)


def test_resolve_review_repo_should_return_no_root_when_unset_and_sdlc_is_not_a_repo(
    tmp_path,
):
    """Test an unset key with a plain .sdlc resolves to nothing.

    Given:
        No configured review-repo and a .sdlc directory with no .git.
    When:
        resolve_review_repo is called.
    Then:
        It should return a null root so the caller asks the user.
    """
    # Arrange
    (tmp_path / ".sdlc").mkdir()

    # Act
    result = resolve_review_repo(None, None, tmp_path)

    # Assert
    assert result == ReviewRepo(root=None, configured=False)


def test_resolve_review_repo_should_not_walk_up_to_an_enclosing_repository(tmp_path):
    """Test an enclosing repository is never selected without being configured.

    Given:
        A repository root whose .sdlc is not itself a repository.
    When:
        resolve_review_repo is called with no configured path.
    Then:
        It should return a null root rather than inferring the enclosing repo.
    """
    # Arrange
    _make_repo(tmp_path)
    (tmp_path / ".sdlc").mkdir()

    # Act
    result = resolve_review_repo(None, None, tmp_path)

    # Assert
    assert result == ReviewRepo(root=None, configured=False)


def test_resolve_review_repo_should_return_no_root_when_configured_path_is_not_a_repo(
    tmp_path,
):
    """Test a configured path that is not a repository is reported, not replaced.

    Given:
        review-repo naming a directory that exists but holds no .git, beside a
        .sdlc directory that IS a repository.
    When:
        resolve_review_repo is called.
    Then:
        It should return a null root flagged as configured, rather than falling
        back to the .sdlc repository the user did not name.
    """
    # Arrange
    (tmp_path / "elsewhere").mkdir()
    _make_repo(tmp_path / ".sdlc")

    # Act
    result = resolve_review_repo("elsewhere", tmp_path, tmp_path)

    # Assert
    assert result == ReviewRepo(root=None, configured=True)


def test_resolve_review_repo_should_return_no_root_when_configured_path_is_missing(
    tmp_path,
):
    """Test a configured path that does not exist resolves to nothing.

    Given:
        review-repo naming a directory that does not exist.
    When:
        resolve_review_repo is called.
    Then:
        It should return a null root flagged as configured.
    """
    # Act
    result = resolve_review_repo("no-such-dir", tmp_path, tmp_path)

    # Assert
    assert result == ReviewRepo(root=None, configured=True)


def test_resolve_review_repo_should_accept_a_git_file(tmp_path):
    """Test a .git file, as in a worktree or submodule, counts as a repository.

    Given:
        A configured directory whose .git is a file rather than a directory.
    When:
        resolve_review_repo is called.
    Then:
        It should treat that directory as the repository root.
    """
    # Arrange
    target = tmp_path / "wt"
    target.mkdir()
    (target / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n")

    # Act
    result = resolve_review_repo("wt", tmp_path, tmp_path)

    # Assert
    assert result == ReviewRepo(root=target.resolve(), configured=True)


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission checks")
def test_resolve_review_repo_should_return_no_root_when_the_path_is_unreadable(
    tmp_path,
):
    """Test an unreadable configured path is reported rather than raising.

    Given:
        review-repo naming a directory inside an unreadable parent.
    When:
        resolve_review_repo is called.
    Then:
        It should return a null root instead of propagating PermissionError.
    """
    # Arrange
    locked = tmp_path / "locked"
    (locked / "repo").mkdir(parents=True)
    os.chmod(locked, 0o000)

    # Act
    try:
        result = resolve_review_repo("locked/repo", tmp_path, tmp_path)
    finally:
        os.chmod(locked, 0o755)

    # Assert
    assert result == ReviewRepo(root=None, configured=True)


def test_resolve_review_repo_should_default_to_the_process_directory_when_no_cwd_given(
    tmp_path, monkeypatch
):
    """Test the current working directory is used when no cwd is supplied.

    Given:
        The process is chdir'd into a directory whose .sdlc is a repository.
    When:
        resolve_review_repo is called without a cwd argument.
    Then:
        It should resolve against that directory.
    """
    # Arrange
    sdlc_dir = _make_repo(tmp_path / ".sdlc")
    monkeypatch.chdir(tmp_path)

    # Act
    result = resolve_review_repo(None, None)

    # Assert
    assert result == ReviewRepo(root=sdlc_dir.resolve(), configured=False)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        " padded",
        "padded ",
        "with\nnewline",
        "with\rcarriage",
        "with\ttab",
        "-leading-dash",
        "double..dot",
        "trailing.lock",
        "trailing.",
        "/leading-slash",
        "trailing-slash/",
        "double//slash",
        "tilde~name",
        "caret^name",
        "colon:name",
        "question?name",
        "star*name",
        "bracket[name",
        "back\\slash",
        "with space",
        "at@{brace",
        "@",
    ],
)
def test_validate_branch_name_should_raise_when_the_name_is_invalid(name):
    """Test names git would reject, or that could forge a directive, are refused.

    Given:
        A branch name violating a git ref-format rule, or containing a control
        character that could forge a second directive line.
    When:
        validate_branch_name is called with it.
    Then:
        It should raise ValueError.
    """
    # Act & assert
    with pytest.raises(ValueError):
        validate_branch_name(name)


@pytest.mark.parametrize(
    "name", ["main", "reviews", "review-log", "feature/x", "v1.2-rc", "a_b"]
)
def test_validate_branch_name_should_return_the_name_when_it_is_valid(name):
    """Test ordinary branch names are accepted unchanged.

    Given:
        A branch name that satisfies the git ref-format rules.
    When:
        validate_branch_name is called with it.
    Then:
        It should return the name unchanged.
    """
    # Act
    result = validate_branch_name(name)

    # Assert
    assert result == name


@settings(max_examples=200)
@given(st.text())
def test_validate_branch_name_should_never_accept_a_control_character(name):
    """Test no generated name carrying a control character is ever accepted.

    Given:
        Any generated text, which may contain control characters.
    When:
        validate_branch_name is called with it.
    Then:
        It should raise whenever the name contains a control character, so a
        name can never forge an extra directive line.
    """
    # Arrange
    has_control = any(ord(c) < 0x20 or ord(c) == 0x7F for c in name)

    # Act
    try:
        validate_branch_name(name)
    except ValueError:
        return

    # Assert
    assert not has_control
