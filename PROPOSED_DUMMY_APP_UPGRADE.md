# Proposal — upgrading `dummy-app` into a real fixture for the indexing + user-story features

> [!IMPORTANT]
> **Status: implemented (2026-09-07/08).** `dummy-app/` has been rebuilt as a React + TypeScript
> SPA matching most of this brief (nested routes via `react-router-dom` 6.3.0, a shared `Header`,
> a transitive component chain, a barrel file, `user-stories/US-001.md` with a deliberately
> unimplemented AC). This document is kept as the as-built reference/checklist, not as pending
> work — cross-check the app itself for ground truth if this drifts.
>
> **One known gap from §0's warning came true:** `control-plane/testability_check.py` was never
> updated for the `.tsx` source, and now silently scans the old, unused `dummy-app/public/`
> instead of `dummy-app/src/`. See `IMPLEMENTATION_STRATEGY.md`'s immediate next steps.

**Audience:** whoever builds this (e.g. Google Antigravity IDE), plus anyone reviewing the plan
first. This is a build brief, written the same way `dummy-app/context.md` was.

**Why:** `PROPOSED_ENHANCEMENTS.md` proposes two changes to the QA workflow — user-story-driven
test planning (Change 1) and a deterministic 4-catalog indexing pipeline (Change 2). **Neither
can be tested against the current `dummy-app`**, which is a single-route static HTML page with
no router, no component tree, and no import graph. Route-scoped filtering and dependency impact
analysis are both no-ops on it.

This document specifies the *minimum* app that makes those features testable, while keeping the
existing seven golden scenarios passing.

> [!IMPORTANT]
> This proposal **supersedes** two things in `dummy-app/context.md`: its explicit
> non-requirement *"No routing framework, build pipeline, or state-management library"*, and its
> *"Suggested stack: plain HTML/JS or a minimal React frontend"*. A router and a component tree
> are now the **point**, not incidental. Everything else in `context.md` — especially the
> integration contract — still holds and is repeated below.

---

## 0. Read this first: the one thing that will silently break

`control-plane/testability_check.py::scan_paths()` dispatches on file extension:

```python
if path.suffix in (".html", ".htm"):   elements = scan_html(path)     # HTMLParser
elif path.suffix == ".js":              elements = scan_js(path)       # regex heuristic
else:                                    continue                       # <-- silently skipped
```

`.tsx` and `.ts` hit that `continue`. So a React version of this app produces an **empty fact
list, with no error raised** — the locate phase "succeeds," `qa-locator-explorer` receives
nothing, and the locator map comes back empty. Every downstream phase then plans and generates
against no selector information at all.

