"""Shared helpers for the control plane. No LLM/adapter-specific code here."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
SCHEMA_DIR = ROOT / "schemas"
STATE_DIR = ROOT / "state"
ROLES_DIR = ROOT / "roles"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_project_config() -> dict[str, Any]:
    return load_json(CONFIG_DIR / "project.json")


def load_pipeline_config() -> dict[str, Any]:
    return load_json(CONFIG_DIR / "pipeline.json")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
    tmp.replace(path)  # atomic on same filesystem — no half-written artifacts on crash


def task_state_dir(task_id: str) -> Path:
    d = STATE_DIR / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def hash_files(paths: list[Path]) -> str:
    """Stable hash of one or more source files, used for manifest/locator-map staleness checks."""
    digest = hashlib.sha256()
    for path in sorted(paths):
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def now_iso() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def project_context_block() -> str:
    """Renders config/project.json's project-specific facts (paths, test-isolation strategy,
    auth strategy) as plain text for a role prompt — IMPLEMENTATION_STRATEGY.md §7.3's fix for
    role files hardcoding a literal 'dummy-app/...' path. The four role files
    (qa-test-planner/generator/healer/locator-explorer) reference this block by name instead of
    a hardcoded path, so pointing this control plane at a second project is a config edit, not a
    role-file rewrite.

    Lives in util.py, not orchestrator.py, specifically so heal_loop.py can use it too without
    an orchestrator<->heal_loop circular import (orchestrator.py already imports heal_loop)."""
    project = load_project_config()
    isolation = project.get("test_isolation", {})
    auth = project.get("auth", {})

    lines = [
        "Project Context (from config/project.json — use these, not any path/testid you recall "
        "from training or from a different project):",
        f"- Application root: {project.get('app_root', '(not configured)')}",
        f"- Application source directory: {project.get('app_source_dir', '(not configured)')}",
        f"- Generated tests directory (you may write here): {project.get('e2e_generated_dir', '(not configured)')}",
        f"- Baseline/regression tests directory (NEVER write here): {project.get('e2e_baseline_dir', '(not configured)')}",
    ]

    strategy = isolation.get("strategy")
    if strategy == "reset_endpoint":
        lines.append(
            f"- Test isolation: call {isolation.get('reset_call', '(not configured)')} in "
            "beforeEach for a clean slate before every test."
        )
    elif strategy:
        lines.append(
            f"- Test isolation strategy: '{strategy}' — this app has no reset endpoint; do not "
            "assume one exists. If you cannot determine how to isolate a test under this "
            "strategy, say so in a finding rather than guessing."
        )

    auth_strategy = auth.get("strategy")
    if auth_strategy == "form_login":
        lines.append(
            f"- Auth: navigate to {auth.get('login_route', '(not configured)')}, fill "
            f"data-testid=\"{auth.get('email_testid')}\"/\"{auth.get('password_testid')}\", "
            f"click data-testid=\"{auth.get('submit_testid')}\"."
        )
    elif auth_strategy:
        lines.append(
            f"- Auth strategy: '{auth_strategy}' — do not assume an in-app login form exists. "
            "If no working authenticated-session mechanism is available, say so in a finding "
            "rather than guessing or inventing a login flow."
        )

    return "\n".join(lines)
