# How This System Actually Works

This document is for the very first person opening this repository who has no context at all.
It explains, in plain language: what this project does, where a run actually *starts*, which
parts are "just code" (predictable, no AI involved) and which parts are "an AI agent thinking"
(unpredictable, different every time), how to run any single piece on its own, exactly what
gets fed into each AI call and what shape it must answer in, and what every configuration file
controls. If you read nothing else in this repo, read this file.

---

## 1. What is this project, in one paragraph

This is a QA (testing) pipeline that uses Claude Code (an AI coding agent) to automatically:
read a code change, plan test scenarios for it, write real Playwright test files, run them, and
— if any fail — try to fix them, but only within tight, code-enforced limits. The interesting
design idea is: **the AI is only ever trusted to do the *judgment* parts** (plan scenarios,
write test code, decide if a failure is a real bug vs. a broken test, judge overall quality).
**Every mechanical part — running tests, deciding when to stop retrying, checking the AI's
output is well-formed, catching a cheating fix — is done by plain, deterministic Python code
that never changes its mind.** That split is the entire point of the architecture.

There's a "dummy app" (`dummy-app/`) included purely as something to test against — a tiny
login/items web app with a couple of deliberately-planted quirks (an element with no stable
selector, a seeded bug) used to prove the safety mechanisms actually catch what they're supposed
to catch.

---

## 2. The two kinds of work in this system

This is the single most important thing to understand before reading any code.

| Kind | What it means | Examples in this repo |
|---|---|---|
| **Deterministic** | Plain Python (or a subprocess like Playwright). Same input → same output, every time. No AI involved. Fast, free, fully predictable. | `executor.py` (runs Playwright, reads its JSON report), `manifest.py` (checkpoint bookkeeping), `ledger.py` (a log file), `gates/qa_gate.py` (PASS/REFACTOR/BLOCKED decision), `diff_guard.py` (checks if an assertion line changed), `testability_check.py` (scans HTML/JS for elements), `invoke.py`'s JSON-parsing/repair/concurrency-limiting logic |
| **Non-deterministic** | A real call out to the `claude` CLI (an AI model). Same input can produce a *different* (though hopefully similarly-good) answer each time. Costs money/tokens, takes seconds-to-minutes, and its output must always be double-checked by deterministic code before being trusted. | Every one of the 6 "roles" in `roles/*.md` — see the table in §7 |

The rule this whole codebase follows: **the AI never gets to be the referee of its own work.**
Whenever an AI call finishes, a plain Python function checks its output before anything is
allowed to act on it. You'll see this pattern everywhere below.

---

## 3. Where does a run actually start?

The single entry point for a full run is:

```bash
cd control-plane
python orchestrator.py <task-id> --changed-files path/to/changed/file.js
```

This calls `orchestrator.py::run_pipeline()`. Nothing happens before this — there is no daemon,
no server, no watcher. You run this command (or call the Python function directly) and it walks
through the stages described in §4, start to finish, printing a final JSON result and exiting
with code 0 (success/REFACTOR) or 1 (BLOCKED).

`<task-id>` is just a label you choose (e.g. `fix-login-bug-42`) — it's used to name the folder
under `state/` where this run's files get written (see §9).

---

## 4. The full pipeline, stage by stage

Here is exactly what happens, in order, when you run the command above. "🤖" marks a real AI
call; "⚙️" marks plain deterministic code.

```
  ⚙️  1. locate    →  scan dummy-app's HTML/JS for elements  →  🤖 qa-locator-explorer
                       (only if the app's source changed since last time — otherwise skipped
                        entirely, no AI call, see §4.1)

  🤖  2. plan      →  qa-test-planner reads the changed file(s) and the locator map,
                       writes a list of test scenarios (plan.json)

  🤖  3. generate  →  qa-test-generator reads plan.json + the locator map,
                       writes real Playwright .spec.ts files (generate.json records what it wrote)

  ⚙️  4. execute   →  run Playwright for real, parse its JSON report (execute.json)

  ── heal loop (bounded, see §4.2) ──
  ⚙️     quarantine check  →  re-run any failing spec a few times; if it flips
                              pass/fail on identical code, it's "flaky", not sent onward
     for each still-failing case:
       🤖   triage    →  qa-failure-triage: is this a broken test, or a real product bug?
       🤖   heal      →  (only if "test defect") qa-test-healer tries a fix
       ⚙️   diff-guard →  checks the healer didn't sneakily edit the assertion; reverts if so
     ⚙️  re-run Playwright on just the cases that were touched
     (repeat, up to `max_heal_cycles` times, or stop early if nothing is improving)

  🤖  5. review    →  qa-reviewer looks at everything (plan, generated tests, heal history,
                       locator map) and gives a final verdict: PASS / REFACTOR / BLOCKED

  ⚙️  6. gate      →  qa_gate.decide() makes the final call — a plain Python function,
                       not the AI, has the last word
```

