# QA Workflow — Claude-powered proof of concept

Validates the guardrail design in `finbook-web-application/.factory/docs/control-flow-guardrails.md`
against Claude Code before porting it back to Factory's `droid exec`. The hypothesis under
test: a **deterministic control plane** (plain Python) plus a **swappable adapter** to whichever
agent runtime is behind it removes the "runaway QA sub-agent" failure mode identified in that
analysis, regardless of vendor.

## Layout

```
config/            Vendor-neutral. project.json + pipeline.json (budgets, heal-cycle limits).
schemas/            Vendor-neutral. JSON Schema per role's output + the shared envelope + locator-map.
control-plane/       Vendor-neutral except adapters/claude_adapter.py.
  invoke.py           Bounded-invocation primitive (§3.0): timeout, schema validation, ledger.
  manifest.py         Control-plane-owned resumable checkpoint (§3.5/GP3) — never agent-written.
  executor.py         Deterministic Playwright runner (§3.5b/XP1) — NOT an LLM.
  testability_check.py  Deterministic testability fact-list generator (§3.6/G4/LP1) — feeds
                        qa-locator-explorer; NOT an LLM.
  heal_loop.py         Bounded heal loop (QP1/QP5/QP6) — no-progress breaker, flake quarantine.
  gates/qa_gate.py      Mechanical PASS/REFACTOR/BLOCKED decision (QP4) — never orchestrator discretion.
  orchestrator.py       Plain-script sequencer, also the single/standalone-phase entrypoint (GP1/GP2).
  adapters/            Only vendor-specific layer. claude_adapter.py today; factory_adapter.py at port time.
roles/               Claude-specific prompt bodies. Maps 1:1 to .factory/droids/*.md.
dummy-app/            Minimal app to test against — 1-2 elements deliberately missing data-testid.
tests/golden/         The 6 scenarios that prove the guardrails work, not just the happy path.
state/               Runtime output: manifests, ledger, locator-map. Gitignored except .gitkeep.
```

## Setup

```bash
cd dummy-app && npm install && npx playwright install
cd ../control-plane && pip install -r requirements.txt
```

Requires the `claude` CLI on PATH (Claude Code).

## Running a single phase (GP1/GP2 — same mechanism as a full pipeline run)

```bash
cd control-plane
python orchestrator.py demo-task-1 --phase plan
```

This is deliberately how you'd hand-test one role: build `state/demo-task-1/plan.json` by hand
to whatever schema you want and re-run `--phase generate` directly — no orchestrator run
required first.

## Running the full pipeline

```bash
cd control-plane
python orchestrator.py demo-task-1 --changed-files ../dummy-app/public/app.js
```

## Before calibrating any limit

Read `state/ledger.jsonl` (one line per invocation: role, duration, tokens, exit, verdict)
*before* changing `config/pipeline.json`'s `max_heal_cycles` or timeouts. Setting these from a
guess is exactly the mistake flagged in the source analysis's §3.3 (originally sequenced
instrumentation last, corrected to first).

## Porting back to Factory

1. Everything in `config/`, `schemas/`, `control-plane/` except `adapters/claude_adapter.py`
   copies over unchanged — that's the point of keeping them vendor-neutral.
2. Write `control-plane/adapters/factory_adapter.py` implementing `adapters/base.py`'s
   `Adapter` interface, calling `droid exec` instead of `claude -p`.
3. For each `roles/*.md`, create the matching `.factory/droids/*.md`, translating the prompt
   body and re-expressing the boundaries section as Factory's `tools:`/`--enabled-tools`
   frontmatter.
4. Re-run `tests/golden/` against the Factory adapter and diff against the Claude run. A
   behavior gap here is prompt/model-quality drift to re-tune, not an architecture problem —
   the control plane doesn't change.

## Relationship to the source analysis

Every non-obvious decision in this scaffold cites back to
`finbook-web-application/.factory/docs/control-flow-guardrails.md` by section/finding ID
(e.g. `XP1`, `QP5`, `G4`) in a code comment at the point it's applied — grep for those IDs if
you need the reasoning behind a specific file.
