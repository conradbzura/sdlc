"""Execute the `review` skill's documented command blocks against real repos.

The skill is an instruction document, so its command blocks are its contract:
an agent following them has no way to discover that the surrounding prose
promises something the commands do not deliver. These tests extract the blocks
from the markdown and run them verbatim, in fixtures matching the cases the
prose names — notably a repository that TRACKS its review documents, and a
working directory that is not the repository top.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from skill_text import (
    EMPTY_TREE,
    GIT_ENV,
    _field,
    _metadata_script,
    _overwrite_guard_script,
)

# Every test here shells out to real `git` or runs a skill command block
# through `bash`, so the marker is honest at module scope.
pytestmark = pytest.mark.integration

_ENV = {"PATH": "/usr/bin:/bin:/usr/local/bin", **GIT_ENV}


def _run(script: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script], cwd=cwd, env=_ENV, capture_output=True, text=True
    )


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=_ENV, capture_output=True, text=True
    )
    assert result.returncode == 0, f"git {args}: {result.stderr}"
    return result.stdout.strip()


def _record(cwd: Path, name: str = "review-1.meta.json", round: int = 1):
    """Run the metadata block from ``cwd`` and return ``(result, parsed meta)``."""
    metadata = cwd / ".sdlc" / "reviews" / "t" / name
    result = _run(_metadata_script(str(metadata), round), cwd)
    meta = json.loads(metadata.read_text()) if metadata.is_file() else None
    return result, meta


def _published(tmp_path: Path) -> Path:
    """A feature branch one commit ahead of a published `main`."""
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "main")
    (work / "app.py").write_text("value = 1\n")
    _git(work, "add", "app.py")
    _git(work, "commit", "-m", "Add app")
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "push", "-u", "origin", "main")
    _git(work, "remote", "set-head", "origin", "main")
    _git(work, "checkout", "-b", "feature")
    (work / "app.py").write_text("value = 2\n")
    _git(work, "commit", "-am", "Change app")
    return work


@pytest.fixture
def published_repo(tmp_path):
    """A clean feature branch off a published `main`, with no review documents."""
    return _published(tmp_path)


@pytest.fixture
def tracked_reviews_repo(tmp_path):
    """A feature branch whose HEAD TRACKS a review document.

    Tracking is the case the exclusion exists for and the one a
    `.gitignore`-based fixture silently fails to exercise.
    """
    work = _published(tmp_path)
    reviews = work / ".sdlc" / "reviews" / "t"
    reviews.mkdir(parents=True)
    (reviews / "review-0.md").write_text("# an earlier review\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Track a review document")
    return work


def test_metadata_block_should_record_the_reviewed_state(published_repo):
    """Test the block writes a complete record for a clean, anchored tree.

    Given:
        A clean feature branch one commit ahead of a published main.
    When:
        The step-2 metadata block is run with round 1.
    Then:
        It should write valid JSON naming the merge-base, the HEAD tree, the
        head sha, the round and a clean working tree.
    """
    # Act
    result, meta = _record(published_repo)

    # Assert
    assert result.returncode == 0, result.stderr
    assert meta["vcs"] == "git"
    assert meta["pass"] == 1
    assert meta["base"] == _git(published_repo, "merge-base", "HEAD", "origin/main")
    assert meta["tree"] == _git(published_repo, "rev-parse", "HEAD^{tree}")
    assert meta["head"] == _git(published_repo, "rev-parse", "HEAD")
    assert meta["worktree_dirty"] is False
    assert meta["excluded"] == ".sdlc/reviews"
    assert meta["anchor_ref"] == "refs/remotes/origin/main"


def test_metadata_block_should_record_the_round_it_is_given(published_repo):
    """Test the record's pass field is the injected round.

    Given:
        A clean published repository.
    When:
        The metadata block is run for round 3 of a review.
    Then:
        It should write pass 3 to the round's own metadata file.
    """
    # Act
    result, meta = _record(published_repo, name="review-1.3.meta.json", round=3)

    # Assert
    assert result.returncode == 0, result.stderr
    assert meta["pass"] == 3


def test_metadata_block_should_hash_the_same_tree_across_rounds(tracked_reviews_repo):
    """Test writing review documents does not move the recorded tree.

    Given:
        A repository that tracks a review document, with the code unchanged
        between two rounds.
    When:
        The block is run, a new review document and its metadata are left on
        disk, and the block is run again.
    Then:
        Both rounds should record the same tree, and neither should report
        the working tree dirty.
    """
    # Arrange
    reviews = tracked_reviews_repo / ".sdlc" / "reviews" / "t"

    # Act
    _, first = _record(tracked_reviews_repo)
    (reviews / "review-1.md").write_text("# round 1\n")
    _, second = _record(tracked_reviews_repo, name="review-1.2.meta.json", round=2)

    # Assert
    assert first["tree"] == second["tree"]
    assert first["tree"] != EMPTY_TREE
    assert (first["worktree_dirty"], second["worktree_dirty"]) == (False, False)


def test_metadata_block_should_leave_review_documents_out_of_the_tree(
    tracked_reviews_repo,
):
    """Test a tracked review document is excluded from the hashed tree.

    Given:
        A repository whose HEAD tracks a document under .sdlc/reviews.
    When:
        The metadata block is run.
    Then:
        The recorded tree should hold the source file and no review document.
    """
    # Act
    result, meta = _record(tracked_reviews_repo)

    # Assert
    assert result.returncode == 0, result.stderr
    listing = _git(tracked_reviews_repo, "ls-tree", "-r", "--name-only", meta["tree"])
    assert listing.splitlines() == ["app.py"]


def test_metadata_block_should_exclude_reviews_from_a_subdirectory(published_repo):
    """Test the exclusion follows the working directory below the top.

    Given:
        A working directory one level below the repository top, holding its
        own .sdlc/reviews with a document in it.
    When:
        The metadata block is run from that subdirectory.
    Then:
        It should exclude that directory by its top-relative path, so the
        recorded tree contains the package's source and no review document.
    """
    # Arrange
    package = published_repo / "pkg"
    reviews = package / ".sdlc" / "reviews" / "t"
    reviews.mkdir(parents=True)
    (package / "mod.py").write_text("x = 1\n")
    (reviews / "review-0.md").write_text("# an earlier review\n")
    _git(published_repo, "add", "-A")
    _git(published_repo, "commit", "-m", "Add a package with reviews")

    # Act
    result, meta = _record(package)

    # Assert
    assert result.returncode == 0, result.stderr
    assert meta["excluded"] == "pkg/.sdlc/reviews"
    listing = _git(
        published_repo, "ls-tree", "-r", "--name-only", "--full-name", meta["tree"]
    )
    assert listing.splitlines() == ["app.py", "pkg/mod.py"]
    assert meta["worktree_dirty"] is False


def test_metadata_block_should_report_uncommitted_source_as_dirty(published_repo):
    """Test untracked source work is hashed and reported.

    Given:
        A published repository with one untracked source file.
    When:
        The metadata block is run.
    Then:
        It should report the working tree dirty and record a tree that
        contains the untracked file and differs from HEAD's.
    """
    # Arrange
    (published_repo / "new.py").write_text("added = True\n")

    # Act
    result, meta = _record(published_repo)

    # Assert
    assert result.returncode == 0, result.stderr
    assert meta["worktree_dirty"] is True
    assert meta["tree"] != _git(published_repo, "rev-parse", "HEAD^{tree}")
    listing = _git(published_repo, "ls-tree", "-r", "--name-only", meta["tree"])
    assert "new.py" in listing.splitlines()


def test_metadata_block_should_leave_the_real_index_untouched(published_repo):
    """Test hashing untracked work stages nothing in the user's index.

    Given:
        A published repository with one untracked source file.
    When:
        The metadata block is run.
    Then:
        The file should still be untracked and nothing should be staged.
    """
    # Arrange
    (published_repo / "new.py").write_text("added = True\n")

    # Act
    result, _ = _record(published_repo)

    # Assert
    assert result.returncode == 0, result.stderr
    assert _git(published_repo, "diff", "--cached", "--name-only") == ""
    assert "?? new.py" in _git(published_repo, "status", "--porcelain").splitlines()


def test_metadata_block_should_tolerate_an_ignored_sdlc_directory(published_repo):
    """Test a project that ignores .sdlc still gets a complete record.

    Given:
        A repository whose .gitignore covers .sdlc, so git warns that the
        excluded path is ignored.
    When:
        The metadata block is run.
    Then:
        It should succeed and record HEAD's tree.
    """
    # Arrange
    (published_repo / ".gitignore").write_text(".sdlc\n")
    _git(published_repo, "add", ".gitignore")
    _git(published_repo, "commit", "-m", "Ignore .sdlc")

    # Act
    result, meta = _record(published_repo)

    # Assert
    assert result.returncode == 0, result.stderr
    assert meta["tree"] == _git(published_repo, "rev-parse", "HEAD^{tree}")
    assert meta["worktree_dirty"] is False


def test_metadata_block_should_record_nulls_outside_a_repository(tmp_path):
    """Test a tree that is not a repository yields a record, not a failure.

    Given:
        A directory that is not inside any git repository.
    When:
        The metadata block is run.
    Then:
        It should write vcs "none" with a null base and tree.
    """
    # Arrange
    bare_tree = tmp_path / "plain"
    bare_tree.mkdir()
    (bare_tree / "notes.md").write_text("hello\n")

    # Act
    result = subprocess.run(
        ["bash", "-c", _metadata_script(str(bare_tree / "review-1.meta.json"))],
        cwd=bare_tree,
        env={**_ENV, "GIT_CEILING_DIRECTORIES": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    meta = json.loads((bare_tree / "review-1.meta.json").read_text())

    # Assert
    assert result.returncode == 0, result.stderr
    assert meta["vcs"] == "none"
    assert (meta["base"], meta["tree"], meta["head"]) == (None, None, None)


def test_metadata_block_should_record_the_tree_without_an_anchor(tmp_path):
    """Test a repository with no default-branch ref is recorded unanchored.

    Given:
        A repository with a commit and no remote at all.
    When:
        The metadata block is run.
    Then:
        It should write vcs "unanchored" with a null base, still record the
        tree, and tell the user how to fix the anchor.
    """
    # Arrange
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "main")
    (work / "app.py").write_text("value = 1\n")
    _git(work, "add", "app.py")
    _git(work, "commit", "-m", "Add app")

    # Act
    result, meta = _record(work)

    # Assert
    assert result.returncode == 0, result.stderr
    assert meta["vcs"] == "unanchored"
    assert meta["base"] is None
    assert meta["tree"] == _git(work, "rev-parse", "HEAD^{tree}")
    assert "set-head" in result.stderr


def test_metadata_block_should_report_the_values_it_wrote(published_repo):
    """Test the shell variables and the written record agree.

    Given:
        A clean published repository.
    When:
        The metadata block is run and its variables are echoed.
    Then:
        The echoed tree and base should equal the JSON fields, so the record
        was written by the invocation that computed them.
    """
    # Act
    result, meta = _record(published_repo)

    # Assert
    assert _field(result.stdout, "TREE") == meta["tree"]
    assert _field(result.stdout, "BASE") == meta["base"]


def test_overwrite_guard_should_proceed_when_the_document_is_new(tmp_path):
    """Test the step-10 guard creates the directory and lets a new file through.

    Given:
        A review directory that does not exist yet.
    When:
        The step-10 guard block is run for a document path inside it.
    Then:
        It should create the directory and proceed.
    """
    # Arrange
    directory = tmp_path / ".sdlc" / "reviews" / "t"
    document = directory / "review-1.2.md"

    # Act
    result = _run(_overwrite_guard_script(str(directory), str(document)), tmp_path)

    # Assert
    assert result.returncode == 0, result.stderr
    assert "PROCEED" in result.stdout
    assert directory.is_dir()


def test_overwrite_guard_should_stop_when_the_document_exists(tmp_path):
    """Test the step-10 guard refuses a path that is already a file.

    Given:
        A review document already on disk at the write target.
    When:
        The step-10 guard block is run.
    Then:
        It should exit non-zero, name the file, and leave it unchanged.
    """
    # Arrange
    directory = tmp_path / ".sdlc" / "reviews" / "t"
    directory.mkdir(parents=True)
    document = directory / "review-1.2.md"
    document.write_text("# an earlier round\n")

    # Act
    result = _run(_overwrite_guard_script(str(directory), str(document)), tmp_path)

    # Assert
    assert result.returncode == 1
    assert "PROCEED" not in result.stdout
    assert "refusing to overwrite" in result.stderr
    assert document.read_text() == "# an earlier round\n"