### 4.1 The "locate" stage (skips itself when nothing changed)

Before planning or generating anything, the system needs to know: which elements on the page
have a reliable way to click/fill them, and which don't? Rather than asking the AI to figure
this out by reading every file (slow, expensive, inconsistent), a deterministic script
(`testability_check.py`) scans the app's HTML and JavaScript first and hands the AI a plain
fact list — the AI's job is only to *interpret and rank* those facts (e.g. "this button has no
ID, but it does have visible text 'Delete', so use that as a fallback"), never to *find* them
from scratch.

The result is `state/locator-map.json` — every interactive element, tagged as:
- `stable-testid` — has a real `data-testid`, safest to use
- `role-fallback` — no ID, but has a stable accessible name (e.g. button text) to fall back on
- `flagged-unstable` — no reliable way to target it at all; anything relying on it is a known gap

This whole stage is **skipped entirely** (no AI call at all) if the app's source hasn't changed
since the last time it ran — a hash of the scanned files is kept in `state/locator-map.hash` and
compared before doing anything.

### 4.2 The "heal loop" in detail (this is where most of the safety logic lives)

After tests run, some may fail. For each failing case, the system does NOT just hand it
straight to an AI and say "fix this." Instead:

1. **Quarantine check (⚙️ deterministic, first, before any AI is involved at all).** Each newly
   failing case gets re-run a couple more times on the exact same code. If it sometimes passes
   and sometimes fails with nothing changed, it's **flaky**, not broken — it gets reported and
   set aside, and is never sent to any AI at all.
2. **Triage (🤖).** For everything still failing, `qa-failure-triage` is asked one narrow
   question: is this a **test defect** (the test itself is wrong — bad selector, bad wait) or a
   **product defect** (the app genuinely doesn't do what it's supposed to)? If the answer is
   anything other than "test defect" — including if the AI call itself fails — the case is
   marked `escalated` and **never reaches the healer**. This one check is what stops the system
   from ever trying to "fix" a test by papering over a real bug.
3. **Heal (🤖, only for genuine test defects).** `qa-test-healer` may edit selectors, waits,
   and setup code — but its instructions explicitly forbid touching any `expect(...)`
   assertion line, because weakening an assertion to make a test pass is worse than leaving it
   failing (a silent false "it works" is worse than a visible "it doesn't").
4. **Diff-guard (⚙️ deterministic — this is the part that doesn't just trust the AI's word).**
   Before invoking the healer, the system saves a copy of the test file. After the healer
   returns — whether it claims success or not — the system re-reads the file and mechanically
   checks whether any assertion actually changed. If one did, **the file is reverted and the
   fix is rejected, no matter what the AI's own report said.** This is the concrete answer to
   "what stops the AI from lying about what it changed" — see `control-plane/diff_guard.py`.
5. **Re-run, repeat — but not forever.** The whole cycle repeats, bounded by
   `config/pipeline.json`'s `max_heal_cycles` (currently 2). If the set of still-failing cases
   stops shrinking between cycles, a circuit breaker trips immediately (it does not wait for the
   cycle count to run out) and the whole thing is marked `BLOCKED`.

---

## 5. Running any single stage on its own

You never have to run the whole pipeline to test one piece. Every stage is individually
runnable — this was a deliberate design goal (so you can hand-build an input file and test just
one AI role in isolation).

```bash
cd control-plane

# Run just one phase, by name. Reads its expected input file(s) from state/<task-id>/,
# writes its output there too. You can hand-write plan.json yourself and run only "generate"
# against it, for example.
python orchestrator.py my-task --phase locate
python orchestrator.py my-task --phase plan --changed-files ../dummy-app/server.js
python orchestrator.py my-task --phase generate
python orchestrator.py my-task --phase execute
python orchestrator.py my-task --phase review
```

