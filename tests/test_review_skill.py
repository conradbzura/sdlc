"""Assert the `review` skill document states what it is supposed to state.

The skill is an instruction document, so its text is its contract: a rule that
drifted, an enumeration that went stale, or a cross-reference that no longer
resolves is a defect an agent cannot discover by following it. These tests read
the markdown and the assembled prompts; none of them starts a subprocess, so
they run in the default suite. The blocks that execute against real git
repositories live in `tests/integration/test_review_skill.py`.
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
    AGENTS,
    RATIONALE,
    SKILL,
    _bash_blocks,
    _invariants,
    _line,
    _scope_section,
    _section,
    _skill_text,
    _step10_block,
    _step10_blocks,
    _step10_section,
    _step2,
    _step7,
    _step8,
    _step9,
    _variant,
)

TEMPLATE = Path(__file__).resolve().parents[1] / "src/sdlc/review-template.md"

# Phrasings that would DENY the gate exists, as opposed to describing when it
# does not fire. The distinction is the finding: a step that says "no approval
# gate" reads as permission to proceed.
_GATE_DENIALS = (
    "no approval gate",
    "absence of an approval gate",
    "without an approval gate",
)

# What makes such a sentence honest: it names the case in which the gate does
# not fire, rather than asserting the write is ungated outright.
_DENIAL_QUALIFIERS = (
    "fresh round",
    "exception",
    "per-finding approval gate",
    "two",
)


from sdlc.pr_state import render_findings

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



def test_rereview_should_secure_the_seeded_document_before_dispatching():
    """Test the irreversible step still precedes any reviewer.

    Given:
        Step 7, which the checklist presents as the agent's plan skeleton,
        and an in-place rewrite that destroys whatever was not secured.
    When:
        The re-review path is read.
    Then:
        It should account for what the seeded block carries and copy the
        document, both before any reviewer is dispatched. The fields the
        block once dropped are still enumerated — now as what it carries
        rather than as what must be recovered — so a later change that makes
        the block lossy again cannot pass silently.
    """
    # Arrange
    section = _step7()

    # Act
    accounting = section.index("Know what the seeded block carries")
    copy = section.index("Copy the file before you do anything else")
    dispatch = section.index("Phase 1 — review.")

    # Assert
    assert accounting < copy < dispatch
    for field in (
        "attribution",
        "Tests to add",
        "cross-cutting decisions",
        "pass counter",
    ):
        assert field in section[accounting:dispatch], field
    assert "**(re-review)** copy the seeded document first" in _skill_text()



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
    assert "sdlc_review_findings(<the Review document path>, [])" in section
    assert not any(
        b.lstrip().startswith(("awk", "grep")) for b in _bash_blocks(section)
    ), "a hand-written scanner is back; call the parser instead"
    assert not any("from sdlc import" in b for b in _bash_blocks(section)), (
        "the enumeration is back on a shell-out. `uv run` resolves against the "
        "REVIEWED project's environment, where this package is not installed, "
        "so the step would be unrunnable everywhere but this repository. Prose "
        "NAMING the pattern is the prohibition and is expected here; an "
        "executable block carrying it is the defect."
    )



def test_the_reviewer_brief_should_be_one_unbroken_blockquote():
    """Test no pointer splits or contaminates the brief the reviewer receives.

    Given:
        The brief is a blockquote, copied wholesale into each reviewer's
        prompt, and the rationale must never be quoted into one.
    When:
        Every line between the brief's introduction and its closing bullet is
        read.
    Then:
        Each should be a quote line. A blank line followed by unquoted prose
        TERMINATES the blockquote — silently dropping every bullet below it,
        including the `.sdlc/reviews/` prohibition that phase-1 blindness
        rests on — and an unquoted line with no blank before it is absorbed
        INTO the preceding bullet, putting orchestrator-directed text in the
        reviewer's prompt.
    """
    # Arrange
    lines = _skill_text().splitlines()
    start = next(
        i for i, l in enumerate(lines) if "Each reviewer's brief MUST include:" in l
    )
    end = next(
        i
        for i, l in enumerate(lines)
        if "return your raw findings to the orchestrator" in l
    )

    # Act
    body = [l for l in lines[start + 1 : end + 1] if l.strip()]

    # Assert
    assert body, "the brief is empty"
    for line in body:
        assert line.startswith(">"), (
            f"non-quote line inside the reviewer brief: {line[:120]!r}"
        )
    assert any("Do NOT read anything under `.sdlc/reviews/`" in l for l in body)



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
    assert "copy the seeded" in invariants
    assert "Retired ids" in invariants
    assert "two reviewers agreeing" in invariants
    assert "explicit user confirmation" in invariants



def test_invariants_should_carry_the_mandatory_fetch():
    """Test the one mandatory fetch has an invariant and a verification.

    Given:
        The seeded block is an outline, so every finding body must be fetched
        with `sdlc_review_findings` before it is acted on.
    When:
        The Invariants block and step 9 are read.
    Then:
        The invariant should be stated where every other load-bearing MUST is
        stated, and step 9 should verify it against the dispositioned set.
        Stated only at its point of use, it was the sole load-bearing rule in
        this skill that nothing restated and nothing checked.
    """
    # Arrange
    invariants = _invariants()
    step9 = _section(_skill_text(), "### 9. Finalize the consolidated document")

    # Act & assert
    assert "sdlc_review_findings" in invariants
    assert "Reconcile the fetched set" in step9



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
        Each should name the path it describes or the exceptions that apply,
        and the document should still describe the gate somewhere — by a
        qualified denial or by stating it positively. The gate is real on a
        re-review, and a bare denial mid-document is what let three documents
        disagree about it for four passes.
    """
    # Arrange
    text = document.read_text()
    sentences = [
        sentence
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if any(denial in sentence for denial in _GATE_DENIALS)
    ]

    # Act & assert
    assert "approval gate" in text, (
        f"{document.name} no longer describes the gate at all"
    )
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
    assert "two reviewers that were dispatched that finding" in step9
    assert "STOP here and wait for the user's answer" in step9



