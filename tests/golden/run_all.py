"""Run all six golden-task scenarios and print a results table.

Each scenario is a live acceptance test against the real `claude` CLI — expect this to take
several minutes and make real LLM calls. Run a single scenario directly
(`python3 scenario_N_*.py`) when iterating on one; use this to run the full suite before
trusting a calibrated limit (max_heal_cycles, timeouts) per the README.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness

SCENARIOS = [
    ("scenario_1_clean_pass", "1. Clean pass"),
    ("scenario_2_healer_converges", "2. Healer converges"),
    ("scenario_3_no_progress_breaker", "3. No-progress breaker trips"),
    ("scenario_4_flake_quarantined", "4. Flake quarantined, not healed"),
    ("scenario_5_locator_fallback_tier", "5. Locator fallback tier surfaces correctly"),
    ("scenario_6_resume_after_crash", "6. Resume after a crash"),
    ("scenario_7_diff_guard_rejects_assertion_edit", "7. Diff-guard rejects assertion edit"),
]


def main() -> int:
    results = []
    for module_name, display_name in SCENARIOS:
        module = importlib.import_module(module_name)
        results.append(harness.run_scenario(display_name, module.run))

    print("\n| # | Scenario | Result | Duration |")
    print("|---|---|---|---|")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"| | {r.name} | {status} | {r.duration_s:.1f}s |")

    failed = [r for r in results if not r.passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