There is no `--phase heal` (the heal loop is a bounded, multi-step process, not a single call) —
run it directly from Python instead:

```python
import heal_loop
heal_loop.run(task_id="my-task", cwd="/path/to/repo/root", plan_input_hash="any-string")
```

Every one of the 6 AI roles can also be called completely directly, bypassing the orchestrator
entirely, via `invoke.py`:

```python
import invoke
envelope = invoke.invoke(
    task_id="my-task", role="qa-test-planner", phase="plan",
    prompt="whatever text you want to send", cwd="/path/to/repo/root",
)
```

This is the actual mechanism the golden-task test scripts (`tests/golden/scenario_*.py`) use —
they hand-build small, controlled inputs and call individual stages directly, rather than
running the whole pipeline, specifically so each test is fast, cheap, and focused on one thing.

---

## 6. The tricky part: what an AI call's raw output actually looks like

This tripped up the very first attempt at wiring this up, so it's worth explaining clearly.

When `invoke.py` runs `claude -p --output-format json ...`, the text that comes back on stdout
is **not** the AI's answer directly. It's a wrapper the `claude` CLI itself adds, that looks
like this (trimmed):

```json
{
  "session_id": "...",
  "total_cost_usd": 0.05,
  "is_error": false,
  "result": "```json\n{ \"schemaVersion\": 1, \"role\": \"qa-test-planner\", ... }\n```"
}
```

Notice: the CLI's own `"result"` field is a **string**, not an object — it's the AI's entire
reply as plain text, which itself often contains a fenced code block. So getting the actual
answer takes two unwrapping steps:

1. Parse the outer JSON (the CLI's wrapper) → pull out the `"result"` string.
2. Strip any ` ```json ... ``` ` fence from that string, then parse *that* as JSON → this is
   the AI role's actual answer, called the **envelope** everywhere in this codebase.

`invoke.py::_parse_envelope()` does exactly this, and it's the reason the phrase "the envelope"
shows up constantly in this repo's comments — it specifically means "the role's own JSON reply,
already unwrapped from the CLI's outer packaging," never the outer CLI wrapper itself.

If the AI's reply still isn't valid JSON after all that, `invoke.py` gets exactly **one** retry:
it shows the AI its own broken text and the exact parse error, and asks it to re-emit corrected
JSON only — nothing else. If that also fails, the whole call is treated as blocked, and nothing
downstream is allowed to proceed on a guess.

---

## 7. What goes into each AI role, and what it must answer with

Every AI call in this system is really "run this one role, with this one prompt, expecting this
one JSON shape back." Here's the cast of characters:

| Role (file in `roles/`) | What it's given | What it must write back | Can it edit files? |
|---|---|---|---|
| **qa-locator-explorer** | A deterministic fact list of every interactive element found in the app's HTML/JS (see §4.1) | A locator map: each element tagged `stable-testid` / `role-fallback` / `flagged-unstable` | No — read-only |
| **qa-test-planner** | The changed file(s)' full text, plus the current locator map | A list of test scenarios (`plan.json`) — priority, type, steps, expected result, which selectors it needs | No — read-only |
| **qa-test-generator** | `plan.json` (or, on a resume, just the not-yet-done cases) plus the locator map | Real Playwright `.spec.ts` files written to `dummy-app/tests/e2e/generated/`, and a summary list (`generate.json`) of what it wrote or skipped | **Yes** — but only inside that one generated-tests folder |
| **qa-failure-triage** | One failing test's case ID, file path, error message, and category | A single word: `test-defect`, `product-bug`, or `unclear` | No — read-only |
| **qa-test-healer** | One failing case's file path, error message, and which attempt number this is | Either a description of the interaction-code fix it made, or `"action": "escalated"` if it concluded the test can't be safely fixed | **Yes** — but never allowed to touch an `expect(...)` line (enforced in code, see §4.2 step 4) |
| **qa-reviewer** | `plan.json`, `generate.json`, the heal loop's full result, and the locator map | A final verdict — `PASS`, `REFACTOR`, or `BLOCKED` — plus a list of findings (things worth flagging, e.g. "this case relies on a fragile fallback selector") | No — read-only |

### Every role's answer is wrapped in the same "envelope" shape

Regardless of which role you're looking at, its JSON reply always has this outer shape (this is
`schemas/envelope.schema.json`):

```json
{
  "schemaVersion": 1,
  "role": "qa-test-planner",
  "status": "completed",
  "terminal": true,
  "result": [ /* role-specific — see below */ ],
  "findings": [ /* optional, only some roles use this */ ],
  "metrics": { "duration_s": 0 }
}
```

The `"result"` field's own shape is different per role, and is checked against its own,
separate schema file:

| Role | `result` validated against |
|---|---|
| qa-test-planner | `schemas/plan.schema.json` — an array of test-case objects |
| qa-test-generator | `schemas/generate.schema.json` — an array of `{caseId, specPath, status}` |
| qa-test-healer | `schemas/heal.schema.json` — one `{caseId, action, attemptNumber, touchedAssertionLine}` object |
| qa-reviewer | `schemas/review.schema.json` — `{verdict, findings}` |
| qa-locator-explorer | `schemas/locator-map.schema.json` — an array of `{route, sourceHash, elements}` |
| qa-failure-triage | *(none — its answer is small enough that the outer envelope's own fields cover it)* |

There's also `schemas/execute.schema.json` — but that one isn't an AI's output at all, it's the
shape `executor.py` (plain code) produces after parsing Playwright's own test-results file.

**Every single field name, allowed value, and required-vs-optional rule in these schema files
is enforced in code** (`control-plane/validate.py`, called from `invoke.py`) before any result
is trusted — if a role's answer doesn't match its schema, the whole call is treated as blocked,
exactly like a JSON-parsing failure.

A recurring lesson from actually building this (documented at length in `TODO.md`): when a role
file's example only shows *one* value for a field that has several allowed options (e.g. an
enum), the AI will sometimes invent a plausible-sounding value that isn't in the schema at all.
Every `roles/*.md` file has since been updated to spell out every allowed value explicitly,
rather than relying on the AI to infer the full list from one example.

---

## 8. Configuration files, explained

### `config/project.json` — "where things live"

```json
{
  "e2e_test_commands": ["npx playwright test"],
  "e2e_generated_dir": "dummy-app/tests/e2e/generated",
  "e2e_baseline_dir": "dummy-app/tests/e2e/regression",
  "e2e_results_path": "dummy-app/test-results/results.json",
  "locator_map_path": "state/locator-map.json",
  "app_root": "dummy-app"
}
```

| Field | Plain-language meaning |
|---|---|
| `e2e_test_commands` | The exact shell command(s) used to run the tests. **Important:** this must not add its own `--reporter` flag — that would override `dummy-app/playwright.config.ts`'s own reporter setting (which writes results to the exact file `e2e_results_path` points at) and results would silently never reach disk. This bit the project once — see `TODO.md`. |
| `e2e_generated_dir` / `e2e_baseline_dir` | Where AI-generated tests live vs. the hand-written "known good" baseline tests that never get touched by any AI. |
| `e2e_results_path` | Where Playwright writes its JSON report after a run — `executor.py` reads this exact file. |
| `locator_map_path` | Where the locator map (§4.1) is stored. |
| `app_root` | The folder the app being tested lives in. |

### `config/pipeline.json` — "how cautious to be"

```json
{
  "timeouts_seconds": { "per_call": 900, "per_loop_cycle": 900, "per_run": 7200 },
  "review": {
    "qa": {
      "enabled": true,
      "max_heal_cycles": 2,
      "flake_recheck_runs": 3,
      "on_refactor": "retry_qa_stage",
      "on_failure": "fail_run"
    }
  },
  "budget": { "max_concurrent_invocations": 4, "max_credits_per_task": null },
  "adapter": "claude"
}
```

| Field | Plain-language meaning | Actually wired up? |
|---|---|---|
| `timeouts_seconds.per_call` | Maximum time to wait for any single AI call before giving up on it | **Yes** — read in `invoke.py` |
| `timeouts_seconds.per_loop_cycle` / `per_run` | Intended outer time budgets for one heal cycle / one whole run | **No** — declared here, but nothing in the code currently reads or enforces these. Worth knowing so you don't assume a 2-hour run is actually capped anywhere yet. |
| `review.qa.max_heal_cycles` | How many times the heal loop is allowed to go around before giving up | **Yes** — `heal_loop.py` |
| `review.qa.flake_recheck_runs` | How many total times a newly-failing case is re-run before deciding it's flaky | **Yes** — `heal_loop.py`'s `quarantine_flaky()` |
| `review.qa.on_refactor` / `on_failure` | Intended "what to do next" policy after a REFACTOR or failed run | **No** — declared, not read anywhere yet |
| `budget.max_concurrent_invocations` | The most AI calls allowed to run at the same time | **Yes** — enforced in `invoke.py` via a semaphore. Note: nothing in this codebase currently *makes* concurrent calls (everything runs one step at a time today), so this cap is a guardrail sitting ready for whenever that changes, not something you'll see in action yet. |
| `budget.max_credits_per_task` | Intended per-task spending cap | **No** — declared, not read anywhere yet |
| `adapter` | Which AI backend to use — `"claude"` today, calling `control-plane/adapters/claude_adapter.py` | **Yes** |

Being upfront about the "not wired up yet" fields matters here specifically because this
project's whole design philosophy is about not trusting things that look configured but aren't
actually enforced — the same scrutiny applies to its own config file.

### How an AI call is actually launched (`adapters/claude_adapter.py`)

Every AI call ultimately runs this exact shell command:

```
claude -p --max-turns 20 --output-format json --permission-mode acceptEdits \
       --append-system-prompt-file roles/<role-name>.md "<the prompt text>"
```

Plain-language meaning of each flag:
- `-p` — run once and print the answer, don't open an interactive chat.
- `--max-turns 20` — the AI gets at most 20 back-and-forth tool-use steps to finish.
- `--output-format json` — get the wrapped JSON output described in §6, not plain chat text.
- `--permission-mode acceptEdits` — **required**, not optional: without this, a role that needs
  to write files (the generator, the healer) has no one to ask for permission in a non-interactive
  run, so it just gives up and asks in plain text instead of doing the work. This was a real bug
  found while building this system.
- `--append-system-prompt-file roles/<role-name>.md` — this is *how a "role" is defined at all*.
  Each file in `roles/` is nothing more than extra system-prompt instructions appended on top of
  the AI's defaults — the role's rules, boundaries, and output contract, exactly as described in
  §7's table.

---

## 9. What ends up on disk (the `state/` folder)

```
state/
  ledger.jsonl              one line per AI call ever made — role, phase, duration,
                             status, cost — an audit trail, never trusted for decisions
  locator-map.json          the current locator map (§4.1)
  locator-map.hash          fingerprint used to decide whether locate() needs to re-run
  <task-id>/
    plan.json                the planner's output
    generate.json            the generator's output (which specs it wrote or skipped)
    generate.manifest.json   checkpoint: which caseIds are done, so a crash mid-generate
                             doesn't force redoing already-written specs on resume
    heal.json                the heal loop's final summary
    heal.manifest.json       checkpoint: which caseIds were fixed/escalated, and why
```

**Important rule that took real effort to get right:** these manifest files are only ever
written by the *control plane* (plain Python), immediately after it has independently verified
a result — never written by the AI itself, and never trusted just because the AI claims
something is "done." The AI reports what it did; the control plane decides whether to believe
it and record it.

A `<task-id>`'s manifest is also automatically invalidated (treated as if nothing were done
yet) if `plan.json`'s content changes in between runs — a stale checkpoint from a different plan
is never silently reused.

---

## 10. Quick glossary

- **Role** — one of the 6 AI "personas" in `roles/*.md`. Each is just a system-prompt file; the
  underlying AI model is the same `claude` CLI every time.
- **Phase** — one named step of the pipeline (`locate`, `plan`, `generate`, `execute`, `review`;
  the heal loop is its own multi-step thing, not a single phase).
- **Envelope** — an AI role's own JSON reply, already unwrapped from the CLI's outer packaging
  (see §6). Every envelope has the same outer shape (`schemas/envelope.schema.json`); its
  `result` field's shape is role-specific.
- **Manifest** — a small JSON file the control plane (never the AI) writes to remember which
  units of work are already done, so a crash-and-restart doesn't redo everything.
- **Ledger** — an append-only log of every AI call ever made, one line per call. Used for
  auditing and (eventually) for tuning limits from real usage data — never used to make
  in-the-moment decisions.
- **Locator map** — the machine-readable list of every interactive element in the app and how
  reliably it can be targeted (`stable-testid` / `role-fallback` / `flagged-unstable`).
- **Diff-guard** — the deterministic check that a healer's file edit didn't touch any assertion
  line, independent of what the AI itself claims it did.
- **No-progress breaker** — the check that stops the heal loop early if the set of still-failing
  cases isn't shrinking between cycles, instead of waiting for the cycle-count cap to be hit.
- **Quarantine** — setting aside a case that fails/passes inconsistently on identical code
  (flaky), so it's never mistakenly sent to the healer as if it were a real, fixable defect.

---

## 11. Day-to-day operator reference

This section is the practical cheat-sheet for actually running the thing day to day — §3–§5
already covered the mechanism; this is just the commands.

**One-time setup:**

```bash
cd dummy-app && npm install && npx playwright install
cd ../control-plane && pip install -r requirements.txt
claude --version   # confirm the CLI is on PATH and authenticated
```

**Pick a task ID.** Every run is namespaced under a `task_id` you choose (e.g. `demo-1`,
`fix-login-bug-42`) — it's just the folder name under `state/` where that run's files land (§9).
There's no registry to update; using a new task ID is how you start a fresh, independent run.

**Inspect what happened after a run:**

| What | Where |
|---|---|
| Phase outputs | `state/<task-id>/plan.json`, `state/<task-id>/generate.json` |
| Heal history (control-plane-owned, per `caseId`) | `state/<task-id>/heal.manifest.json` |
| Every invocation, every task, one line each | `state/ledger.jsonl` |
| Raw Playwright results | `dummy-app/test-results/results.json` |

```bash
tail -f ../state/ledger.jsonl   # watch invocations as they happen
```

**Re-running after a fix or a crash:**
- Force a full replan: delete `state/<task-id>/plan.json` and rerun `--phase plan`.
- Resume a partially-completed `generate`/`heal` phase: just rerun the same phase — the manifest
  (§9) skips `caseId`s already recorded done, unless the plan's content changed since, in which
  case the input-hash mismatch invalidates the manifest automatically and it starts over.

**Reading a `BLOCKED` result.** `orchestrator.py`'s JSON output names the reason: `"planning
failed"`, `"generation failed"`, `"heal loop exhausted or no-progress"`, or an
`InvocationBlocked` message (schema-invalid output, or a timeout). Check the last few lines of
`state/ledger.jsonl` for the specific role/phase/exit_code that caused it before retrying
anything — a timeout (`exit_code: 124`) needs a different fix than a schema failure.

**Resetting the dummy app's data between manual runs.** Generated/baseline specs already call
the reset endpoint via `beforeEach`; to reset outside a test run:

```bash
curl -X POST http://localhost:4000/api/__test__/reset
```

**Clearing all state and starting fresh:**

```bash
rm -rf state/*
touch state/.gitkeep
```

**Running the golden-task acceptance scenarios** (see `tests/golden/README.md` for what each
one proves):

```bash
cd tests/golden
python3 run_all.py                       # all 7 scenarios
python3 scenario_1_clean_pass.py         # or just one, while iterating
```

---

## 12. Where to look next

- `README.md` — short project overview, file layout, and how to point this at a different app
  (not just `dummy-app/`) or port it to Factory. This file (`HOW_IT_WORKS.md`) is the primary
  reference for how the system actually works and how to operate it day to day.
- `TODO.md` — a historical, dated log of every gap found and fixed while building this
  (all items are done — it's a build diary, not an active task list), including several real
  bugs discovered only by actually running the system live — genuinely useful reading for
  understanding *why* certain things are built the way they are, not just *what* they do.
- `tests/golden/README.md` — the seven acceptance scenarios that prove the safety mechanisms
  actually work, and the runnable scripts that verify them.
- `MIGRATION_TO_FACTORY.md` — what changes (and, more importantly, what *doesn't*) if this gets
  ported to a different underlying agent runtime.
