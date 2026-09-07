"""Deterministic sequencer. docs/control-flow-guardrails.md §3.3 (Phase 5 note).

This script IS the hypothesis under test: Factory's orchestrator is an LLM reasoning over
prose to decide sequencing/retries (the root cause the whole analysis is about). Here,
sequencing is a plain script from day one. If this works fine, that's direct evidence for
demoting Factory's orchestrator role too, not just its QA sub-agents.

Supports single-phase invocation (GP2: "granular invocation" and "test one subagent directly"
are the same feature once phases are addressable) via --phase.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import executor
import heal_loop
import manifest
import testability_check
from gates.qa_gate import decide
from invoke import InvocationBlocked, invoke
from util import ROOT, STATE_DIR, hash_files, load_json, load_project_config, task_state_dir, write_json

PHASES = ["locate", "plan", "generate", "execute", "review"]

# "execute" (deterministic script, not an LLM — see executor.py) and "locate" (deterministic
# script + qa-locator-explorer, handled by locate() below) are not in this map; run_phase()
# special-cases both instead of going through the generic invoke() path.
PHASE_ROLES = {
    "plan": "qa-test-planner",
    "generate": "qa-test-generator",
    "review": "qa-reviewer",
}

LOCATOR_MAP_PATH = STATE_DIR / "locator-map.json"
LOCATOR_MAP_HASH_PATH = STATE_DIR / "locator-map.hash"

_MAX_EMBED_CHARS = 20_000  # crude cap so one huge changed file can't blow out the prompt


def phase_artifact_path(task_id: str, phase: str) -> Path:
    return task_state_dir(task_id) / f"{phase}.json"


def _artifact_block(path: Path, label: str) -> str:
    if not path.is_file():
        return f"{label}: (not present)"
    text = path.read_text(encoding="utf-8")
    if len(text) > _MAX_EMBED_CHARS:
        text = text[:_MAX_EMBED_CHARS] + "\n... <truncated>"
    return f"{label}:\n{text}"


def _changed_files_block(changed_files: list[str]) -> str:
    if not changed_files:
        return "Changed files: (none given)"
    parts = ["Changed files:"]
    for f in changed_files:
        path = Path(f)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            text = f"<< could not read: {exc} >>"
        if len(text) > _MAX_EMBED_CHARS:
            text = text[:_MAX_EMBED_CHARS] + "\n... <truncated>"
        parts.append(f"--- {f} ---\n{text}")
    return "\n\n".join(parts)


def _build_prompt(
    task_id: str,
    phase: str,
    changed_files: list[str] | None,
    *,
    plan_override: list | None = None,
) -> str:
    """Each role's contract (roles/*.md) names exactly what it needs in the prompt — this
    embeds the real artifact content rather than sending a one-line description of it, per
    docs/control-flow-guardrails.md's general preference for handing an agent facts directly
    over having it re-derive them by exploring (the same reasoning as G4/LP1).

    `plan_override` is used on a generate-phase resume (see `_run_generate_phase`): only the
    still-pending cases are sent, not the full plan, so a crash-and-restart doesn't re-ask the
    generator to redo work `state/<task-id>/generate.manifest.json` already has recorded."""
    if phase == "plan":
        return "\n\n".join([
            _changed_files_block(changed_files or []),
            _artifact_block(LOCATOR_MAP_PATH, "state/locator-map.json"),
        ])
    if phase == "generate":
        if plan_override is not None:
            plan_block = (
                "plan.json (RESUMED — only still-pending cases shown below; others are "
                "already generated per state/<task-id>/generate.manifest.json and must not be "
                "redone):\n" + json.dumps(plan_override, indent=2)
            )
        else:
            plan_block = _artifact_block(phase_artifact_path(task_id, "plan"), "plan.json")
        return "\n\n".join([plan_block, _artifact_block(LOCATOR_MAP_PATH, "state/locator-map.json")])
    if phase == "review":
        return "\n\n".join([
            _artifact_block(phase_artifact_path(task_id, "plan"), "plan.json"),
            _artifact_block(phase_artifact_path(task_id, "generate"), "generate.json"),
            _artifact_block(phase_artifact_path(task_id, "heal"), "heal loop result"),
            _artifact_block(LOCATOR_MAP_PATH, "state/locator-map.json"),
            "All cases above have been executed; give your final review verdict.",
        ])
    raise ValueError(f"no prompt builder for phase {phase!r}")


def locate(cwd: str) -> dict | None:
    """Deterministic testability check (testability_check.py, LP1) → qa-locator-explorer →
    state/locator-map.json. Skips the LLM call when the scanned source hasn't changed since the
    last locate — a coarse, whole-app version of the per-route delta trigger item 12 defers;
    good enough for this POC's one-shot full-crawl mode (see README's Layout section)."""
    scan_paths = testability_check._default_paths()
    current_hash = hash_files(scan_paths)
    if (
        LOCATOR_MAP_HASH_PATH.is_file()
        and LOCATOR_MAP_HASH_PATH.read_text().strip() == current_hash
        and LOCATOR_MAP_PATH.is_file()
    ):
        return None  # up to date, nothing to do

    facts_json = testability_check.facts_to_json(testability_check.scan_paths(scan_paths))
    prompt = (
        "Testability fact list (from a deterministic grep/AST check the control plane ran — "
        "control-plane/testability_check.py):\n"
        f"{facts_json}\n\n"
        "Crawl dummy-app/public/ source to confirm/interpret these facts and produce the "
        "locator map."
    )
    envelope = invoke(task_id="_locator", role="qa-locator-explorer", phase="locate", prompt=prompt, cwd=cwd)
    if envelope["status"] == "completed":
        write_json(LOCATOR_MAP_PATH, envelope["result"])
        LOCATOR_MAP_HASH_PATH.write_text(current_hash)
    return envelope


def _plan_hash(task_id: str) -> str:
    """Generate's manifest is keyed off plan.json's own content — manifest.py's docstring
    example is exactly this case ("input changed... e.g. plan.json regenerated"). Distinct from
    heal's manifest, which stays keyed off the changed-files hash (unmodified here)."""
    plan_path = phase_artifact_path(task_id, "plan")
    return hash_files([plan_path]) if plan_path.is_file() else ""


