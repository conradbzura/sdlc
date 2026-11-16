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


def _fill_meta(script: str, round: int = 1) -> str:
    """Fill the metadata placeholders as a PATHS-mode agent is told to.

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
    script = script.replace("<Review round>", str(round))
    return re.sub(r"<true\|false[^>]*>", "false", script)


def _metadata_script(metadata: str, round: int = 1) -> str:
    """The step-2 metadata block, extracted verbatim and pointed at `metadata`."""
    section = _section(_skill_text(), "#### Record the reviewed state (all modes)")
    blocks = _bash_blocks(section)
    assert len(blocks) == 1, f"expected 1 metadata block, found {len(blocks)}"
    script = "set -e\n" + blocks[0]
    # Fail loudly if the extraction drifted off the block the prose describes.
    assert "git read-tree --empty" in script
    assert '":(exclude,top)$excl"' in script
    assert 'meta="<Review metadata>"' in script, "the metadata placeholder moved"
    script = _fill_meta(script.replace("<Review metadata>", metadata), round)
    return script + '\necho "TREE=$tree"\necho "BASE=$base"\n'


def _overwrite_guard_script(directory: str, document: str) -> str:
    """The step-10 guard that refuses to write over an existing document."""
    section = _section(_skill_text(), "### 10. Write the review document")
    blocks = [b for b in _bash_blocks(section) if "refusing to overwrite" in b]
    assert len(blocks) == 1, f"expected 1 guard block, found {len(blocks)}"
    script = blocks[0].replace("<Review document directory>", directory)
    return script.replace("<Review document>", document) + "\necho PROCEED\n"


def _field(output: str, name: str) -> str:
    match = re.search(rf"^{name}=(.*)$", output, flags=re.MULTILINE)
    assert match is not None, f"{name} missing from:\n{output}"
    return match.group(1).strip()


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
