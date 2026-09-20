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
import string
import subprocess
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

SKILL = Path(__file__).resolve().parents[1] / "src/sdlc/skills/review.md"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _skill_text() -> str:
    return SKILL.read_text()


def _section(text: str, heading: str) -> str:
    """Return the body of the section introduced by `heading`."""
    start = text.index(heading)
    nxt = text.find("\n### ", start + len(heading))
    end = nxt if nxt != -1 else len(text)
    return text[start:end]


def _bash_blocks(text: str) -> list[str]:
    """Return every ```bash fenced block in `text`, in order."""
    return re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL)


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


def _fill_meta(script: str, pass_number: int = 1) -> str:
    """Substitute the `meta.json` placeholders the agent is meant to fill in."""
    script = re.sub(r'^\s*"pr": <[^>]*>,\n', "", script, flags=re.MULTILINE)
    script = script.replace("<pr|paths>", "paths")
    script = script.replace("<k>", str(pass_number))
    return re.sub(r"<true\|false[^>]*>", "false", script)


def _capture_script(snapshot_dir: str) -> str:
    """The step-2 capture, extracted verbatim and pointed at `snapshot_dir`."""
    section = _section(_skill_text(), "#### Capture the reviewed state (all modes)")
    blocks = _bash_blocks(section)
    assert len(blocks) == 3, f"expected 3 capture blocks, found {len(blocks)}"
    script = "set -e\n" + "".join(blocks)
    # Fail loudly if the extraction drifted off the block the prose describes.
    assert "git read-tree --empty" in script
    assert "':(exclude,top).sdlc'" in script
    assert "git commit-tree" in script
    script = _fill_meta(script.replace("<Review snapshot directory>", snapshot_dir))
    return script + '\necho "TREE=$tree"\necho "BASE=$base"\necho "STAGING=$staging"\n'


def _promote_script(snapshot_dir: str) -> str:
    """The step-10(c) promote, which moves the staged capture into place."""
    blocks = [b for b in _step10_blocks() if '"$staging"' in b]
    assert len(blocks) == 1, f"expected 1 promote block, found {len(blocks)}"
    return "set -e\n" + blocks[0].replace("<Review snapshot directory>", snapshot_dir)


def _restore_script(patch: str, base: str) -> str:
    """The step-10 restore recipe, extracted verbatim.

    Nothing is appended. The block's own `git write-tree` is the command under
    test and prints the recomputed SHA on stdout; appending another one would
    run it after the block's `unset GIT_INDEX_FILE` and read the real index
    instead — which is the very defect this recipe was corrected for.
    """
    section = _section(_skill_text(), "### 10. Write and commit the review document")
    blocks = [b for b in _bash_blocks(section) if "git apply" in b]
    assert len(blocks) == 1, f"expected 1 restore block, found {len(blocks)}"
    script = "set -e\n" + blocks[0]
    assert "export GIT_INDEX_FILE" in script
    assert "git read-tree --empty" in script
    assert "':(exclude,top).sdlc'" in script
    script = script.replace('"<path to review.patch>"', f'"{patch}"')
    script = script.replace('"<meta.base>"', f'"{base}"')
    return script


def _field(output: str, name: str) -> str:
    match = re.search(rf"^{name}=(.+)$", output, flags=re.MULTILINE)
    assert match is not None, f"{name} missing from:\n{output}"
    return match.group(1).strip()


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


def test_skill_should_not_carry_shell_state_between_steps():
    """Test no step depends on a shell variable another step assigned.

    Given:
        The review skill markdown.
    When:
        Its bash blocks are scanned for the scratch and worktree handles.
    Then:
        `$scratch` should be gone entirely, and `$worktree` should be assigned
        in every block that reads it.
    """
    # Arrange
    text = _skill_text()

    # Act
    blocks = _bash_blocks(text)
    unassigned = [
        block
        for block in blocks
        if "$worktree" in block and 'worktree="${TMPDIR' not in block
    ]

    # Assert
    assert "$scratch" not in text
    assert unassigned == []
    # Guard the assertion above against passing because nothing uses the handle.
    assert any("$worktree" in block for block in blocks)


def test_rereview_brief_should_withhold_the_seeded_findings_from_phase_one():
    """Test the phase-1 dispatch carries no seeded-finding text.

    Given:
        The step-7 re-review dispatch protocol.
    When:
        Its phase-1 instruction is read.
    Then:
        It should require the fresh-round brief alone, and defer the seeded
        set to a second message.
    """
    # Arrange
    section = _section(_skill_text(), "### 7. Dispatch reviewer subagents (N per role)")

    # Act
    phase_one = section[section.index("1. **Phase 1"): section.index("2. Collect")]

    # Assert
    assert "NOTHING else" in phase_one
    assert "no seeded finding" in phase_one
    assert "<the seeded findings" not in phase_one
    assert "SendMessage" in section


# --- Step 10: the commit protocol --------------------------------------------


def _step10_section() -> str:
    return _section(_skill_text(), "### 10. Write and commit the review document")


def _step10_blocks() -> list[str]:
    return _bash_blocks(_step10_section())


def _step10_block(*needles: str) -> str:
    """Return the single step-10 block containing every needle."""
    matches = [b for b in _step10_blocks() if all(n in b for n in needles)]
    assert len(matches) == 1, f"expected 1 block matching {needles}, found {len(matches)}"
    return matches[0]


