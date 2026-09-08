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

There's also a second, alternate track alongside the browser-based (Playwright/E2E) one
described below: generating and running **component-level tests** (Jest + React Testing
Library) against a component in isolation instead of a whole running app. Proven against a real
external repo (see `IMPLEMENTATION_STRATEGY.md`'s Stage 3) — same `qa-test-planner`/
`qa-test-generator` roles, unchanged, just a different executor (`executor.py::run_jest()`
instead of `run_playwright()`). Everything below describes the E2E track by default; where the
component track differs, it's called out explicitly.

There's a "dummy app" (`dummy-app/`) included purely as something to test against — a tiny
login/items web app with a couple of deliberately-planted quirks (an element with no stable
selector, a seeded bug) used to prove the safety mechanisms actually catch what they're supposed
to catch.

---

## 2. The two kinds of work in this system

This is the single most important thing to understand before reading any code.

| Kind | What it means | Examples in this repo |
|---|---|---|
| **Deterministic** | Plain Python (or a subprocess like Playwright, or a Node/Playwright browser-automation script). Same input → same output, every time. No AI involved. Fast, free, fully predictable. | `executor.py` (runs Playwright *or* Jest, reads the JSON report either produces), `browser_crawler.py` + `crawl.js` (crawls the running app in a real browser to find elements — see §4.1), `traceability.py` (records which test cases touch which source files/modules), `manifest.py` (checkpoint bookkeeping), `ledger.py` (a log file), `gates/qa_gate.py` (PASS/REFACTOR/BLOCKED decision), `diff_guard.py` (checks if an assertion line changed), `invoke.py`'s JSON-parsing/repair/concurrency-limiting logic |
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
  ⚙️  1. locate    →  crawl the running app in a real browser for elements  →  🤖 qa-locator-explorer
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
this out by reading every source file (slow, expensive, and it can't see elements a page only
creates dynamically in JavaScript), a deterministic script opens the *real, running app* in a
real headless browser first and hands the AI a plain fact list — the AI's job is only to
*interpret and rank* those facts (e.g. "this button has no ID, but it does have visible text
'Delete', so use that as a fallback"), never to *find* them from scratch.

Concretely: `browser_crawler.py` starts the app if it isn't already running, then hands off to
`crawl.js` (Node/Playwright — driving a real browser needs a real browser-automation engine,
which is why this one piece isn't Python). For each page listed in `config/project.json`'s
`crawl_pages`: log in once if the page needs authentication (`config`'s `auth` block says how —
see §8), then read every interactive element's tag, computed accessible role, computed
accessible name, `data-testid` (if any), and real visibility. **Important, found by actually
building this:** once logged in, every later page is reached by clicking a real in-app
navigation link, never by loading a fresh URL — this specific app's login state is
kept only in memory and does not survive a full page reload, so a fresh URL load would silently
bounce back to the login page and get treated as if it were the destination page. Loading a
fresh URL is only safe for the very first, not-yet-authenticated page.

The result is `state/locator-map.json` — every interactive element, tagged as:
- `stable-testid` — has a real `data-testid`, safest to use
- `role-fallback` — no ID, but has a stable accessible name (e.g. button text) to fall back on
- `flagged-unstable` — no reliable way to target it at all (or its name is ambiguous — e.g. two
  "Delete" buttons on the same page with no way to tell them apart); anything relying on it is a
  known gap

This whole stage is **skipped entirely** (no AI call, and no browser launch — a real browser is
far more expensive to start than hashing a few files) if the app's source hasn't changed since
the last time it ran — a hash of the relevant source files is kept in `state/locator-map.hash`
and compared before doing anything.

**Known, honest limitation:** the crawler only sees what's on screen in the state it lands on
after login/navigation. A confirmation dialog that only appears after clicking something, a
list that's only populated after real data exists, an error message that only shows after a
failed submission — none of these are visible to a one-shot crawl of each page's *default*
state. Elements like that simply won't appear in the fact list, and any planned test case that
needs them will (correctly) show up as "unmapped" rather than a wrong guess — see §4.4's
traceability report for a live example of exactly this.

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

### 4.3 Not sending the AI everything: page-scoped filtering

`state/locator-map.json` can hold every route's elements — every page's clickable things, all
at once. Sending that whole thing on *every* `plan` and `generate` call wastes context on
elements the current task has nothing to do with, and on a real, larger app than the one this
was built against, that adds up.

So `orchestrator.py` filters the locator map down before embedding it in a prompt:
- For `plan`: which routes do the **changed files** belong to (`config/project.json`'s
  `route_source_files` — a plain, hand-maintained map, deliberately not a dependency-graph
  tool; see `IMPLEMENTATION_STRATEGY.md` §5 for why one wasn't built)?
- For `generate`: which routes do the **plan's own cases** reference (matched against the
  locator map's `testId`/`name` fields)?

**The one rule that matters more than the filtering itself: fail open, loudly.** If a changed
file (or a case) doesn't match anything in the route map, the system does **not** narrow the
prompt at all — it sends the full, unfiltered locator map and prints a warning to stderr saying
so. A hand-maintained route map going stale silently is a real risk (someone adds a new
component and forgets to add it to `route_source_files`), and the failure mode of under-sending
context — the AI planning around selectors it was never told about — is worse than the failure
mode of over-sending it. Even a *partial* miss fails the whole batch open: if a batch of cases
being generated together has even one case that couldn't be matched to any route, the entire
batch gets the full map, not just that one case's fair share of it — narrowing only the matched
cases' share would have silently starved the very cases most likely to need help.

Measured, not guessed: filtering the same real prompt down to one matched route instead of five
cut its size by half (a real, repeatable ~53% drop in `state/ledger.jsonl`'s `prompt_chars`
field for byte-identical input — see `IMPLEMENTATION_STRATEGY.md` §5 for the exact numbers).

### 4.4 Traceability: which files does each test case actually touch?

A separate, smaller question from locating elements: once a test case exists, which parts of
the app's *source* does it actually exercise? `control-plane/traceability.py` keeps
`state/traceability.json` — one entry per case, recorded automatically the moment a case is
generated, never written by the AI.

Two tiers, in increasing trust:
- **"derived"** — worked out from the case's own selectors: which crawled route has an element
  matching that selector (§4.1's locator map), then which source files `config/project.json`'s
  `route_source_files` says that route belongs to. Available immediately, at generate time, but
  only as good as that config's own accuracy — and it has a real, found-not-assumed limit: the
  planner and the locator-explorer are two *separate* AI calls, and for an element with no
  `data-testid` at all, each is free to invent its own name for it (one real case: the planner
  called a button `sort-toggle-button`, the locator map called the same button
  `sort-az-button`). Cases like that come back "unmapped" rather than silently guessed at.
- **"measured"** — real coverage data from an actual test run (Jest's own `--collectCoverage`,
  for the component-test track). Ground truth, available only after a case has actually run at
  least once, and it always wins over a "derived" entry once it exists.

What this is for: real, concrete questions a project like this needs answered, not just data
for its own sake — e.g. `traceability.py`'s own report showed a real run where one whole page
(`ProfilePage.tsx`) had **zero** test cases touching it at all, and five planned cases were
never generated in the first place because of a real app defect (an "Add to Cart" button that
turned out to be unreachable from any page) — the kind of gap that's easy to miss without an
index like this to ask.

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
| **qa-locator-explorer** | A deterministic fact list of every interactive element found by crawling the running app in a real browser (see §4.1) | A locator map: each element tagged `stable-testid` / `role-fallback` / `flagged-unstable` | No — read-only |
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

This file has grown a lot since the pipeline was first built — every field below was added to
answer one specific question: *"how would this work on a second, different app?"* rather than
hardcoding an answer into an AI role's instructions. Shown here trimmed of its explanatory
`_comment` fields (the real file has one next to almost every section — read those for the
full reasoning):

```json
{
  "e2e_test_commands": ["npx playwright test"],
  "e2e_generated_dir": "dummy-app/tests/e2e/generated",
  "e2e_baseline_dir": "dummy-app/tests/e2e/regression",
  "e2e_results_path": "dummy-app/test-results/results.json",
  "locator_map_path": "state/locator-map.json",
  "app_root": "dummy-app",
  "app_source_dir": "dummy-app/src",
  "test_isolation": { "strategy": "reset_endpoint", "reset_call": "POST /api/__test__/reset" },
  "auth": {
    "strategy": "form_login", "login_route": "/login",
    "email_testid": "login-email", "password_testid": "login-password",
    "submit_testid": "login-submit",
    "test_credentials": { "email": "user@example.com", "password": "password123" }
  },
  "base_url": "http://localhost:4000",
  "crawl_pages": [
    { "route": "/login", "requiresAuth": false },
    { "route": "/items", "requiresAuth": true, "navLinkName": "Items" }
  ],
  "route_source_files": {
    "/items": ["dummy-app/src/pages/ItemsPage.tsx", "dummy-app/server.js"]
  },
  "traceability_path": "state/traceability.json",
  "component_test_app_root": "/Users/you/Projects/some-other-repo",
  "component_test_command": ["npx react-scripts test"],
  "component_test_results_path": "state/component-test-results.json"
}
```

| Field | Plain-language meaning |
|---|---|
| `e2e_test_commands` | The exact shell command(s) used to run the tests. **Important:** this must not add its own `--reporter` flag — that would override `dummy-app/playwright.config.ts`'s own reporter setting (which writes results to the exact file `e2e_results_path` points at) and results would silently never reach disk. This bit the project once — see `TODO.md`. |
| `e2e_generated_dir` / `e2e_baseline_dir` | Where AI-generated tests live vs. the hand-written "known good" baseline tests that never get touched by any AI. |
| `e2e_results_path` | Where Playwright writes its JSON report after a run — `executor.py` reads this exact file. |
| `locator_map_path` | Where the locator map (§4.1) is stored. |
| `app_root` | The folder the app being tested lives in. |
| `app_source_dir` | Where the app's actual UI source code lives — used by the (currently secondary, not in the critical path) source-scanning fallback, and as the fallback answer for "which folder can the AI read/write in" that the four role files reference instead of hardcoding a path themselves. |
| `test_isolation` | How a generated test gets a clean slate. `"strategy": "reset_endpoint"` + `reset_call` for an app like this one that has a dedicated reset API; a real app usually won't have one — see `IMPLEMENTATION_STRATEGY.md` §7.1 for the alternative strategies this is designed to be extended to. |
| `auth` | How a test (or the browser crawler, §4.1) establishes a logged-in session. `"strategy": "form_login"` fills the three named testids and submits — real credential *values* live here as plain fixture data for `dummy-app` since they're already public; a real project should point these at environment-variable names instead of committing real credentials. A real app behind external SSO would need a different strategy entirely — not yet built, see `IMPLEMENTATION_STRATEGY.md` §7.2/§2.2. |
| `base_url` / `crawl_pages` | Where the app is actually served, and the explicit list of pages the browser crawler (§4.1) visits — deliberately a plain list, not something parsed out of a router config. `navLinkName` is the visible text of the in-app link used to reach that page (see §4.1 on why a fresh page load isn't safe once logged in). |
| `route_source_files` | The page-scoped filtering (§4.3) and traceability (§4.4) map: which source files "belong" to each route. Plain, hand-maintained config — deliberately not a dependency-graph tool; see `IMPLEMENTATION_STRATEGY.md` §5 for why. |
| `traceability_path` | Where `state/traceability.json` (§4.4) is stored. |
| `component_test_app_root` / `component_test_command` / `component_test_results_path` | The component-test track's (§1) equivalent of `app_root`/`e2e_test_commands`/`e2e_results_path`. `component_test_app_root` is the one path in this whole file that's absolute rather than relative — the component-test target is typically a separate repo entirely, not a folder inside this one. |

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
                             status, real cost/tokens (not the AI's own self-report),
                             prompt size — an audit trail, never trusted for decisions
  locator-map.json          the current locator map (§4.1)
  locator-map.hash          fingerprint used to decide whether locate() needs to re-run
  traceability.json         which source files each test case actually touches (§4.4)
  component-test-results.json   the component-test track's raw Jest JSON output
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
- **Browser crawl** — how the locate stage finds elements: opening the real, running app in a
  real headless browser and reading what's actually there, instead of parsing source files
  (§4.1). Works the same way no matter what framework the app is built with.
- **Traceability** — the recorded link between a test case and the source files it actually
  touches (§4.4), kept in `state/traceability.json`, either worked out from selectors
  ("derived") or measured from real test coverage ("measured").
- **Page-scoped filtering** — sending the AI only the locator-map routes relevant to the current
  task instead of every route in the app, with a hard "fail open" rule for anything it can't
  confidently match (§4.3).
- **Component-test track** — the alternate path (§1) that generates and runs Jest + React
  Testing Library tests against one component in isolation, instead of a whole running app in a
  browser. Same planner/generator roles, a different executor.

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

**Running the newer deterministic pieces standalone** — none of these need an AI call:

```bash
cd control-plane
python3 browser_crawler.py              # crawl the app, print the raw fact list to stdout
python3 traceability.py                 # print the audit report — unmapped cases,
                                         # modules with zero test coverage, cases never
                                         # generated at all
```

**Running the component-test track** (§1) instead of the browser/E2E one — same phases, a
different executor:

```python
import executor
executor.run_jest(["SomeComponent.test"])       # run one spec by name pattern
executor.run_jest(with_coverage=True)           # + collect real coverage for traceability.py
print(executor.parse_jest_results())            # execute.schema.json-shaped results
```

---

## 12. Where to look next

This file (`HOW_IT_WORKS.md`) is the single source of truth for **how the system works today**
and how to operate it. Every other root document has one clear job — this is the map:

| Document | What it's for | Status |
|---|---|---|
| **`HOW_IT_WORKS.md`** (this file) | How it works + day-to-day operation | Current, authoritative |
| `README.md` | Project overview, file layout, pointing at a new app, Factory-porting steps | Current |
| **`IMPLEMENTATION_STRATEGY.md`** | The risk-ordered build plan, with a stage-by-stage record of what's done | **Every stage is done except one** — a real-environment access question that needs human/organisational input, not more building. Read this for the one open item and the full history of what was found and fixed along the way. |
| `TODO.md` | Dated historical log of every gap found and fixed while building this so far | Historical build diary, not an active task list — all items done |
| `PROPOSED_ENHANCEMENTS.md` | The original two-change proposal (user-story planning, indexing) | **Superseded** by `IMPLEMENTATION_STRATEGY.md` — kept for the reasoning trail, not as a current plan |
| `PROPOSED_DUMMY_APP_UPGRADE.md` | The build brief for upgrading `dummy-app` to a React SPA | **Implemented** — `dummy-app/` now matches it. Kept as the as-built reference |
| `MIGRATION_TO_FACTORY.md` | What changes (and doesn't) porting this to Factory | **On hold** — known to contain stale claims about Factory's current config/scripts; paused pending a real trial run against the Finbook project |
| `tests/golden/README.md` | The seven acceptance scenarios proving the safety mechanisms work | Current |

If you only read one more document after this one, make it `IMPLEMENTATION_STRATEGY.md`.
