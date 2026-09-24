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

from sdlc.pr_state import parse_review_document
from sdlc.server import review_skill, sdlc_review

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "src/sdlc/skills"
SKILL = SKILLS / "review.md"
RATIONALE = ROOT / "src/sdlc/review-rationale.md"
AGENTS = ROOT / "src/sdlc/AGENTS.md"
README = ROOT / "README.md"
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
#
# Raised a second time, for the context/scope definitions. Worth recording
# what the two raises have cost together: #37 cut the assembled fresh prompt
# from 138,587 to 85,790 bytes, and the two features since have spent most of
# that back. That entry then said a third raise should be answered with an
# extraction pass rather than another number.
#
# Raised a third time anyway, for the review-2 pass-2 remediation, and the
# reasoning is recorded here rather than left to contradict the line above.
# The re-review budget is the one that moved; the fresh one did not, because
# the same pass REMOVED 2,233 bytes of re-review-only material that had been
# leaking into every fresh round. What pushed the re-review assembly over was
# not regrowth of the kind this guard exists to catch: it is the gate wording
# the pass's own findings required — a close gate restated over the reviewers
# that judged a finding rather than over glob coverage, a STOP that step 9
# never carried, and routing defined over every role recorded on a finding
# instead of one. Those are rules, and rules belong in the skill; the
# rationale resource cannot absorb them. Two enumerations were collapsed into
# template pointers in the same pass to pay part of it back.
#
# The extraction pass that entry asks for is still the right answer to the
# NEXT raise. This one bought correctness in the approval gates, which is the
# thing the budget is protecting the agent's attention for.
FRESH_PROMPT_BUDGET = 106_000
REREVIEW_PROMPT_BUDGET = 132_000

# The rationale's own size. This REPLACES a combined skill-plus-rationale cap,
# and the replacement is a real loosening, so here is the argument for it.
#
# The combined cap existed to stop the split becoming licence to write more
# prose overall. It treated the two files as fungible, and they are not: the
# skill is paid on every call, the rationale only when an agent fetches it.
# Adding a paragraph to the skill costs every pass of every chain; adding one
# here costs nothing until something goes wrong. Three features in, the
# combined cap was firing on rationale growth — which is the behaviour the
# split exists to encourage — while the number that actually matters, the
# assembled prompt above, still had headroom.
#
# The discipline the combined cap was standing in for is kept where it bites:
# the fresh prompt is 3 KB under its budget, so the "extraction pass, not
# another number" rule still governs the skill. What is given up is a guard
# against the rationale becoming a dumping ground — and that is covered by
# `test_every_rationale_section_should_be_cited`, which already fails on a
# section nothing points at.
RATIONALE_BUDGET = 50_000

