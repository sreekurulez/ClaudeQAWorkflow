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

import browser_crawler
import executor
import heal_loop
import manifest
import testability_check
import traceability
from gates.qa_gate import decide
from invoke import InvocationBlocked, invoke
from util import (
    ROOT,
    STATE_DIR,
    hash_files,
    load_json,
    load_project_config,
    project_context_block,
    task_state_dir,
    write_json,
)

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


def _truncate(text: str, *, label: str) -> str:
    """Caps embedded prompt content at _MAX_EMBED_CHARS. Loud, not silent (IMPLEMENTATION_
    STRATEGY.md §0/§8): a cut here used to just append '... <truncated>' with no warning —
    on a small file nothing ever got cut, so this was invisible until a real, larger app hit it,
    at which point an AI role would silently plan/generate/review against a half-file with no
    one able to tell "it worked" from "the cut-off hid the problem." Now it says so on stderr,
    naming exactly what was cut and by how much."""
    if len(text) <= _MAX_EMBED_CHARS:
        return text
    dropped = len(text) - _MAX_EMBED_CHARS
    print(
        f"orchestrator: TRUNCATED {label} — {len(text)} chars exceeds the "
        f"{_MAX_EMBED_CHARS}-char prompt-embed cap, {dropped} chars dropped. The AI role "
        "receiving this prompt is working from a PARTIAL file, not the whole thing.",
        file=sys.stderr,
    )
    return text[:_MAX_EMBED_CHARS] + "\n... <truncated>"


def _artifact_block(path: Path, label: str) -> str:
    if not path.is_file():
        return f"{label}: (not present)"
    text = _truncate(path.read_text(encoding="utf-8"), label=label)
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
        else:
            text = _truncate(text, label=f)
        parts.append(f"--- {f} ---\n{text}")
    return "\n\n".join(parts)


def _locator_map_block(routes: list[str] | None) -> str:
    """IMPLEMENTATION_STRATEGY.md §5/Stage 9 — page-scoped prompt filtering. `routes=None` or
    `[]` means fail open (§5's own correction of an earlier overstatement: a hand-maintained
    route map going stale is a real, silent risk) — send the FULL map, exactly as before this
    stage existed, and say so on stderr so an operator can tell "filtering worked" from
    "filtering never engaged" rather than the two looking identical in the prompt itself."""
    if not LOCATOR_MAP_PATH.is_file():
        return "state/locator-map.json: (not present)"
    full_map = load_json(LOCATOR_MAP_PATH)
    if not routes:
        print(
            "orchestrator: locator map filter did not match any route — sending the FULL "
            f"locator map ({len(full_map)} routes) rather than guessing at an empty subset.",
            file=sys.stderr,
        )
        filtered = full_map
    else:
        filtered = [r for r in full_map if r["route"] in routes]
        excluded = len(full_map) - len(filtered)
        if excluded:
            print(
                f"orchestrator: locator map filtered to {len(filtered)}/{len(full_map)} routes "
                f"({routes}) — {excluded} route(s) excluded from this prompt.",
                file=sys.stderr,
            )
        if not filtered:
            # Matched routes but none of them exist in the current map (stale route names?) —
            # fail open rather than send an empty, silently-useless block.
            print(
                "orchestrator: matched routes not found in the current locator map — sending "
                "the FULL map instead of an empty one.",
                file=sys.stderr,
            )
            filtered = full_map
    return "state/locator-map.json (page-scoped):\n" + json.dumps(filtered, indent=2)


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
    context_block = project_context_block()
    project = load_project_config()
    route_source_files = project.get("route_source_files", {})
    if phase == "plan":
        routes = traceability.resolve_routes_for_files(changed_files or [], route_source_files)
        return "\n\n".join([
            context_block,
            _changed_files_block(changed_files or []),
            _locator_map_block(routes),
        ])
    if phase == "generate":
        if plan_override is not None:
            plan_block = (
                "plan.json (RESUMED — only still-pending cases shown below; others are "
                "already generated per state/<task-id>/generate.manifest.json and must not be "
                "redone):\n" + json.dumps(plan_override, indent=2)
            )
            cases_for_routes = plan_override
        else:
            plan_block = _artifact_block(phase_artifact_path(task_id, "plan"), "plan.json")
            cases_for_routes = load_json(phase_artifact_path(task_id, "plan")) if phase_artifact_path(task_id, "plan").is_file() else []
        locator_map = load_json(LOCATOR_MAP_PATH) if LOCATOR_MAP_PATH.is_file() else []
        routes: list[str] = []
        any_case_unmatched = False
        for case in cases_for_routes:
            case_routes = traceability.derive_routes_for_case(case, locator_map)
            if not case_routes:
                # Real risk, found by running this against stage1-quality's actual 20-case plan
                # (IMPLEMENTATION_STRATEGY.md §9): narrowing to the union of MATCHED cases'
                # routes would silently strip locator context from the cases that didn't match
                # anything (Stage 8's "unmapped" cases) — exactly the ones that need it most,
                # since they still have to be generated. One unmatched case fails the whole
                # batch open, not just its own share of it.
                any_case_unmatched = True
            for r in case_routes:
                if r not in routes:
                    routes.append(r)
        if any_case_unmatched:
            routes = []
        return "\n\n".join([context_block, plan_block, _locator_map_block(routes)])
    if phase == "review":
        return "\n\n".join([
            context_block,
            _artifact_block(phase_artifact_path(task_id, "plan"), "plan.json"),
            _artifact_block(phase_artifact_path(task_id, "generate"), "generate.json"),
            _artifact_block(phase_artifact_path(task_id, "heal"), "heal loop result"),
            _artifact_block(LOCATOR_MAP_PATH, "state/locator-map.json"),
            "All cases above have been executed; give your final review verdict.",
        ])
    raise ValueError(f"no prompt builder for phase {phase!r}")