def test_the_blocking_close_gate_should_count_dispositioning_reviewers_everywhere():
    """Test all four statements of the close gate name the same predicate.

    Given:
        The gate appears in review.md's Invariants, step 8 and step 9, and in
        AGENTS.md.
    When:
        Each statement is read.
    Then:
        Every one should key on the reviewers that were dispatched the
        finding, and none should key on glob coverage. "Covers" means glob
        coverage everywhere else in these documents, and both shipped roles
        cover every skill file — so the glob-keyed form exempted the gate for
        essentially every finding in the ordinary two-role composition.
    """
    # Arrange
    predicate = "two reviewers that were dispatched that finding"
    skill, agents = SKILL.read_text(), AGENTS.read_text()

    # Act & assert
    assert skill.count(predicate) == 3, "Invariants, step 8 and step 9"
    assert agents.count(predicate) == 1
    for text, name in ((skill, "review.md"), (agents, "AGENTS.md")):
        assert "a single role covers it" not in text, name
        assert "only one role covers the finding" not in text, name
        assert "one reviewer of one role covers it" not in text, name



def test_the_new_id_rule_should_never_be_qualified_by_tier():
    """Test no statement of the id rule computes the maximum per tier.

    Given:
        Every place review.md, AGENTS.md and the template state how a new
        finding's id is chosen.
    When:
        Each is read.
    Then:
        None should qualify the maximum by tier. Re-tiering keeps a finding's
        id, so a `B4` re-tiered into Tier 2 is invisible to a maximum taken
        over Tier 1 and the next blocking finding is issued `B4` again — a
        live collision with an open finding, which silently re-points every
        commit-history and implement-loop citation of it at a different
        defect. Three of five sites carried the tier reading before this.
    """
    # Arrange
    template = (
        Path(__file__).resolve().parents[1] / "src/sdlc/review-template.md"
    ).read_text()

    # Act & assert
    for text, name in (
        (SKILL.read_text(), "review.md"),
        (AGENTS.read_text(), "AGENTS.md"),
        (template, "review-template.md"),
    ):
        for phrase in ("in its tier", "in their tier", "in that tier"):
            assert phrase not in text, f"{name} states the id rule per tier"



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
    # Act
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



