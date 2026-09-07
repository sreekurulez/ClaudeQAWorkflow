"""Golden scenario 2 — Healer converges.

Generator produces one case with a broken selector; healer fixes it within max_heal_cycles;
final result has nothing still failing and nothing escalated. Confirms heal_loop.py's happy
path and that manifest.py records the fix (not just that the file changed).

Deterministic by design: rather than relying on a live planner/generator to happen to produce a
broken selector (unpredictable), this hand-writes a spec with a single, known selector typo
("login-emial" for "login-email") — a genuine test defect a healer should be able to fix without
touching any assertion line. Skips plan/generate/locate entirely to keep this cheap: only
qa-failure-triage + qa-test-healer are live LLM calls here.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness
from harness import GENERATED_DIR, ROOT

TASK_ID = "golden-2-healer-converges"
SPEC_NAME = "golden2-e01-broken-selector.spec.ts"

SPEC_CONTENT = """\
// @plan golden-2-healer-converges
// @case golden2-E01
import { test, expect } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  await request.post("/api/__test__/reset");
});

test("golden2-E01: valid credentials log the user in", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("login-emial").fill("user@example.com");
  await page.getByTestId("login-password").fill("password123");
  await page.getByTestId("login-submit").click();

  await expect(page.getByTestId("current-user-indicator")).toBeVisible();
});
"""


def run() -> str:
    harness.clean_task_state(TASK_ID)
    harness.kill_dummy_app_server()
    (GENERATED_DIR / SPEC_NAME).write_text(SPEC_CONTENT)

    import heal_loop
    import manifest

    heal_result = heal_loop.run(TASK_ID, str(ROOT), plan_input_hash="golden-2-fixed-hash")

    manifest_state = manifest.load_manifest(TASK_ID, "heal")
    entry = manifest_state["entries"].get("golden2-E01")

    (GENERATED_DIR / SPEC_NAME).unlink(missing_ok=True)
    harness.clean_task_state(TASK_ID)

    assert not heal_result["still_failing"], f"expected nothing still failing: {heal_result}"
    assert not heal_result["escalated"], f"expected no escalation for a genuine selector typo: {heal_result}"
    assert heal_result["heal_cycle"] <= heal_result["max_heal_cycles"]
    assert entry is not None, "expected a manifest entry for golden2-E01"
    assert entry.get("action") == "fixed", f"expected action=fixed, got: {entry}"
    assert entry.get("touchedAssertionLine") is False, f"healer touched an assertion line: {entry}"
    return (
        f"healed in {heal_result['heal_cycle']} cycle(s), manifest recorded "
        f"action=fixed, touchedAssertionLine=False"
    )


if __name__ == "__main__":
    harness.run_scenario("2. Healer converges", run)
