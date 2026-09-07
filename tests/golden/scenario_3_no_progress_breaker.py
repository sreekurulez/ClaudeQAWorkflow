"""Golden scenario 3 — No-progress breaker trips.

A case that can't be fixed by selector/wait changes alone (the app genuinely doesn't do what
the plan expects) — confirm the loop stops via no_progress_detected() *before*
max_heal_cycles is exhausted (not just because the cap was hit), the case is escalated rather
than sent to the healer repeatedly, and the final result is BLOCKED with the case named.

Targets dummy-app/server.js's deliberately-seeded SEED_BUG=1 defect (see dummy-app/context.md
§5): with it set, GET /api/items always drops the last matching item — no amount of
selector/wait fixing in a spec can make that true. qa-failure-triage should classify this as a
product-bug on the very first pass, meaning the healer should never even be invoked.

Proof the breaker fired on genuine non-convergence, not just the cycle cap: the ledger should
show exactly ONE qa-failure-triage call for this case, not one per cycle — a second cycle would
mean the loop kept spending budget on a case already known not to be converging.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness
from harness import GENERATED_DIR, ROOT

TASK_ID = "golden-3-no-progress-breaker"
SPEC_NAME = "golden3-e01-seed-bug.spec.ts"

SPEC_CONTENT = """\
// @plan golden-3-no-progress-breaker
// @case golden3-E01
// Hand-written: targets server.js's seeded SEED_BUG=1 defect (drops the last item from
// GET /api/items) — a genuine, unfixable-by-test-edit product defect.
import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page, request }) => {
  await request.post("/api/__test__/reset");
  await page.goto("/");
  await page.getByTestId("login-email").fill("user@example.com");
  await page.getByTestId("login-password").fill("password123");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("item-list")).toBeVisible();
});

test("golden3-E01: all seed items are listed even under SEED_BUG=1", async ({ page }) => {
  await expect(page.getByTestId("item-list").locator("li")).toHaveCount(2);
});
"""


def run() -> str:
    harness.clean_task_state(TASK_ID)
    harness.reset_ledger()
    (GENERATED_DIR / SPEC_NAME).write_text(SPEC_CONTENT)

    import heal_loop

    with harness.seed_bug_env():
        heal_result = heal_loop.run(TASK_ID, str(ROOT), plan_input_hash="golden-3-fixed-hash")

    ledger = harness.ledger_lines()
    triage_calls = [line for line in ledger if line["role"] == "qa-failure-triage"]
    healer_calls = [line for line in ledger if line["role"] == "qa-test-healer"]

    (GENERATED_DIR / SPEC_NAME).unlink(missing_ok=True)
    harness.clean_task_state(TASK_ID)
    harness.reset_ledger()

    assert heal_result["final_verdict"] == "BLOCKED", f"expected BLOCKED: {heal_result}"
    assert heal_result["still_failing"] == ["golden3-E01"], f"expected the case still failing: {heal_result}"
    assert heal_result["escalated"] == ["golden3-E01"], f"expected the case escalated: {heal_result}"
    assert heal_result["no_progress"] is True, f"expected no_progress=True: {heal_result}"
    assert not healer_calls, f"healer should never have been invoked: {healer_calls}"
    assert len(triage_calls) == 1, (
        f"expected exactly one triage call (breaker should stop before a second cycle "
        f"re-triages the same never-converging case), got {len(triage_calls)}"
    )
    return (
        "BLOCKED with golden3-E01 escalated and still failing; exactly 1 triage call and 0 "
        "healer calls confirm the breaker fired before spending a second cycle's budget"
    )


if __name__ == "__main__":
    harness.run_scenario("3. No-progress breaker trips", run)
