"""Golden scenario 6 — Resume after a crash.

Kill the process mid-generate (after some specs are written) — confirm orchestrator.py
--phase generate (or a re-run) picks up from manifest.py's recorded state and does not
regenerate specs already marked done, and that a plan.json change in between correctly
invalidates the manifest instead of silently reusing stale work.

Simulates the crash by pre-seeding generate.manifest.json with one case already marked
"generated" (as if a prior run wrote its spec and then died before reaching the second case),
then calling orchestrator._run_generate_phase() for real: the pending case gets a genuine live
generator call, the already-done case does not (confirmed via the ledger showing exactly one
qa-test-generator invocation, not two), and the final generate.json contains both. Then, with
no more LLM calls, confirms a plan.json content change invalidates the manifest as designed
(both cases become pending again) rather than silently trusting stale entries.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness
from harness import GENERATED_DIR, ROOT

TASK_ID = "golden-6-resume-after-crash"
PRE_EXISTING_SPEC_NAME = "golden6-e01-preexisting.spec.ts"

PLAN = [
    {
        "caseId": "golden6-E01", "priority": "P0", "type": "functional",
        "preconditions": "seed user exists", "steps": "log in with valid credentials",
        "expected": "login succeeds", "selectors": ["login-email", "login-password", "login-submit"],
        "gap": False,
    },
    {
        "caseId": "golden6-E02", "priority": "P1", "type": "functional",
        "preconditions": "logged in", "steps": "log out",
        "expected": "returns to the login screen", "selectors": ["logout-button"], "gap": False,
    },
]


def run() -> str:
    harness.clean_task_state(TASK_ID)
    harness.reset_ledger()

    import manifest
    import orchestrator
    from util import write_json

    orchestrator.write_json(orchestrator.phase_artifact_path(TASK_ID, "plan"), PLAN)
    plan_hash = orchestrator._plan_hash(TASK_ID)

    # Simulate a crash: golden6-E01's spec already exists and is recorded done; golden6-E02 never
    # got that far.
    manifest.upsert(
        TASK_ID, "generate", input_hash=plan_hash, case_id="golden6-E01",
        entry={
            "caseId": "golden6-E01",
            "specPath": f"dummy-app/tests/e2e/generated/{PRE_EXISTING_SPEC_NAME}",
            "status": "generated",
        },
    )

    result = orchestrator._run_generate_phase(TASK_ID, str(ROOT))

    ledger = harness.ledger_lines()
    generator_calls = [line for line in ledger if line["role"] == "qa-test-generator"]

    result_case_ids = {e["caseId"] for e in result["result"]}
    new_spec_files = [
        Path(e["specPath"]).name
        for e in result["result"]
        if e.get("status") == "generated" and e["caseId"] != "golden6-E01"
    ]

    # Part 2: a plan.json content change must invalidate the manifest (no LLM call needed to
    # check this — pure control-plane logic, same as verified during development).
    changed_plan = [dict(PLAN[0], steps="log in with valid credentials (CHANGED)"), PLAN[1]]
    write_json(orchestrator.phase_artifact_path(TASK_ID, "plan"), changed_plan)
    new_hash = orchestrator._plan_hash(TASK_ID)
    pending_after_change = manifest.pending_case_ids(
        TASK_ID, "generate", ["golden6-E01", "golden6-E02"], new_hash
    )

    harness.clean_generated_specs(*new_spec_files)
    harness.clean_task_state(TASK_ID)
    harness.reset_ledger()

    assert result["status"] == "completed", f"expected generate phase to complete: {result}"
    assert result_case_ids == {"golden6-E01", "golden6-E02"}, (
        f"expected generate.json to contain both cases after resume: {result_case_ids}"
    )
    assert len(generator_calls) == 1, (
        f"expected exactly one qa-test-generator call (only for the pending case), got "
        f"{len(generator_calls)}"
    )
    assert set(pending_after_change) == {"golden6-E01", "golden6-E02"}, (
        f"a plan.json content change must invalidate the whole manifest, not just the changed "
        f"case: {pending_after_change}"
    )
    return (
        "resume sent exactly 1 generator call for the pending case, merged result has both "
        "cases, and a plan.json change correctly invalidated the manifest"
    )


if __name__ == "__main__":
    harness.run_scenario("6. Resume after a crash", run)
