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


def test_a_remediation_with_no_owning_commit_should_get_a_new_commit():
    """Test the fixup block handles a finding that creates code.

    Given:
        A finding can now report a change that was never made, so its
        remediation writes code no commit on the branch owns.
    When:
        The fixup-command step is read.
    Then:
        It should branch to an ordinary commit for that case, rather than
        emitting `--fixup` against a sha that does not exist.
    """
    # Arrange
    step = _section(_skill_text(), "### 8. Emit fixup commands after each remediation")

    # Act & assert
    assert "no commit — omission" in step
    assert "--fixup" in step
    assert "new commit" in step


def test_the_walk_should_fetch_a_finding_body_before_restating_it():
    """Test the walk reads a finding before it proposes work on it.

    Given:
        The endpoint now injects the document as an outline, with each
        finding's issue text and remediation checklist elided.
    When:
        The sequential walk is read.
    Then:
        It should fetch the body with `sdlc_review_findings` when it reaches
        a finding, before restating it or presenting a remediation — the
        pre-selected option lives in the body, so an unfetched finding has
        no remediation to present.
    """
    # Arrange
    walk = _section(_skill_text(), "### 7. Walk through findings sequentially")

    # Act & assert
    assert "sdlc_review_findings" in walk
    assert "MUST" in walk


def test_incidental_findings_should_need_no_fetch():
    """Test a deferral costs nothing to report.

    Given:
        Incidental findings are listed, not walked, and the outline already
        carries every id, title and reference.
    When:
        The deferral report is read.
    Then:
        It should say no fetch is needed for them, so the one part of the
        document that is never acted on is never paid for either.
    """
    # Arrange
    walk = _section(_skill_text(), "### 7. Walk through findings sequentially")
    report = walk[walk.index("After the walk"):]

    # Act & assert
    assert "no fetch" in report.lower() or "without fetching" in report.lower()
