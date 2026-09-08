"""Requirement -> test case -> test script -> module traceability. IMPLEMENTATION_STRATEGY.md
§6/Stage 8.

Control-plane-owned, like manifest.py — never written by an AI, and referencing caseId/specPath/
route/file strings rather than being stored inside another tool's graph (no graphify: see §5's
reasoning for why that was rejected).

Two ways an entry's `modules` gets populated, in increasing trust (§6's table):
  - "derived"  — case.selectors -> which crawled route(s) expose that testId (locator-map.json)
                 -> config's route_source_files. Plain code, available at generate time.
  - "measured" — real coverage from an actual test run (e.g. Jest's --coverage). Ground truth,
                 available only after a spec has actually executed at least once.
"derive at creation, measure at first run, prefer measured thereafter" — the same declare-then-
verify pattern diff_guard.py and manifest.py already use, so the mapping self-corrects instead
of decaying (§6).
"""
from __future__ import annotations

from typing import Any

from util import ROOT, load_json, load_project_config, write_json


def _traceability_path():
    project = load_project_config()
    return ROOT / project.get("traceability_path", "state/traceability.json")


def load() -> dict[str, Any]:
    path = _traceability_path()
    return load_json(path) if path.is_file() else {"entries": {}}


def _save(data: dict[str, Any]) -> None:
    write_json(_traceability_path(), data)


def _selector_prefix(selector: str) -> str:
    """plan.json's `selectors` values are frequently not a clean literal testId: templated
    patterns like "item-edit-{id}" (the planner describing a per-row element abstractly, a
    reasonable thing to write) and messy descriptive entries like "item-delete-button
    (flagged-unstable: getByRole(...))" (the planner explaining a role-fallback case inline)
    both showed up in real, live plan.json output — verified, not a hypothetical. Reduce either
    down to a clean prefix by cutting at the first template/parenthesis/whitespace marker."""
    for sep in ("{", "(", " "):
        idx = selector.find(sep)
        if idx != -1:
            selector = selector[:idx]
    return selector.rstrip("-")


def derive_routes_for_case(case: dict[str, Any], locator_map: list[dict[str, Any]]) -> list[str]:
    """Every route whose crawled elements plausibly match at least one of this case's
    selectors — by testId (the common case) or by `name` (locator-map's semantic label, for
    role-fallback elements that carry no testId at all) — using a prefix match in both
    directions so "item-edit-{id}" matches the crawled "item-edit-1"/"item-edit-2". A case can
    legitimately match more than one route (e.g. it asserts on a shared nav link) — union,
    don't pick just one, per §6's fail-open bias towards over-inclusion over under-inclusion
    for a traceability edge."""
    prefixes = [_selector_prefix(s) for s in case.get("selectors", [])]
    prefixes = [p for p in prefixes if p]
    if not prefixes:
        return []

    def matches(candidate: str) -> bool:
        return any(candidate.startswith(p) or p.startswith(candidate) for p in prefixes)

    routes = []
    for route_entry in locator_map:
        for el in route_entry.get("elements", []):
            if (el.get("testId") and matches(el["testId"])) or (el.get("name") and matches(el["name"])):
                routes.append(route_entry["route"])
                break
    return routes


def resolve_routes_for_files(changed_files: list[str], route_source_files: dict[str, list[str]]) -> list[str]:
    """The reverse of route_source_files — given changed files, which routes do they belong to?
    IMPLEMENTATION_STRATEGY.md §5/Stage 9: page-scoped prompt filtering reuses this exact
    config, in the opposite direction from Stage 8's derive_*. A changed file matching none of
    the declared routes returns an empty list — callers MUST treat that as "fail open, send
    everything," never as "this file affects nothing" (§5's own correction of an earlier
    overstatement: a hand-maintained map going stale is a real, silent risk, not a solved one)."""
    changed = set(changed_files)
    routes = []
    for route, files in route_source_files.items():
        if changed & set(files):
            routes.append(route)
    return routes