def test_count_reconciliation_should_agree_with_the_parser_on_a_fenced_heading(
    tmp_path, monkeypatch
):
    """Test the id-set gate does not fire on a document that parsed cleanly.

    Given:
        A review document whose finding quotes a finding heading inside a
        fence, and which carries a heading outside the severity tiers.
    When:
        Step 7(0)'s reconciliation route is run against it.
    Then:
        It should yield exactly the ids `parse_review_document` yields — the
        incidental tier included, the fenced sample and the heading quoted
        inside a NESTED fence both skipped, and the out-of-tier heading
        ignored. The scanner this replaced failed all three: it matched only
        Tiers 1 and 2, and its fence toggle desynced on a nested opener and
        invented an id. A MUST-STOP gate that fires on healthy input is one
        an agent learns to skip.
    """
    # Arrange
    monkeypatch.chdir(tmp_path)
    document = tmp_path / ".sdlc" / "reviews" / "issue-#1" / "review-1.md"
    document.parent.mkdir(parents=True)
    document.write_text(
        "# Doc\n\n## Tier 1 — Blocking\n\n"
        "### B1 — Real one **(BLOCKING)** — aie\n"
        "**Reference:** `a.py:1`\n\n"
        "**Issue:** quoting a sample:\n\n"
        "```markdown\n### B9 — Phantom **(BLOCKING)** — aie\n```\n\n"
        "**Remediation:**\n- [x] Fix.\n\n"
        "### B2 — Quoting a nested sample **(BLOCKING)** — aie\n"
        "**Reference:** `a.py:9`\n\n"
        "**Issue:** the template heads its findings like this:\n\n"
        "````markdown\n```\n### B98 — Phantom inside a nested fence\n```\n````\n\n"
        "**Remediation:**\n- [x] Fix.\n\n"
        "## Tier 2 — Advisory\n\n"
        "### A1 — Real advisory — aie\n"
        "**Reference:** `b.py:2`\n\n"
        "Body.\n- [x] Fix.\n\n"
        "## Tier 3 — Incidental\n\n"
        "### I1 — Real incidental — aie\n"
        "**Reference:** `c.py:3`\n\n"
        "Body.\n- [x] Fix.\n\n"
        "## Cross-cutting decisions\n\n"
        "### B99 — Outside the tiers — aie\n"
    )
    # Act
    enumeration = render_findings(document, [])

    # Assert
    from sdlc.pr_state import parse_review_document

    ids = enumeration.rpartition("\nIds: ")[2].split()
    parsed = [f.id for f in parse_review_document(document, 1, 1).findings]
    assert ids == ["B1", "B2", "A1", "I1"], enumeration
    assert ids == parsed



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
    """Test both summaries defer to step 7(0) instead of re-listing fields.

    Given:
        Three passages could describe what the seeded block carries — the
        Arguments note, the re-review read-back invariant, and step 7(0).
    When:
        The Arguments note and the invariant are read.
    Then:
        Both should defer to step 7(0) rather than enumerate the fields, and
        neither should call the block lossy. Two independent lists drift, and
        they had: the Arguments copy inverted the truth in both directions
        while the invariant listed the exact COMPLEMENT of what is elided.
    """
    # Arrange
    text = _skill_text()
    note = next(
        line for line in text.splitlines() if "The block is an **outline**" in line
    )
    invariant = next(
        line for line in _invariants().splitlines() if "MUST copy the seeded" in line
    )

    # Act & assert
    assert "The block is **lossy**" not in text
    assert "Step 7(0) enumerates what arrives verbatim" in note
    for passage in (note, invariant):
        assert "Tests to add" not in passage
        assert "cross-cutting decisions" not in passage
        assert "Step 7(0)" in passage



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
        if "only with corroboration" in line
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



