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
RATIONALE = Path(__file__).resolve().parents[1] / "src/sdlc/review-rationale.md"
AGENTS = Path(__file__).resolve().parents[1] / "src/sdlc/AGENTS.md"
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


def _line(text: str, prefix: str) -> str:
    """Return the single line starting with `prefix`.

    Markdown prose here is never hard-wrapped, so a block-level element is one
    line and can be asserted on without a section scan picking up its
    neighbours.
    """
    return next(line for line in text.splitlines() if line.startswith(prefix))


def _bash_blocks(text: str) -> list[str]:
    """Return every ```bash fenced block in `text`, in order.

    The closing fence is anchored to the start of a line. A block whose body
    legitimately contains a backtick run — an awk program matching Markdown
    fences, say — would otherwise be truncated at that run, and the tests that
    EXECUTE these blocks would then run a fragment.
    """
    return re.findall(
        r"^[ \t]*```bash\n(.*?)^[ \t]*```", text, flags=re.DOTALL | re.MULTILINE
    )


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
    """Fill the `meta.json` placeholders as a PATHS-mode agent is told to.

    Every field whose placeholder says to omit the whole line is dropped,
    rather than named one by one — that is the instruction the block carries
    inline, so following it generically keeps this helper from silently
    diverging when a field is added.
    """
    script = re.sub(
        r'^\s*"[a-z_]+": <[^>]*omit this WHOLE LINE[^>]*>,?\n',
        "",
        script,
        flags=re.MULTILINE,
    )
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
    assert '":(exclude,top)$excl"' in script
    assert "git commit-tree" in script
    script = re.sub(r"excl='<[^']*>'", "excl='.sdlc'", script)
    assert "excl='.sdlc'" in script, "the exclusion placeholder moved"
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
    section = _section(RATIONALE.read_text(), "### R10.5 Restoring a snapshot")
    blocks = [b for b in _bash_blocks(section) if "git apply" in b]
    assert len(blocks) == 1, f"expected 1 restore block, found {len(blocks)}"
    script = "set -e\n" + blocks[0]
    assert "export GIT_INDEX_FILE" in script
    assert "git read-tree --empty" in script
    script = re.sub(
        r"':\(exclude,top\)<meta\.excluded[^']*>'", "':(exclude,top).sdlc'", script
    )
    assert "':(exclude,top).sdlc'" in script, "the meta.excluded placeholder moved"
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
        if "$worktree" in block and "worktree=" not in block
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
        It should withhold every seeded-finding slot and the disposition
        vocabulary, keep the `.sdlc/reviews/` prohibition, tell the reviewer a
        second turn follows, and defer the seeded set to a second message.
        The prohibition is on seeded CONTENT — operational scaffolding is
        explicitly allowed, because phase 2 needs the reviewer to still hold
        its phase-1 findings individually.
    """
    # Arrange
    section = _section(_skill_text(), "### 7. Dispatch reviewer subagents (N per role)")

    # Act
    phase_one = section[section.index("1. **Phase 1"): section.index("2. Collect")]

    # Assert — no seeded content reaches phase 1
    assert "<the seeded findings" not in phase_one
    assert "<the Rejected in earlier passes ledger>" not in phase_one
    for vocabulary in ("**close**", "**reject**", "**carry**"):
        assert vocabulary not in phase_one
    # ...and the two things phase 1 must carry
    assert ".sdlc/reviews/" in phase_one
    assert "follow-up message" in phase_one
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
    """Return the `# <label>` half of a block showing two commit variants.

    The header may carry a trailing comment, and may wrap onto further comment
    lines, so the variant runs until the OTHER variant's header rather than
    until the next comment.
    """
    other = "# in place" if label == "worktree" else "# worktree"
    lines = block.splitlines(keepends=True)
    start = next(
        (i for i, line in enumerate(lines) if line.startswith(f"# {label}")), None
    )
    assert start is not None, f"'# {label}' missing from:\n{block}"
    rest = lines[start:]
    end = next(
        (i for i, line in enumerate(rest[1:], 1) if line.startswith(other)), len(rest)
    )
    return "".join(rest[:end])


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


def test_rereview_worktree_commits_should_copy_the_document_first():
    """Test both re-review commit blocks re-mirror the document before staging.

    Given:
        The snapshot-and-header block and the per-mutation block, the two that
        commit a document which changed since 10(c) mirrored it.
    When:
        Their worktree variants are inspected.
    Then:
        Each should copy the working-directory document into the worktree in
        the same fence. Shell state does not survive between tool calls, so a
        block that stages without copying commits the previous content under a
        message justifying a change it does not carry.
    """
    # Arrange
    snapshot = _step10_block(
        'add "<Review snapshot in repository>" "<Review document in repository>"'
    )
    mutation = _step10_block('add "<Review document in repository>"\n')

    # Act
    variants = [_variant(snapshot, "worktree"), _variant(mutation, "worktree")]

    # Assert
    for variant in variants:
        assert 'git -C "$worktree" add' in variant
        assert (
            'cp "<Review document>" "$worktree/<Review document in repository>"'
            in variant
        ), variant


def test_target_path_should_be_keyed_on_the_working_directory_document():
    """Test the scratch target is derivable when no review repository resolves.

    Given:
        The two blocks that derive the step-9 target — step 9 itself and the
        terminal check at the end of 10(d).
    When:
        Their derivation keys are compared.
    Then:
        Both should key on `<Review document>` and neither on the
        repository-relative directives, which are omitted entirely when the
        review repository is unresolved — a branch on which the document is
        still written and the target is still needed.
    """
    # Arrange
    derivations = [
        line
        for block in _bash_blocks(_skill_text())
        for line in block.splitlines()
        if line.startswith("target=")
    ]

    # Act & assert
    assert len(derivations) == 2, derivations
    assert len(set(derivations)) == 1, "the two derivations disagree"
    assert '"<Review document>"' in derivations[0]
    assert "<repo>" not in derivations[0]
    assert "<Review document in repository>" not in derivations[0]


def test_commit_destinations_should_be_transcribed_before_step_ten():
    """Test every directive step 10 interpolates is written down beforehand.

    Given:
        The step-10 command blocks, which interpolate injected directive
        values many tool calls after the directive block was read.
    When:
        The transcription block earlier in the skill is compared against them.
    Then:
        Every directive-backed placeholder step 10 uses should be named there,
        and step 10 should READ the file back from the same derived path. A
        transcription nothing reads is not ground truth, it is a second copy
        of the value the orchestrator was already recalling.
    """
    # Arrange
    labels = {
        "<repo>": "Review repository:",
        "<Review document in repository>": "Review document in repository:",
        "<Review snapshot in repository>": "Review snapshot in repository:",
        "<Review snapshot directory>": "Review snapshot directory:",
        "<branch>": "Review commit branch:",
    }
    step_ten = "".join(_step10_blocks())
    blocks = [b for b in _bash_blocks(_skill_text()) if ".directives" in b]
    derivation = 'sdlc-review-$(printf \'%s\' "<Review document>" | shasum | cut -c1-12).directives'

    # Act
    writes = [b for b in blocks if b.lstrip().startswith("cat >")]
    reads = [b for b in blocks if b.lstrip().startswith("cat ") and b not in writes]
    used = [ph for ph in labels if ph in step_ten]

    # Assert
    assert len(writes) == 1, f"expected 1 transcription block, found {len(writes)}"
    assert reads, "nothing reads the transcribed directives back"
    assert used, "step 10 interpolates no directive placeholders"
    for placeholder in used:
        assert labels[placeholder] in writes[0], labels[placeholder]
    # The read must resolve to the file the write produced.
    for block in writes + reads:
        assert derivation in block, block


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
    script = _capture_script(str(work / "snap")).replace("excl='.sdlc'", "excl='*'")

    # Act
    result = _run(script, work)

    # Assert
    assert result.returncode != 0
    assert "snapshot tree is empty" in result.stderr


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


# --- Steps 7-8: the re-review reconciliation ----------------------------------


TEMPLATE = Path(__file__).resolve().parents[1] / "src/sdlc/review-template.md"


def _step7() -> str:
    return _section(_skill_text(), "### 7. Dispatch reviewer subagents (N per role)")


def _step8() -> str:
    return _section(_skill_text(), "### 8. Consolidate the findings")


def test_rereview_should_read_the_document_back_before_dispatching():
    """Test the lossy-block read-back is wired into an actual step.

    Given:
        Step 7, which the checklist presents as the agent's plan skeleton.
    When:
        The re-review path is read.
    Then:
        It should require reading the seeded document back, name the fields
        the block drops, and do so before any reviewer is dispatched.
    """
    # Arrange
    section = _step7()

    # Act
    readback = section.index("Read the seeded document back")
    dispatch = section.index("Phase 1 — review.")

    # Assert
    assert readback < dispatch
    for field in ("attribution", "Tests to add", "Cross-cutting", "pass counter"):
        assert field in section[readback:dispatch], field
    assert "**(re-review)** read the seeded document back" in _skill_text()


def test_rereview_should_reconcile_the_seeded_count_against_the_file():
    """Test a finding the parser dropped is detected rather than deleted.

    Given:
        Step 7's read-back.
    When:
        Its reconciliation instruction is read.
    Then:
        It should compare id SETS against the block's, computed the way the
        parser computes them — outside fences, inside the tiers — and stop on
        a mismatch. A raw heading count is fence-blind where the parser is
        not, so it reports a mismatch on a document that parsed perfectly.
    """
    # Arrange
    section = _step7()

    # Act & assert
    assert "Findings (N):" in section
    assert "STOP and name the ids present in the file but missing" in section
    assert "id sets" in section
    awk = next(b for b in _bash_blocks(section) if b.lstrip().startswith("awk"))
    assert "fence" in awk
    assert "Tier" in awk


def test_phase_one_brief_should_forbid_reading_review_artifacts():
    """Test phase-1 blindness is enforced, not merely asserted.

    Given:
        The reviewer brief, which otherwise permits reading any file.
    When:
        Its file-access rules are read.
    Then:
        It should prohibit `.sdlc/reviews/`, where the seeded document sits
        at a guessable path inside the tree under review.
    """
    # Arrange
    section = _step7()

    # Act & assert
    assert "Do NOT read anything under `.sdlc/reviews/`" in section
    assert "the phase-1 brief forbids reading `.sdlc/reviews/`" in section
    assert "phase 1 never saw the seeded set" not in _skill_text()


def test_reviewer_brief_should_not_assert_the_pr_head_unconditionally():
    """Test the brief does not claim a verification that may not have run.

    Given:
        Step 2 permits continuing past a `HEAD != headRefOid` mismatch.
    When:
        The brief's PR-head wording is read.
    Then:
        It should offer a verified and an unverified variant rather than
        asserting the checkout is at the PR head.
    """
    # Arrange
    section = _step7()

    # Act & assert
    assert "the orchestrator verified this in step 2" not in section
    assert "**(verified)**" in section
    assert "**(not verified)**" in section


def test_rejected_findings_should_be_recorded_in_a_ledger():
    """Test a rejection survives the pass that made it.

    Given:
        A rejected finding leaves the document, and phase 1 is blind.
    When:
        Step 8 and the template are read.
    Then:
        The rejection should be recorded in a ledger supplied to phase 2
        only, so a later pass cannot re-raise it as new unnoticed.
    """
    # Arrange
    template = TEMPLATE.read_text()

    # Act & assert
    assert "## Rejected in earlier passes" in template
    assert "Rejected in earlier passes" in _step8()
    assert "the Rejected in earlier passes ledger" in _step7()
    assert "NEVER to phase 1" in _step8()


def _invariants() -> str:
    return _section(_skill_text(), "## Invariants")


def test_invariants_should_carry_the_irreversible_rereview_rules():
    """Test the rules whose omission cannot be undone sit in the leading span.

    Given:
        The Invariants block, which the subagent brief singles out ("follow
        every step faithfully, especially the Invariants section") and which
        is the document's own high-salience summary.
    When:
        It is read.
    Then:
        It should carry the re-review read-back and the blocking-disposition
        corroboration gate. Both previously sat past the midpoint of a
        765-line document — the read-back is the only instruction here whose
        omission destroys data irreversibly, and the corroboration gate is the
        only human-in-the-loop gate the re-review adds.
    """
    # Arrange
    invariants = _invariants()

    # Act & assert
    assert "read the seeded" in invariants
    assert "Retired ids" in invariants
    assert "two reviewers agreeing" in invariants
    assert "explicit user confirmation" in invariants


def _step9() -> str:
    return _section(_skill_text(), "### 9. Finalize the consolidated document")


# Every phrase in these documents that says the write is ungated. Each MUST be
# scoped, because an unqualified one is what step 9 carried for four passes
# while step 8 and step 10 said the opposite.
_GATE_DENIALS = (
    "no approval gate",
    "absence of an approval gate",
    "without an approval gate",
)

# A denial is legitimate when it says WHICH path it describes, or names what
# the exceptions are.
_DENIAL_QUALIFIERS = (
    "fresh round",
    "exception",
    "per-finding approval gate",
    "two",
)


@pytest.mark.parametrize("document", [SKILL, AGENTS], ids=lambda p: p.name)
def test_the_write_should_never_be_described_as_ungated_without_qualification(
    document,
):
    """Test no sentence claims the write is ungated without saying where.

    Given:
        Every sentence in the skill and in AGENTS.md that says there is no
        approval gate.
    When:
        Each is read on its own, as an agent retrieving one passage would.
    Then:
        Each should name the path it describes or the exceptions that apply.
        The gate is real on a re-review, and a bare denial mid-document is
        what let three documents disagree about it for four passes.
    """
    # Arrange
    text = document.read_text()
    sentences = [
        sentence
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if any(denial in sentence for denial in _GATE_DENIALS)
    ]

    # Act & assert
    assert sentences, f"{document.name} no longer describes the gate at all"
    for sentence in sentences:
        assert any(q in sentence for q in _DENIAL_QUALIFIERS), sentence


def test_the_gate_count_should_agree_across_the_invariants_and_step_10():
    """Test the two passages that COUNT the exceptions report the same number.

    Given:
        Invariant :72 and step 10, which each enumerate the cases where the
        write is not autonomous.
    When:
        Both are read.
    Then:
        They should name the same count. A model reading the tail has been
        told exactly how many exceptions exist, so a disagreement licenses it
        to reason past whichever gate it did not see enumerated.
    """
    # Arrange
    text = _skill_text()
    invariant = next(
        line for line in text.splitlines() if "MUST write AND commit" in line
    )
    step10 = _section(text, "### 10. Write and commit the review document")
    opening = step10.split("\n\n")[1]

    # Act
    written = {
        name: re.search(r"\*\*(one|two|three)\*\*", passage)
        for name, passage in (("invariant", invariant), ("step10", opening))
    }

    # Assert
    assert written["invariant"] is not None, invariant
    assert written["step10"] is not None, opening
    assert written["invariant"].group(1) == written["step10"].group(1)
    assert "unresolved review repository" in invariant
    assert "unresolved review repository" in opening


def test_step9_should_route_the_uncorroborated_blocking_disposition_to_the_user():
    """Test the step the gate is routed to actually performs it.

    Given:
        Step 8 requires corroboration before a blocking finding leaves the
        termination predicate and routes the uncorroborated case to step 9.
    When:
        Step 9 is read.
    Then:
        It should gate both dispositions, require the quoted remediating text
        for a close, and name `carry` as the outcome when the user does not
        confirm — so the routing has a destination rather than terminating in
        a step that denies the gate exists.
    """
    # Arrange
    step9 = _step9()

    # Act & assert
    assert "close" in step9 and "reject" in step9
    assert "carry" in step9
    assert "quote" in step9.lower()
    assert "Reviewers per role" in step9


def test_agents_md_should_state_the_same_blocking_safeguards_as_the_skill():
    """Test the canonical document does not state a weaker rule than the skill.

    Given:
        AGENTS.md, which step 4 makes every reviewer read and which the
        reviewer brief interpolates — so it is read BEFORE step 8.
    When:
        Its re-review consolidation account is read.
    Then:
        It should carry every safeguard the skill defines, not just the
        carry-beats-close rule, and cover all three ways a blocking finding
        can leave the termination predicate. A reviewer that reads only the
        weaker version applies the weaker version.
    """
    # Arrange
    text = AGENTS.read_text()
    paragraph = next(
        line for line in text.splitlines() if "carry beats close" in line
    )

    # Act & assert
    assert "two reviewers agreeing" in paragraph
    assert "explicit user confirmation" in paragraph
    assert "quote the remediating text" in paragraph
    # The third way out of the termination predicate takes the same gate.
    assert "incidental" in paragraph


def test_step8_should_instruct_the_write_that_the_retired_id_rule_depends_on():
    """Test something actually APPENDS to the Retired ids line.

    Given:
        `max(retired ∪ open) + 1` is stated in the Invariants, in step 8 and
        in the template, and every one of those is a read.
    When:
        Step 8's disposition bullets are read.
    Then:
        They should instruct the write. A line nothing extends freezes, at
        which point `max(retired ∪ open)` collapses to `max(open)` and the
        pass after a closure reissues the closed id to a different defect.
    """
    # Arrange
    step8 = _step8()

    # Act
    apply_bullet = _section(step8, "- **Apply each disposition**").split("\n- ")[0]

    # Assert
    assert "Retired ids" in apply_bullet
    assert "append" in apply_bullet.lower()


def test_step8_should_move_the_blocking_marker_with_a_retiered_finding():
    """Test a re-tier is told to strip or add the heading marker.

    Given:
        `parse_review_document` treats `**(BLOCKING)**` as authoritative over
        the enclosing tier, and re-tiering is the primary outcome of a reject.
    When:
        Step 8 and the bundled template are read.
    Then:
        Both should say the marker moves with the finding. A Tier 2 finding
        that kept its marker re-seeds as blocking, so the termination
        predicate never clears and the chain cannot end.
    """
    # Arrange
    step8 = _step8()
    template = TEMPLATE.read_text()

    # Act & assert
    for text in (step8, template):
        assert "**(BLOCKING)**" in text
        assert "strip" in text
        assert "re-tier" in text.lower()


def test_the_disposition_block_should_have_a_slot_for_every_named_disposition():
    """Test no disposition the phase-2 message names lacks a field value.

    Given:
        The phase-2 message names close, reject, carry and re-open.
    When:
        Its machine-readable disposition block and field list are read.
    Then:
        Every named disposition should appear as a value. One that has to
        ride in free prose is the one that gets dropped — and re-open is the
        signal that keeps a wrongly rejected blocking finding from blocking
        forever.
    """
    # Arrange
    step7 = _step7()
    fields = next(
        line for line in step7.splitlines() if "`|`-separated fields" in line
    )

    # Act
    # The sample block sits inside a blockquote, so its lines carry a `> ` prefix.
    sample = "\n".join(
        line for line in step7.splitlines() if re.search(r"\|\s*\w+\s*\|", line)
    )

    # Assert
    for disposition in ("close", "reject", "carry", "reopen"):
        assert f"`{disposition}`" in fields, disposition
        assert disposition in sample, disposition


def test_a_reopened_finding_should_have_an_id_rule():
    """Test re-open says which id the restored finding takes.

    Given:
        A re-opened finding's original id sits in `Retired ids`, while the
        new-id rule would allocate it a fresh one.
    When:
        Step 8 is read.
    Then:
        It should state which id applies and what happens to the retired
        line, rather than leaving a load-bearing id decision to the agent.
    """
    # Arrange
    step8 = _step8()

    # Act
    bullet = _section(step8, "- **A re-opened finding").split("\n- ")[0]

    # Assert
    assert "original" in bullet
    assert "Retired ids" in bullet


def test_the_cross_role_merge_should_span_carried_and_new_findings():
    """Test a cross-role rediscovery cannot acquire a second id.

    Given:
        Seeded findings route by originating role, so a reviewer never sees
        another role's subset and cannot report a cross-role rediscovery.
    When:
        Step 8's re-review preamble is read.
    Then:
        It should scope the cross-role merge over carried AND new findings.
        Scoped to new findings alone, one defect ends the pass with two open
        ids, inflating the blocking count that termination depends on.
    """
    # Arrange
    preamble = _step8().split("\n- ")[0]

    # Assert
    assert "carried" in preamble.lower()
    assert "Merge across roles" in preamble


def test_the_stale_reference_warning_should_reach_the_phase_two_message():
    """Test reviewers are told the seeded line numbers have moved.

    Given:
        The user runs `sdlc_implement --review <#>` between passes, which by
        construction edits the files the seeded references cite.
    When:
        The phase-2 message is read.
    Then:
        It should warn that a missing or unrelated line at the cited offset
        is not evidence of a close, and step 8 should carry such a
        disposition. Both failure directions delete a blocking finding on a
        citation that merely drifted.
    """
    # Arrange
    step7 = _step7()
    step8 = _step8()

    # Act & assert
    assert "not evidence of a close" in step7.lower().replace("**", "")
    assert "re-reference" in step7.lower()
    assert "absence at a line is a carry" in step8.lower().replace("**", "")


def test_the_unexamined_count_should_carry_both_of_its_causes():
    """Test `<u>`'s two causes are distinguishable wherever it is reported.

    Given:
        A finding is carried unexamined either because its role was absent or
        because a dispatched reviewer returned nothing for it.
    When:
        Step 8's counting bullet and step 11's prompts are read.
    Then:
        Both should cover both causes. The first cause's remedy — re-run with
        the missing roles — is a false diagnosis for the second, since that
        role already ran.
    """
    # Arrange
    text = _skill_text()
    counting = next(
        line
        for line in text.splitlines()
        if "**carried without re-examination** (`<u>`)" in line
    )
    step11 = _section(text, "### 11. Prompt the user with next steps")

    # Act & assert
    assert "two" in counting
    assert "no disposition" in counting
    assert "returned no disposition" in step11
    assert "were not in this pass" in step11


def test_step7_should_persist_the_seeded_document_to_disk():
    """Test the one irreversible read-back has a durable carrier.

    Given:
        Step 7(0) reads fields that the in-place rewrite destroys, and their
        use in step 9 is separated from that read by the whole dispatch.
    When:
        Step 7(0) is read.
    Then:
        It should copy the document to a scratch path and direct step 9 to
        read it back, the same treatment steps 3 and 9 give values that cross
        far fewer tool calls.
    """
    # Arrange
    step7 = _step7()

    # Act
    blocks = _bash_blocks(step7)

    # Assert
    assert any("seed=" in block and "cp " in block for block in blocks), blocks
    assert "$seed" in step7


def test_the_inline_fallback_should_not_claim_the_blindness_guarantee():
    """Test the non-subagent path says what it actually delivers.

    Given:
        On the inline path there is no separate phase-1 prompt — the endpoint
        appends the seeded block to the tool return the orchestrator reads,
        and the orchestrator is the reviewer.
    When:
        The fallback paragraph and step 8's weighting are read.
    Then:
        The fallback should state the asymmetry, and the weighting it cannot
        earn should be withdrawn for inline-run roles rather than applied
        unconditionally on a foundation that is absent.
    """
    # Arrange
    step7 = _step7()
    step8 = _step8()

    # Act
    fallback = step7[step7.index("**Other LLM assistants:** where agent messaging"):]

    # Assert
    assert "NOT the same" in fallback
    assert "instructional" in fallback
    assert "inline" in step8


def test_step7_should_reconcile_returned_dispositions_against_the_dispatch():
    """Test a reviewer's dropped disposition is noticed rather than counted.

    Given:
        Step 8 defaults a missing disposition to carry, silently, and the
        dispatched subsets are long enumerations.
    When:
        Step 7's collection step is read.
    Then:
        It should compare returned ids against dispatched ids and re-ask once
        before falling back, so the gap is closed where it occurs rather than
        counted downstream under a cause that misdescribes it.
    """
    # Arrange
    step7 = _step7()

    # Act
    collect = next(
        line for line in step7.splitlines() if line.startswith("4. Collect")
    )

    # Assert
    assert "reconcile" in collect.lower()
    assert "re-send" in collect.lower()


@pytest.mark.parametrize(
    ("excl", "accepted"),
    [
        (".sdlc", True),
        ("docs/reviews", True),
        ("_reviews", True),
        ("/abs/path/.sdlc", False),
        ("unresolved", False),
        ("", False),
        (".", False),
        ("..", False),
        ("../x", False),
        ("a/../b", False),
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
        It should reject the absolute form the `Review repository:` directive
        actually emits, the literal `unresolved` that directive carries on
        every project's first review, and any root-or-ancestor form — while
        accepting an ordinary relative path. Both rejected shapes exclude
        NOTHING, so the review repository lands in the snapshot of the code it
        reviews and the tree SHA churns every pass; no sentinel fires, because
        the empty-tree check only catches over-exclusion.
    """
    # Arrange
    guards = re.findall(
        r'^case "\$excl" in\n.*?^esac', _skill_text(), re.DOTALL | re.MULTILINE
    )
    assert guards, "the exclusion guard moved"
    script = f"excl={excl!r}\n" + "\n".join(guards) + '\necho ACCEPTED'

    # Act
    result = _run(script, tmp_path)

    # Assert
    assert ("ACCEPTED" in result.stdout) is accepted, result


def test_count_reconciliation_should_agree_with_the_parser_on_a_fenced_heading(
    tmp_path,
):
    """Test the id-set gate does not fire on a document that parsed cleanly.

    Given:
        A review document whose finding quotes a finding heading inside a
        fence, and which carries a heading outside the severity tiers.
    When:
        Step 7(0)'s extraction command is run against it.
    Then:
        It should yield exactly the ids `parse_review_document` yields —
        skipping the fenced sample and the out-of-tier heading. A raw heading
        count reports a mismatch here on a healthy document, and a MUST-STOP
        gate that fires on healthy input is one an agent learns to skip.
    """
    # Arrange
    document = tmp_path / "review-1.md"
    document.write_text(
        "# Doc\n\n## Tier 1 — Blocking\n\n"
        "### B1 — Real one **(BLOCKING)** — aie\n"
        "**Reference:** `a.py:1`\n\n"
        "**Issue:** quoting a sample:\n\n"
        "```markdown\n### B9 — Phantom **(BLOCKING)** — aie\n```\n\n"
        "**Remediation:**\n- [x] Fix.\n\n"
        "## Tier 2 — Advisory\n\n"
        "### A1 — Real advisory — aie\n"
        "**Reference:** `b.py:2`\n\n"
        "Body.\n- [x] Fix.\n\n"
        "## Cross-cutting decisions\n\n"
        "### B99 — Outside the tiers — aie\n"
    )
    awk = next(
        b for b in _bash_blocks(_step7()) if b.lstrip().startswith("awk")
    ).replace('"<Review document>"', f'"{document}"')

    # Act
    result = _run(awk, tmp_path)

    # Assert
    assert result.stdout.split() == ["B1", "A1"], result
    from sdlc.pr_state import parse_review_document

    parsed = [f.id for f in parse_review_document(document, 1, 1).findings]
    assert result.stdout.split() == parsed


def test_the_knowledge_graph_mandate_should_be_conditioned_on_freshness():
    """Test a stale graph is treated as absent rather than fed to N briefs.

    Given:
        The graph's summary lands in every reviewer brief's architectural
        context slot, where it reads as ground truth.
    When:
        The invariant and step 6 are read.
    Then:
        Both should condition the mandate on the graph being current, not on
        the file existing. A graph describing a layout the tree no longer has
        is worse than no graph, in all N briefs at once.
    """
    # Arrange
    invariant = next(
        line for line in _invariants().splitlines() if "understand-chat" in line
    )
    step6 = _section(_skill_text(), "### 6. Gather knowledge graph context")

    # Act & assert
    assert "current" in invariant
    assert "ABSENT" in invariant or "absent" in invariant
    assert "stale" in step6.lower()
    assert "analysis commit" in step6


def test_the_unresolved_rereview_branch_should_still_promote_the_snapshot():
    """Test the document and the snapshot describe the same pass.

    Given:
        10(a)'s re-review carve-out writes the document and skips (c) and (d),
        so the promote never runs.
    When:
        That carve-out is read.
    Then:
        It should promote the staged capture before stopping. Otherwise this
        pass's capture is cleared by the next pass while `snapshot-<#>/` still
        holds the previous pass's meta — beside a document rewritten to this
        pass's finding set, which is what staging exists to prevent.
    """
    # Arrange
    step10 = _step10_section()
    carve_out = step10[step10.index("the whole pass in one write"):]

    # Act
    clause = carve_out[: carve_out.index("Do not attempt (d)")]

    # Assert
    assert "promote" in clause.lower()
    assert "needs no repository" in clause


def test_the_git_init_answer_should_get_the_per_mutation_history():
    """Test authorizing a repository routes back into the normal commit path.

    Given:
        10(a)'s one-write clause and its `git init` exception were written for
        different branches and meet when the user answers yes.
    When:
        The one-write clause is read.
    Then:
        It should be scoped to the case where no repository is authorized, so
        a user who answers `git init .sdlc` gets the per-finding history that
        is the whole deliverable the question exists to enable.
    """
    # Arrange
    step10 = _step10_section()

    # Act
    clause = step10[step10.index("the whole pass in one write"):]
    scope = clause[: clause.index("**(b)")] if "**(b)" in clause else clause

    # Assert
    assert "does NOT authorize" in scope
    assert "(c) and (d)" in scope


def test_readback_fields_should_be_enumerated_in_exactly_one_place():
    """Test the lossy-block note points at step 7(0) instead of re-listing.

    Given:
        Two passages describe what the seeded block drops — the Arguments
        note and step 7(0).
    When:
        The Arguments note is read.
    Then:
        It should defer to step 7(0) rather than enumerate the fields itself.
        Two independent lists drift, and they had: the Arguments copy named
        four fields while step 7(0) named six.
    """
    # Arrange
    note = next(
        line
        for line in _skill_text().splitlines()
        if "The block is **lossy**" in line
    )

    # Act & assert
    assert "Step 7(0) enumerates those fields" in note
    assert "Tests to add" not in note
    assert "cross-cutting decisions" not in note


def test_step_eleven_should_have_an_uncommitted_rereview_prompt():
    """Test the unresolved-repository prompt has a re-review variant.

    Given:
        A re-review whose review repository is unresolved writes the document
        but records no per-mutation history.
    When:
        Step 11's not-committed prompts are read.
    Then:
        Every path that can end uncommitted should have its own prompt —
        PR-mode fresh, PR-mode re-review, and paths mode. The fresh-round
        wording claims only that a commit is pending, which is a false
        statement about what a re-review pass lost, and paths mode is the
        mode reachable with no `gh` at all so it meets this state most often.
    """
    # Arrange
    section = _section(_skill_text(), "### 11. Prompt the user with next steps")
    quotes = [line for line in section.splitlines() if line.startswith("> ")]

    # Act
    uncommitted = [q for q in quotes if "not committed" in q]

    # Assert — coverage, not a count: a new variant is an addition, not a break
    assert any("per-finding history" in q for q in uncommitted), uncommitted
    assert any(
        "<Review document directory>" in q for q in uncommitted
    ), "paths mode has no uncommitted prompt"
    assert any(
        ".sdlc/reviews/issue-#<N>" in q and "per-finding history" not in q
        for q in uncommitted
    ), "PR-mode fresh has no uncommitted prompt"


def test_retired_ids_should_be_recorded_so_they_are_not_reused():
    """Test the next id is computed from a high-water mark, not the survivors.

    Given:
        Closed and rejected findings are deleted from the tiers.
    When:
        Step 8's id rule and the template header are read.
    Then:
        Both should take the maximum across the retired line AND the surviving
        findings. Either source alone is wrong, and in opposite directions:
        the survivors miss every retired id, and the retired line misses the
        highest-ever id whenever it is still open — the normal case.
    """
    # Arrange
    template = TEMPLATE.read_text()
    rule = next(
        line for line in _step8().splitlines() if "Keep finding IDs stable" in line
    )

    # Act & assert
    assert "**Retired ids**" in template
    assert "Retired ids" in rule
    assert "surviving findings" in rule
    # The rule must not name the retired line as the sole source.
    assert "read from the document's **Retired ids** line" not in rule


def test_blocking_rejection_should_require_corroboration():
    """Test one reviewer cannot delete a blocking finding unaided.

    Given:
        `reject` removes a finding and reviewers-per-role defaults to 1.
    When:
        Step 8's disposition rules are read.
    Then:
        A blocking rejection should need two reviewers or the user, and
        closing a blocking finding — which removes it from the same
        termination predicate — should carry a check of its own rather than
        being grouped with carry as unconditionally autonomous.
    """
    # Arrange
    rule = next(
        line
        for line in _step8().splitlines()
        if "rejected only with corroboration" in line
    )

    # Act & assert
    assert "two reviewers agreeing" in rule
    assert "explicit user confirmation" in rule
    assert "carry" in rule and "autonomous" in rule
    # `close` also removes a blocking finding, so it is not unconditional.
    assert "`close` and `carry` stay autonomous" not in rule
    assert "quote the remediating text" in rule


def test_pass_line_should_count_findings_carried_unexamined():
    """Test a finding nobody looked at is reported as such.

    Given:
        A seeded finding whose originating role is absent carries unchanged.
    When:
        The template's pass line and step 8's counting rule are read.
    Then:
        Both should carry a carried-unexamined count.
    """
    # Arrange
    template = TEMPLATE.read_text()

    # Act & assert
    assert "carried unexamined <u>" in template
    assert "carried without re-examination" in _step8()
    assert "carried WITHOUT re-examination" in _skill_text()


def _scope_section() -> str:
    return _section(_skill_text(), "## Context and scope")


def test_the_skill_should_define_context_and_scope_separately():
    """Test reading a file and being answerable for it are distinct.

    Given:
        "You MAY read any file for context" appeared only in passing, so
        nothing separated what a reviewer may look at from what it is
        responsible for finding defects in.
    When:
        The Context and scope section is read.
    Then:
        It should define both by name — context unbounded across the
        repository, scope as an obligation — and state that reading alone is
        never grounds for a finding.
    """
    # Arrange
    section = _scope_section()

    # Act & assert
    assert "**Review context**" in section
    assert "**Review scope**" in section
    assert "entire repository" in section
    assert "never, by itself, grounds for a finding" in section
    assert "responsible for" in section


def test_scope_should_be_defined_by_the_issue_rather_than_the_diff():
    """Test a change that was never made can still be found.

    Given:
        Scope was the role's mapped subset of the PR's changed files, so
        code an acceptance criterion required but nobody wrote was in no
        reviewer's scope and the omission could not be raised.
    When:
        The scope definition is read.
    Then:
        It should admit code the PR did not touch, keep the role's globs as
        the outer bound, and say what scope means in paths mode, which has
        no issue to derive relatedness from.
    """
    # Arrange
    section = _scope_section()

    # Act & assert
    assert "whether or not this PR touched it" in section
    assert "nobody made is in scope precisely because it is missing" in section
    assert "expected outcomes" in section
    assert "guide-map.role" in section
    assert "paths mode" in section


def test_the_confinement_invariant_should_defer_to_the_scope_definition():
    """Test the invariant and the definition cannot state different bounds.

    Given:
        The invariant stated the whole of scope itself — the role's mapped
        changed files — which is now only its outer bound.
    When:
        The confinement invariant is read.
    Then:
        It should point at the definition rather than restate a narrower
        one, and express the confinement as a property of the finished
        document, which is the only place it can be checked.
    """
    # Arrange
    invariant = next(
        line
        for line in _skill_text().splitlines()
        if line.startswith("- Every finding in the document MUST")
    )

    # Act & assert
    assert "Context and scope" in invariant
    assert "guide-map.role" in invariant
    assert "step 8" in invariant


def _step2() -> str:
    return _section(_skill_text(), "### 2. Acquire the review targets")


def test_step2_should_capture_the_originating_issue_for_relevance():
    """Test the issue the PR closes is fetched and held for the reviewers.

    Given:
        A reviewer can only judge a finding's relevance against the issue's
        acceptance criteria, and it is spawned into a fresh context that
        inherits none of the orchestrator's reads.
    When:
        Step 2's PR-mode acquisition is read.
    Then:
        It should fetch the issue body, say it is interpolated into the
        step-7 brief, and skip the fetch when the endpoint reported the
        issue unresolved — the branch step 3 stops the run on.
    """
    # Arrange
    step2 = _step2()

    # Act & assert
    assert "gh issue view <N> --repo <target> --json title,body" in step2
    assert "step 7" in step2.split("gh issue view")[1]
    assert "unresolved" in step2


def test_the_reviewer_brief_should_classify_findings_against_the_issue():
    """Test a reviewer is asked whether a finding pertains to the issue.

    Given:
        Confinement to a role's mapped files is file scope, not relevance —
        a reviewer may raise anything anywhere in those files.
    When:
        The step-7 reviewer brief is read.
    Then:
        It should name all three tiers, carry the issue's acceptance criteria
        as a slot, and state the test that separates Incidental: the finding
        traces to no criterion and to no code this PR introduced.
    """
    # Arrange
    brief = _step7()

    # Act & assert
    assert "**Blocking**, **Advisory** or **Incidental**" in brief
    assert "acceptance criteri" in brief
    assert "<the originating issue" in brief
    # Paths mode has no issue, so it has neither the slot nor the tier.
    assert "**(paths mode)**" in brief
    assert "Incidental" in brief.split("**(paths mode)**")[1]


def test_severity_definitions_should_agree_between_the_skill_and_the_template():
    """Test the consolidator and the document define the tiers identically.

    Given:
        The consolidator reads step 8's definitions and fills the template's
        legend, so a disagreement between them is a tiering the document
        contradicts.
    When:
        Both are read.
    Then:
        Each should define all three tiers by what a finding is, and neither
        should define a tier by its effect on approval alone.
    """
    # Arrange
    definitions = _step8()
    legend = _line(TEMPLATE.read_text(), "**Severity legend**")

    # Act & assert
    for phrase in ("incorrect intent", "technical debt", "not role-relative"):
        assert phrase in definitions, phrase
        assert phrase in legend, phrase
    assert "does not pertain to the originating issue" in definitions
    assert "deferral" in definitions and "dismissal" in definitions
    assert "paths mode" in definitions


def test_the_template_should_carry_an_incidental_tier():
    """Test the document shape has somewhere to record a deferral.

    Given:
        A finding that is real but does not pertain to the originating issue.
    When:
        The review template is read.
    Then:
        It should carry a Tier 3 section after Tier 2, with the pass line
        counting its open findings, so the observation is recorded without
        holding the chain open.
    """
    # Arrange
    template = TEMPLATE.read_text()

    # Act & assert
    assert "## Tier 3 — Incidental" in template
    assert template.index("## Tier 2 — Advisory") < template.index(
        "## Tier 3 — Incidental"
    )
    assert "<I> incidental" in template


def test_the_template_should_define_the_tiers_by_what_a_finding_is():
    """Test the severity legend is about the work, not about approval.

    Given:
        Both original tiers were glossed by their effect on approval, which
        says nothing about whether a finding pertains to the issue.
    When:
        The severity legend is read.
    Then:
        Each tier should be defined by what the finding is — a correctness
        or incorrect-intent defect, technical debt, or an observation off
        the issue — and relevance should be named as what separates the
        third from the other two.
    """
    # Arrange
    legend = _line(TEMPLATE.read_text(), "**Severity legend**")

    # Act & assert
    assert "incorrect intent" in legend
    assert "technical debt" in legend
    assert "does not pertain to the originating issue" in legend
    assert "not role-relative" in legend
    # A deferral, not a dismissal: the evidence survives.
    assert "deferral" in legend and "dismissal" in legend


def test_the_template_should_give_the_incidental_tier_no_heading_marker():
    """Test the third tier is not given a demoting heading marker.

    Given:
        The BLOCKING marker outranks the enclosing tier, and that override
        only ever promotes a finding into the termination predicate.
    When:
        The template's re-tiering rule is read.
    Then:
        It should forbid an INCIDENTAL peer outright, since a stale demoting
        marker would drop a blocking finding out of the predicate silently
        rather than costing a recoverable wasted pass.
    """
    # Arrange
    template = TEMPLATE.read_text()
    rule = _line(template, "**Re-tiering**")

    # Act & assert
    assert "**(INCIDENTAL)**" in rule and "MUST NOT be introduced" in rule
    assert "by section alone" in rule
    # And nowhere does the template model one on a heading.
    headings = [line for line in template.splitlines() if line.startswith("### ")]
    assert headings
    assert not any("(INCIDENTAL)" in line for line in headings)


def test_step8_should_resolve_a_blocking_versus_incidental_disagreement():
    """Test the consolidator is told how to settle a relevance disagreement.

    Given:
        One role calls a finding blocking and another calls it incidental.
        Highest-severity-wins treats that as a severity disagreement, but it
        is a disagreement about whether the issue asked for the work at all.
    When:
        Step 8's merge rules are read.
    Then:
        They should rank the three tiers, and route a blocking-versus-
        incidental split to the acceptance criteria rather than to tier
        arithmetic — keeping the finding blocking until it is resolved, so
        nothing leaves the predicate by default.
    """
    # Arrange
    rule = _line(_step8(), "- **Highest severity wins**")

    # Act & assert
    assert "blocking > advisory > incidental" in rule
    assert "acceptance criteri" in rule
    assert "relevance" in rule
    assert "stays blocking" in rule


def test_retiering_a_blocking_finding_should_require_corroboration():
    """Test the third way out of the termination predicate is gated too.

    Given:
        `close` and `reject` are gated because each removes a blocking
        finding from the single predicate termination depends on. Moving one
        to Tier 3 has the same effect by a different door.
    When:
        Step 8's corroboration rule and step 9's gate are read.
    Then:
        Both should name the re-tier alongside close and reject, and treat an
        uncorroborated one as carry.
    """
    # Arrange
    rule = next(
        line
        for line in _step8().splitlines()
        if "rejected only with corroboration" in line
    )
    step9 = _step9()

    # Act & assert
    assert "incidental" in rule
    assert "two reviewers agreeing" in rule
    assert "incidental" in step9
    assert "carry" in step9


def test_pass_line_should_count_incidental_findings():
    """Test a deferral is counted where a debt item is counted.

    Given:
        The pass header states the open counts the document carries.
    When:
        The template's pass line and step 8's counting rule are read.
    Then:
        Both should carry an incidental count, so a reader can size the
        deferral backlog without reading the tier.
    """
    # Arrange
    template = TEMPLATE.read_text()
    counting = _line(_step8(), "- **Count what changed**")

    # Act & assert
    assert "<I> incidental" in template
    assert "incidental (`<I>`)" in counting
    # The deltas are not per tier, and the document says so rather than
    # leaving a reader to infer whether `<c>` covers a closed deferral.
    pass_line = _line(template, "**Pass line**")
    assert "across all three tiers" in pass_line


def test_the_dedup_rule_should_carry_the_relevance_exception():
    """Test the document states the split highest-severity-wins cannot settle.

    Given:
        The template's dedup paragraph is what a later pass reads to learn
        how cross-role disagreement was resolved.
    When:
        It is read.
    Then:
        It should name Blocking-versus-Incidental as a relevance question
        settled against the acceptance criteria, not by ranking the tiers.
    """
    # Arrange
    dedup = _line(TEMPLATE.read_text(), "**Dedup approach**")

    # Act & assert
    assert "relevance" in dedup
    assert "acceptance criteri" in dedup
    assert "stays blocking" in dedup


def test_termination_should_report_advisory_and_incidental_separately():
    """Test the completion prompt distinguishes debt from deferral.

    Given:
        Termination gates on blocking alone, and the two non-gating tiers
        mean different things — work to do later against work for another
        issue entirely.
    When:
        Step 11's no-blocking-findings prompt is read.
    Then:
        It should still gate on blocking alone and report the other two
        counts as separate numbers rather than a single carried total.
    """
    # Arrange
    step11 = _section(_skill_text(), "### 11. Prompt the user with next steps")
    prompt = _line(step11, "  > No blocking findings remain")

    # Act & assert
    assert "`<A>` advisory" in prompt
    assert "`<I>` incidental" in prompt
    assert "When `<B>` == 0:" in step11
    # The gate itself is unchanged: blocking alone.
    assert "When `<B>` > 0:" in step11


def test_the_skill_should_give_the_incidental_tier_no_heading_marker():
    """Test the marker asymmetry is stated where a re-tier is performed.

    Given:
        The template forbids an INCIDENTAL marker, but step 8 is where the
        consolidator actually moves a finding between tiers.
    When:
        Step 8's re-tier rule is read.
    Then:
        It should cover the move to Tier 3 and forbid inventing a marker for
        it, so the rule is present at the point of use rather than only in
        the document the consolidator is filling in.
    """
    # Arrange
    rule = _line(_step8(), "- **A re-tier MUST move the `**(BLOCKING)**` marker")

    # Act & assert
    assert "Tier 3" in rule
    assert "**(INCIDENTAL)**" in rule
    assert "by section alone" in rule


def test_paths_mode_edge_case_should_state_the_incidental_tier_is_unavailable():
    """Test the mode without an originating issue says so where it is read.

    Given:
        Paths mode has no linked issue, so there is nothing to test a
        finding's relevance against.
    When:
        The Edge Cases section is read.
    Then:
        It should state that the incidental tier is unavailable there and
        say what becomes of an off-issue observation instead.
    """
    # Arrange
    edge_cases = _section(_skill_text(), "## Edge Cases")
    entry = _line(edge_cases, "**No originating issue in paths mode")

    # Act & assert
    assert "incidental" in entry.lower()
    assert "Advisory" in entry
    assert "Tier 3" in entry


def test_subagent_brief_should_request_every_declared_artifact():
    """Test the brief asks for what the frontmatter promises.

    Given:
        The frontmatter declares the subagent artifacts.
    When:
        The orchestrator brief is read.
    Then:
        Each declared artifact should be named, since step 11's re-review
        prompt reports the three deltas.
    """
    # Arrange
    text = _skill_text()
    declared = re.search(r"  artifacts:\n((?:    - \w+\n)+)", text)
    assert declared is not None
    names = re.findall(r"- (\w+)", declared.group(1))

    # Act
    start = text.index("4. Return a structured summary")
    end = text.index("\n\n", start)
    brief = text[start:end]

    # Assert
    assert names, "the frontmatter declares no artifacts"
    for name in names:
        assert name in brief, name


def test_paths_mode_prompt_should_name_the_commit_and_the_chain():
    """Test the paths-mode prompt matches what the skill actually does.

    Given:
        Committing is mandatory in both modes, and paths mode supports
        re-review.
    When:
        Step 11's paths-mode prompt is read.
    Then:
        It should name the commit and the snapshot, and point at --verify
        rather than at a fresh review that starts a separate chain.
    """
    # Arrange
    section = _section(_skill_text(), "### 11. Prompt the user with next steps")

    # Act
    paths_prompt = section[section.index("**(paths mode):**") :]
    paths_prompt = paths_prompt[: paths_prompt.index("**(re-review):**")]

    # Assert
    assert "committed to the review repository" in paths_prompt
    assert "snapshot-<iteration>" in paths_prompt
    assert "sdlc_review --verify <iteration>" in paths_prompt
    assert "SEPARATE chain" in paths_prompt
