"""Execute the `review` skill's documented command blocks against real repos.

The skill is an instruction document, so its command blocks are its contract:
an agent following them has no way to discover that the surrounding prose
promises something the commands do not deliver. These tests extract the blocks
from the markdown and run them verbatim, in fixtures matching the cases the
prose names — notably a repository that TRACKS its review directory, which is
the case the exclusion pathspec exists for.
"""

from __future__ import annotations

import json
import re
import shlex
import string
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from skill_text import (
    EMPTY_TREE,
    GIT_ENV,
    _capture_script,
    _field,
    _guard_script,
    _meta,
    _promote_script,
    _restore_script,
    _step10_block,
    _substitute,
    _variant,
)

# Every test here shells out to real `git` or runs a skill command block
# through `bash`, so the marker is honest at module scope — which it was not
# when this suite shared a file with the document-assertion tests and
# `-m "not integration"` deselected 69 checks that touch no subprocess.
pytestmark = pytest.mark.integration

def _run(script: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script],
        cwd=cwd,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", **GIT_ENV},
        capture_output=True,
        text=True,
    )



def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", **GIT_ENV},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"git {args}: {result.stderr}"
    return result.stdout.strip()



@pytest.fixture
def tracked_sdlc_repo(tmp_path):
    """A feature branch off a published `main`, with `.sdlc` TRACKED in HEAD.

    Tracking `.sdlc` is the case `review.md`'s exclusion rationale names and
    the case a `.gitignore`-based fixture silently fails to exercise.
    """
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

    _git(work, "checkout", "-b", "feature")
    (work / "app.py").write_text("value = 2\n")
    (work / "new.py").write_text("added = True\n")
    reviews = work / ".sdlc" / "reviews"
    reviews.mkdir(parents=True)
    (reviews / "review-1.md").write_text("# pass 1\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Change app and track .sdlc")
    return work



def _make_review_repo(base: Path) -> Path:
    """Build a project whose `.sdlc` is its own repository, checked out on main."""
    repo = base / ".sdlc"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    (repo / ".gitkeep").write_text("")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "Initialize the review document repository")
    snapshot = repo / "reviews" / "issue-#1" / "snapshot-1"
    snapshot.mkdir(parents=True)
    (repo / "reviews" / "issue-#1" / "review-1.md").write_text("# pass 1\n")
    (snapshot / "meta.json").write_text("{}\n")
    (snapshot / "review.patch").write_text("")
    return base



def _derive(repo: str, document: str, cwd: Path) -> str:
    """Run the documented worktree derivation for one (repo, document) pair."""
    line = _step10_block("worktree list --porcelain").splitlines()[0]
    script = line.replace("<repo>", repo).replace(
        "<Review document in repository>", document
    )
    result = _run(script + '\necho "$worktree"', cwd)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()



@pytest.fixture
def review_repo(tmp_path):
    """A project whose `.sdlc` repository is checked out on a non-target branch.

    Mirrors the directive layout: the document is `.sdlc/reviews/...` from the
    working directory and `reviews/...` from the repository root.
    """
    project = tmp_path / "project"
    project.mkdir()
    return _make_review_repo(project)



@pytest.fixture
def remoteless_repo(tmp_path):
    """A repository with commits but no remotes configured."""
    work = tmp_path / "local"
    work.mkdir()
    _git(work, "init", "-b", "main")
    (work / "app.py").write_text("value = 1\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Add app")
    return work



