"""Fixtures shared by the review-skill suites.

A fixture only registers when pytest imports the module that defines it,
so a shared one lives here rather than in `skill_text.py`, which both
suites import as an ordinary module.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def bare_tree(tmp_path):
    """A directory of files that is not a git repository at all."""
    tree = tmp_path / "loose"
    tree.mkdir()
    (tree / "notes.md").write_text("# notes\n")
    return tree