# The share of a full render that the disclosed block may cost. The review
# document outgrew the skill without anyone measuring it — 108,405 bytes for
# 55 findings, against a 102,452-byte fresh prompt — because nothing budgeted
# the one artifact that grows with every pass of every chain.
DISCLOSURE_SHARE = 0.60

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
        It should fit the budget, and the rationale should fit its own. The
        two are budgeted separately because they are paid differently: the
        skill on every call, the rationale only when an agent fetches it.
    """
    # Act
    rereview = len(review_skill(rereview=True))
    rationale = RATIONALE.stat().st_size

    # Assert
    assert rereview <= REREVIEW_PROMPT_BUDGET, (
        f"re-review skill is {rereview - REREVIEW_PROMPT_BUDGET} bytes over "
        f"budget. {REMEDY}"
    )
    assert rationale <= RATIONALE_BUDGET, (
        f"the rationale is {rationale - RATIONALE_BUDGET} bytes over its "
        "budget. It is read on demand, so this is a one-off cost rather than "
        "a per-call one — but a document this size is one nobody finishes. "
        "Consider the templated `sdlc://review-rationale/{topic}` split."
    )


# Content belonging to the re-review protocol alone. A fresh round has no
# seeded findings and no prior pass, so each of these describes a state it can
# never reach. Every entry is also asserted PRESENT in the re-review assembly,
# so the list cannot rot into strings that match nothing and pass vacuously —
# which is how the six-literal sample this replaced went green while the whole
# of step 10(d)'s commit protocol leaked into a fresh round.
REREVIEW_ONLY = (
    "MUST copy the seeded",
    "Phase 2 — reconcile",
    "Fold the seeded findings' dispositions",
    "Retired ids",
    "rediscovered",
    "disposition block",
    "Each finding-set mutation is then its OWN commit",
    "When every seeded finding carries",
    ".target.md",
    "On a re-review, repeat the document",
    "carried WITHOUT re-examination",
    "Every seeded finding carried",
)

# A line OPENING with the marker is a block only a re-review can act on — a
# paragraph, bullet or command block that inherits the label. An inline
# `**(re-review)**` clause inside a rule both modes need is a different thing
# and stays: fencing those would fragment rules that have to be read whole.
_OPENS_REREVIEW = re.compile(r"^\s*(?:[-*]|\d+\.)?\s*(?:—\s*)?\*\*\(re-review\)\*\*")

# Content BOTH assemblies need. A fence that swallows one of these DELETES it
# from the fresh prompt, and no absence check can see a deletion — which is
# why this list exists alongside the one above rather than instead of it.
MODE_INDEPENDENT = (
    "**(paths mode):**",
    'mkdir -p "$worktree/$(dirname "<Review document in repository>")"',
    'cp "<Review snapshot directory>"/*',
    "The committed variant above continues",
    'git -C "<repo>" worktree remove --force "$worktree"',
)


# A line that opens a new block element, so a line break before it is Markdown
# structure rather than a wrap. `*Why:` is this repository's rationale-pointer
# idiom, which always follows the sentence it annotates as its own block.
_BLOCK_START = re.compile(r"^(\||#|>|<!--|\*Why:|([-*+]|\d+\.)\s)")


def _wrapped_paragraphs(text: str) -> list[list[tuple[int, str]]]:
    """Return runs of consecutive prose lines that look hard-wrapped."""
    runs: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    in_fence = in_frontmatter = False
    for number, line in enumerate(text.splitlines(), 1):
        if number == 1 and line.strip() == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            in_frontmatter = line.strip() != "---"
            continue
        if re.match(r"^\s*(`{3,}|~{3,})", line):
            in_fence = not in_fence
            current = []
            continue
        stripped = line.strip()
        if in_fence or not stripped or _BLOCK_START.match(stripped):
            if len(current) > 1:
                runs.append(current)
            current = []
            continue
        current.append((number, line))
    if len(current) > 1:
        runs.append(current)
    # A run is a wrap only if every line but the last stopped short of the
    # width a deliberate long line would have run past.
    return [r for r in runs if all(len(l) < 100 for _, l in r[:-1])]


@pytest.mark.parametrize(
    "document",
    sorted((ROOT / "src/sdlc").rglob("*.md")),
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_bundled_markdown_should_never_hard_wrap_prose(document):
    """Test no bundled document wraps a paragraph at a fixed column.

    Given:
        The Markdown style guide's only MUST NOT: prose is never arbitrarily
        hard-wrapped, and each block-level element is a single long line.
    When:
        Every bundled document is scanned outside fences and frontmatter.
    Then:
        No run of consecutive prose lines should look wrapped. The convention
        is load-bearing here beyond the rule: this suite and the skill tests
        assert on block-level elements by line, so a wrapped paragraph
        silently breaks the assertions that read them.
    """
    # Act
    runs = _wrapped_paragraphs(document.read_text())

    # Assert
    assert not runs, "\n".join(
        f"{document.name}:{r[0][0]}-{r[-1][0]} looks hard-wrapped: {r[0][1][:70]!r}"
        for r in runs
    )


def test_the_rereview_fences_should_be_balanced_and_flat():
    """Test the mode fences are well formed and the assemblies nest.

    Given:
        The review skill, whose re-review spans are fenced with paired HTML
        comments.
    When:
        Both assemblies are built.
    Then:
        Fences should be balanced and non-nested, neither assembly should
        emit a marker, and the fresh assembly should be the re-review one
        with whole spans removed — every fresh line present, in order. An
        unbalanced fence would silently delete the rest of the document from
        a fresh round.
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
    fresh = review_skill(rereview=False)
    rereview = review_skill(rereview=True)

    # Assert
    assert depth == 0, "a re-review fence was opened and never closed"
    assert "<!-- rereview:" not in fresh
    assert "<!-- rereview:" not in rereview
    assert len(fresh) < len(rereview)
    remaining = iter(rereview.splitlines())
    for line in fresh.splitlines():
        assert line in remaining, (
            f"fresh assembly line is not in the re-review assembly, in order: "
            f"{line!r}. The two must differ only by whole fenced spans."
        )