@pytest.fixture
def headless_remote_repo(tmp_path):
    """A repository with a remote whose `HEAD` symref is absent."""
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "main")
    (work / "app.py").write_text("value = 1\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Add app")
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "push", "-u", "origin", "main")
    # `push -u` does not create refs/remotes/origin/HEAD; make sure of it, then
    # point the remote somewhere unreachable so `set-head -a` cannot recover it
    # either — the offline / sandboxed case the skill calls out.
    subprocess.run(["git", "symbolic-ref", "-d", "refs/remotes/origin/HEAD"],
                   cwd=work, capture_output=True,
                   env={"PATH": "/usr/bin:/bin:/usr/local/bin", **GIT_ENV})
    _git(work, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    return work



@pytest.fixture
def tracked_at_base(tmp_path):
    """A branch whose merge-base already tracks `.sdlc`, changing only source."""
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    work = tmp_path / "based"
    work.mkdir()
    _git(work, "init", "-b", "main")
    (work / "app.py").write_text("value = 1\n")
    reviews = work / ".sdlc" / "reviews"
    reviews.mkdir(parents=True)
    (reviews / "review-1.md").write_text("# base pass\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Add app and track .sdlc")
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "push", "-q", "-u", "origin", "main")
    _git(work, "checkout", "-q", "-b", "feature")
    (work / "app.py").write_text("value = 2\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Change app only")
    return work



@pytest.fixture
def ignored_sdlc_repo(tmp_path):
    """A repository whose .gitignore matches the review repository.

    This is the common case and the one this project is in: a leading `.*`
    rule makes `.sdlc` ignored, so `git add` names it in an "ignored by one of
    your .gitignore files" message and exits non-zero while staging the rest
    of the tree correctly.
    """
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    work = tmp_path / "ignored"
    work.mkdir()
    _git(work, "init", "-b", "main")
    (work / ".gitignore").write_text(".*\n!.gitignore\n")
    (work / "app.py").write_text("value = 1\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Add app")
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "push", "-q", "-u", "origin", "main")
    (work / ".sdlc" / "reviews").mkdir(parents=True)
    (work / ".sdlc" / "config.json").write_text('{"review-repo": "."}\n')
    (work / "feature.py").write_text("value = 2\n")
    return work



def test_capture_should_exclude_a_tracked_review_directory(tracked_sdlc_repo):
    """Test the documented capture omits `.sdlc` when the repo tracks it.

    Given:
        A feature branch whose HEAD tracks `.sdlc/reviews/review-1.md`.
    When:
        The step-2 capture blocks are run verbatim.
    Then:
        The snapshot tree should contain the source files and no `.sdlc`
        entry, and should not be the empty tree.
    """
    # Arrange
    snapshot = tracked_sdlc_repo / ".sdlc" / "reviews" / "snapshot-1"

    # Act
    result = _run(_capture_script(str(snapshot)), tracked_sdlc_repo)

    # Assert
    assert result.returncode == 0, result.stderr
    tree = _field(result.stdout, "TREE")
    assert tree != EMPTY_TREE
    entries = _git(tracked_sdlc_repo, "ls-tree", "-r", "--name-only", tree).split()
    assert "app.py" in entries
    assert "new.py" in entries
    assert not [e for e in entries if e.startswith(".sdlc")], entries



def test_capture_should_be_stable_when_only_the_review_changes(tracked_sdlc_repo):
    """Test two passes differing only in review content yield the same tree.

    Given:
        A capture taken, then `.sdlc` content changed and committed.
    When:
        The capture is run a second time.
    Then:
        Both passes should produce the same tree SHA, so the integrity check
        distinguishes code changes rather than review churn.
    """
    # Arrange
    snapshot = tracked_sdlc_repo / ".sdlc" / "reviews" / "snapshot-1"
    first = _run(_capture_script(str(snapshot)), tracked_sdlc_repo)
    assert first.returncode == 0, first.stderr

    # Act
    review = tracked_sdlc_repo / ".sdlc" / "reviews" / "review-1.md"
    review.write_text("# pass 2\n\nmany more findings\n")
    _git(tracked_sdlc_repo, "add", "-A", "--", ".sdlc")
    _git(tracked_sdlc_repo, "commit", "-m", "Update the review")
    second = _run(_capture_script(str(snapshot)), tracked_sdlc_repo)

    # Assert
    assert second.returncode == 0, second.stderr
    assert _field(first.stdout, "TREE") == _field(second.stdout, "TREE")



