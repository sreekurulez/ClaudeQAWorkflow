# Golden-task eval suite

Six scenarios that validate the guardrails, not just the happy path — from the setup guide's
Phase 7. Implemented as runnable scripts (`harness.py` + `scenario_N_*.py`, driven by
`run_all.py`) — live acceptance tests against the real `claude` CLI, not unit tests of the
logic in isolation. Run a single scenario directly while iterating
(`python3 scenario_1_clean_pass.py`); run `python3 run_all.py` for the full suite before
trusting any calibrated limit (max_heal_cycles, timeouts), and again after the Factory port to
diff behavior. Each scenario cleans up its own state/generated files and can run standalone or
in any order.

**Note on scenario 1's acceptance criterion:** refined from the README's original literal
"verdict: PASS" to "verdict PASS or REFACTOR, zero heal cycles, nothing still failing" — this
app deliberately plants a couple of role-fallback (non-`data-testid`) elements
(`dummy-app/context.md`'s testability requirements), which `qa-reviewer` correctly flags at
least P2 on every real run per its own contract. `REFACTOR` there means "shippable, quality
notes to raise," not a defect — see `scenario_1_clean_pass.py`'s docstring for the full
reasoning.

1. **Clean pass.** plan → generate → execute → review, zero heal cycles, `verdict: PASS`.
2. **Healer converges.** Generator produces one case with a broken selector; healer fixes it
   within `max_heal_cycles`; final `verdict: PASS`. Confirms `heal_loop.py`'s happy path and
   that `manifest.py` records the fix.
3. **No-progress breaker trips.** A case that can't be fixed by selector/wait changes alone
   (e.g. the app genuinely doesn't expose what the plan expects) — confirm the loop stops via
   `no_progress_detected()` *before* `max_heal_cycles` is exhausted, not after, and that the
   final artifact is `BLOCKED` with the still-failing case named.
4. **Flake is quarantined, not healed.** A case that fails once then passes on identical code
   (simulate with a deliberately timing-sensitive assertion) — confirm `quarantine_flaky()`
   catches it before it ever reaches `qa-test-healer`, and it's reported, not silently dropped.
5. **Locator fallback tier surfaces correctly.** Run `qa-locator-explorer` against the item
   list's delete button (no `data-testid`, see `dummy-app/public/app.js`) — confirm it's tagged
   `role-fallback`, and that `qa-reviewer` flags any case using it at least `P2`.
6. **Resume after a crash.** Kill the process mid-`generate` (after some specs are written) —
   confirm `orchestrator.py --phase generate` (or a re-run) picks up from `manifest.py`'s
   recorded state and does not regenerate specs already marked done, and that a `plan.json`
   change in between correctly invalidates the manifest instead of silently reusing stale work.

Track results in a table here once run; that table is the evidence base for calibrating
`config/pipeline.json`'s `max_heal_cycles` and timeout values instead of guessing.

## Results — 2026-09-06 (run individually while building each, not via a single `run_all.py` pass)

| # | Scenario | Result | Duration | Notes |
|---|---|---|---|---|
| 1 | Clean pass | PASS | 147.7s | verdict=REFACTOR (quality notes only, see note above), heal_cycle=0, 13 cases generated and executed clean |
| 2 | Healer converges | PASS | 113.7s | Hand-planted selector typo; healed in 1 cycle, `touchedAssertionLine: false` |
| 3 | No-progress breaker trips | PASS | 34.9s | SEED_BUG=1 case escalated by triage; exactly 1 triage call, 0 healer calls — breaker fired before a second cycle |
| 4 | Flake quarantined, not healed | PASS | 2.4s | Deterministic file-counter flake; quarantined before ever reaching triage or the healer |
| 5 | Locator fallback tier surfaces correctly | PASS | 45.1s | Delete button tagged `role-fallback`; reviewer flagged the case using it |
| 6 | Resume after a crash | PASS | 23.2s | Pre-seeded manifest entry skipped on resume (1 generator call, not 2); plan.json change correctly invalidated the manifest |

Two real bugs surfaced and fixed while writing these (beyond the ones item 9 exists to catch):
`executor.py` was miscounting a legitimately-`skipped` Playwright test (e.g. an env-gated case)
as a failure, which would have blocked scenario 1 from ever reaching a clean result; and
`roles/qa-locator-explorer.md` didn't state that `sourceHash` must always be a single string
even when a route spans multiple source files, so the model sometimes emitted an object instead.

## Scenario 7 — added after item 10 (the diff-guard)

Not one of the original six — added once `control-plane/diff_guard.py` existed, to lock in a
regression test for it. Unlike 1–6, it's not a live LLM test: a real, well-behaved model won't
deliberately violate its own role instructions on request, so the only reliable way to exercise
the *rejection* path is a mocked `invoke()` simulating a healer that edits an assertion and lies
about it in `touchedAssertionLine`. Runs in well under a second (no real LLM call).

| # | Scenario | Result | Duration | Notes |
|---|---|---|---|---|
| 7 | Diff-guard rejects assertion edit | PASS | 0.0s | Cheated assertion edit detected and reverted; manifest correctly overrode the false self-report; case remained failing |
