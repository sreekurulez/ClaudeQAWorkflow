"""Control-plane-owned resumable manifest. docs/control-flow-guardrails.md §3.5/GP3/GP4.

Deliberately NOT written by the agent. The control plane upserts an entry only after a
schema-valid, ledger-recorded result for that caseId — never from the model's own claim of
progress. This is the direct application of the "don't trust the LLM with bookkeeping"
lesson from the Factory analysis to checkpointing specifically.

Batching per docs §3.3b: `generate` checkpoints per spec written (one invocation, many specs);
`heal` checkpoints per invocation (one caseId per call, isolation is worth the overhead).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from util import load_json, task_state_dir, write_json


def manifest_path(task_id: str, phase: str) -> Path:
    return task_state_dir(task_id) / f"{phase}.manifest.json"


def load_manifest(task_id: str, phase: str) -> dict[str, Any]:
    path = manifest_path(task_id, phase)
    if not path.is_file():
        return {"inputHash": None, "entries": {}}
    return load_json(path)


def upsert(task_id: str, phase: str, *, input_hash: str, case_id: str, entry: dict[str, Any]) -> None:
    """Record one unit of work as done. Called by the control plane immediately after a
    schema-validated result for `case_id`, never in bulk at the end of a phase."""
    manifest = load_manifest(task_id, phase)
    if manifest["inputHash"] is not None and manifest["inputHash"] != input_hash:
        # Input changed since this manifest was built (e.g. plan.json regenerated) — a
        # "done" entry from the old hash describes work for a different input, so start over
        # rather than silently skip cases (§3.3b).
        manifest = {"inputHash": None, "entries": {}}
    manifest["inputHash"] = input_hash
    manifest["entries"][case_id] = entry
    write_json(manifest_path(task_id, phase), manifest)


def pending_case_ids(task_id: str, phase: str, all_case_ids: list[str], input_hash: str) -> list[str]:
    """Cases not yet marked done for this phase, given the plan's current input hash.
    A hash mismatch invalidates the whole manifest (§3.3b) rather than silently skipping
    cases that describe stale work."""
    manifest = load_manifest(task_id, phase)
    if manifest["inputHash"] is not None and manifest["inputHash"] != input_hash:
        return list(all_case_ids)  # stale manifest — treat as if nothing is done
    done = {cid for cid, e in manifest["entries"].items() if e.get("done", True)}
    return [cid for cid in all_case_ids if cid not in done]