def test_restore_should_recompute_the_captured_tree(tracked_sdlc_repo):
    """Test the documented restore recipe reproduces `meta.tree`.

    Given:
        A capture producing a non-empty patch and a tree SHA.
    When:
        The step-10 restore recipe is run verbatim against the base.
    Then:
        The recomputed tree SHA should equal the captured one.
    """
    # Arrange
    snapshot = tracked_sdlc_repo / ".sdlc" / "reviews" / "snapshot-1"
    captured = _run(_capture_script(str(snapshot)), tracked_sdlc_repo)
    assert captured.returncode == 0, captured.stderr
    tree = _field(captured.stdout, "TREE")
    base = _field(captured.stdout, "BASE")
    patch = Path(_field(captured.stdout, "STAGING")) / "review.patch"
    assert patch.stat().st_size > 0, "the patch should not be empty"

    # Act
    result = _run(_restore_script(str(patch), base), tracked_sdlc_repo)

    # Assert
    assert result.returncode == 0, result.stderr
    recomputed = result.stdout.strip().splitlines()[-1].strip()
    assert re.fullmatch(r"[0-9a-f]{40}", recomputed), result.stdout
    assert recomputed == tree



def test_promote_should_clear_a_stale_artifact_from_a_previous_pass(tracked_sdlc_repo):
    """Test promoting a capture replaces the whole snapshot directory.

    Given:
        A snapshot directory holding a patch, a meta, and a third artifact
        left behind by an earlier pass.
    When:
        The capture runs and step 10 promotes it.
    Then:
        Only the freshly captured artifacts should remain, so nothing survives
        beside a `meta.json` that no longer describes it.
    """
    # Arrange
    snapshot = tracked_sdlc_repo / ".sdlc" / "reviews" / "snapshot-1"
    snapshot.mkdir(parents=True)
    (snapshot / "review.patch").write_text("stale patch\n")
    (snapshot / "meta.json").write_text('{"pass": 0}\n')
    (snapshot / "target_head").write_text("stale sidecar\n")
    captured = _run(_capture_script(str(snapshot)), tracked_sdlc_repo)
    assert captured.returncode == 0, captured.stderr

    # Act
    result = _run(_promote_script(str(snapshot)), tracked_sdlc_repo)

    # Assert
    assert result.returncode == 0, result.stderr
    assert (snapshot / "review.patch").read_text() != "stale patch\n"
    assert not (snapshot / "target_head").exists(), "a third artifact survived"
    assert '"pass": 0' not in (snapshot / "meta.json").read_text()



def test_commit_should_land_on_the_named_branch_when_it_differs_from_head(review_repo):
    """Test the documented commit reaches the branch the directive names.

    Given:
        A review repository checked out on `main`, with a `Review commit
        branch:` of `reviews`.
    When:
        Step 10's (b), (c) and (d) blocks are run verbatim.
    Then:
        The document commit should be reachable from `refs/heads/reviews` and
        absent from `refs/heads/main`.
    """
    # Arrange
    resolve = _step10_block("worktree list --porcelain")
    mirror = _step10_block("$worktree/$(dirname", "<Review snapshot directory>")
    fresh = _step10_block(
        'add "<Review document in repository>" "<Review snapshot in repository>"'
    )
    script = "set -e\n" + resolve + mirror + _variant(fresh, "worktree")
    repo = review_repo / ".sdlc"

    # Act
    result = _run(_substitute(script, review_repo), review_repo)

    # Assert
    assert result.returncode == 0, result.stderr
    assert "review: Add review-1" in _git(repo, "log", "--format=%s", "refs/heads/reviews")
    tracked = _git(repo, "ls-tree", "-r", "--name-only", "refs/heads/reviews")
    assert "reviews/issue-#1/review-1.md" in tracked
    assert "review: Add review-1" not in _git(repo, "log", "--format=%s", "refs/heads/main")



