"""Shared fixtures for the review-skill suites.

Not a test module: it holds the constants and text helpers that both the
document-assertion suite in `tests/` and the subprocess suite in
`tests/integration/` read. The test guide requires routines exercised by
integration tests to live outside a `test_`-prefixed file so pytest does not
collect them, and these are read by both suites besides.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


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


def _guard_script(value: str) -> str:
    """The step-2 exclusion guard alone, pointed at `value`."""
    section = _section(_skill_text(), "#### Capture the reviewed state (all modes)")
    block = next(b for b in _bash_blocks(section) if "accepted=1" in b)
    start = block.index("excl='")
    end = block.index("vcs=git;")
    guard = block[start:end].replace(
        block[start : block.index("\n", start)], f"excl={value!r}"
    )
    return guard + '\necho ACCEPTED\n'


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


def _meta(stdout: str) -> dict:
    """Parse the `meta.json` the capture block wrote into its staging directory."""
    staging = Path(_field(stdout, "STAGING"))
    return json.loads((staging / "meta.json").read_text())


def _step7() -> str:
    return _section(_skill_text(), "### 7. Dispatch reviewer subagents (N per role)")


def _step8() -> str:
    return _section(_skill_text(), "### 8. Consolidate the findings")


def _invariants() -> str:
    return _section(_skill_text(), "## Invariants")


def _step9() -> str:
    return _section(_skill_text(), "### 9. Finalize the consolidated document")


def _scope_section() -> str:
    return _section(_skill_text(), "## Context and scope")


def _step2() -> str:
    return _section(_skill_text(), "### 2. Acquire the review targets")