def test_the_fresh_assembly_should_carry_no_rereview_protocol():
    """Test a fresh round is not handed instructions it cannot act on.

    Given:
        Both assemblies.
    When:
        They are searched for the re-review protocol.
    Then:
        None of it should reach the fresh assembly, and all of it should be
        in the re-review one. A fresh round has no seeded findings, so a
        disposition rule or a per-mutation commit recipe is not merely wasted
        context — it describes a state the run can never reach.
    """
    # Act
    fresh = review_skill(rereview=False)
    rereview = review_skill(rereview=True)

    # Assert
    for protocol in REREVIEW_ONLY:
        assert protocol in rereview, (
            f"{protocol!r} is in neither assembly, so the check below is "
            "vacuous. Update the list to track the skill."
        )
        assert protocol not in fresh, protocol
    for line in fresh.splitlines():
        assert not _OPENS_REREVIEW.match(line), (
            f"a re-review-only block reached the fresh assembly: {line[:120]!r}. "
            "A fence is enclosing the label rather than the material it governs."
        )


def test_the_fresh_assembly_should_orphan_no_rationale_pointer():
    """Test no `*Why:` pointer survives the stripping of what it points at.

    Given:
        Both assemblies. A `*Why:` line is trigger-gated disclosure: it names
        an observable symptom and the block it sits under is what the symptom
        is about.
    When:
        Each pointer's preceding non-blank line is compared between them.
    Then:
        It should be the same line in both. A pointer whose subject block is
        fenced while the pointer is not lands in the fresh prompt attached to
        whatever happens to precede it — advice about a state that round
        cannot reach, filed under an unrelated instruction.

        This is a property rather than a list, so unlike `REREVIEW_ONLY` it
        cannot rot: a fence added anywhere is checked the moment it lands.
    """
    # Arrange
    fresh = review_skill(rereview=False).splitlines()
    rereview = review_skill(rereview=True).splitlines()

    def preceding(lines, index):
        cursor = index - 1
        while cursor >= 0 and not lines[cursor].strip():
            cursor -= 1
        return lines[cursor] if cursor >= 0 else ""

    subjects = {}
    for index, line in enumerate(rereview):
        if line.startswith("*Why:"):
            subjects.setdefault(line, []).append(preceding(rereview, index))

    # Act & assert
    for index, line in enumerate(fresh):
        if not line.startswith("*Why:"):
            continue
        assert line in subjects, (
            f"a pointer is in the fresh assembly but not the re-review one, "
            f"which cannot happen unless the fences are unbalanced: {line[:90]!r}"
        )
        assert preceding(fresh, index) in subjects[line], (
            f"orphaned rationale pointer in the fresh assembly: {line[:90]!r}\n"
            f"  it follows: {preceding(fresh, index)[:90]!r}\n"
            f"  but in the re-review assembly it follows: "
            f"{subjects[line][0][:90]!r}\n"
            "The fence encloses the subject block but not the pointer."
        )


def test_the_fresh_assembly_should_define_every_marker_it_carries():
    """Test no `**(re-review)**` marker outlives its own definition.

    Given:
        The fresh assembly, and the two sentences in the source that say what
        the marker means.
    When:
        The assembly is searched for the marker.
    Then:
        Either no marker should survive, or the sentence defining it should
        survive with them. An inline marker is deliberately left unfenced —
        fencing it would fragment a rule both modes need — but that only works
        while the fresh prompt still says what the label means. One of the
        markers that leaked was on the approval-gate invariant, pointing at an
        invariant that had itself been fenced away.
    """
    # Act
    fresh = review_skill(rereview=False)

    # Assert
    if "**(re-review)**" in fresh:
        assert "applies only when the `Re-review` directive is present" in fresh, (
            f"the fresh assembly carries {fresh.count('**(re-review)**')} "
            "`**(re-review)**` marker(s) while every sentence defining the "
            "marker is fenced out of it. Either fence the clauses carrying "
            "the marker, or leave an unfenced gloss of what it means."
        )


def test_the_fresh_assembly_should_keep_every_mode_independent_block():
    """Test a fence has not swallowed a block a fresh round needs.

    Given:
        Both assemblies.
    When:
        They are searched for blocks neither mode can do without — the
        worktree mirror that step 10(d) stages from, the paths-mode
        next-steps prompt, and the worktree teardown.
    Then:
        Each should be present in both. A fence misplaced around a label
        rather than around the material it governs deletes these from the
        fresh prompt silently, and an absence check cannot detect a deletion.
    """
    # Act
    fresh = review_skill(rereview=False)
    rereview = review_skill(rereview=True)

    # Assert
    for block in MODE_INDEPENDENT:
        assert block in rereview, f"{block!r} is missing from the skill entirely"
        assert block in fresh, (
            f"{block!r} was stripped from the fresh assembly. A re-review "
            "fence is enclosing material that is not re-review-only."
        )


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