def test_worktree_should_not_be_shared_between_repositories(tmp_path):
    """Test two projects at the same round number get separate worktrees.

    Given:
        Two review repositories, each holding its own `review-1.md`.
    When:
        Step 10(b) is run in each.
    Then:
        Each worktree should be registered to its own repository, and the
        second should not adopt the first's directory.
    """
    # Arrange
    first = _make_review_repo(tmp_path / "first")
    second = _make_review_repo(tmp_path / "second")
    block = _step10_block("worktree list --porcelain")

    # Act
    left = _run(_substitute("set -e\n" + block, first), first)
    right = _run(_substitute("set -e\n" + block, second), second)

    # Assert
    assert left.returncode == 0, left.stderr
    assert right.returncode == 0, right.stderr
    left_path = _derive(str(first / ".sdlc"), "reviews/issue-#1/review-1.md", first)
    right_path = _derive(str(second / ".sdlc"), "reviews/issue-#1/review-1.md", second)
    assert left_path != right_path
    # The documented check is `grep -Fqx "worktree $worktree"`, which is line
    # anchored. A Python `in` is not: it is satisfied by /tmp/x against
    # /private/tmp/x, which is exactly the mismatch that made the real
    # predicate fail while this test passed.
    left_lines = _git(first / ".sdlc", "worktree", "list", "--porcelain").splitlines()
    right_lines = _git(second / ".sdlc", "worktree", "list", "--porcelain").splitlines()
    assert f"worktree {left_path}" in left_lines
    assert f"worktree {left_path}" not in right_lines



def test_snapshot_commit_should_mirror_the_bumped_document_into_the_worktree(
    review_repo,
):
    """Test the pass-header bump reaches the committed document on a re-review.

    Given:
        A re-review whose snapshot-and-header commit carries the pass bump, run
        on the worktree path a `review-branch` project takes.
    When:
        10(b), 10(c)'s mirror and the snapshot-and-header commit are run, with
        the working-directory document bumped to pass 2 beforehand.
    Then:
        The COMMITTED document should carry the bump. Without a `cp` in that
        block the worktree copy still holds the seeded content, so the commit
        that exists to record the bump records the state before it — and on a
        pass where every finding carries there is no later commit to fix it.
    """
    # Arrange
    document = review_repo / ".sdlc" / "reviews" / "issue-#1" / "review-1.md"
    resolve = _step10_block("worktree list --porcelain")
    mirror = _step10_block("$worktree/$(dirname", "<Review snapshot directory>")
    snapshot = _step10_block(
        'add "<Review snapshot in repository>" "<Review document in repository>"'
    )
    script = "set -e\n" + resolve + mirror
    setup = _run(_substitute(script, review_repo), review_repo)
    assert setup.returncode == 0, setup.stderr
    document.write_text("# pass 2\n")

    # Act
    result = _run(
        _substitute("set -e\n" + resolve + _variant(snapshot, "worktree"), review_repo),
        review_repo,
    )

    # Assert
    assert result.returncode == 0, result.stderr
    committed = _git(
        review_repo / ".sdlc",
        "show",
        "refs/heads/reviews:reviews/issue-#1/review-1.md",
    )
    assert committed.strip() == "# pass 2"



def test_worktree_resolution_should_reuse_a_registered_worktree(review_repo):
    """Test a second run adopts the worktree the first one registered.

    Given:
        Step 10(b) already run once, leaving a worktree registered to this
        repository — the state any interrupted pass leaves behind, since the
        worktree is removed only after the last commit of 10(d).
    When:
        10(b) is run again.
    Then:
        It should exit 0 and reuse it. The derivation must name the path the
        way `git worktree list --porcelain` prints it — normalized — or this
        branch is unreachable and the run aborts on its own worktree.
    """
    # Arrange
    block = _step10_block("worktree list --porcelain")
    script = _substitute("set -e\n" + block, review_repo)
    first = _run(script, review_repo)
    assert first.returncode == 0, first.stderr

    # Act
    second = _run(script, review_repo)

    # Assert
    assert second.returncode == 0, second.stderr
    assert "not registered" not in second.stderr
    derived = _derive(
        str(review_repo / ".sdlc"), "reviews/issue-#1/review-1.md", review_repo
    )
    registered = _git(
        review_repo / ".sdlc", "worktree", "list", "--porcelain"
    ).splitlines()
    assert f"worktree {derived}" in registered



