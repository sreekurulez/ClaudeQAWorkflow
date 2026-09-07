"""Bounded QA heal loop. docs/control-flow-guardrails.md QP1/QP5/QP6/XP3.

Ported logic from finbook-web-application/.factory/scripts/prepush_qa_droids.sh's bash
while-loop (the one place in that framework which got bounding right) — adapted to call
invoke() instead of `droid exec`, and to re-run only failing specs per cycle (XP3) instead of
the whole suite.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import diff_guard
import executor
import manifest
from gates.qa_gate import BLOCKED, no_progress_detected
from invoke import InvocationBlocked, invoke
from util import load_pipeline_config

FLAKE_RERUN_COUNT_DEFAULT = 3  # reuses qa-regression-bootstrapper.md's existing convention (§3.3b)


def quarantine_flaky(task_id: str, cwd: str, failing: list[dict[str, Any]]) -> set[str]:
    """Re-run each newly-failing case up to N times on identical code. A case that both fails
    and passes is flaky — quarantine and report it, never send it to the healer (QP6)."""
    config = load_pipeline_config()
    reruns = config["review"]["qa"].get("flake_recheck_runs", FLAKE_RERUN_COUNT_DEFAULT)
    flaky_ids: set[str] = set()
    for entry in failing:
        spec_path = entry["specPath"]
        outcomes = {entry["result"]}
        for _ in range(reruns - 1):
            executor.run_playwright([spec_path])
            rerun_entries = [e for e in executor.parse_results() if e["specPath"] == spec_path]
            outcomes.update(e["result"] for e in rerun_entries)
        if len(outcomes) > 1:  # both pass and fail observed across reruns
            flaky_ids.add(entry["caseId"])
    return flaky_ids


def triage(task_id: str, cwd: str, entry: dict[str, Any], attempt: int) -> str | None:
    """Classify a failing case as test-defect / product-bug / unclear before it ever reaches
    the healer (docs §3.2/QP1: "product-bug/unclear never healed"). Returns None if triage
    itself failed (timeout, schema-invalid) — treated the same as an explicit "unclear" by the
    caller, since a missing verdict must default safe, not default to healing."""
    try:
        envelope = invoke(
            task_id=task_id,
            role="qa-failure-triage",
            phase="triage",
            prompt=(
                f"Failing entry from execute.json: caseId={entry['caseId']}, "
                f"specPath={entry['specPath']}, category={entry.get('category')}, "
                f"errorSignature={entry.get('errorSignature')}. "
                "Decide: is this a test defect or a product defect?"
            ),
            cwd=cwd,
            attempt=attempt,
        )
    except InvocationBlocked:
        return None
    return envelope.get("result", {}).get("suspected")


def _revert_if_assertion_touched(spec_path: Path, prior_content: str) -> bool:
    """The code-level enforcement of QP7 (docs §3.2): diff the spec's content from before/after
    the healer ran and revert it if any `expect(...)` statement differs at all, independent of
    whatever the model's own `touchedAssertionLine` self-report claims. Assumes the healer is
    always editing a spec that already existed (heal_loop only ever targets specs a prior
    generate phase wrote) — reverting means restoring `prior_content`, never deleting a file."""
    new_content = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""
    if not diff_guard.assertions_changed(prior_content, new_content):
        return False
    spec_path.write_text(prior_content, encoding="utf-8")
    return True


def run(task_id: str, cwd: str, plan_input_hash: str) -> dict[str, Any]:
    config = load_pipeline_config()["review"]["qa"]
    max_heal_cycles = config["max_heal_cycles"]

    executor.run_playwright()
    entries = executor.parse_results()
    failing = [e for e in entries if e["result"] == "fail"]

    flaky_ids = quarantine_flaky(task_id, cwd, failing) if failing else set()
    failing = [e for e in failing if e["caseId"] not in flaky_ids]

    heal_cycle = 0
    prev_failing_ids: set[str] = set()
    # Resume per docs §3.5/GP3/GP4: a case already escalated in a prior (crashed) run of this
    # exact input shouldn't be re-triaged just to reach the same "not a test defect" verdict
    # again. A case previously "fixed" gets no special treatment here — if it's back in
    # `failing` despite that, something regressed since, and it deserves a fresh look.
    prior_manifest = manifest.load_manifest(task_id, "heal")
    escalated_ids: set[str] = (
        {cid for cid, e in prior_manifest["entries"].items() if e.get("action") == "escalated"}
        if prior_manifest["inputHash"] == plan_input_hash
        else set()
    )

    while failing and heal_cycle < max_heal_cycles:
        heal_cycle += 1
        curr_failing_ids = {e["caseId"] for e in failing}

        if no_progress_detected(prev_failing_ids, curr_failing_ids):
            break  # QP5: circuit breaker — stop spending budget on a loop that isn't converging

        for entry in failing:
            case_id = entry["caseId"]
            if case_id in escalated_ids:
                continue  # already triaged off the healer path this run; nothing new to do

            suspected = triage(task_id, cwd, entry, heal_cycle)
            if suspected != "test-defect":
                escalated_ids.add(case_id)
                manifest.upsert(
                    task_id, "heal", input_hash=plan_input_hash, case_id=case_id,
                    entry={
                        "caseId": case_id,
                        "action": "escalated",
                        "attemptNumber": heal_cycle,
                        "touchedAssertionLine": False,
                        "diffSummary": (
                            f"qa-failure-triage: suspected={suspected!r} — not sent to the "
                            "healer (QP1: product-bug/unclear never healed)"
                        ),
                    },
                )
                continue

            spec_path = Path(cwd) / entry["specPath"]
            prior_content = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""

            try:
                envelope = invoke(
                    task_id=task_id,
                    role="qa-test-healer",
                    phase="heal",
                    prompt=(
                        f"Heal case {case_id} at {entry['specPath']}. "
                        f"Failure category: {entry.get('category')}. "
                        f"Error signature: {entry.get('errorSignature')}. "
                        f"This is heal attempt {heal_cycle} of {max_heal_cycles}."
                    ),
                    cwd=cwd,
                    attempt=heal_cycle,
                )
            except InvocationBlocked:
                # Even a blocked/failed invocation may have edited the file before the model's
                # final report failed to parse/validate — the diff-guard applies regardless.
                _revert_if_assertion_touched(spec_path, prior_content)
                continue  # counts against the cycle via ledger; loop bound still applies

            result = envelope.get("result", {})
            if _revert_if_assertion_touched(spec_path, prior_content):
                # QP7, enforced in code: reject and revert regardless of the self-report —
                # never trust `result.get("touchedAssertionLine")` as the deciding factor.
                manifest.upsert(
                    task_id, "heal", input_hash=plan_input_hash, case_id=case_id,
                    entry={
                        "caseId": case_id,
                        "action": "escalated",
                        "attemptNumber": heal_cycle,
                        "touchedAssertionLine": True,
                        "diffSummary": (
                            "diff-guard: heal touched an assertion line and was reverted "
                            f"(model self-reported touchedAssertionLine="
                            f"{result.get('touchedAssertionLine')!r})"
                        ),
                    },
                )
                continue
            manifest.upsert(
                task_id, "heal", input_hash=plan_input_hash, case_id=case_id, entry=result
            )

        executor.run_playwright([e["specPath"] for e in failing])
        entries = executor.parse_results()
        failing = [e for e in entries if e["result"] == "fail" and e["caseId"] not in flaky_ids]
        prev_failing_ids = curr_failing_ids

    no_progress = bool(failing) and no_progress_detected(
        prev_failing_ids, {e["caseId"] for e in failing}
    )

    return {
        "heal_cycle": heal_cycle,
        "max_heal_cycles": max_heal_cycles,
        "still_failing": [e["caseId"] for e in failing],
        "quarantined": sorted(flaky_ids),
        "escalated": sorted(escalated_ids),
        "no_progress": no_progress,
        "final_verdict": BLOCKED if failing else None,  # None = let qa_gate.decide use the reviewer's verdict
    }


if __name__ == "__main__":
    import sys

    print(json.dumps(run(sys.argv[1], sys.argv[2], sys.argv[3]), indent=2))
