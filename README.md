# QA Workflow — Claude-powered proof of concept

Validates the guardrail design in `finbook-web-application/.factory/docs/control-flow-guardrails.md`
against Claude Code before porting it back to Factory's `droid exec`. The hypothesis under
test: a **deterministic control plane** (plain Python) plus a **swappable adapter** to whichever
agent runtime is behind it removes the "runaway QA sub-agent" failure mode identified in that
analysis, regardless of vendor.

**→ Read `HOW_IT_WORKS.md` first.** It's the single source of truth for how this system works
and how to operate it day to day (entry point, pipeline stages, running any phase standalone,
the AI-role schemas, configuration, operator commands). This file covers only what
`HOW_IT_WORKS.md` doesn't: project layout, and how to point the workflow at a different app or
port it to Factory.

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
tests/golden/         The 7 scenarios that prove the guardrails work, not just the happy path
                       (6 original + 1 added for the diff-guard — see tests/golden/README.md).
state/               Runtime output: manifests, ledger, locator-map. Gitignored except .gitkeep.
```

Requires the `claude` CLI on PATH (Claude Code). See `HOW_IT_WORKS.md` §11 for one-time setup
and every other day-to-day operator command (running a phase, running the full pipeline,
inspecting state, re-running after a crash, calibrating limits from `state/ledger.jsonl`).

## Pointing this at a new repo (not just dummy-app)

Everything below works today only because `dummy-app/` satisfies a specific integration
contract and a handful of files hardcode its path literally. Porting to a real app means
satisfying that same contract and updating every hardcoded reference — there's no single
config flag that does it. Do these in order; each step is independently checkable before
moving to the next.

### 1. Make the target app satisfy the integration contract

The control plane assumes the app under test behaves like `dummy-app/` does. Before touching
any config, confirm the new app (or add to it):

- **A reset endpoint** the generated/baseline specs call in `beforeEach` for test isolation
  (dummy-app's is `POST /api/__test__/reset`, returning known seed data). Without this, tests
  interfere with each other and `workers: 1`-style hacks won't save you.
- **A Playwright config with a JSON reporter writing to a fixed path** —
  `control-plane/executor.py::parse_results()` reads one exact file, so
  `playwright.config.ts`'s `reporter` must write JSON there, and the `webServer` block (if any)
  must auto-start the app so a bare `npx playwright test` works headlessly.
  ⚠️ Don't pass `--reporter=json` on the CLI instead of configuring it in `playwright.config.ts`
  — that flag *overrides* the config's file-output reporter and results never reach disk (this
  bit us once with dummy-app; see `TODO.md`).
- **Two separate spec directories** — one for AI-generated specs, one for hand-written
  baseline/regression specs the healer/generator must never touch.
- **Stable `data-testid` attributes** on interactive elements where practical. Where they're
  missing, that's not a blocker — `qa-locator-explorer` tiers those as `role-fallback` or
  `flagged-unstable` and `qa-reviewer` flags cases that rely on them — but expect more REFACTOR
  verdicts on an app that skips `data-testid` broadly.

`dummy-app/context.md` documents this contract in full (it's a human-facing build brief, not
something any code reads) — use it as the checklist when prepping a new app.

### 2. Point `config/project.json` at the new app

```json
{
  "e2e_test_commands": ["npx playwright test"],
  "e2e_generated_dir": "<new-app>/tests/e2e/generated",
  "e2e_baseline_dir": "<new-app>/tests/e2e/regression",
  "e2e_results_path": "<new-app>/test-results/results.json",
  "locator_map_path": "state/locator-map.json",
  "app_root": "<new-app>"
}
```

`app_root`, the two `e2e_*_dir` values, and `e2e_results_path` are the only paths
`control-plane/executor.py` reads from config — they're genuinely config-driven, not
hardcoded. `locator_map_path` should stay as-is; it's control-plane state, not app-specific.

⚠️ `control-plane/executor.py`'s spec-path resolution (`_walk_suite`, around line 81) still
assumes a `tests/e2e/<...>` layout under `app_root` when reconciling reporter output back to
repo-relative spec paths. If the new app's Playwright tests don't live under `<app_root>/tests/e2e/`,
this needs a matching code change, not just a config change.

### 3. Update the hardcoded `dummy-app/` path literals

`grep -rn "dummy-app" control-plane/ roles/` turns up two categories:

- **Role prompt files** (`roles/qa-test-planner.md`, `roles/qa-test-generator.md`,
  `roles/qa-locator-explorer.md`, `roles/qa-test-healer.md`) — these tell the model literally
  which folders it may read from or write to (e.g. "Write only under
  `dummy-app/tests/e2e/generated/`. Never touch `dummy-app/tests/e2e/regression/`"). These are
  instructions to the AI, not code — find/replace `dummy-app/` with the new app's root in each.
  Getting this wrong doesn't crash anything; it just lets the model write or read from the wrong
  place, which is a correctness bug, not a startup error, so verify by reading the diff after a
  live phase run, not just by re-running successfully.
- **`control-plane/testability_check.py`'s `_default_paths()`** — hardcodes
  `dummy-app/public/**/*.{html,js}` as the default scan target when no `--paths` are passed.
  Either update this function for the new app's source layout, or always invoke it (directly or
  via `orchestrator.py locate()`) with explicit `--paths`.
- **`control-plane/orchestrator.py`'s `locate()` prompt text** (~line 132) also names
  `dummy-app/public/` in the instruction sent to `qa-locator-explorer`. Update it alongside the
  `testability_check.py` paths so the prompt and the actual scanned files agree.

### 4. Verify one phase at a time before trusting a full run

Don't jump straight to `run_pipeline` on a new app. In order:

```bash
cd control-plane
python testability_check.py --paths ../<new-app>/public/**/*.html   # sanity-check the fact list first
python orchestrator.py new-app-task-1 --phase plan                  # then one AI phase
python orchestrator.py new-app-task-1 --phase generate               # then the next
```

Read each phase's `state/new-app-task-1/<phase>.json` output before moving to the next phase —
a wrong path reference from step 3 usually shows up here as an empty or off-target result, not
a crash.

### 5. Re-run (or adapt) the golden suite against the new app

`tests/golden/` scenarios 1, 2, 3, 5, and 6 are live, app-agnostic in *mechanism* but currently
hand-planted around dummy-app's specific selectors and behaviors (its login form, item list,
`SEED_BUG` env var, missing-`data-testid` delete button). They won't run unmodified against a
different app. Before trusting `max_heal_cycles`/timeout values on the new app, either re-point
these scenarios at equivalent features of the new app, or write new task IDs through
`orchestrator.py run_pipeline` directly and read `state/ledger.jsonl` — don't calibrate off
dummy-app's numbers for a different app's LLM-call cost/latency profile.

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