def derive_modules_for_case(
    case: dict[str, Any], locator_map: list[dict[str, Any]], route_source_files: dict[str, list[str]]
) -> tuple[list[str], list[str]]:
    """Returns (modules, matched_routes). Empty modules means genuinely unmapped — none of this
    case's selectors were seen on any crawled route (e.g. it references an element the crawler's
    interactive-only query doesn't capture, like a status span) — NOT the same as "this case
    touches no files"; callers must treat empty as "unknown," never as a hard negative."""
    routes = derive_routes_for_case(case, locator_map)
    modules: list[str] = []
    for route in routes:
        for f in route_source_files.get(route, []):
            if f not in modules:
                modules.append(f)
    return sorted(modules), routes


def record_generate(
    plan: list[dict[str, Any]],
    generate_result: list[dict[str, Any]],
) -> dict[str, Any]:
    """Called right after a real generate phase (orchestrator.py::_run_generate_phase) — capture
    traceability as each test is born (§6: cheap now, expensive to retrofit onto hundreds of
    specs later). Records EVERY case, including skipped ones — a case the generator refused to
    write is itself a real, reportable gap (see report()'s "never generated" bucket), not
    something to silently drop from the index."""
    project = load_project_config()
    locator_map = load_json(ROOT / project["locator_map_path"]) if (ROOT / project["locator_map_path"]).is_file() else []
    route_source_files = project.get("route_source_files", {})
    plan_by_id = {c["caseId"]: c for c in plan}

    data = load()
    for entry in generate_result:
        case_id = entry["caseId"]
        case = plan_by_id.get(case_id, {})
        existing = data["entries"].get(case_id, {})
        if existing.get("source") == "measured":
            # Ground truth from a real run outranks a fresh derivation — don't regress it just
            # because the case was regenerated/re-recorded (§6: "prefer measured thereafter").
            continue
        modules, routes = derive_modules_for_case(case, locator_map, route_source_files)
        data["entries"][case_id] = {
            "caseId": case_id,
            "specPath": entry.get("specPath"),
            "status": entry["status"],
            "routes": routes,
            "modules": modules,
            "source": "derived" if modules else "unmapped",
        }
    _save(data)
    return data


def record_measured(spec_path: str, files_touched: list[str]) -> None:
    """Upgrades every entry for this specPath to ground truth from a real coverage-instrumented
    run (e.g. Jest's --coverage). Multiple caseIds sharing one spec file (the common case — see
    Stage 3's Accordion.test.tsx, 6 cases in 1 file) all get the same measured module list; finer
    per-case granularity would need per-test coverage isolation, out of scope here."""
    data = load()
    changed = False
    for case_id, entry in data["entries"].items():
        if entry.get("specPath") == spec_path:
            entry["modules"] = sorted(set(files_touched))
            entry["source"] = "measured"
            changed = True
    if changed:
        _save(data)


def report() -> dict[str, Any]:
    """Answers the questions §6 says this is for: which planned cases have no traceable module
    (a real gap — either the case was never generated, or its selectors don't appear on any
    crawled route), and which declared modules have zero cases referencing them at all."""
    project = load_project_config()
    route_source_files = project.get("route_source_files", {})
    all_known_modules = sorted({f for files in route_source_files.values() for f in files})

    data = load()
    entries = data["entries"]

    never_generated = [e["caseId"] for e in entries.values() if e["status"] == "skipped"]
    unmapped = [e["caseId"] for e in entries.values() if e["status"] == "generated" and not e["modules"]]
    covered_modules = {m for e in entries.values() for m in e.get("modules", [])}
    uncovered_modules = [m for m in all_known_modules if m not in covered_modules]

    return {
        "totalCases": len(entries),
        "neverGenerated": never_generated,
        "unmappedButGenerated": unmapped,
        "uncoveredModules": uncovered_modules,
        "measuredCount": sum(1 for e in entries.values() if e.get("source") == "measured"),
        "derivedCount": sum(1 for e in entries.values() if e.get("source") == "derived"),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(report(), indent=2))