def test_the_brief_should_seed_scope_rather_than_bound_it():
    """Test the changed files start the reviewer off instead of fencing it in.

    Given:
        `sdlc_role_scope` can only ever return changed files, so treating
        its result as the boundary is what put a missing change out of
        reach.
    When:
        Step 5 and the reviewer brief are read.
    Then:
        Both should call that set a seed, and the brief should authorize
        extension to any file the role covers that is related to a
        criterion — naming the criterion that admits it.
    """
    # Arrange
    step5 = _section(_skill_text(), "### 5. Resolve each role's lens and mapped files")
    brief = _step7()

    # Act & assert
    assert "seed" in step5
    assert "not the boundary" in step5
    assert "starting point" in brief
    assert "name the criterion" in brief
    # The hard outer bound survives the widening.
    assert "guide-map.role" in brief



def test_the_brief_should_direct_a_sweep_for_changes_that_were_never_made():
    """Test a reviewer is sent looking for what is absent, not just present.

    Given:
        A change an acceptance criterion required and nobody made leaves no
        trace in the diff, so nothing in a diff-driven review surfaces it.
    When:
        The reviewer brief is read.
    Then:
        It should direct a per-criterion sweep — identify the code that
        should satisfy each criterion and verify it does — and name the
        missing change as a finding in its own right.
    """
    # Arrange
    brief = _step7()

    # Act & assert
    assert "should have been made and was not" in brief
    assert "first-class finding" in brief
    assert "verify that it does" in brief
    assert "identify the code that should satisfy it" in brief



def test_step8_should_validate_the_role_a_finding_is_attributed_to():
    """Test the confinement invariant is checked and not merely instructed.

    Given:
        Reviewers now extend their own scope, so the role glob is the only
        mechanical bound left and the brief is the only thing that had ever
        enforced it.
    When:
        Step 8's consolidation rules are read.
    Then:
        They should re-run `sdlc_role_scope` per finding and re-attribute an
        out-of-map finding rather than drop it — losing a real finding to a
        bookkeeping rule is the worse of the two failures.
    """
    # Arrange
    rule = _line(_step8(), "- **Validate each finding's attribution**")

    # Act & assert
    assert "sdlc_role_scope" in rule
    assert "NOT dropped" in rule
    assert "re-attribute" in rule.lower()



def test_a_finding_with_no_owning_commit_should_still_be_attributable():
    """Test an omission can be recorded where every finding needs a commit.

    Given:
        A change that was never made has no commit that touched it, and
        every PR-mode finding carries a `Touched commit`.
    When:
        Step 8's attribution rule, the template and the fixup mapping are
        read.
    Then:
        All three should carry the omission form, and the fixup mapping
        should route it to a new commit rather than to a fixup against a
        commit that does not exist.
    """
    # Arrange
    rule = _line(_step8(), "- **(PR mode) Attribute each finding to a commit**")
    template = TEMPLATE.read_text()

    # Act & assert
    assert "(no commit — omission)" in rule
    assert "(no commit — omission)" in template
    assert "new commit" in rule
    assert "new commit" in _section(template, "## Fixup mapping")



def test_the_document_should_record_scope_extensions():
    """Test a widened scope is auditable after the fact.

    Given:
        Reviewers may now admit files the PR never touched, on their own
        judgement.
    When:
        The template's header is read.
    Then:
        It should record, per role, the globs that scoped it and any file
        admitted by extension with the criterion that admitted it — so a
        later pass can see what was reviewed and why.
    """
    # Arrange
    scope_line = _line(TEMPLATE.read_text(), "**Scope**")

    # Act & assert
    assert "globs" in scope_line
    assert "extension" in scope_line
    assert "criterion" in scope_line



