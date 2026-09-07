"""Golden scenario 1 — Clean pass.

plan -> locate -> generate -> execute -> review, zero heal cycles, verdict PASS or REFACTOR.

Live acceptance test: runs the real orchestrator.run_pipeline() against a real, small change to
dummy-app/server.js and asserts the whole thing converges without ever needing the heal loop.

Refined from the README's literal "verdict: PASS": a live run against this app's full surface
touches its deliberately-planted role-fallback elements (the delete/logout buttons — see
dummy-app/context.md's testability requirements), and qa-reviewer correctly flags those at least
P2 every time per its own contract, which makes REFACTOR ("shippable, quality notes to raise")
the honest verdict, not a defect. What this scenario actually guarantees — that nothing failed,
no heal cycle was needed, and the pipeline didn't get stuck or wrongly BLOCKED — holds either
way, so both PASS and REFACTOR count as "clean" here; only BLOCKED (or a still-failing case)
would mean the guardrail machinery itself broke, which is what this scenario exists to catch.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness
from harness import ROOT

TASK_ID = "golden-1-clean-pass"


def run() -> str:
    harness.clean_task_state(TASK_ID)
    harness.kill_dummy_app_server()  # ensure no stale SEED_BUG=1 server from another scenario

    import orchestrator

    result = orchestrator.run_pipeline(
        task_id=TASK_ID,
        cwd=str(ROOT),
        changed_files=[str(ROOT / "dummy-app" / "server.js")],
    )

    generate_result = orchestrator.load_json(orchestrator.phase_artifact_path(TASK_ID, "generate"))
    specs_written = [
        Path(e["specPath"]).name for e in generate_result if e.get("status") == "generated"
    ]
    harness.clean_generated_specs(*specs_written)
    harness.clean_task_state(TASK_ID)

    verdict = result.get("verdict")
    assert verdict in ("PASS", "REFACTOR"), f"expected PASS or REFACTOR, got: {result}"
    heal_cycle = result.get("heal_result", {}).get("heal_cycle")
    assert heal_cycle == 0, f"expected zero heal cycles for a clean pass, got heal_cycle={heal_cycle}"
    still_failing = result.get("heal_result", {}).get("still_failing", [])
    assert not still_failing, f"expected nothing still failing, got: {still_failing}"
    return (
        f"verdict={verdict}, heal_cycle=0, {len(specs_written)} case(s) generated and executed "
        "clean (REFACTOR here means quality notes only, e.g. role-fallback locators — not a defect)"
    )


if __name__ == "__main__":
    harness.run_scenario("1. Clean pass", run)
