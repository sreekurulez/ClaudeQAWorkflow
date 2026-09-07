# Context — building the sample application (for Google Antigravity)

You are building the application this project's QA workflow will be tested against. The
workflow itself (planner/generator/executor/healer/reviewer/locator-explorer, all in
`control-plane/` + `roles/`) is already built and documented in `HOW_IT_WORKS.md` (the single
source of truth for how it works and how to operate it), `README.md`, and
`tests/golden/README.md` — read `tests/golden/README.md` in particular, since the seven
scenarios listed there are the acceptance test for whatever you build: each one needs a real
feature in this app to exercise it.

A minimal placeholder currently lives in `dummy-app/` (`server.js` + `public/`). Your job is to
replace/extend it into something more realistic while preserving the integration contract below
exactly — the rest of this project (`config/project.json`, `control-plane/executor.py`,
`playwright.config.ts`) already points at these specific paths/behaviors and should not need to
change because of what you build.

## Integration contract — do not change these

- Lives under `dummy-app/`. `npm start` runs it; it listens on port `4000`.
- `dummy-app/playwright.config.ts` keeps its `webServer` block (auto-starts the app for test
  runs) and its JSON reporter writing to `dummy-app/test-results/results.json` —
  `control-plane/executor.py::parse_results()` reads that exact path.
- Exposes a test-only reset endpoint, `POST /api/__test__/reset`, that returns the app to known
  seed data. Every generated/baseline spec calls this in `beforeEach` for test isolation — see
  `dummy-app/tests/e2e/regression/auth-login.spec.ts` for the existing convention.
- In-memory state only. No real database, no real auth hardening — this app exists to be
  tested, not to be secure or persistent.
- If you change the existing `data-testid` values (`login-email`, `login-password`,
  `login-submit`, `current-user-indicator`, `item-list`), update
  `dummy-app/tests/e2e/regression/auth-login.spec.ts` to match, or clearly call out the new
  ones so it can be updated.

## Functional requirements, and why each one exists

Build a small multi-module app — at least two feature modules (e.g. `auth`, `items`) — so the
locator-explorer role has more than one module to rank across (it ranks flows per-module,
exactly one P0 each; a single-module app under-tests that logic).

1. **Auth (login/logout).** Already partially present. Keep it — it's the P0 baseline flow the
   golden-task "clean pass" scenario runs against.
2. **A CRUD list, extended beyond add/delete.** Add edit-in-place or a filter/sort control, so
   the planner has more than two trivial cases to plan and the generator has more than one
   spec shape to produce.
3. **A destructive action with a confirmation step** (e.g. "delete requires confirming in a
   dialog first"). Mirrors the pattern already established in
   `finbook-web-application/.factory/templates/qa/tests/e2e/regression/admin/destructive-action-confirmation.spec.ts`
   — destructive/irreversible actions are the highest-blast-radius flows the locator-explorer's
   ranking logic is designed to surface as P0.
4. **One flow with a genuinely race-prone element** — e.g. a toast/notification that
   auto-dismisses after a short timeout, or a debounced search input. This is what golden-task
   scenario 4 (flake quarantine) needs a real target for; without a real timing-sensitive
   element, that scenario has nothing authentic to catch.
5. **One flow with a toggleable, seeded product bug** — e.g. an environment flag
   (`SEED_BUG=1`) that makes one flow's actual behavior quietly disagree with its obviously
   correct expected behavior (an off-by-one in a filter, a wrong success message, etc). This is
   what golden-task scenario 3 (no-progress breaker → `BLOCKED`/escalation) needs: a failure
   that no amount of selector/wait fixing will resolve, so the loop's circuit breaker has
   something real to trip on instead of being tested only against a synthetic case.

## Testability requirements — deliberate, specific gaps

- Most interactive elements get a `data-testid`, following the existing convention
  (`kebab-case`, e.g. `add-item-submit`).
- **Exactly 2–3 elements must deliberately have no `data-testid`** — keep the existing one
  (the item list's delete button in `dummy-app/public/app.js`) and add one or two more (e.g. a
  sort/filter toggle). Each of these still needs a stable accessible role and name (e.g. a real
  `<button>` with clear text, not a bare `<div onclick>`) — the locator-explorer's fallback tier
  depends on a real role/label existing, not just on the `data-testid` being absent.

## Explicit non-requirements — keep this small

- No visual design/styling polish.
- No real password hashing, no session persistence across restarts.
- No routing framework, build pipeline, or state-management library beyond what the chosen
  stack needs by default — this app is a test fixture, not a demo of frontend engineering.

## Suggested stack (your call — the contract above is what actually matters)

Whatever is fastest for you to build correctly: a small Node/Express-style backend plus either
plain HTML/JS or a minimal React frontend is enough to satisfy every requirement above.

## Reference material already in this repo

- `README.md` — this project's overall architecture, so you understand what will call this app.
- `tests/golden/README.md` — the six scenarios this app must support; treat it as the spec you
  are actually building against.
- `dummy-app/server.js`, `dummy-app/public/`, `dummy-app/playwright.config.ts` — the current
  placeholder implementing the integration contract in code; match its shape even as you
  replace its content.
