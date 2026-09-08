"""Deterministic test executor. docs/control-flow-guardrails.md XP1 — NOT an LLM.

Runs Playwright, parses its JSON reporter output directly into execute.json. Factory's
qa-test-executor droid used an LLM to do this same mechanical extraction (case ID, pass/fail,
failure category) while holding `Execute` — that's half of the actual runaway feedback loop.
Building it as a script from day one removes that failure mode entirely rather than adding a
guardrail around it later. Only real judgment (test-defect vs. product-bug on a *failure*) is
a separate, narrow LLM call — see roles/qa-failure-triage.md, invoked only when needed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from util import ROOT, load_project_config

_CASE_COMMENT_RE = re.compile(r"//\s*@case\s+(\S+)")

# Playwright's actual JSON-reporter status vocabulary: "passed" | "failed" | "timedOut" |
# "skipped" | "interrupted". "skipped" is deliberately NOT mapped here — an env-gated case
# (e.g. a spec that only runs under SEED_BUG=1) being absent from this run is neither a pass
# nor a failure; counting it as "fail" would make no-progress detection and the heal loop treat
# an inapplicable case as a real defect to chase.
_STATUS_MAP = {"passed": "pass", "failed": "fail", "timedOut": "fail", "interrupted": "fail"}

CATEGORY_HINTS = {
    "toBeVisible": "selector",
    "getByTestId": "selector",
    "getByRole": "selector",
    "toHaveText": "assertion",
    "toHaveURL": "assertion",
    "Timeout": "timing",
    "exceeded": "timing",
}


def run_playwright(spec_paths: list[str] | None = None) -> None:
    """Runs the configured e2e command(s). When spec_paths is given, runs only those specs
    (docs XP3 — heal cycles re-run only failing specs, not the whole suite)."""
    project = load_project_config()
    app_root = ROOT / project["app_root"]
    for command in project["e2e_test_commands"]:
        cmd = command.split()
        if spec_paths:
            cmd += spec_paths
        subprocess.run(cmd, cwd=app_root, check=False)


def _categorize(error_text: str) -> str:
    for hint, category in CATEGORY_HINTS.items():
        if hint in error_text:
            return category
    return "unknown"


def parse_results() -> list[dict[str, Any]]:
    """Reads Playwright's JSON reporter output and emits execute.schema.json-shaped entries."""
    project = load_project_config()
    results_path = ROOT / project["e2e_results_path"]
    if not results_path.is_file():
        return []

    with results_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    entries: list[dict[str, Any]] = []
    for suite in raw.get("suites", []):
        _walk_suite(suite, entries)
    return entries