def _run_generate_phase(task_id: str, cwd: str) -> dict:
    """Resumable per docs §3.5/GP3/GP4: a crash after some specs are written must not force a
    full re-run. Reads plan.json, asks manifest.py which caseIds are still pending under the
    plan's current hash, and — when the manifest is only partially done — sends the generator
    just those, then merges its result with the already-recorded entries so generate.json still
    ends up complete. A plan.json change (different hash) invalidates the whole manifest instead
    of silently reusing stale entries (manifest.py's own rule, not re-implemented here)."""
    plan_path = phase_artifact_path(task_id, "plan")
    plan = load_json(plan_path) if plan_path.is_file() else []
    all_case_ids = [c["caseId"] for c in plan]
    plan_hash = _plan_hash(task_id)

    manifest_state = manifest.load_manifest(task_id, "generate")
    done_entries = dict(manifest_state["entries"]) if manifest_state["inputHash"] == plan_hash else {}
    pending_ids = manifest.pending_case_ids(task_id, "generate", all_case_ids, plan_hash)

    if not pending_ids:
        # Everything in the current plan is already recorded done — no LLM call needed at all.
        result = list(done_entries.values())
        write_json(phase_artifact_path(task_id, "generate"), result)
        return {"status": "completed", "result": result}

    plan_override = [c for c in plan if c["caseId"] in pending_ids] if done_entries else None
    prompt = _build_prompt(task_id, "generate", None, plan_override=plan_override)
    envelope = invoke(task_id=task_id, role="qa-test-generator", phase="generate", prompt=prompt, cwd=cwd)

    new_entries = envelope.get("result", []) if envelope["status"] == "completed" else []
    for entry in new_entries:
        manifest.upsert(task_id, "generate", input_hash=plan_hash, case_id=entry["caseId"], entry=entry)

    merged = {**done_entries, **{e["caseId"]: e for e in new_entries}}
    write_json(phase_artifact_path(task_id, "generate"), list(merged.values()))
    return {**envelope, "result": list(merged.values())}


def run_phase(
    task_id: str, phase: str, cwd: str, changed_files: list[str] | None = None
) -> dict:
    """Invoke exactly one phase, reading its declared input artifact and writing its declared
    output artifact — callable standalone (a human hand-building the input file) or as part of
    run_pipeline() below. Same call either way (GP1/GP2)."""
    if phase == "locate":
        envelope = locate(cwd)
        return envelope if envelope is not None else {"status": "completed", "result": "up-to-date, skipped"}
    if phase == "execute":
        executor.run_playwright()
        entries = executor.parse_results()
        write_json(phase_artifact_path(task_id, "execute"), entries)
        return {"status": "completed", "result": entries}
    if phase == "generate":
        return _run_generate_phase(task_id, cwd)

    role = PHASE_ROLES[phase]
    prompt = _build_prompt(task_id, phase, changed_files)
    envelope = invoke(task_id=task_id, role=role, phase=phase, prompt=prompt, cwd=cwd)
    write_json(phase_artifact_path(task_id, phase), envelope.get("result", {}))
    return envelope


def run_pipeline(task_id: str, cwd: str, changed_files: list[str]) -> dict:
    project = load_project_config()
    plan_input_hash = hash_files([Path(f) for f in changed_files])

    locate(cwd)  # keep state/locator-map.json in sync before plan/generate can consume it

    plan_envelope = run_phase(task_id, "plan", cwd, changed_files=changed_files)
    if plan_envelope["status"] != "completed":
        return {"verdict": "BLOCKED", "reason": "planning failed"}

    gen_envelope = run_phase(task_id, "generate", cwd)
    if gen_envelope["status"] != "completed":
        return {"verdict": "BLOCKED", "reason": "generation failed"}

    heal_result = heal_loop.run(task_id, cwd, plan_input_hash)
    write_json(phase_artifact_path(task_id, "heal"), heal_result)
    if heal_result["final_verdict"] == "BLOCKED":
        return {
            "verdict": "BLOCKED",
            "reason": "heal loop exhausted or no-progress" ,
            "detail": heal_result,
        }

    try:
        review_envelope = run_phase(task_id, "review", cwd)
    except InvocationBlocked as exc:
        return {"verdict": "BLOCKED", "reason": str(exc)}

    verdict = decide(
        heal_cycle=heal_result["heal_cycle"],
        max_heal_cycles=heal_result["max_heal_cycles"],
        no_progress=heal_result["no_progress"],
        review_envelope=review_envelope,
    )
    return {"verdict": verdict, "heal_result": heal_result, "review": review_envelope.get("result")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--phase", choices=PHASES, help="run exactly one phase, standalone")
    parser.add_argument("--cwd", default=str(ROOT))
    parser.add_argument("--changed-files", nargs="*", default=[])
    args = parser.parse_args()

    if args.phase:
        result = run_phase(args.task_id, args.phase, args.cwd, changed_files=args.changed_files)
    else:
        result = run_pipeline(args.task_id, args.cwd, args.changed_files)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("verdict") != "BLOCKED" else 1)


if __name__ == "__main__":
    main()