**Consequence:** this upgrade is only half a job. It requires a matching control-plane change —
a JSX/TSX-aware element scanner in `testability_check.py`. That work is **not** Antigravity's
(it's in the Python control plane, outside `dummy-app/`), but it must land alongside, or the
upgraded app cannot be exercised at all.

The good news: that scanner is needed for the real target (`finbook-web-application`, 2,529
`.ts/.tsx` files) regardless. Building it against a small, purpose-built React fixture is
strictly easier than building it against finbook directly — which is the main argument for
doing this upgrade at all.

---

## 1. Design constraint that shapes everything: keep the golden suite alive

Seven scenarios in `tests/golden/` are the only evidence the guardrails work. They hardcode
specifics about today's app. **The upgrade must preserve these exactly**, or each scenario needs
rewriting and re-verifying (a much larger job than the app itself):

| Hardcoded thing | Where | Must stay |
|---|---|---|
| `pkill -f "node server.js"` | `harness.py::kill_dummy_app_server()` | The app must still be started by **`node server.js`** — not `vite`, not `next dev` |
| Port `4000` | `harness.py`, `playwright.config.ts` `webServer` | Same port |
| `POST /api/__test__/reset` | every spec's `beforeEach` | Same path, same reset-to-seed behavior |
| `SEED_BUG=1` env flag | scenarios 1 + 3 | Same flag name, still makes one flow quietly wrong |
| testids `login-email`, `login-password`, `login-submit`, `current-user-indicator`, `item-list` | `regression/auth-login.spec.ts`, scenarios 2/3/7 | Same values, still reachable on the app's **landing route** |
| testids `confirm-delete-button`, `cancel-delete-button` | scenario 5's filter logic | Same values, still `stable-testid` |
| A delete button with **no** testid but a real role+name | scenario 5 | Still `role-fallback` |
| `dummy-app/tests/e2e/{generated,regression}/` | `config/project.json`, role files | Same paths |
| `dummy-app/test-results/results.json` | `executor.py::parse_results()` | Same path, JSON reporter configured **in `playwright.config.ts`**, never via a `--reporter` CLI flag |

### The architecture that satisfies this

**Keep `server.js` as the single process.** Express serves the API *and* the built frontend
assets as static files. There is **no separate frontend dev server**.

```
node server.js  →  :4000
                   ├── /api/*        Express JSON API (as today, extended)
                   └── /*            serves dist/ (built React SPA), history-fallback to index.html
```

`npm start` must run the build (or serve a committed `dist/`) and then `node server.js`, so a
bare `npx playwright test` with the existing `webServer` block still works headlessly. This one
decision preserves every row in the table above.

> Note for the scanner: `testability_check.py` must scan **`src/**/*.tsx`** (the source), never
> the built bundle in `dist/`. Minified output has no meaningful element facts.

---

## 2. What each proposed feature needs as a fixture

This is the core of the brief. Each subsection names a feature from
`PROPOSED_ENHANCEMENTS.md` and the *specific* app characteristic required to exercise it.

### 2.1 Catalog 1 — Route Registry (route → source file)

**Needs:** a real client-side router with enough structural variety that a naive regex fails and
a correct parser succeeds.

Build with **`react-router-dom` 6.3.0** and **JSX `<Route>` elements** (not
`createBrowserRouter`), because that is exactly what finbook uses — mirroring it is the entire
point of the fixture.

Required route-shape variety:
1. **Nested/layout routes** — a parent `<Route>` wrapping children, so full paths must be
   composed from parent + child segments. This is the case regex cannot handle correctly and
   finbook has throughout its `App.tsx`.
2. **A route with a URL parameter** — e.g. `/items/:id`.
3. **Multi-line JSX attributes** — at least a few `<Route>` elements with `path` and `element`
   on separate lines, since finbook's are formatted that way and single-line regex misses them.
4. **An index route** and a **catch-all `*`** route.
5. **All routes declared in one `App.tsx`**, matching finbook's layout.

**Scale:** 8–12 routes. Enough to make filtering meaningful (finbook has 238); small enough to
stay a fixture. Do **not** build 238 routes.

### 2.2 Catalog 2 — Component-to-Route Map (import graph)

**Needs:** an import graph with the specific shapes that break naive dependency tracing.

1. **A shared component imported by 3+ pages** (e.g. `Header`) — the "high impact" case.
2. **A transitive chain at least 3 deep** — `PriceDisplay` ← `CartButton` ← `ProductList`, so
   changing the leaf must be traced up two hops to a route.
3. **A component reached by two independent paths** — e.g. `PriceDisplay` also imported directly
   by a different page, so the reverse graph must union both, not overwrite.
4. **A barrel file** (`components/index.ts` doing `export * from './X'`) — this is the case that
   degenerates a reverse graph into "everything affects everything." The fixture must contain
   one so the indexer's handling of it is *tested*, not discovered on finbook.
5. **1–2 `React.lazy(() => import('./Page'))` dynamic imports** — finbook has 26. A static
   import parser will not resolve these. The fixture must include them so the indexer is forced
   to **report them as unresolved rather than silently drop them**.
6. **No `tsconfig.json` path aliases** — finbook has none; don't add complexity it won't face.

### 2.3 Catalog 3 — Per-route locator index

**Needs:** interactive elements genuinely distributed across routes, so splitting the map per
route actually reduces context (on a one-route app, filtering saves nothing).

- Each route should own **3–8 interactive elements**, with names scoped to their route so
  cross-route collisions are visible (e.g. both `/items` and `/cart` having a "remove" button is
  *useful* — it tests that filtering picks the right one).
- **Preserve the deliberate testability gaps, now spread across routes** rather than all on one
  page:
  - The item list's **delete button keeps no `data-testid`** but keeps a real `<button>` role and
    clear text → stays `role-fallback` (scenario 5 depends on this).
  - Keep **one dynamically-created element** with no stable anchor → stays `flagged-unstable`.
  - Add **one more no-testid element on a different route** (e.g. a sort/filter toggle), so the
    fallback tier appears on more than one route.
- Everything else gets a `kebab-case` `data-testid`, per existing convention.

### 2.4 Catalog 4 — API contract index

**Needs:** a backend surface with enough shape to parse meaningfully. Extend `server.js`:

- **8–12 endpoints** across 2–3 resource groups.
- **All the methods** — `GET`, `POST`, `PUT`, `DELETE` (mostly present already).
- **Path params** (`/api/items/:id`) *and* **query params** (`/api/items?sort=&filter=`).
- **Multiple response codes per endpoint** — at least one endpoint each returning `200`, `400`,
  `401`, and `404`, so the extracted contract has real `responses` to record.
- Keep every handler in `server.js` (or a small `routes/` folder) — plain Express, regex-parsable.

### 2.5 Change 1 — user-story-driven planning

**Needs the one fixture that doesn't exist today: a deliberately *unimplemented* requirement.**

Write a real user story with numbered acceptance criteria, committed at
`dummy-app/user-stories/<story-id>.md`, where **exactly one criterion is deliberately not
implemented in the app**.

Critical distinction — this must be a **missing feature**, not a bug:
- ✅ *"AC-4: Deleting an item that is referenced by a pending order must be blocked with an
  error message."* → the app has no such check at all; the endpoint deletes unconditionally.
- ❌ Not a selector typo (that's scenario 2's healable test defect).
- ❌ Not `SEED_BUG` (that's scenario 3's wrong-behavior product bug).

This is a **third, distinct failure category**: *the requirement was never built*. It's what
proves Change 1's whole thesis — a code-diff-driven planner cannot plan a test for code that
doesn't exist, while a requirements-driven planner can.

Also useful: **an acceptance criterion whose UI element doesn't exist yet**, which lets the
planner set the already-required `gap: true` field in `plan.schema.json` at plan time — a
cheaper, more deterministic gap signal than waiting for a failing test plus triage.

Include 4–6 ACs total: mostly implemented (so most planned cases pass), one unimplemented, one
gap-flagging.

### 2.6 Scope resolution (user-story text → routes)

**Needs:** route names and element names that are **lexically findable in prose**, so the
deterministic keyword matcher has something honest to match against — plus at least one
deliberate trap:

- Name routes and testids with words a story would naturally use (`/items`, `item-delete-button`).
- Include **one route whose name does *not* appear in the story text** but which *is* affected
  via the import graph (e.g. the story says "cart" but `Header` is shared, so `/profile` is
  affected too). This tests the union of text-hints and dependency-derived routes — and is
  exactly where a text-only matcher under-selects and starves the planner.

---

## 3. Preserved fixtures (do not lose these in the rewrite)

Restating from `context.md` §"Functional requirements" — each exists because a golden scenario
needs it:

1. **Auth (login/logout)** — the P0 baseline for scenario 1's clean pass. Same testids.
2. **CRUD list with edit-in-place and a filter/sort control** — gives the planner non-trivial
   cases.
3. **Destructive action with a confirmation dialog** — highest blast radius; scenario 5's
   `confirm-delete-button` / `cancel-delete-button` live here.
4. **One genuinely race-prone element** (auto-dismissing toast, or debounced search) — scenario
   4's flake quarantine needs a real timing-sensitive target.
5. **`SEED_BUG=1`** — one flow quietly disagrees with its obviously-correct expected behavior;
   unfixable by any selector/wait change. Scenario 3's no-progress breaker depends on it.
6. **In-memory state only**, reset by `POST /api/__test__/reset`. No DB, no persistence, no real
   auth hardening.

---

## 4. Explicit non-requirements — this is still a fixture, not a product

- No visual design or styling polish. Unstyled semantic HTML is ideal.
- No state-management library (no Redux/Zustand) — `useState`/`useContext` is plenty.
- No real password hashing, no session persistence across restarts.
- No test framework beyond Playwright.
- **Do not scale to finbook's size.** 8–12 routes, ~30 components, ~40 testids. The goal is
  *structural* fidelity to finbook's shapes, not volume.
- Do not add `tsconfig` path aliases, a monorepo layout, or SSR.
- **Do not rewrite anything in `control-plane/`, `roles/`, `schemas/`, or `config/`** — those
  belong to the workflow, not the app. If the app's shape seems to require a control-plane
  change, say so in your handoff notes instead of making it.

---

## 5. Suggested stack

Chosen for finbook fidelity, not preference:

| Layer | Choice | Why |
|---|---|---|
| Frontend | **React 18 + TypeScript** | Matches finbook (`react ^18.2.0`, `typescript 4.6.4`) |
| Routing | **`react-router-dom` 6.3.0**, JSX `<Route>` style | Exact finbook version and declaration style |
| Build | Vite (or CRA) → static `dist/` | Any bundler is fine; output must be static files |
| Backend | **Existing Express `server.js`**, extended | Preserves port 4000, `node server.js`, reset endpoint, harness `pkill` |
| Tests | Existing `@playwright/test` + `playwright.config.ts` | Keep `workers: 1` and the file-output JSON reporter |

---

## 6. Definition of done

The upgrade is complete when all of the following hold:

1. `cd dummy-app && npm install && npm start` serves the app on `:4000` from a single
   `node server.js` process.
2. `npx playwright test` runs headlessly via the existing `webServer` block and writes
   `dummy-app/test-results/results.json`.
3. `dummy-app/tests/e2e/regression/auth-login.spec.ts` **passes unmodified** (or, if its
   selectors genuinely had to move, the exact changes are listed in your handoff notes).
4. `POST /api/__test__/reset` restores known seed data; `SEED_BUG=1` still makes exactly one
   flow quietly wrong.
5. `dummy-app/user-stories/<story-id>.md` exists with 4–6 ACs, one of them **deliberately
   unimplemented**, and the notes say plainly which one and why.
6. The import graph contains all six shapes from §2.2 (shared component, 3-deep transitive
   chain, dual-path component, barrel file, `React.lazy`, no aliases) — list where each lives.
7. The deliberate testability gaps survive: the delete button is still `role-fallback`, one
   element is still `flagged-unstable`, and `confirm-delete-button` / `cancel-delete-button` are
   still `stable-testid`.
8. A handoff note lists: every route and its source file, every `data-testid` added, every
   endpoint and its response codes, and anything in this brief you deliberately deviated from.

**Explicitly out of scope for this build, and expected to fail until the control plane catches
up:** `python3 control-plane/testability_check.py` will return an empty fact list against a
`.tsx` app (see §0). That is a known, accepted gap — the JSX-aware scanner is separate,
Python-side work. Do not attempt to work around it by keeping the UI in `.html`/`.js`.

---

## 7. Reference material in this repo

- `HOW_IT_WORKS.md` — how the workflow that consumes this app actually works. Read §4 (the
  pipeline) and §4.1 (the locate phase) at minimum.
- `PROPOSED_ENHANCEMENTS.md` — the two features this upgrade exists to make testable.
- `tests/golden/README.md` — the seven scenarios; treat them as the acceptance spec.
- `dummy-app/context.md` — the original build brief. Still authoritative for the integration
  contract; superseded only where §0 of this document says so.
- `dummy-app/server.js`, `dummy-app/playwright.config.ts` — the current contract in code.
  Match their shape even as you extend them.
- `../finbook-web-application/src/App.tsx` — the real router this fixture is mirroring, if
  available. Worth reading for the nested-`<Route>` formatting to imitate.