def test_worktree_resolution_should_refuse_an_unregistered_directory(review_repo):
    """Test a foreign directory at the derived path is an error, not a reuse.

    Given:
        A plain directory sitting at the path step 10(b) derives.
    When:
        Step 10(b) is run.
    Then:
        It should fail loudly rather than silently commit into that directory.
    """
    # Arrange
    path = Path(_derive(str(review_repo / ".sdlc"), "reviews/issue-#1/review-1.md", review_repo))
    path.mkdir(parents=True, exist_ok=True)
    (path / "someone-elses.txt").write_text("not our worktree\n")

    # Act
    result = _run(_substitute("set -e\n" + _step10_block("worktree list --porcelain"), review_repo), review_repo)

    # Assert
    assert result.returncode != 0
    assert "not registered" in result.stderr



@settings(max_examples=20, deadline=None)
@given(
    first=st.text(alphabet=string.ascii_letters + string.digits + "/_-.", min_size=1, max_size=40),
    second=st.text(alphabet=string.ascii_letters + string.digits + "/_-.", min_size=1, max_size=40),
)
def test_worktree_derivation_should_differ_for_distinct_documents(first, second):
    """Test the derived worktree path is keyed on the document, not the round.

    Given:
        Any two distinct repository-relative document paths.
    When:
        The documented derivation is applied to each.
    Then:
        The two worktree paths should differ, so no two rounds collide.
    """
    # Arrange
    assume(first != second)
    here = Path(__file__).resolve().parent

    # Act
    left = _derive("/repo", first, here)
    right = _derive("/repo", second, here)

    # Assert
    assert left != right



def test_ignore_check_should_report_an_ignored_snapshot(review_repo):
    """Test the ignore check covers the snapshot, not the document alone.

    Given:
        A review repository whose `.gitignore` hides the snapshot directory.
    When:
        Step 10(a)'s check-ignore command is run verbatim.
    Then:
        It should exit zero and name the ignored path.
    """
    # Arrange
    (review_repo / ".sdlc" / ".gitignore").write_text("snapshot-*/\n")

    # Act
    result = _run(_substitute(_step10_block("check-ignore"), review_repo), review_repo)

    # Assert
    assert result.returncode == 0, result.stderr
    assert "snapshot-1" in result.stdout



def test_ignore_check_should_pass_when_neither_path_is_ignored(review_repo):
    """Test the ignore check reports a clean repository as clean.

    Given:
        A review repository with no `.gitignore`.
    When:
        Step 10(a)'s check-ignore command is run verbatim.
    Then:
        It should exit 1 — the documented "proceed" status — and not 128.
    """
    # Act
    result = _run(_substitute(_step10_block("check-ignore"), review_repo), review_repo)

    # Assert
    assert result.returncode == 1, f"rc={result.returncode}: {result.stderr}"
    assert result.stdout.strip() == ""



def test_capture_should_exclude_the_review_repo_from_a_subdirectory(tracked_sdlc_repo):
    """Test the exclusion holds regardless of the working directory.

    Given:
        A repository tracking `.sdlc`, and a subdirectory within it.
    When:
        The capture runs from the root and again from the subdirectory.
    Then:
        Both should yield the same tree, with no gitlink to the review repo.
    """
    # Arrange
    snapshot = tracked_sdlc_repo / ".sdlc" / "reviews" / "snapshot-1"
    nested = tracked_sdlc_repo / "src"
    nested.mkdir()
    (nested / "mod.py").write_text("x = 1\n")
    _git(tracked_sdlc_repo, "add", "-A")
    _git(tracked_sdlc_repo, "commit", "-m", "Add a subdirectory")

    # Act
    from_root = _run(_capture_script(str(snapshot)), tracked_sdlc_repo)
    from_nested = _run(_capture_script(str(snapshot)), nested)

    # Assert
    assert from_root.returncode == 0, from_root.stderr
    assert from_nested.returncode == 0, from_nested.stderr
    tree = _field(from_nested.stdout, "TREE")
    assert tree == _field(from_root.stdout, "TREE")
    listing = _git(tracked_sdlc_repo, "ls-tree", "-r", tree)
    assert "160000" not in listing, "a gitlink to the review repository was captured"



