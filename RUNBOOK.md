# Runbook — invoking the QA workflow

Day-to-day operator reference. For architecture rationale see `README.md`; for what's still
missing see `TODO.md` (read that first — several commands below won't do anything useful until
`TODO.md` items 1–7 are done); for the eventual Factory port see `MIGRATION_TO_FACTORY.md`.

## 0. One-time setup

```bash
cd dummy-app && npm install && npx playwright install
cd ../control-plane && pip install -r requirements.txt
claude --version   # confirm the CLI is on PATH and authenticated
```

## 1. Pick a task ID

Every run is namespaced under a `task_id`, written to `state/<task_id>/` — the same convention
Factory uses for its per-task worktrees, just without an actual git worktree here. Use a short
slug, e.g. `demo-1`.

## 2. Run one phase standalone

This is the granular-invocation mechanism from the design (`GP1`/`GP2`) — a single phase is
callable directly, the same way the orchestrator would call it internally:

```bash
cd control-plane
python orchestrator.py demo-1 --phase plan
cat ../state/demo-1/plan.json
```

To test a downstream role without re-running planning, hand-edit `state/demo-1/plan.json` to
whatever shape you want (validate it against `schemas/plan.schema.json` first) and run the next
phase directly:

```bash
python orchestrator.py demo-1 --phase generate
```

## 3. Run the full pipeline

```bash
python orchestrator.py demo-1 --changed-files ../dummy-app/public/app.js
```

Exit code `0` means the run wasn't blocked (check the printed `verdict`); exit code `1` means
`BLOCKED` — see §6 below before re-running anything.

## 4. Inspect what happened

| What | Where |
|---|---|
| Phase outputs | `state/demo-1/plan.json`, `state/demo-1/generate.json` |
| Heal history (control-plane-owned, per `caseId`) | `state/demo-1/heal.manifest.json` |
| Every invocation, every task, one line each | `state/ledger.jsonl` |
| Raw Playwright results | `dummy-app/test-results/results.json` |

```bash
tail -f ../state/ledger.jsonl   # watch invocations as they happen
```

## 5. Re-running after a fix or a crash

- **Force a full replan:** delete `state/demo-1/plan.json` and rerun `--phase plan`.
- **Resume a partially-completed `generate`/`heal` phase:** just rerun the same phase.
  `manifest.py` skips `caseId`s already recorded as done — unless the plan's content changed
  since, in which case the input-hash mismatch invalidates the manifest automatically and it
  starts over (this is deliberate: a "done" entry against a stale plan means nothing).

## 6. Reading a `BLOCKED` result

`orchestrator.py`'s JSON output names the reason: `"planning failed"`, `"generation failed"`,
`"heal loop exhausted or no-progress"`, or an `InvocationBlocked` message (schema-invalid
output, or a timeout). Check the last few lines of `state/ledger.jsonl` for the specific
role/phase/exit_code that caused it before retrying anything — a timeout (`exit_code: 124`)
needs a different fix than a schema failure.

## 7. Resetting the dummy app's data between manual runs

Generated/baseline specs already call the reset endpoint via `beforeEach`; to reset outside a
test run:

```bash
curl -X POST http://localhost:4000/api/__test__/reset
```

## 8. Clearing all state and starting fresh

```bash
rm -rf state/*
touch state/.gitkeep
```

## 9. Running the golden-task scenarios

Once `TODO.md` item 9 is done (they're currently prose acceptance criteria in
`tests/golden/README.md`, not runnable yet):

```bash
cd tests/golden && python scenario_1_clean_pass.py   # etc., once these scripts exist
```