def locate(cwd: str) -> dict | None:
    """Browser-based crawl (browser_crawler.py + crawl.js, IMPLEMENTATION_STRATEGY.md §4/Stage 7
    "Option B") → qa-locator-explorer → state/locator-map.json. Skips both the crawl AND the LLM
    call when the scanned source hasn't changed since the last locate — a coarse, whole-app
    version of the per-route delta trigger item 12 defers; good enough for this POC's one-shot
    full-crawl mode (see README's Layout section). The staleness check still hashes source
    files, not crawl output — a real browser launch is far more expensive than hashing files, so
    skipping it when nothing changed matters even more here than it did for the old
    testability_check.py-based scan.

    Supersedes the source-scanning approach (testability_check.py): reading a real, rendered
    page gives exact route attribution for free (we navigated there, so what we found IS on that
    route — no AI re-derivation needed for that part), the browser's own real accessibility
    computation instead of an inferred one, and dynamically-created elements are just elements
    (no more JS-heuristic guessing). testability_check.py is kept for now as a fallback/reference
    (see its own module docstring) but is no longer in locate()'s critical path."""
    scan_paths = testability_check._default_paths()
    current_hash = hash_files(scan_paths)
    if (
        LOCATOR_MAP_HASH_PATH.is_file()
        and LOCATOR_MAP_HASH_PATH.read_text().strip() == current_hash
        and LOCATOR_MAP_PATH.is_file()
    ):
        return None  # up to date, nothing to do

    facts_json = browser_crawler.facts_to_json(browser_crawler.crawl())
    prompt = (
        f"{project_context_block()}\n\n"
        "Testability fact list (from a real browser crawl the control plane ran — "
        "control-plane/browser_crawler.py + crawl.js — NOT a source-code scan; every element "
        "listed was actually observed, rendered, on the named route):\n"
        f"{facts_json}\n\n"
        "Rank/interpret these facts (confidence tier per element) and produce the locator map. "
        "This fact list is already organized by route and already comprehensive — no need to "
        "read application source yourself to fill gaps."
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
        traceability.record_generate(plan, result)
        return {"status": "completed", "result": result}

    plan_override = [c for c in plan if c["caseId"] in pending_ids] if done_entries else None
    prompt = _build_prompt(task_id, "generate", None, plan_override=plan_override)
    envelope = invoke(task_id=task_id, role="qa-test-generator", phase="generate", prompt=prompt, cwd=cwd)

    new_entries = envelope.get("result", []) if envelope["status"] == "completed" else []
    for entry in new_entries:
        manifest.upsert(task_id, "generate", input_hash=plan_hash, case_id=entry["caseId"], entry=entry)

    merged = {**done_entries, **{e["caseId"]: e for e in new_entries}}
    result = list(merged.values())
    write_json(phase_artifact_path(task_id, "generate"), result)
    traceability.record_generate(plan, result)
    return {**envelope, "result": result}


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