def test_step7_should_fetch_bodies_before_composing_a_phase_two_message():
    """Test a reviewer is never handed a finding with its body elided.

    Given:
        The seeded block now carries each finding's heading and reference
        with the issue text and remediation held back.
    When:
        Step 7's phase-2 dispatch is read.
    Then:
        It should require fetching the role's subset with
        `sdlc_review_findings` before the message is composed — a reviewer
        cannot disposition a finding whose body it was not shown.
    """
    # Arrange
    step7 = _step7()

    # Act & assert
    assert "sdlc_review_findings" in step7
    assert "elided" in step7
    assert "MUST" in step7.split("sdlc_review_findings")[0].rsplit("\n", 3)[0]



def test_step8_should_forbid_dispositioning_an_unfetched_finding():
    """Test the fetch is a precondition for acting, not a suggestion.

    Given:
        A disposition is judged against a finding's body, which the outline
        does not carry.
    When:
        Step 8 is read.
    Then:
        It should forbid applying a disposition to a finding whose body was
        never fetched — the failure that would make disclosure worse than no
        disclosure.
    """
    # Arrange
    step8 = _step8()

    # Act & assert
    assert "sdlc_review_findings" in step8
    assert "MUST NOT" in step8



def test_step7_zero_should_no_longer_read_back_what_the_block_carries():
    """Test the read-back shrank to what the outline cannot supply.

    Given:
        The seeded block is the document's own structure now, so role
        attribution, full titles, `Tests to add`, both ledgers and the
        cross-cutting sections arrive verbatim.
    When:
        Step 7(0) is read.
    Then:
        It should say those arrive in the block and name finding bodies as
        what still has to be fetched — an instruction that still claims to
        recover them is an instruction nobody will follow twice.
    """
    # Arrange
    step7 = _step7()
    start = step7.index("**(re-review) 0. Know what the seeded block carries")
    section = step7[start : step7.index("\n\n**Copy the file", start)]

    # Act & assert
    assert "verbatim" in section
    assert "body" in section.lower()
    assert "sdlc_review_findings" in section



def test_the_body_fetch_should_not_use_the_rationale_pointer_idiom():
    """Test a required fetch is not written as an optional one.

    Given:
        `sdlc://review-rationale` pointers are italic, trigger-gated and
        skippable by design.
    When:
        The skill's `sdlc_review_findings` mentions are read.
    Then:
        None should be written in that idiom. The two look alike, and a
        later pass that harmonizes them turns a required read into an
        optional one.
    """
    # Arrange
    mentions = [
        line
        for line in _skill_text().splitlines()
        if "sdlc_review_findings" in line
    ]

    # Act & assert
    assert mentions
    for line in mentions:
        assert not line.strip().startswith("*Why:"), line



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
        if "only with corroboration" in line
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


def test_every_cited_rationale_section_should_carry_prose():
    """Test no `*Why:` pointer resolves to an unwritten section.

    Given:
        Every `§R<n>` id review.md cites, and the rationale's sections.
    When:
        Each cited section is read.
    Then:
        It should resolve, and carry prose rather than a placeholder. The
        `*Why:` idiom is trigger-gated disclosure: an agent that fetches on
        the stated trigger and finds `_Pending extraction._` proceeds on its
        own guess, which is the outcome the idiom exists to prevent. A
        pointer to a placeholder is worse than no pointer.
    """
    # Arrange
    rationale = RATIONALE.read_text()
    cited = set(re.findall(r"§(R\d+(?:\.\d+)*)", SKILL.read_text()))
    sections = {
        match.group(1): match.start()
        for match in re.finditer(r"^#{2,4} (R\d+(?:\.\d+)*)\.?\s", rationale, re.M)
    }

    # Act & assert
    assert cited, "review.md cites no rationale sections at all"
    for anchor in sorted(cited):
        assert anchor in sections, f"§{anchor} is cited but has no section"
    assert "_Pending extraction._" not in rationale, (
        "a rationale section is still a placeholder; every §R id review.md "
        "cites must resolve to prose that answers the trigger it names"
    )
