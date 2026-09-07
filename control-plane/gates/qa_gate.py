"""Mechanical QA gate. docs/control-flow-guardrails.md QP4/QP5/Q5.

Decides PASS/REFACTOR/BLOCKED from structured data (heal-cycle count vs. max_heal_cycles,
failing-caseId-set comparisons, reviewer envelope) — never from prose-scanning, and never
leaves "cycles exhausted" as advice the orchestrator may or may not act on. This is deliberately
a plain function, not an agent call: everything it needs is already a fact by the time it runs.
"""
from __future__ import annotations

from typing import Any

PASS, REFACTOR, BLOCKED = "PASS", "REFACTOR", "BLOCKED"


def decide(
    *,
    heal_cycle: int,
    max_heal_cycles: int,
    no_progress: bool,
    review_envelope: dict[str, Any] | None,
) -> str:
    """Single mechanical decision point. Call this instead of asking an agent 'should we
    keep going?' — every input here is already a fact, not a judgment call."""
    if no_progress:
        return BLOCKED  # QP5: failing-case set didn't shrink across cycles — stop, don't spend the rest of the budget
    if heal_cycle >= max_heal_cycles:
        return BLOCKED  # QP4: mechanically enforced regardless of what any agent concluded

    if review_envelope is None:
        return BLOCKED  # missing verdict defaults safe, per Factory's qa_gate.py precedent

    verdict = review_envelope.get("verdict")
    if verdict not in (PASS, REFACTOR, BLOCKED):
        return BLOCKED
    return verdict


def no_progress_detected(prev_failing_ids: set[str], curr_failing_ids: set[str]) -> bool:
    """Compare failing-caseId SETS across cycles, not counts (§2 downside: fixing one case can
    legitimately expose others temporarily, so a raw count can false-positive)."""
    if not prev_failing_ids:
        return False
    return curr_failing_ids >= prev_failing_ids  # no strict shrinkage
