"""Pin the `implement-feedback` skill's treatment of the three severity tiers.

The skill is an instruction document, so its prose is its contract: an agent
following it has no way to discover that the review document it is walking
carries a tier the skill never mentions. These tests assert the tiers the
document can hold are the tiers the walk accounts for.
"""

from __future__ import annotations

from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "src/sdlc/skills/implement-feedback.md"


def _skill_text() -> str:
    return SKILL.read_text()


def _section(text: str, heading: str) -> str:
    """Return the body of the section introduced by `heading`."""
    start = text.index(heading)
    nxt = text.find("\n### ", start + len(heading))
    return text[start : nxt if nxt != -1 else len(text)]


def test_the_skill_should_enumerate_all_three_severity_tiers():
    """Test the walk knows about every tier the document can carry.

    Given:
        A review document holds Tier 1, Tier 2 and Tier 3 findings.
    When:
        The skill's description of the document is read.
    Then:
        It should enumerate all three, so a tier the skill never names
        cannot be silently skipped by an agent working from this prose.
    """
    # Arrange
    text = _skill_text()

    # Act & assert
    assert "**Tier 1 — Blocking**" in text
    assert "**Tier 2 — Advisory**" in text
    assert "**Tier 3 — Incidental**" in text


def test_incidental_findings_should_be_reported_rather_than_walked():
    """Test a deferral is not pushed through the per-finding approval gate.

    Given:
        An incidental finding does not pertain to the issue the PR closes,
        so remediating it here is the churn the tier exists to prevent.
    When:
        The sequential walk is read.
    Then:
        It should walk Tier 1 and Tier 2 only, and report the incidental
        findings afterwards as deferrals already recorded in the review
        document — the observation surfaced without work being proposed.
    """
    # Arrange
    walk = _section(_skill_text(), "### 7. Walk through findings sequentially")

    # Act & assert
    assert "Tier 1 and Tier 2" in walk
    assert "not walked" in walk
    assert "deferral" in walk
    assert "not remediated in this PR" in walk


def test_the_ordering_invariant_should_cover_the_incidental_tier():
    """Test the canonical severity ordering accounts for the third tier.

    Given:
        The invariant names the tiering the canonical sequence is applied
        within, and that tiering now has three members.
    When:
        The invariant is read.
    Then:
        It should name the incidental tier too, so the ordering rule and the
        document cannot describe different finding sets.
    """
    # Arrange
    invariant = next(
        line
        for line in _skill_text().splitlines()
        if "canonical severity sequence" in line
    )

    # Act & assert
    assert "incidental" in invariant.lower()