def _registered(kind: str) -> set[str]:
    """Names registered with `@mcp.<kind>()` in server.py.

    Resources are keyed by their URI argument; tools have none, so they are
    keyed by the decorated function's name.
    """
    tree = ast.parse(SERVER.read_text())
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            if not (isinstance(d, ast.Call) and getattr(d.func, "attr", None) == kind):
                continue
            if d.args and isinstance(d.args[0], ast.Constant):
                found.add(d.args[0].value)
            else:
                found.add(node.name)
    return found


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

        This deliberately does NOT also run over README.md yet: the README
        documents templated URIs by concrete instance rather than by pattern,
        and it is missing `sdlc://config/default` — a finding recorded as
        incidental (it predates this branch), so it is deferred rather than
        fixed here. The tool check below DOES cover both documents, which is
        the half that matters: a tool a consumer is required to call.
    """
    # Arrange
    uris = _registered("resource")
    agents = AGENTS.read_text()

    # Act
    undocumented = sorted(u for u in uris if u not in agents)

    # Assert
    assert uris, "no resources found in server.py"
    assert not undocumented, f"undocumented resources: {undocumented}"


@pytest.mark.parametrize("document", [AGENTS, README], ids=lambda p: p.name)
def test_every_registered_tool_should_be_documented(document):
    """Test both user-facing documents list every registered tool.

    Given:
        The `@mcp.tool` registrations in server.py.
    When:
        They are checked against AGENTS.md and README.md.
    Then:
        Each tool name should appear in both. A tool a consumer is REQUIRED
        to call is the one whose absence costs most, and that is exactly the
        one that shipped undocumented.
    """
    # Arrange
    tools = _registered("tool")
    text = document.read_text()

    # Act
    undocumented = sorted(t for t in tools if f"`{t}`" not in text)

    # Assert
    assert tools, "no tools found in server.py"
    assert not undocumented, f"undocumented in {document.name}: {undocumented}"


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


def _synthetic_review_document(findings: int) -> str:
    """Build a review document with `findings` blocking findings."""
    blocks = []
    for n in range(1, findings + 1):
        blocks.append(
            f"### B{n} — A finding with a reasonably typical title **(BLOCKING)** "
            f"— general-purpose (1/1)\n"
            f"**Reference:** `src/sdlc/module_{n}.py:{n * 7}`\n\n"
            "**Issue:** " + ("Evidence prose that states the defect concretely. " * 12)
            + "\n\n**Remediation:**\n"
            "- [x] Do the recommended thing. *(Recommended — it is the fix.)*\n"
            "- [ ] Do the alternative thing.\n"
            "- [ ] Other: ________________________________________________\n\n"
            f"**Touched commit:** `abc{n:04d}`\n"
        )
    return (
        "# PR #1 — Round 1 Review\n\n**Pass 1** — "
        f"{findings} blocking, 0 advisory, 0 incidental open.\n\n"
        "---\n\n## Tier 1 — Blocking\n\n"
        + "\n---\n\n".join(blocks)
        + "\n## Tier 2 — Advisory\n\n## Cross-cutting decisions\n\nNone.\n"
    )


def test_the_disclosed_document_should_cost_a_fraction_of_the_full_render(tmp_path):
    """Test the review document is disclosed rather than dumped.

    Given:
        A fifty-finding review document, the size a chain reaches after a
        few passes.
    When:
        The block both endpoints inject is compared with the full render
        they used to inject.
    Then:
        It should cost a fraction of it while still naming every finding.
        This is the first budget on the review document, which outgrew the
        skill precisely because nothing measured it.
    """
    # Arrange
    path = tmp_path / "review-1.md"
    path.write_text(_synthetic_review_document(50))
    parsed = parse_review_document(path, issue_number=1, iteration=1)

    # Act
    disclosed = parsed.disclose()
    full = parsed.format()

    # Assert
    assert len(disclosed) <= DISCLOSURE_SHARE * len(full), (
        f"the disclosed block is {len(disclosed):,} bytes against a "
        f"{len(full):,}-byte full render — over the "
        f"{DISCLOSURE_SHARE:.0%} share. Finding bodies belong behind "
        "`sdlc_review_findings`, not in the injected block."
    )
    # And the enumeration is whole, which is what makes the elision safe.
    for n in range(1, 51):
        assert f"### B{n} —" in disclosed, n
    assert disclosed.count("body elided") == 50
