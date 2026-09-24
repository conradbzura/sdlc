"""Budget the assembled skill prompts and verify the rationale split holds.

A skill is returned in full on every call of its tool, so its size is a cost
paid per invocation rather than per release. `review.md` grew 2.95x in a single
PR by a mechanism that repeats: a rule is missed mid-document, so the next pass
promotes it into the Invariants block, which lengthens the document for the
rule after that. These budgets exist to make that growth a deliberate, visible
act rather than an accumulation.

The numbers are bytes rather than tokens because bytes are deterministic;
roughly four bytes to the token.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from sdlc.server import _review_skill, _strip_rereview, sdlc_review

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "src/sdlc/skills"
SKILL = SKILLS / "review.md"
RATIONALE = ROOT / "src/sdlc/review-rationale.md"
AGENTS = ROOT / "src/sdlc/AGENTS.md"
SERVER = ROOT / "src/sdlc/server.py"

# The assembled prompt a fresh round pays. This is the number that matters:
# what a caller is charged, not what is on disk.
#
# Raised once, for the third severity tier (#36), which added protocol rather
# than rationale: a classification step in the reviewer brief, a relevance
# rule and a third gated removal path in step 8, a third list at step 9's
# gate, and a tier section in the template. That is new required content, and
# compressing it to hold a number would have meant paraphrasing rules that
# have to be unambiguous. The guard is against *regrowth* — a justification
# promoted into the skill because a rule was missed mid-document — which is
# what the rationale resource exists to absorb. A raise is a deliberate,
# reviewable act; that is the whole point of the budget, not a defect in it.
FRESH_PROMPT_BUDGET = 100_000
REREVIEW_PROMPT_BUDGET = 130_000
# Splitting the file is not licence to write more prose overall.
COMBINED_BUDGET = 160_000

REMEDY = (
    "Design rationale belongs in src/sdlc/review-rationale.md "
    "(`sdlc://review-rationale`), not in the skill."
)


@pytest.mark.asyncio
async def test_sdlc_review_should_stay_within_the_fresh_prompt_budget():
    """Test a fresh round's assembled prompt stays inside its budget.

    Given:
        A fresh paths-mode review, which carries the skill, the template and
        the directives.
    When:
        The prompt is assembled.
    Then:
        It should fit the budget. A fresh round pays this before the diff or
        any file contents arrive, on every pass of every chain.
    """
    # Act
    prompt = await sdlc_review(paths=["src/sdlc/server.py"])

    # Assert
    assert len(prompt) <= FRESH_PROMPT_BUDGET, (
        f"fresh review prompt is {len(prompt) - FRESH_PROMPT_BUDGET} bytes over "
        f"its {FRESH_PROMPT_BUDGET}-byte budget. {REMEDY}"
    )


def test_review_skill_should_stay_within_the_rereview_budget():
    """Test the full skill stays inside the re-review budget.

    Given:
        The re-review assembly, which is the whole skill.
    When:
        Its size is measured.
    Then:
        It should fit the budget, and the skill plus its rationale together
        should fit the combined budget — so the split cannot become a reason
        to write more prose in total.
    """
    # Act
    rereview = len(_review_skill(rereview=True))
    combined = SKILL.stat().st_size + RATIONALE.stat().st_size

    # Assert
    assert rereview <= REREVIEW_PROMPT_BUDGET, (
        f"re-review skill is {rereview - REREVIEW_PROMPT_BUDGET} bytes over "
        f"budget. {REMEDY}"
    )
    assert combined <= COMBINED_BUDGET, (
        f"skill plus rationale is {combined - COMBINED_BUDGET} bytes over the "
        "combined budget: the split is for relocating prose, not adding it."
    )


def test_the_rereview_fences_should_be_balanced_and_flat():
    """Test the mode fences are well formed and the assemblies agree.

    Given:
        The review skill, whose re-review spans are fenced with paired HTML
        comments.
    When:
        Both assemblies are built.
    Then:
        Fences should be balanced and non-nested, the re-review assembly
        should equal the source minus the fence lines, and the fresh assembly
        should be strictly smaller. An unbalanced fence would silently delete
        the rest of the document from a fresh round.
    """
    # Arrange
    raw = SKILL.read_text()
    depth = 0
    for line in raw.splitlines():
        marker = line.strip()
        if marker == "<!-- rereview:begin -->":
            depth += 1
            assert depth == 1, "re-review fences must not nest"
        elif marker == "<!-- rereview:end -->":
            depth -= 1
            assert depth >= 0, "re-review fence closed before it opened"

    # Act
    fresh = _review_skill(rereview=False)
    rereview = _review_skill(rereview=True)

    # Assert
    assert depth == 0, "a re-review fence was opened and never closed"
    assert rereview == raw.replace("<!-- rereview:begin -->\n", "").replace(
        "<!-- rereview:end -->\n", ""
    )
    assert len(fresh) < len(rereview)
    assert _strip_rereview(raw) == fresh


def test_the_fresh_assembly_should_carry_no_rereview_protocol():
    """Test a fresh round is not handed instructions it cannot act on.

    Given:
        The fresh assembly.
    When:
        It is searched for the re-review protocol.
    Then:
        None of it should be present. A fresh round has no seeded findings, so
        a disposition rule or a seeded read-back is not merely wasted context
        — it describes a state the run can never reach.
    """
    # Act
    fresh = _review_skill(rereview=False)

    # Assert
    for protocol in (
        "Read the seeded document back",
        "Phase 2 — reconcile",
        "Fold the seeded findings' dispositions",
        "Retired ids",
        "rediscovered",
        "disposition block",
    ):
        assert protocol not in fresh, protocol


def _cited_anchors() -> set[str]:
    return set(re.findall(r"§(R\d+(?:\.\d+)?)", SKILL.read_text()))


def _rationale_sections() -> set[str]:
    return set(re.findall(r"^#{2,3} (R\d+(?:\.\d+)?)\b", RATIONALE.read_text(), re.M))


def test_every_cited_rationale_anchor_should_resolve():
    """Test no pointer in the skill names a section that does not exist.

    Given:
        The skill's `§R<n>` citations.
    When:
        They are resolved against the rationale's headings.
    Then:
        Every one should resolve. A pointer to a missing section sends an
        agent looking for reasoning that is not there, at the moment it has
        already decided something is wrong.
    """
    # Act & assert
    assert _cited_anchors(), "the skill cites no rationale sections at all"
    assert _cited_anchors() <= _rationale_sections(), (
        f"dangling: {sorted(_cited_anchors() - _rationale_sections())}"
    )


def test_every_rationale_section_should_be_cited():
    """Test the rationale does not become a write-only dumping ground.

    Given:
        The rationale's sections.
    When:
        They are checked against the skill's citations.
    Then:
        Each should be cited by at least one pointer. Rationale nothing leads
        an agent to is rationale nobody reads, and this is the direction that
        rots quietly — a dangling pointer is noticed, an orphaned section is
        not.
    """
    # Act — a parent section is reached through any cited child, so `R8` counts
    # as cited when `R8.3` is.
    cited = _cited_anchors()
    reached = {a.split(".")[0] for a in cited} | cited
    orphans = sorted(_rationale_sections() - reached)

    # Assert
    assert not orphans, f"uncited rationale sections: {orphans}"


def test_rationale_pointers_should_be_conditional_rather_than_imperative():
    """Test a rationale pointer never reads like an instruction to obey.

    Given:
        Every mention of the rationale resource in the skill.
    When:
        Each is inspected.
    Then:
        All but the single Invariants introduction should be italic, lead with
        "Why:", and name an observable trigger. A guide is read
        unconditionally; rationale is read when a block misbehaves, and a
        pointer shaped like the guide idiom would put a resource fetch on the
        critical path of every run.
    """
    # Arrange
    mentions = [
        line for line in SKILL.read_text().splitlines()
        if "sdlc://review-rationale" in line
    ]

    # Act
    pointers = [m for m in mentions if "Passages below and in the steps cite" not in m]

    # Assert
    assert len(mentions) - len(pointers) == 1, "expected exactly one unconditional mention"
    for pointer in pointers:
        body = pointer.strip()
        # Inside a shell fence a pointer is a comment, where markdown italics
        # would be literal text; there it leads with "See" instead.
        in_fence = body.startswith("#")
        assert in_fence or "*Why:" in body, body
        assert "read it" in body or "See `sdlc://review-rationale`" in body, body
        assert any(t in body for t in (" if ", " before ", " when ")), body


def test_the_rationale_should_carry_no_rules():
    """Test no obligation can have been moved out of the skill.

    Given:
        The rationale document.
    When:
        Its lines are scanned for normative sentences.
    Then:
        None should open with an obligation. This is the safety property the
        whole split rests on: every rule either stays in the skill, where the
        existing contract tests assert it, or it would have to appear here as
        a normative sentence — which this forbids. A bare "MUST" substring
        check would be wrong, because the rationale legitimately QUOTES rules
        while explaining them.
    """
    # Arrange
    normative = re.compile(r"^(?:[-*]\s+)?\*{0,2}(MUST|SHALL|STOP|Do NOT)\b")

    # Act
    offenders = [
        line for line in RATIONALE.read_text().splitlines()
        if normative.match(line.strip())
    ]

    # Assert
    assert not offenders, f"rules found in the rationale: {offenders}"
    assert "**This document carries NO rules.**" in RATIONALE.read_text()


def test_every_registered_resource_should_be_documented():
    """Test AGENTS.md's resource table lists every registered resource.

    Given:
        The `@mcp.resource` registrations in server.py.
    When:
        They are checked against AGENTS.md, which calls itself the canonical
        source for pipeline behaviour and is served as a resource itself.
    Then:
        Each URI should appear in the table, so adding a resource without
        documenting it fails here rather than going unnoticed.
    """
    # Arrange
    tree = ast.parse(SERVER.read_text())
    uris = {
        d.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for d in node.decorator_list
        if isinstance(d, ast.Call)
        and getattr(d.func, "attr", None) == "resource"
        and d.args
        and isinstance(d.args[0], ast.Constant)
    }
    agents = AGENTS.read_text()

    # Act
    undocumented = sorted(u for u in uris if u not in agents)

    # Assert
    assert uris, "no resources found in server.py"
    assert not undocumented, f"undocumented resources: {undocumented}"


def test_the_excluded_pathspec_argument_should_appear_once():
    """Test the collapsed duplicate argument did not come back.

    Given:
        The argument about a top-anchored pathspec that excludes nothing was
        written down three times — in step 2's prose, in step 10's third
        validation, and in an in-fence comment.
    When:
        The skill and the rationale are searched for it.
    Then:
        It should appear exactly once, in the rationale. Three copies of one
        argument is how a document grows without saying anything new.
    """
    # Arrange
    needle = "excludes NOTHING"

    # Act
    in_skill = SKILL.read_text().count(needle)
    in_rationale = RATIONALE.read_text().count(needle)

    # Assert
    assert in_skill == 0, f"the argument is back in the skill ({in_skill}x)"
    assert in_rationale == 1, f"expected one copy in the rationale, found {in_rationale}"


@pytest.mark.parametrize(
    ("skill", "budget"),
    [(p, 26_000) for p in sorted(SKILLS.glob("*.md")) if p.name != "review.md"],
    ids=lambda x: x.name if isinstance(x, Path) else x,
)
def test_other_skills_should_stay_within_their_budget(skill, budget):
    """Test no other skill drifts toward review.md's size.

    Given:
        Each bundled skill other than the review skill.
    When:
        Its size is measured.
    Then:
        It should fit a common budget. review.md reached 7.7x the next
        largest skill before anyone measured; this is the measurement.
    """
    # Act & assert
    assert skill.stat().st_size <= budget, (
        f"{skill.name} is {skill.stat().st_size - budget} bytes over budget"
    )