def _variant(block: str, label: str) -> str:
    """Return the `# <label>` half of a block showing two commit variants."""
    marker = f"# {label}\n"
    assert marker in block, f"{marker!r} missing from:\n{block}"
    body = block[block.index(marker) + len(marker) :]
    nxt = body.find("\n# ")
    return body[:nxt] if nxt != -1 else body


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


def _substitute(script: str, project: Path, branch: str = "reviews") -> str:
    message = project / "msg.txt"
    message.write_text("review: Add review-1 with 0 blocking findings\n")
    for key, value in {
        "<repo>": str(project / ".sdlc"),
        "<Review document in repository>": "reviews/issue-#1/review-1.md",
        "<Review snapshot in repository>": "reviews/issue-#1/snapshot-1",
        "<Review document>": ".sdlc/reviews/issue-#1/review-1.md",
        "<Review snapshot directory>": ".sdlc/reviews/issue-#1/snapshot-1",
        "<branch>": branch,
        "<message-file>": str(message),
    }.items():
        script = script.replace(key, value)
    return script


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
    mirror = _step10_block("$worktree/$(dirname")
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
    assert left_path in _git(first / ".sdlc", "worktree", "list", "--porcelain")
    assert left_path not in _git(second / ".sdlc", "worktree", "list", "--porcelain")


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


def test_rereview_should_verify_the_document_against_an_on_disk_target():
    """Test the terminal equality check reads the filesystem, not recollection.

    Given:
        Steps 9 and 10 of the skill.
    When:
        The re-review verification is read.
    Then:
        Step 9 should write a target file and step 10 should diff against it,
        with no prose-only equality assertion left behind.
    """
    # Arrange
    step_nine = _section(_skill_text(), "### 9. Finalize the consolidated document")
    step_ten = _step10_section()

    # Act
    checks = [b for b in _bash_blocks(step_ten) if "diff -u" in b]

    # Assert
    assert ".target.md" in step_nine
    assert len(checks) == 1, f"expected 1 diff block, found {len(checks)}"
    assert "MUST equal step 9's consolidated document" not in step_ten


def test_unresolved_repository_should_still_write_the_document():
    """Test only the commit stops when no review repository resolves.

    Given:
        Step 10(a)'s unresolved-repository branch.
    When:
        Its instruction is read.
    Then:
        It should direct the agent to write the document and stop only before
        committing, so a round's reviewer work is never discarded.
    """
    # Arrange
    section = _step10_section()

    # Act
    start = section.index("`Review repository: unresolved`")
    branch = section[start : start + 800]

    # Assert
    assert "write the document first" in branch
    assert "STOP before **committing**" in branch
    assert "STOP before writing anything" not in section


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


def test_snapshot_commit_should_carry_the_pass_header_bump():
    """Test a pass that changes no finding still has a commit to make.

    Given:
        The re-review commit protocol and the skill's edge cases.
    When:
        The pass-counter bump is traced to a commit.
    Then:
        It should belong to the snapshot commit, and a carry-everything pass
        should be covered as an edge case.
    """
    # Arrange
    text = _skill_text()

    # Act
    section = _step10_section()

    # Assert
    assert "pass-header bump" in section
    assert "Every seeded finding carries (re-review):" in text


# --- Step 2: the reviewed-state capture ---------------------------------------


def _meta(stdout: str) -> dict:
    """Parse the `meta.json` the capture block wrote into its staging directory."""
    staging = Path(_field(stdout, "STAGING"))
    return json.loads((staging / "meta.json").read_text())


@pytest.fixture
def bare_tree(tmp_path):
    """A directory of files that is not a git repository at all."""
    tree = tmp_path / "loose"
    tree.mkdir()
    (tree / "notes.md").write_text("# notes\n")
    return tree


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
        It should write `meta.json` alone, recording no version control and
        no anchor, rather than exiting non-zero.
    """
    # Act
    result = _run(_capture_script(str(bare_tree / "snapshot-1")), bare_tree)

    # Assert
    assert result.returncode == 0, result.stderr
    meta = _meta(result.stdout)
    assert meta["vcs"] == "none"
    assert meta["base"] == ""
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
    script = _capture_script(str(work / "snap")).replace(
        "':(exclude,top).sdlc'", "':(exclude,top)*'"
    )

    # Act
    result = _run(script, work)

    # Assert
    assert result.returncode != 0
    assert "snapshot tree is empty" in result.stderr


def test_directive_placeholders_should_be_quoted_in_command_blocks():
    """Test every substituted path is quoted against shell globbing.

    Given:
        The skill's bash blocks, whose PR-mode paths always contain a `#`.
    When:
        Directive placeholders are located in them.
    Then:
        Each should sit inside double quotes, since an unquoted `issue-#33`
        path fails under zsh with extendedglob.
    """
    # Arrange
    placeholders = [
        "<Review snapshot directory>",
        "<Review document in repository>",
        "<Review snapshot in repository>",
        "<Review document>",
        "<repo>",
    ]

    # Act
    unquoted = []
    for block in _bash_blocks(_skill_text()):
        for line in block.splitlines():
            for token in line.split():
                for placeholder in placeholders:
                    index = token.find(placeholder)
                    if index == -1:
                        continue
                    quoted = '"' in token[:index] or token[index + len(placeholder):].startswith('"')
                    if not quoted:
                        unquoted.append(token)

    # Assert
    assert unquoted == []
