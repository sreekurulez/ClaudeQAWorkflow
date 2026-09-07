"""Golden scenario 4 — Flake is quarantined, not healed.

A case that fails once then passes on identical code — confirm quarantine_flaky() catches it
before it ever reaches qa-failure-triage or qa-test-healer, and it's reported (not silently
dropped).

Deterministic by design: rather than relying on a genuinely racy UI element (unreliable to
reproduce identically on every golden-suite run), this uses a small file-counter the spec
itself reads/writes to alternate fail/pass/fail across successive `npx playwright test`
invocations — control-plane-testing scaffolding only, not something the real app or a real
generated spec would ever do. With flake_recheck_runs=3 (config/pipeline.json default), the
case is observed on invocations 1, 2, 3 -> fail, pass, fail -> both outcomes seen -> flaky.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness
from harness import GENERATED_DIR, ROOT

TASK_ID = "golden-4-flake-quarantined"
SPEC_NAME = "golden4-e01-flaky.spec.ts"
COUNTER_FILE = Path("/tmp/golden4-flake-counter.txt")

SPEC_CONTENT = """\
// @plan golden-4-flake-quarantined
// @case golden4-E01
// Deliberately flaky via a file counter (control-plane-testing scaffolding only, not a real
// app interaction) — fails on odd invocation counts, passes on even, so it's observed as both
// failing and passing across quarantine_flaky()'s reruns on identical code.
import { test, expect } from "@playwright/test";
import fs from "fs";

const COUNTER_FILE = "/tmp/golden4-flake-counter.txt";

test("golden4-E01: deliberately flaky demo assertion", async () => {
  let count = 0;
  try {
    count = parseInt(fs.readFileSync(COUNTER_FILE, "utf-8"), 10) || 0;
  } catch {}
  count += 1;
  fs.writeFileSync(COUNTER_FILE, String(count));
  expect(count % 2).toBe(0);
});
"""


def run() -> str:
    harness.clean_task_state(TASK_ID)
    harness.reset_ledger()
    COUNTER_FILE.unlink(missing_ok=True)
    (GENERATED_DIR / SPEC_NAME).write_text(SPEC_CONTENT)

    import heal_loop

    heal_result = heal_loop.run(TASK_ID, str(ROOT), plan_input_hash="golden-4-fixed-hash")

    ledger = harness.ledger_lines()
    triage_calls = [line for line in ledger if line["role"] == "qa-failure-triage"]
    healer_calls = [line for line in ledger if line["role"] == "qa-test-healer"]

    (GENERATED_DIR / SPEC_NAME).unlink(missing_ok=True)
    COUNTER_FILE.unlink(missing_ok=True)
    harness.clean_task_state(TASK_ID)
    harness.reset_ledger()

    assert heal_result["quarantined"] == ["golden4-E01"], f"expected quarantined: {heal_result}"
    assert "golden4-E01" not in heal_result["still_failing"], (
        f"quarantined case must not appear as still failing: {heal_result}"
    )
    assert not heal_result["escalated"], f"quarantine must happen before triage: {heal_result}"
    assert not triage_calls, f"flaky case reached qa-failure-triage, should never have: {triage_calls}"
    assert not healer_calls, f"flaky case reached qa-test-healer, should never have: {healer_calls}"
    return "quarantined before reaching triage or the healer; reported, not silently dropped"


if __name__ == "__main__":
    harness.run_scenario("4. Flake quarantined, not healed", run)
