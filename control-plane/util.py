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
