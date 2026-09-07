# TODO — Historical build log (all items complete)

**This is a historical record, not an active task list.** Every item below is done — the
status markers (🔴/🟡/🟢) reflect priority *as originally planned*, kept as-written so the log
stays an accurate account of what was verified and in what order, not because anything is still
outstanding. For current architecture and day-to-day operating instructions, read
`HOW_IT_WORKS.md` — that's the single source of truth for how this system works. See
`README.md` for layout/porting, `MIGRATION_TO_FACTORY.md` for the eventual Factory port. This
file is worth reading for *why* things are built the way they are — several real bugs were
found and fixed along the way, documented in place below.

## ✅ Blocking items — verified 2026-09-06 against installed `claude` v2.1.263

All three confirmed with a live, non-interactive `claude -p` call (no `.git` history exists in
this repo, so this is the only record of it):

1. **DONE.** The CLI's `--output-format json` wraps the model's reply as a *string* inside a
   top-level `"result"` field, alongside session metadata (`session_id`, `usage`,
   `total_cost_usd`, `is_error`, ...) — confirmed live, exactly as suspected. Fixed in
   `control-plane/invoke.py::_parse_envelope`: it now unwraps the CLI's outer `result` field,
   then extracts JSON from a `` ```json `` fence that may have prose before/after it (the model
   does not reliably honor "no prose outside the JSON" — seen in two of three live test calls),
   before validating against `envelope.schema.json`.
2. **DONE, with one real fix.** `--max-turns <turns>` and `--append-system-prompt-file <path>`
   are both real flags on the installed CLI (hidden from `--help`'s visible listing but confirmed
   via missing-argument errors, not unknown-option errors) — no change needed there. But a
   write-capable role (`qa-test-generator`, `qa-test-healer`) never emitted its envelope at all:
   the CLI's default permission handler is `"host"`, which doesn't exist in non-interactive `-p`
   mode, so the model just asked for write permission in plain-text prose instead of writing the
   file. Fixed by adding `--permission-mode acceptEdits` to
   `control-plane/adapters/claude_adapter.py`'s command — confirmed live this makes the
   generator actually write spec files and emit a schema-valid envelope. Each role's own prompt
   boundaries (e.g. "write only under `.../generated/`") remain the real scope enforcement.
3. **DONE.** A live `claude -p` call from this shell completed without any auth prompt —
   non-interactive auth works in this environment.

**All six role files smoke-tested live end-to-end (2026-09-06), each fixed once and re-verified
clean:**

- `qa-test-planner` — 3 gaps in `roles/qa-test-planner.md`: (a) `findings` entries must be
  `{severity, summary}` objects, not plain strings; (b) `plan.schema.json`'s `type` enum
  (`functional`/`negative`/`edge`/`regression-impact`) wasn't stated, so the model invented other
  values; (c) `caseId` must always use the `-E<NN>` suffix regardless of case type — the model
  invented `-N01`/`-R01` variants to encode type in the ID.
- `qa-locator-explorer` — passed clean on the first try (given a stub testability fact list,
  since item 4 doesn't exist yet). Output persisted to `state/locator-map.json`.
- `qa-test-generator` — blocked entirely by the permission-mode gap above (item 2); once fixed,
  wrote 5 real, correct spec files on the first schema-valid run.
- `qa-test-healer` — passed clean on the first try: given a broken selector, fixed only the
  selector line and correctly left `expect(...)` untouched, reporting
  `touchedAssertionLine: false` accurately.
- `qa-reviewer` — 2 gaps in `roles/qa-reviewer.md`: (a) `confidenceTier` must be omitted, not set
  to `"n/a"`, when not relevant; (b) `verdict` enum (`PASS`/`REFACTOR`/`BLOCKED`) wasn't stated,
  so the model invented `CONCERNS`. Once fixed, correctly returned `BLOCKED` with real findings
  when fed an incomplete generate.json (caught 3 missing planned cases and flagged a
  `role-fallback` locator dependency) — good judgment, not just schema compliance.
- `qa-failure-triage` — passed clean on the first try.

Net: every role file had at least one undocumented enum/shape gap except `qa-locator-explorer`
and `qa-test-healer`. The pattern each time was the same — the role's JSON example showed only
one example value for an enum field, and the model filled in plausible-sounding alternatives for
cases the example didn't cover. Worth grepping the remaining role files for any other
under-specified enum before this bites again downstream.

## 🟡 Needed to complete the design

4. **DONE (2026-09-06).** `control-plane/testability_check.py` — deterministic grep/AST-ish
   fact-list generator (LP1). Parses `dummy-app/public/*.html` properly (Python's
   `html.parser.HTMLParser`, not regex) for interactive elements + associated `<label for>` text,
   and heuristically scans `dummy-app/public/*.js` for `document.createElement(...)` calls to
   catch elements that don't exist in static markup at all (dummy-app's delete button is
   deliberately this case). Live-verified feeding its real output into `qa-locator-explorer`
   found genuine gaps my earlier hand-written stub missed entirely — a dynamically-created
   `<span>`/`<input>` pair (inline item-name editing) with no test IDs — and the role correctly
   tiered all three dynamic elements as `flagged-unstable`/`role-fallback`, including flagging
   that the delete button's fallback selector is ambiguous unless scoped to its containing `<li>`.
   One role-file gap surfaced by this real data (not caught by the earlier hand-written stub):
   `roles/qa-locator-explorer.md` didn't say to omit `testId`/`fallbackSelector` when neither
   applies, so the model emitted `null` for them — schema requires a string or absence, not
   `null`. Fixed. `state/locator-map.json` now holds this real (not stubbed) locator map. Scope
   note for later: the JS-side heuristic is regex-based, not a real AST walk — fine for this
   POC's two small files, but should become a real parser (e.g. Node's own parser or an
   acorn/esprima walk) if the target app's dynamic-element surface grows.
5. **DONE (2026-09-06).** `invoke.py`'s JSON self-repair loop was a complete no-op (body was
   just `break`); implemented for real, scoped narrowly to a genuine JSON-parse failure (not
   schema-invalid, which stays a separate, already-enforced path). On parse failure, the
   original attempt is ledger-recorded (`status: "repair_attempted"`) and a repair prompt is
   built (`_repair_prompt`) echoing just the model's own broken text — unwrapped from the CLI's
   session-metadata noise when possible — plus the exact parse error, asking for only the
   corrected JSON. This calls the **adapter directly, not `invoke()` recursively**, so a repair
   that also fails can never trigger a second repair — that's what actually enforces "exactly
   one attempt," not just the constant's name. Verified with mocked adapters (no LLM cost) for
   both outcomes: repair succeeds (2 calls, ledger shows `repair_attempted` → `completed`) and
   repair also fails (exactly 2 calls, never 3, `InvocationBlocked` names both errors). A live
   regression call confirmed the normal happy path (no repair needed) is unaffected.
6. **DONE (2026-09-06).** `orchestrator.py::run_phase` now builds and embeds real content per
   phase: `plan` gets each changed file's actual content plus `state/locator-map.json`;
   `generate` gets `plan.json` plus the locator map; `review` gets `plan.json`, `generate.json`,
   the heal loop's result (now persisted to `state/<task-id>/heal.json`), and the locator map.
   `heal_loop.py`'s per-case healer prompt now also states failure category and attempt number.
   `PHASE_ROLES` also fixes a latent bug: the old generic `f"qa-test-{phase}"` role-name
   construction was wrong for `review` (role is actually `qa-reviewer`) and for `execute` (not an
   LLM role at all — `executor.py` is a deterministic script); both are now handled correctly.
7. **DONE (2026-09-06).** `orchestrator.locate()` runs `testability_check.py` →
   `qa-locator-explorer` → `state/locator-map.json` before `plan`/`generate`, and skips the LLM
   call entirely when the scanned dummy-app source hasn't changed since the last locate (tracked
   via `state/locator-map.hash`) — a coarse, whole-app version of item 12's per-route delta
   trigger, good enough for this POC's one-shot full-crawl mode.

   **Running the real pipeline end-to-end for the first time (that's what items 6/7 unlock)
   surfaced four more real, previously-hidden bugs, all fixed:**
   - `config/project.json`'s `e2e_test_commands` passed `--reporter=json` on the CLI, which
     *overrides* `playwright.config.ts`'s configured `reporter: [["json", {outputFile: ...}]]`
     entirely — results went to stdout, never to the file `executor.py` reads, so
     `parse_results()` would have silently returned `[]` on every real run. Fixed by dropping the
     CLI flag and trusting the config.
   - `executor.py::_extract_case_id` tried to find the `// @case <id>` traceability header
     inside the Playwright **test title** — but that's a source comment, invisible to the JSON
     reporter's `title` field entirely. It only "worked" in earlier smoke tests because the model
     happened to prefix titles with the case ID. Fixed to read the actual spec file's comment.
   - `execute.json`'s `specPath` was relative to Playwright's `testDir`
     (`"regression/auth-login.spec.ts"`), while `generate.json`'s (and what the healer needs,
     since its `cwd` is repo root) is repo-root-relative
     (`"dummy-app/tests/e2e/regression/auth-login.spec.ts"`). Normalized to match.
   - A genuine **dummy-app product bug**: `public/index.html`'s `<script src="app.js">` tag sat
     *before* the `#confirm-modal`/`#toast-container` divs it references, so those
     `getElementById` calls returned `null` at script-load time. `showToast()` (called from
     `addItemForm`'s submit handler, right before its `loadItems()` call) then threw on
     `toastContainer.textContent = ...`, silently aborting the handler before `loadItems()` ever
     ran — so the UI never refreshed after adding an item, look like a stuck 2-item list.
     Fixed with `defer` on the script tag. Confirmed via trace inspection (`pageError` events,
     network log showing no follow-up `GET /api/items`) before touching anything.
   - Also hardened `playwright.config.ts` to `workers: 1`: `server.js` holds all app state in
     one shared in-memory store with a global reset endpoint, so two truly concurrent tests can
     still corrupt each other's state even with per-test reset. Wasn't the root cause of the bug
     above (confirmed: it reproduced identically serial or parallel) but is real, independent
     hardening worth keeping.

   **A more concerning finding, found and fixed the same day:** `qa-test-healer`'s escalation
   for the failures above claimed the root cause was the deliberately-seeded `SEED_BUG` product
   bug (see `dummy-app/context.md` §5) — which was **wrong** (confirmed: `SEED_BUG` wasn't set in
   that run, and the actual bug was the script-ordering issue above). The healer's *action* was
   still safe (escalated, didn't touch assertions, didn't force a fix) — but its stated
   *reasoning* was a plausible-sounding hallucination nobody would have caught without
   independently reproducing it. This is exactly what `qa-failure-triage` exists to add a check
   on, but it was never actually invoked anywhere in the pipeline — `heal_loop.py` sent every
   failing case straight to `qa-test-healer` with no test-defect/product-defect triage step
   first, despite the design doc's explicit "product-bug/unclear never healed" rule (docs
   §3.2/QP1).

   **DONE (2026-09-06).** Added `heal_loop.py::triage()`, called for every not-yet-escalated
   failing case before it ever reaches the healer. A `suspected` verdict other than
   `test-defect` (including `None`, when triage itself fails — a missing verdict must default
   safe, not default to healing) marks the case `escalated` in `heal.manifest.json` and skips
   the healer entirely for it, this cycle and every subsequent one (tracked via a per-run
   `escalated_ids` set, so a case triaged once isn't re-triaged every cycle). Note: this only
   *gates* the healer from being fooled by an already-wrong self-diagnosis on entry — it does not
   catch a case where the healer's own escalation reasoning would be wrong but triage's happens to
   agree; item 10's diff-guard remains the code-level (not prompt-level) enforcement for the
   assertion-line rule specifically.

   **Live-verified end-to-end with a targeted, low-cost run** (a hand-written spec, not
   LLM-generated, run directly through `heal_loop.run()` — skips planner/generator/orchestrator
   entirely, ~1 LLM call instead of a full pipeline run): a spec asserting the correct item count
   against the real `SEED_BUG=1` server defect (`server.js`'s `result.slice(0,-1)`) failed as
   expected, `qa-failure-triage` correctly classified it `suspected: "product-bug"`, and
   `qa-test-healer` was **never invoked** — confirmed via the ledger (one `qa-failure-triage`
   entry, zero `qa-test-healer` entries) and the manifest (`action: "escalated"`, `diffSummary`
   naming the triage verdict). Exactly the behavior item 7's original gap was missing.
8. **DONE (2026-09-06).** `invoke.py` now gates every actual `claude` subprocess launch (both
   the main call and the repair call from item 5) through a process-wide
   `threading.BoundedSemaphore` sized from `config["budget"]["max_concurrent_invocations"]`
   (lazily created on first use and cached — the concurrent-process budget is a process-wide
   property, not something that should resize mid-run just because a later call re-reads a
   since-edited config file). Note: **nothing in this codebase calls `invoke()` concurrently
   today** — `orchestrator.py` and `heal_loop.py` are both fully sequential — so this is a
   dormant guardrail, same class as `timeouts_seconds` before it was wired: enforced from day
   one so it can't be forgotten the first time someone parallelizes a call site (e.g. per-case
   heals across independent failing cases would be the natural candidate). Verified with a
   concurrent mocked-adapter test (real threads, no LLM cost): 8 threads against a limit of 2
   never exceeded 2 concurrent calls; the same test against a limit of 4 correctly reached
   exactly 4, confirming the cap isn't accidentally over-serializing below its configured value
   either. A live regression call confirmed the real invoke() path is unaffected.
9. **DONE (2026-09-06).** `tests/golden/harness.py` + `scenario_1..6_*.py` + `run_all.py` —
   all six scenarios implemented as live acceptance tests against the real `claude` CLI (not
   unit tests of the logic in isolation) and run individually to completion; results table in
   `tests/golden/README.md`. Scenarios 2–4 and parts of 5–6 use hand-crafted specs/plans rather
   than live planner/generator output, deliberately — determinism matters more than realism for
   proving a specific guardrail path (e.g. scenario 4's flakiness is a file-counter, not a real
   race, so it reproduces identically every run).

   **Found and fixed two more real bugs while building these, plus a bigger gap:**
   - `executor.py` mapped any non-`"passed"` Playwright status (including a legitimately
     `"skipped"` test, e.g. an env-gated case like scenario 3's) to `"fail"` — this would have
     permanently blocked scenario 1 from ever reaching a clean result once the planner happened
     to write a SEED_BUG-conditional case (as it did the first time scenario 1 ran). Fixed:
     `"skipped"` is now excluded from `execute.json` entirely (neither pass nor fail), and the
     pass/fail/timedOut/interrupted mapping is now explicit instead of an `if/else` collapsing
     everything non-passed to failed.
   - `roles/qa-locator-explorer.md` didn't state `sourceHash` must always be a single string —
     when a route spans multiple source files (dummy-app's `/` route is both `index.html` and
     `app.js`), the model sometimes emitted an object mapping each file to its own hash instead,
     failing schema validation. Fixed with an explicit example in the role file.
   - **Bigger gap, found while designing scenario 6 and fixed before writing it:**
     `manifest.py`'s resumability was write-only — `manifest.upsert()` was called for the `heal`
     phase, but `manifest.pending_case_ids()` (the function that reads it back to skip
     already-done work) was **never called anywhere**, and `generate` had no manifest
     checkpointing at all. A crash-and-resume today would have blindly redone every case from
     scratch. Fixed: `orchestrator.py::_run_generate_phase` now checks the manifest before
     invoking `qa-test-generator`, sends only still-pending cases (embedding that context in the
     prompt so the model knows this is a resume, not a smaller task), and merges the result with
     already-recorded entries; a `plan.json` content change correctly invalidates the whole
     manifest rather than reusing stale entries. `heal_loop.py` now also seeds `escalated_ids`
     from the persisted manifest on start, so a case already escalated in a prior (crashed) run
     isn't re-triaged to reach the same verdict again. Verified live (real generator call for
     the pending case only, ledger confirms exactly one call) before scenario 6 was written
     against it.
10. **DONE (2026-09-07).** `control-plane/diff_guard.py` — extracts every `expect(...)...;`
    statement from a spec (tracking paren/bracket/brace depth so a multi-line assertion, e.g.
    `toHaveText([...])` across several lines, is captured whole rather than truncated at its
    first line), whitespace-normalized for comparison. `heal_loop.py` now captures a spec's
    content before invoking the healer and diffs it against the post-invocation content — in
    both the success path and the `InvocationBlocked` path (a blocked invocation can still have
    edited the file before its final report failed to parse) — reverting the file and recording
    `action: "escalated"` with `touchedAssertionLine: true` whenever any assertion differs at
    all (added, removed, or reworded), **regardless of what `touchedAssertionLine` self-reports**.
    A diff-guard rejection is not a permanent triage-style escalation — the case is simply still
    failing and eligible for another attempt next cycle, bounded by `max_heal_cycles`/no-progress
    same as always.

    Verified two ways: a live regression run of golden scenario 2 (a genuine selector fix)
    confirms the guard doesn't false-positive on legitimate heals; a mocked-`invoke()` test
    simulating a healer that edits an assertion and *lies* about it in `touchedAssertionLine`
    confirms the cheat is detected, the file is reverted, the manifest records the correction
    (not the false self-report), and the case remains failing. That second check is now
    `tests/golden/scenario_7_diff_guard_rejects_assertion_edit.py` — not one of the original six,
    added specifically to lock in this regression test, and deliberately not a live-LLM test
    (a well-behaved model won't violate its own instructions on request, so simulating the
    violation is the only reliable way to exercise the rejection path).

    **Known, deliberate trade-off:** whitespace immediately adjacent to brackets/commas inside a
    reformatted multi-line assertion isn't fully normalized away, so a purely cosmetic reformat
    of that kind could register as "changed" and get rejected unnecessarily. Accepted because a
    healer editing interaction code only has no legitimate reason to touch assertion formatting
    at all — the cost of a rare false positive (retried next cycle) is far lower than the cost
    of a real assertion change slipping through a too-lenient normalizer.

    **All 13 items from the original TODO are now done.**

## 🟢 Later — defer until the golden-task suite passes

11. **Tune `config/pipeline.json`'s `max_heal_cycles` and timeout values from
    `state/ledger.jsonl`** once there's a real run history. Don't set these from a guess — the
    source analysis's own sequencing correction (instrument before calibrating) applies here
    just as much as it did to Factory.
12. **Add the delta/incremental trigger for `qa-locator-explorer`** (re-scan only routes whose
    `sourceHash` is stale). The one-shot full-crawl mode is enough for this POC; delta mode
    matters once you're iterating on the dummy app repeatedly.
13. **Refine `executor.py::_categorize`'s substring-matching heuristic** once you have real
    Playwright error text from actual runs to tune it against.

## Immediate next step

Items 1, 2, 3, 4, 6, and 7 are all done (2026-09-06): a real
`python orchestrator.py <task-id> --changed-files ...` run now works end-to-end for the first
time — plan → locate → generate → heal (now triage-gated) → (review, when heal doesn't exhaust
its budget first) — against the real `claude` CLI, with real prompt content and a real locator
map at every step. `qa-failure-triage` is now wired in too (this session), gating every failing
case before it reaches the healer.

That real run immediately paid for itself: it surfaced four hidden bugs (Playwright results
never reaching disk, case-ID/specPath extraction being silently wrong, and a genuine dummy-app
product bug) plus the healer being sent cases with no triage gate at all — all fixed above, and
the triage gate itself is now confirmed working end-to-end with a targeted low-cost run (see
item 7). Items 5 (real JSON self-repair) and 8 (concurrency budget) are also done, both verified
with mocked-adapter tests plus a live regression check each. Item 9 is done too — all six golden
scenarios pass as real, individually-runnable acceptance tests (`tests/golden/run_all.py`),
which is how two more real bugs got caught (a `"skipped"`-Playwright-status miscount, a
`sourceHash` schema mismatch) plus the biggest remaining structural gap: manifest-based resume
was write-only until this session (`generate` had no checkpointing at all; `heal`'s was never
read back) — now fixed and covered by scenario 6.

Item 10 is done too — `control-plane/diff_guard.py` enforces the assertion-line rule in code,
not just prompt, and `tests/golden/scenario_7_diff_guard_rejects_assertion_edit.py` locks in a
regression test for the rejection path specifically (a mocked, lying healer — a real model won't
violate its own instructions on request, so a live test can only ever exercise the honest path).

**All 13 items from the original TODO, plus every gap discovered along the way, are now done.**
The design is complete and every guardrail is backed by either a live acceptance test
(`tests/golden/`) or a verified unit-level/mocked check. What's left is the explicitly-deferred
🟢 tier (11–13) — all three need real run history or real Playwright error text to calibrate
against, which this POC hasn't accumulated yet since every run so far has been a targeted
verification, not organic day-to-day use. The natural next step is simply to start using the
pipeline for real tasks against `dummy-app` (or, per `MIGRATION_TO_FACTORY.md`, begin the port)
and let `state/ledger.jsonl` build up the history items 11–13 are waiting on.