def test_capture_should_write_every_meta_field_itself(tracked_sdlc_repo):
    """Test no `meta.json` value has to survive the end of the invocation.

    Given:
        A repository with a resolvable anchor.
    When:
        The capture runs as a single invocation.
    Then:
        `meta.json` should already hold the resolved shas and refs, with no
        unsubstituted shell variable left in it.
    """
    # Arrange
    snapshot = tracked_sdlc_repo / ".sdlc" / "reviews" / "snapshot-1"

    # Act
    result = _run(_capture_script(str(snapshot)), tracked_sdlc_repo)

    # Assert
    assert result.returncode == 0, result.stderr
    meta = _meta(result.stdout)
    assert meta["base"] == _field(result.stdout, "BASE")
    assert meta["tree"] == _field(result.stdout, "TREE")
    assert meta["anchor_ref"] == "refs/remotes/origin/main"
    assert meta["upstream"], "upstream URL was not resolved"
    assert meta["excluded"] == [".sdlc"]
    assert "$" not in json.dumps(meta)



def test_capture_should_not_record_the_review_repo_as_deleted(tracked_at_base):
    """Test the patch excludes the review repo rather than deleting it.

    Given:
        A repository whose merge-base tracks `.sdlc`.
    When:
        The capture generates `review.patch`.
    Then:
        The patch should contain no deletion under the excluded path, so a
        restore does not lose it.
    """
    # Arrange
    work = tracked_at_base
    snapshot = work / ".sdlc" / "reviews" / "snapshot-1"

    # Act
    result = _run(_capture_script(str(snapshot)), work)

    # Assert
    assert result.returncode == 0, result.stderr
    patch = (Path(_field(result.stdout, "STAGING")) / "review.patch").read_text()
    assert patch, "the source change should still produce a patch"
    assert ".sdlc" not in patch, f"the excluded path appears in the patch:\n{patch}"
    assert "deleted file mode" not in patch



def test_capture_should_record_no_vcs_outside_a_repository(bare_tree):
    """Test a non-repository reaches its documented outcome, not an abort.

    Given:
        A directory of files that is not a git repository.
    When:
        The capture runs.
    Then:
        It should write `meta.json` alone, recording no version control and a
        null anchor, rather than exiting non-zero. The absent fields are JSON
        `null`, not `""` — a consumer written against the criterion tests
        `meta["base"] is None`, and an empty string is falsy but present.
    """
    # Act
    result = _run(_capture_script(str(bare_tree / "snapshot-1")), bare_tree)

    # Assert
    assert result.returncode == 0, result.stderr
    meta = _meta(result.stdout)
    assert meta["vcs"] == "none"
    assert meta["base"] is None
    assert meta["tree"] is None
    assert meta["anchor_ref"] is None
    assert meta["head"] is None
    assert not (Path(_field(result.stdout, "STAGING")) / "review.patch").exists()



def test_capture_should_abort_unanchored_when_no_remote_exists(remoteless_repo):
    """Test a repository with no remotes loses provenance, not the review.

    Given:
        A repository with commits but no configured remote.
    When:
        The capture runs.
    Then:
        It should record an unanchored capture and exit zero, so the round
        still reaches step 3.
    """
    # Act
    result = _run(_capture_script(str(remoteless_repo / "snap")), remoteless_repo)

    # Assert
    assert result.returncode == 0, result.stderr
    assert _meta(result.stdout)["vcs"] == "unanchored"
    assert "set-head" in result.stderr



def test_capture_should_abort_unanchored_when_the_remote_head_is_unset(
    headless_remote_repo,
):
    """Test an unresolvable remote HEAD is survivable, not fatal.

    Given:
        A repository with a remote whose HEAD symref does not exist and
        cannot be fetched.
    When:
        The capture runs.
    Then:
        It should record an unanchored capture and exit zero.
    """
    # Act
    result = _run(
        _capture_script(str(headless_remote_repo / "snap")), headless_remote_repo
    )

    # Assert
    assert result.returncode == 0, result.stderr
    assert _meta(result.stdout)["vcs"] == "unanchored"



