"""Golden scenario 5 — Locator fallback tier surfaces correctly.

Run qa-locator-explorer against the item list's delete button (no data-testid, see
dummy-app/public/app.js) — confirm it's tagged role-fallback, and that qa-reviewer flags any
case using it (severity present at all; P2 is already the schema's lowest tier, so "at least
P2" means the finding must exist, not be silently omitted).

Self-contained: builds its own locator map via a direct invoke() call (real testability_check
facts, real live qa-locator-explorer call) rather than touching the project's shared
state/locator-map.json, so running this scenario has no side effect on that cached file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness
from harness import ROOT

TASK_ID = "golden-5-locator-fallback"


def run() -> str:
    harness.reset_ledger()

    import invoke
    import testability_check

    facts_json = testability_check.facts_to_json(
        testability_check.scan_paths(testability_check._default_paths())
    )
    locate_prompt = (
        "Testability fact list (from a deterministic grep/AST check the control plane ran — "
        "control-plane/testability_check.py):\n"
        f"{facts_json}\n\n"
        "Crawl dummy-app/public/ source to confirm/interpret these facts and produce the "
        "locator map."
    )
    locate_envelope = invoke.invoke(
        task_id=TASK_ID, role="qa-locator-explorer", phase="locate", prompt=locate_prompt, cwd=str(ROOT)
    )
    locator_map = locate_envelope["result"]

    # Match on fallbackSelector text, not `name` — dummy-app also has confirm-delete-button /
    # cancel-delete-button, which are legitimately stable-testid and would false-positive on a
    # name-only "delete" match. Only role-fallback/flagged-unstable elements carry a
    # fallbackSelector at all, so this is inherently scoped to the element this scenario targets.
    delete_elements = [
        el
        for route in locator_map
        for el in route["elements"]
        if "delete" in el.get("fallbackSelector", "").lower()
    ]
    assert delete_elements, f"no delete-button-like element found in the locator map: {locator_map}"
    for el in delete_elements:
        assert el["confidenceTier"] == "role-fallback", f"expected role-fallback, got: {el}"

    plan = [{
        "caseId": "golden5-E01", "priority": "P1", "type": "functional",
        "steps": "Delete an item via its Delete button and confirm the deletion.",
        "expected": "The item is removed from the list.",
        "selectors": ["item-delete-button"], "gap": False,
    }]
    generate_result = [{
        "caseId": "golden5-E01",
        "specPath": "dummy-app/tests/e2e/generated/golden5-e01-delete.spec.ts",
        "status": "generated",
    }]
    heal_result = {
        "heal_cycle": 0, "max_heal_cycles": 2, "still_failing": [], "quarantined": [],
        "escalated": [], "no_progress": False, "final_verdict": None,
    }
    review_prompt = (
        f"plan.json:\n{json.dumps(plan, indent=2)}\n\n"
        f"generate.json:\n{json.dumps(generate_result, indent=2)}\n\n"
        f"heal loop result:\n{json.dumps(heal_result, indent=2)}\n\n"
        f"state/locator-map.json:\n{json.dumps(locator_map, indent=2)}\n\n"
        "All cases above have been executed and passed. Give your final review verdict."
    )
    review_envelope = invoke.invoke(
        task_id=TASK_ID, role="qa-reviewer", phase="review", prompt=review_prompt, cwd=str(ROOT)
    )
    findings = review_envelope["result"]["findings"]
    matching = [f for f in findings if f.get("caseId") == "golden5-E01"]

    harness.reset_ledger()

    assert matching, f"expected qa-reviewer to flag golden5-E01 (uses a role-fallback locator): {findings}"
    for finding in matching:
        assert finding.get("severity") in ("P0", "P1", "P2"), f"unexpected severity: {finding}"
    return (
        f"delete button tagged role-fallback ({len(delete_elements)} element(s)); "
        f"reviewer flagged golden5-E01 with {len(matching)} finding(s)"
    )


if __name__ == "__main__":
    harness.run_scenario("5. Locator fallback tier surfaces correctly", run)