def _walk_suite(suite: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    project = load_project_config()
    for spec in suite.get("specs", []):
        # Playwright reports `file` relative to testDir; every other artifact (generate.json,
        # what the healer is told to open) uses repo-root-relative paths, so normalize here once.
        file_rel = spec.get("file", "")
        abs_spec_path = ROOT / project["app_root"] / "tests" / "e2e" / file_rel if file_rel else None
        repo_rel_spec_path = str(abs_spec_path.relative_to(ROOT)) if abs_spec_path else file_rel
        case_id = _extract_case_id(spec, abs_spec_path)
        for test in spec.get("tests", []):
            for result in test.get("results", []):
                status = result.get("status", "unknown")
                if status == "skipped":
                    continue  # not applicable this run — not a pass or a failure, see _STATUS_MAP
                outcome = _STATUS_MAP.get(status, "fail")
                error_text = " ".join(
                    e.get("message", "") for e in result.get("errors", [])
                )
                entries.append(
                    {
                        "caseId": case_id,
                        "specPath": repo_rel_spec_path,
                        "result": outcome,
                        "errorSignature": error_text[:200] if error_text else None,
                        "category": _categorize(error_text) if error_text else None,
                        "durationMs": result.get("duration", 0),
                    }
                )
    for child in suite.get("suites", []):
        _walk_suite(child, entries)


def _extract_case_id(spec: dict[str, Any], abs_spec_path: Path | None) -> str:
    """Generated specs carry `// @case <id>` per roles/qa-test-generator.md's contract — but
    that's a source comment, not part of the test title, so Playwright's JSON reporter never
    surfaces it via `title`. Read the spec file itself; fall back to the title only if the
    comment is missing (e.g. hand-written specs that don't follow the convention)."""
    if abs_spec_path is not None and abs_spec_path.is_file():
        match = _CASE_COMMENT_RE.search(abs_spec_path.read_text(encoding="utf-8"))
        if match:
            return match.group(1)
    title = spec.get("title", "unknown")
    return title.split("@case")[-1].strip().split()[0] if "@case" in title else title


def _resolve_app_root(value: str) -> Path:
    """Every other config path is ROOT-relative because dummy-app lives inside this repo.
    component_test_app_root doesn't — the component-test target (e.g. finbook-web-application)
    is a sibling repo outside this one — so this accepts an absolute path too, rather than
    forcing an awkward '../' relative value into a config convention built for paths inside
    ROOT."""
    path = Path(value)
    return path if path.is_absolute() else ROOT / value


def run_jest(spec_paths: list[str] | None = None, *, with_coverage: bool = False) -> None:
    """Component-test-track equivalent of run_playwright() (IMPLEMENTATION_STRATEGY.md §2.3 —
    Stage 3). Reads `component_test_command` from project config rather than assuming
    `react-scripts test` or bare `jest` — Finbook uses the former, a Jest-native project the
    latter. `--json --outputFile=<component_test_results_path>` is appended here, not baked
    into config, so the config value stays a plain "how do I run this project's tests" command
    a human could also run by hand.

    `with_coverage` opts into Jest's own --collectCoverage (IMPLEMENTATION_STRATEGY.md §6/Stage
    8's "measured" traceability tier) — real overhead (~19s vs <1s, verified live), so this is
    never the default; call it explicitly once a spec has already passed once via the normal
    path, not on every run."""
    project = load_project_config()
    app_root = _resolve_app_root(project["component_test_app_root"])
    results_path = ROOT / project["component_test_results_path"]
    for command in project["component_test_command"]:
        cmd = command.split() + ["--json", f"--outputFile={results_path}"]
        if spec_paths:
            cmd += ["--testPathPattern", "|".join(re.escape(p) for p in spec_paths)]
        if with_coverage:
            cmd += ["--collectCoverage", "--coverageReporters=json-summary"]
        subprocess.run(cmd, cwd=app_root, check=False, env={**os.environ, "CI": "true"})


def parse_jest_coverage() -> list[str]:
    """Reads Jest's own coverage-summary.json (produced by run_jest(with_coverage=True)) and
    returns repo-relative paths of files with genuine statement coverage — verified live
    against a real run: the summary lists every instrumented file in the project (thousands),
    almost all at zero: filtering on statements.covered > 0 isolates exactly the files the run
    actually touched, cleanly, no further heuristics needed."""
    project = load_project_config()
    app_root = _resolve_app_root(project["component_test_app_root"])
    summary_path = app_root / "coverage" / "coverage-summary.json"
    if not summary_path.is_file():
        return []
    with summary_path.open("r", encoding="utf-8") as handle:
        summary = json.load(handle)
    touched = []
    for file_path, stats in summary.items():
        if file_path == "total":
            continue
        if stats.get("statements", {}).get("covered", 0) > 0:
            abs_path = Path(file_path)
            touched.append(str(abs_path.relative_to(app_root)) if abs_path.is_relative_to(app_root) else file_path)
    return touched


def parse_jest_results() -> list[dict[str, Any]]:
    """Reads Jest's own --json reporter output (verified against a live run against the real
    finbook-web-application repo, 2026-09-08 — not assumed) into execute.schema.json-shaped
    entries, mirroring parse_results()'s Playwright path. Jest's shape is simpler than
    Playwright's: no nested suite tree to walk, and (in the version actually installed) no
    per-assertion duration — durationMs is reported as 0, which is schema-valid (the field is
    required, not required non-zero)."""
    project = load_project_config()
    results_path = ROOT / project["component_test_results_path"]
    if not results_path.is_file():
        return []

    with results_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    entries: list[dict[str, Any]] = []
    for test_file in raw.get("testResults", []):
        abs_path = Path(test_file["name"])
        repo_rel_spec_path = str(abs_path.relative_to(ROOT)) if abs_path.is_relative_to(ROOT) else test_file["name"]
        case_id = _extract_case_id({}, abs_path)
        for assertion in test_file.get("assertionResults", []):
            status = assertion.get("status", "unknown")
            if status in ("pending", "todo"):
                continue  # same "not applicable this run" treatment as Playwright's "skipped"
            outcome = "pass" if status == "passed" else "fail"
            error_text = " ".join(assertion.get("failureMessages", []))
            entries.append(
                {
                    "caseId": case_id,
                    "specPath": repo_rel_spec_path,
                    "result": outcome,
                    "errorSignature": error_text[:200] if error_text else None,
                    "category": _categorize(error_text) if error_text else None,
                    "durationMs": 0,
                }
            )
    return entries


def mark_flaky(entries: list[dict[str, Any]], flaky_case_ids: set[str]) -> list[dict[str, Any]]:
    for entry in entries:
        if entry["caseId"] in flaky_case_ids:
            entry["result"] = "flaky"
    return entries


if __name__ == "__main__":
    run_playwright()
    print(json.dumps(parse_results(), indent=2))