def test_capture_should_record_a_dirty_worktree(tracked_sdlc_repo):
    """Test cleanliness is detected, which the HEAD sha alone cannot do.

    Given:
        The same commit, captured once clean and once with an uncommitted edit.
    When:
        The capture runs in each state.
    Then:
        `worktree_dirty` should distinguish them even though `HEAD` does not.
    """
    # Arrange
    snapshot = tracked_sdlc_repo / ".sdlc" / "reviews" / "snapshot-1"
    clean = _run(_capture_script(str(snapshot)), tracked_sdlc_repo)
    assert clean.returncode == 0, clean.stderr
    clean_meta = _meta(clean.stdout)   # staging is reused; read before overwriting

    # Act
    (tracked_sdlc_repo / "app.py").write_text("value = 999\n")
    dirty = _run(_capture_script(str(snapshot)), tracked_sdlc_repo)

    # Assert
    assert dirty.returncode == 0, dirty.stderr
    dirty_meta = _meta(dirty.stdout)
    assert clean_meta["worktree_dirty"] is False
    assert dirty_meta["worktree_dirty"] is True
    assert clean_meta["head"] == dirty_meta["head"]
    assert clean_meta["tree"] != dirty_meta["tree"]



def test_capture_should_leave_the_previous_snapshot_untouched(tracked_sdlc_repo):
    """Test an abandoned run cannot destroy the prior pass's capture.

    Given:
        A snapshot directory holding the previous pass's artifacts.
    When:
        The capture runs but the round is abandoned before step 10 promotes.
    Then:
        The previous pass's artifacts should still be intact.
    """
    # Arrange
    snapshot = tracked_sdlc_repo / ".sdlc" / "reviews" / "snapshot-1"
    snapshot.mkdir(parents=True)
    (snapshot / "review.patch").write_text("pass 1 patch\n")
    (snapshot / "meta.json").write_text('{"pass": 1}\n')

    # Act
    result = _run(_capture_script(str(snapshot)), tracked_sdlc_repo)

    # Assert
    assert result.returncode == 0, result.stderr
    assert (snapshot / "review.patch").read_text() == "pass 1 patch\n"
    assert json.loads((snapshot / "meta.json").read_text())["pass"] == 1



def test_restore_should_succeed_on_the_empty_patch(tmp_path):
    """Test the restore survives the empty patch the capture calls correct.

    Given:
        A clean tree on the default branch, where `base == HEAD`.
    When:
        The capture runs and the restore recipe is applied to its patch.
    Then:
        Both should succeed, and the restore should reproduce `meta.tree`.
    """
    # Arrange
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "main")
    (work / "app.py").write_text("value = 1\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Add app")
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "push", "-q", "-u", "origin", "main")
    captured = _run(_capture_script(str(work / "snap")), work)
    assert captured.returncode == 0, captured.stderr
    patch = Path(_field(captured.stdout, "STAGING")) / "review.patch"
    assert patch.stat().st_size == 0, "a clean default branch should yield no patch"

    # Act
    result = _run(_restore_script(str(patch), _field(captured.stdout, "BASE")), work)

    # Assert
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1].strip() == _field(captured.stdout, "TREE")



def test_empty_tree_guard_should_hold_under_sha256(tmp_path):
    """Test the guard derives its sentinel rather than hard-coding SHA-1.

    Given:
        A repository using the sha256 object format, where the empty tree has
        a different hash from the SHA-1 constant.
    When:
        The capture runs with an exclusion covering the whole tree.
    Then:
        The guard should still fire rather than capturing nothing silently.
    """
    # Arrange
    work = tmp_path / "wide"
    work.mkdir()
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", "--object-format=sha256", str(bare))
    _git(work, "init", "-b", "main", "--object-format=sha256")
    (work / "app.py").write_text("value = 1\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "Add app")
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "push", "-q", "-u", "origin", "main")
    script = _capture_script(str(work / "snap")).replace("excl='.sdlc'", "excl='*'")

    # Act
    result = _run(script, work)

    # Assert
    assert result.returncode != 0
    assert "snapshot tree is empty" in result.stderr



