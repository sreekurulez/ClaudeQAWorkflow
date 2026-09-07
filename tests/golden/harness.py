"""Shared plumbing for the golden-task scenarios (tests/golden/README.md).

Each scenario is a live acceptance test against the real `claude` CLI — these are the
acceptance criteria for the control plane, not unit tests of its logic in isolation (that's
what the ad-hoc mocked-adapter checks done during development covered). Run individually
(`python3 scenario_N_*.py`) or all via `run_all.py`; each is responsible for its own cleanup so
scenarios can run in any order without interfering with each other.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CONTROL_PLANE = ROOT / "control-plane"
GENERATED_DIR = ROOT / "dummy-app" / "tests" / "e2e" / "generated"

if str(CONTROL_PLANE) not in sys.path:
    sys.path.insert(0, str(CONTROL_PLANE))

import manifest  # noqa: E402
import orchestrator  # noqa: E402
from util import STATE_DIR, write_json  # noqa: E402


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    detail: str
    duration_s: float


def run_scenario(name: str, fn) -> ScenarioResult:
    start = time.monotonic()
    try:
        detail = fn()
        passed = True
    except AssertionError as exc:
        detail = f"ASSERTION FAILED: {exc}"
        passed = False
    except Exception as exc:  # noqa: BLE001 — a scenario erroring out is a result, not a crash
        detail = f"ERROR: {type(exc).__name__}: {exc}"
        passed = False
    duration_s = time.monotonic() - start
    result = ScenarioResult(name=name, passed=passed, detail=detail or "", duration_s=duration_s)
    _print_result(result)
    return result


def _print_result(result: ScenarioResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    print(f"[{status}] {result.name} ({result.duration_s:.1f}s)")
    if result.detail:
        print(f"    {result.detail}")


def clean_task_state(task_id: str) -> None:
    task_dir = STATE_DIR / task_id
    if task_dir.exists():
        shutil.rmtree(task_dir)


def clean_generated_specs(*filenames: str) -> None:
    for name in filenames:
        path = GENERATED_DIR / name
        if path.exists():
            path.unlink()


def write_plan(task_id: str, cases: list[dict]) -> None:
    write_json(orchestrator.phase_artifact_path(task_id, "plan"), cases)


def kill_dummy_app_server() -> None:
    """Playwright's `webServer.reuseExistingServer` means a stale server from a prior scenario
    (started with different env, e.g. SEED_BUG) would otherwise silently be reused. Scenarios
    that depend on a specific server env call this first to guarantee a fresh start."""
    subprocess.run(["pkill", "-f", "node server.js"], check=False)
    time.sleep(0.5)


@contextmanager
def seed_bug_env():
    """Runs the wrapped block with SEED_BUG=1 set for any subprocess it launches (Playwright's
    webServer inherits this process's env when it starts dummy-app/server.js)."""
    import os

    kill_dummy_app_server()
    os.environ["SEED_BUG"] = "1"
    try:
        yield
    finally:
        del os.environ["SEED_BUG"]
        kill_dummy_app_server()  # don't leave a SEED_BUG=1 server for the next scenario


def reset_ledger() -> None:
    (STATE_DIR / "ledger.jsonl").write_text("")


def ledger_lines() -> list[dict]:
    import json

    path = STATE_DIR / "ledger.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