def test_capture_should_succeed_when_the_review_repo_is_gitignored(
    ignored_sdlc_repo,
):
    """Test a gitignored review repository does not abort the capture.

    Given:
        A repository whose .gitignore matches .sdlc, so `git add` exits
        non-zero while staging the whole tree correctly.
    When:
        The step-2 capture is run as the single invocation it documents.
    Then:
        It should exit 0 and write both artifacts, with the review repository
        absent from the captured tree. An exit-status guard here would abort
        the sequence before meta.json was written and the feature would
        silently never run on any project that ignores its review repository.
    """
    # Arrange
    snapshot = ignored_sdlc_repo / ".sdlc" / "reviews" / "snapshot-1"

    # Act
    result = _run(_capture_script(str(snapshot)), ignored_sdlc_repo)

    # Assert
    assert result.returncode == 0, result.stderr
    staging = Path(_field(result.stdout, "STAGING"))
    assert (staging / "meta.json").is_file()
    assert (staging / "review.patch").is_file()
    tree = _field(result.stdout, "TREE")
    listing = _git(ignored_sdlc_repo, "ls-tree", "-r", "--name-only", tree)
    assert "app.py" in listing
    assert "feature.py" in listing
    assert ".sdlc" not in listing



def test_capture_should_refuse_an_exclusion_that_excludes_nothing(
    tracked_sdlc_repo,
):
    """Test a review repository at the reviewed root is refused at step 2.

    Given:
        An exclusion pathspec whose relative path is `.`, which is what a
        review repository resolving to the reviewed tree's root produces.
    When:
        The step-2 capture is run.
    Then:
        It should abort before capturing. Anchored to the top, `.` excludes
        NOTHING, so the empty-tree sentinel never fires and the review
        repository would be captured into the snapshot of the code it reviews.
    """
    # Arrange
    snapshot = tracked_sdlc_repo / ".sdlc" / "reviews" / "snapshot-1"
    script = _capture_script(str(snapshot)).replace("excl='.sdlc'", "excl='.'")

    # Act
    result = _run(script, tracked_sdlc_repo)

    # Assert
    assert result.returncode != 0
    assert "excludes nothing" in result.stderr



@pytest.mark.parametrize(
    ("excl", "accepted"),
    [
        (".sdlc", True),
        ("docs/reviews", True),
        ("_reviews", True),
        (".sdlc/", True),
        ("/abs/path/.sdlc", False),
        ("~/x", False),
        ("unresolved", False),
        ("", False),
        (".", False),
        ("./", False),
        ("..", False),
        ("../x", False),
        ("x/..", False),
        ("a/../b", False),
        ("a//b", False),
        (" .sdlc", False),
        (".sdlc ", False),
        ("   ", False),
    ],
)
def test_exclusion_guard_should_accept_only_a_usable_relative_pathspec(
    excl, accepted, tmp_path
):
    """Test the guard rejects every pathspec shape that excludes nothing.

    Given:
        Step 2's exclusion guard, extracted verbatim.
    When:
        It runs against a pathspec shape.
    Then:
        It should accept only a non-empty relative path of ordinary
        components, and refuse everything else — the absolute form the
        `Review repository:` directive actually emits, the literal
        `unresolved` it carries on every project's first review, any
        root-or-ancestor form, a `~` prefix, and surrounding whitespace. The
        guard is an ALLOW-list, so a shape nobody enumerated is refused by
        default; the two blocklists that stood here were each wrong. A
        wrongly-accepted value excludes NOTHING, so the review repository
        lands in the snapshot of the code it reviews and the tree SHA churns
        every pass; no sentinel fires, because the empty-tree check only
        catches over-exclusion.
    """
    # Arrange
    script = _guard_script(excl)

    # Act
    result = _run(script, tmp_path)

    # Assert
    assert ("ACCEPTED" in result.stdout) is accepted, result
