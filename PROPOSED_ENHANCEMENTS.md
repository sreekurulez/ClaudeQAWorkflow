# Proposed Enhancements to the QA Workflow

> [!IMPORTANT]
> **Status: superseded.** This was the original proposal. After analysis, feasibility checks
> against the real target app, and several rounds of critique, it was substantially revised —
> most of Change 2's four catalogues were dropped or replaced (browser-based locator discovery
> instead of source parsing; no graph/dependency-tracer dependency), and both changes were
> re-ordered behind bigger unaddressed risks (test quality, real-app feasibility, portability).
> **`IMPLEMENTATION_STRATEGY.md` is the current plan.** This document is kept only for the
> original reasoning trail — do not implement from it directly.

This document proposes two architectural enhancements to the ClaudeQA Workflow system
described in `HOW_IT_WORKS.md`. Both changes address real gaps identified during analysis
of the current proof-of-concept and are designed to make the system production-ready at
scale.

> [!NOTE]
> The current system is a working proof-of-concept that validates the **guardrail
> architecture** (deterministic control plane + bounded AI workers). These enhancements
> do not change that architecture — they improve the **inputs** the system operates on.

---

## Change 1: User-Story-Driven Test Planning

### The Current Behavior

Today, Phase 2 (`plan`) receives two inputs:
1. **The developer's changed files** — the full text of modified source files.
2. **The full `state/locator-map.json`** — every interactive element across all pages.

The AI planner reads the code diff and plans test scenarios based on **what code was
changed**. There is no awareness of the original requirement or acceptance criteria.

### The Problem

A code-change-driven planner can only test **what was implemented**, not **what should
have been implemented**. This creates a blind spot:

| Scenario | Code-Diff Planner (Current) | User-Story Planner (Proposed) |
|---|---|---|
| Developer implements delete button correctly | ✅ Plans delete tests | ✅ Plans delete tests |
| Developer forgets to implement "block delete on pending order" | ❌ No test planned (code doesn't exist) | ✅ Plans test from acceptance criteria, test fails, gap caught |
| Developer implements feature but breaks unrelated page | ❌ Only tests the changed file | ✅ Tests all flows mentioned in the User Story |

In a standard SDLC, test plans are always derived from **requirements and acceptance
criteria**, not from code inspection alone. Code diffs tell you *where to look*, not
*what to test*.

### The Proposed Change

#### New Input to Phase 2 (Plan) — Purely Requirement-Driven

Phase 2 (`plan`) should accept a **User Story** (or acceptance criteria) as its primary
input, alongside filtered locators. **Changed files are NOT sent to the planner** —
they belong in Phase 3 (`generate`), where the generator needs them to write accurate
test code against the real implementation.

The rationale: in a standard SDLC, a QA analyst writes a test plan from the Jira ticket
**before** looking at the developer's code. The test plan defines *what should work*
based on requirements, not *what was coded*. If the planner sees the code, it risks
planning only for what was implemented and missing what was not.

| | Phase 2: Plan | Phase 3: Generate |
|---|---|---|
| **Question it answers** | *"What should we test?"* | *"How do we write the test code?"* |
| **Driven by** | Requirements (User Story) | Implementation (actual code) |
| **Needs changed files?** | ❌ No — requirements exist before code | ✅ Yes — must see real code to write accurate tests |
| **Analogy** | QA Analyst writing test cases from a Jira ticket | SDET writing Playwright scripts from test cases + source code |

**Current prompt construction** (`orchestrator.py::_build_prompt`, phase `"plan"`):
```python
# Current — plans from code diff only
return "\n\n".join([
    _changed_files_block(changed_files or []),
    _artifact_block(LOCATOR_MAP_PATH, "state/locator-map.json"),
])
```

**Proposed prompt construction for Phase 2 (`plan`):**
```python
# Proposed — plans from User Story + filtered locators ONLY (no changed files)
if phase == "plan":
    return "\n\n".join([
        _user_story_block(user_story_text),
        _filtered_locator_block(task_id, user_story_text),    # see Change 2
        # NO _changed_files_block() here — code context belongs in generate phase
    ])
```

**Proposed prompt construction for Phase 3 (`generate`) — changed files move here:**
```python
# Proposed — generator receives plan + locators + actual code
if phase == "generate":
    return "\n\n".join([
        _artifact_block(plan_path, "plan.json"),
        _filtered_locator_block(task_id, user_story_text),
        _changed_files_block(changed_files),    # moved HERE from plan phase
    ])
```

The generator needs the changed files because writing correct Playwright tests requires
knowing the real implementation details: actual API endpoints, response formats, DOM
update patterns, error handling flows, and timing behavior. Without the code, the
generator would guess — and those guesses become failing tests that waste heal cycles.

#### New CLI Interface

```bash
# Current
python orchestrator.py <task-id> --changed-files path/to/file.js

# Proposed
python orchestrator.py <task-id> \
    --user-story "As a user, I want to delete items from my cart..." \
    --user-story-file path/to/story.md \
    --changed-files path/to/file.js    # used by generate phase + dependency analysis
```

The `--user-story` or `--user-story-file` argument provides the acceptance criteria
text for the planner. The `--changed-files` argument is used by the **generate** phase
(to write accurate test code) and by the **scope resolution** step (to identify
affected routes via the Component-to-Route Map — see Change 2).

#### Updated `qa-test-planner` Role Prompt

The planner's role instructions (`roles/qa-test-planner.md`) should be updated to:
1. **Primary source of test scenarios:** The User Story's acceptance criteria.
2. **Supporting context:** The filtered locator map (to know which UI elements exist
   and how to target them).
3. **No code inspection:** The planner does NOT receive changed files and does NOT
   inspect application source code. It plans based purely on what the requirements say
   should work.

#### Updated `qa-test-generator` Role Prompt

The generator's role instructions (`roles/qa-test-generator.md`) should be updated to
accept the changed files as a new input:
1. **Test cases to implement:** `plan.json` from Phase 2.
2. **UI element selectors:** Filtered locator map.
3. **Implementation details (NEW):** The actual changed source files, so the generator
   can write tests that match how the feature was really built (correct API endpoints,
   DOM behavior, error messages, timing, etc.).

#### Updated `plan.json` Output Schema

Add a new field to each test case linking it back to the requirement:

```json
{
  "caseId": "task-42-E01",
  "priority": "P0",
  "type": "functional",
  "acceptanceCriteria": "User can delete an item from the cart",
  "preconditions": "User is logged in with items in cart",
  "steps": "1. Navigate to /cart 2. Click remove button on first item",
  "expected": "Item is removed and cart total updates",
  "selectors": ["cart-item-list", "remove-button", "cart-total"],
  "gap": false
}
```

New field:
- `acceptanceCriteria`: Which requirement this test validates (traceability).

#### How Missing Features Are Surfaced

When the planner creates a test case from an acceptance criterion, but the developer
has not implemented that feature:

1. **Phase 2 (Plan):** Plans the test case from the User Story (e.g., *"block delete on
   pending order"*). The planner has no way to know this is missing — it plans it like
   any other case.
2. **Phase 3 (Generate):** The generator receives `plan.json` + the actual code. It
   either writes a test that will **correctly fail** at runtime (because the feature
   does not exist), or marks the case `"status": "skipped"` with a note.
3. **Phase 4 (Execute):** The test fails.
4. **Heal Loop:** `qa-failure-triage` classifies it as `product-bug` (not a test
   defect). It is **escalated, never healed** — exactly the right behavior.

The missing requirement is surfaced to the developer as an escalated product bug.

#### Files to Modify

| File | Change |
|---|---|
| `control-plane/orchestrator.py` | Add `--user-story` / `--user-story-file` CLI args; update `_build_prompt()` for `plan` phase (User Story + locators only) and `generate` phase (add changed files); add `_user_story_block()` helper |
| `roles/qa-test-planner.md` | Rewrite to plan from acceptance criteria as primary input; remove all references to reading changed files or source code |
| `roles/qa-test-generator.md` | Add changed files as a new input; instruct the generator to inspect implementation details when writing tests |
| `schemas/plan.schema.json` | Add optional `acceptanceCriteria` field |
| `schemas/envelope.schema.json` | No change needed (envelope shape is role-agnostic) |

---

## Change 2: Deterministic Indexing Pipeline

### The Current Behavior

Today, Phase 1 (`locate`) works as follows:
1. `testability_check.py` scans **all** files in `dummy-app/public/**/*.{html,js}`.
2. It extracts a flat fact list of interactive elements.
3. `qa-locator-explorer` (AI) turns those facts into `state/locator-map.json` — one
   single JSON file containing every element across every route.
4. In Phase 2 (`plan`), the **entire** `locator-map.json` is embedded in the AI prompt.

The only optimization: a hash check skips the locate phase entirely if the source files
haven't changed since the last run.

### The Problem

For a real-world application with 50+ routes and hundreds of interactive elements:
- `locator-map.json` could be 50,000–200,000 tokens.
- Sending the full file on every plan/generate call wastes 80–95% of those tokens on
  elements the current task will never interact with.
- At \$3 per million input tokens (Claude Sonnet), this adds up to \$15+/day at 100
  runs/day — most of it wasted on irrelevant context.

Additionally, the system has no knowledge of which pages are affected when a shared
component changes. If `Header.tsx` is modified, every page that imports it should be
tested, but the current system has no way to know this.

### The Proposed Change: 4-Catalog Indexing Pipeline

Add a new **Phase 0 (`index`)** that runs once at project setup and updates
incrementally on each code change. This phase builds four searchable catalogs using
plain Python (no AI), stored as simple JSON files on disk.

#### Catalog 1: Route Registry

**What:** Maps every URL route in the application to its source file(s).

**How:** Python parses the application's router configuration file (React Router, Vue
Router, Express routes, etc.) using regex or AST parsing. No AI needed.

**Input:** The app's router/routing file(s).

**Output:** `state/index/route-registry.json`

```json
{
  "/login":        { "component": "LoginPage",    "file": "src/pages/LoginPage.tsx" },
  "/products":     { "component": "ProductList",   "file": "src/pages/ProductList.tsx" },
  "/products/:id": { "component": "ProductDetail", "file": "src/pages/ProductDetail.tsx" },
  "/cart":          { "component": "CartPage",      "file": "src/pages/CartPage.tsx" },
  "/checkout":     { "component": "CheckoutPage",  "file": "src/pages/CheckoutPage.tsx" }
}
```

**Extraction method:** Regex patterns matched to the app's framework. Examples:
- React Router: `<Route path="..." element={<Component />} />`
- Express: `router.get('/path', handler)`
- Vue Router: `{ path: '/path', component: Component }`

#### Catalog 2: Component-to-Route Map

**What:** For every source file, lists which routes/pages are affected if that file
changes. Traces `import` chains transitively (if A imports B, and B imports C, then a
change to C affects A).

**How:** Python parses `import` / `require` statements and builds a reverse dependency
graph. Tools like `madge` (for JavaScript) or Python's `ast` module can automate this.
No AI needed.

**Input:** All source files in the application.

**Output:** `state/index/component-route-map.json`

```json
{
  "src/components/Header.tsx": {
    "affected_routes": ["/login", "/products", "/cart", "/checkout"],
    "impact": "high"
  },
  "src/components/CartButton.tsx": {
    "affected_routes": ["/products", "/cart"],
    "impact": "medium"
  },
  "src/components/ItemCard.tsx": {
    "affected_routes": ["/products"],
    "impact": "low"
  }
}
```

**Transitive resolution example:**
```
PriceDisplay.tsx is imported by CartButton.tsx
CartButton.tsx is imported by ProductList.tsx (/products) and CartPage.tsx (/cart)
PriceDisplay.tsx is also directly imported by CheckoutPage.tsx (/checkout)

Therefore:
PriceDisplay.tsx → affected_routes: ["/products", "/cart", "/checkout"]
```

#### Catalog 3: Per-Route Locator Index

**What:** The same locator data currently in `state/locator-map.json`, but split into
**one file per route** instead of one monolithic file.

**How:** The existing `testability_check.py` + `qa-locator-explorer` pipeline, with the
output written to separate files per route.

**Output:** `state/index/locators/<route-slug>.json`

```
state/index/locators/
├── login.json         (3 elements)
├── products.json      (18 elements)
├── cart.json           (9 elements)
├── checkout.json      (15 elements)
└── profile.json       (11 elements)
```

Each file contains only that route's elements:
```json
[
  {
    "name": "email-input",
    "role": "textbox",
    "testId": "login-email",
    "confidenceTier": "stable-testid"
  },
  {
    "name": "password-input",
    "role": "textbox",
    "testId": "login-password",
    "confidenceTier": "stable-testid"
  },
  {
    "name": "submit-button",
    "role": "button",
    "testId": "login-submit",
    "confidenceTier": "stable-testid"
  }
]
```

**Backward compatibility:** `state/locator-map.json` can still be generated as a merged
view of all per-route files, so existing code that reads it does not break.

#### Catalog 4: API Contract Index

**What:** Lists every backend API endpoint, its HTTP method, URL parameters, and
request/response shape.

**How:** Python parses backend route handler files using regex. No AI needed.

**Input:** Backend route files (e.g., `server.js`, `routes/*.py`).

**Output:** `state/index/api-contracts.json`

```json
{
  "POST /api/login": {
    "file": "server.js",
    "line": 12,
    "params": ["email", "password"],
    "responses": ["200 OK", "401 Unauthorized"]
  },
  "DELETE /api/items/:id": {
    "file": "server.js",
    "line": 42,
    "params": ["id"],
    "responses": ["200 OK", "404 Not Found"]
  },
  "GET /api/cart/total": {
    "file": "server.js",
    "line": 51,
    "params": [],
    "responses": ["200 OK"]
  }
}
```

### When Does Indexing Run?

| Event | Action | Cost |
|---|---|---|
| First-time project setup | Full index of entire codebase | Seconds, no AI |
| Each git commit / PR | Incremental: re-index only changed files | Milliseconds, no AI |
| New route added | Route Registry auto-detects on next index | Milliseconds, no AI |
| Component moved/renamed | Import map updates on next index | Milliseconds, no AI |

### New Files to Create

| File | Purpose |
|---|---|
| `control-plane/indexer.py` | Main indexing script: runs all 4 catalogs |
| `control-plane/index_routes.py` | Catalog 1: Route Registry extraction |
| `control-plane/index_dependencies.py` | Catalog 2: Component-to-Route Map (import tracing) |
| `control-plane/index_locators.py` | Catalog 3: Per-route locator splitting (wraps existing `testability_check.py`) |
| `control-plane/index_api.py` | Catalog 4: API contract extraction |
| `state/index/` | Directory for all index output files |

### Files to Modify

| File | Change |
|---|---|
| `control-plane/orchestrator.py` | Add `index` phase; update `_build_prompt()` to use filtered locators from per-route files instead of the full `locator-map.json`; add `_resolve_affected_routes()` helper |
| `control-plane/testability_check.py` | Optionally refactor to output per-route fact lists (or keep as-is and let `index_locators.py` split the output) |
| `config/project.json` | Add `index_dir`, `router_file`, and `framework` fields |

---

## How Both Changes Work Together

The two changes combine into a unified, optimized flow:

```
Phase 0: Index (one-time + incremental updates, no AI)
│
├── Route Registry:         /login → LoginPage.tsx
├── Component-Route Map:    CartButton.tsx → [/products, /cart]
├── Per-Route Locators:     locators/cart.json (9 elements)
└── API Contracts:          DELETE /api/items/:id
│
▼

Phase 1: Locate (existing, unchanged)
│
├── ⚙️ testability_check.py extracts element facts
└── 🤖 qa-locator-explorer ranks/tags elements
│   Output now split into per-route files by index_locators.py
│
▼

Phase 2: Plan (enhanced — purely requirement-driven)
│
├── Input 1: User Story / Acceptance Criteria (NEW — primary source)
│             "What SHOULD the app do?"
│
│   ⚙️ Scope Resolution (new, deterministic Python):
│   ├── Extract route hints from User Story text (keyword/NLP)
│   ├── Look up changed files → affected routes (from Component-Route Map)
│   ├── Merge both route sets (union)
│   └── Fetch ONLY those routes' locators (from Per-Route Locator Index)
│
├── Input 2: Filtered locators (NEW — only relevant routes)
│             "What UI elements exist on these pages?"
│
├── ❌ NO changed files — planner does not see implementation code
│
└── 🤖 qa-test-planner receives focused, minimal context
    Output: plan.json with requirement traceability (acceptanceCriteria field)
│
▼

Phase 3: Generate (enhanced — implementation-aware)
│
├── Input 1: plan.json from Phase 2     ← "What test cases to write"
├── Input 2: Filtered locators          ← "How to target UI elements"
├── Input 3: Changed files (NEW here)   ← "How was the feature actually built?"
├── Input 4: Relevant API contracts     ← "What endpoints and responses exist?"
│
└── 🤖 qa-test-generator writes .spec.ts files using real implementation details
    (API endpoints, DOM behavior, error messages, timing)
│
▼

Phases 4–6: Execute → Heal → Gate (unchanged)
```

### Why Changed Files Belong in Generate, Not Plan

| Concern | Explanation |
|---|---|
| **Plan purity** | The test plan should define *what to verify* based on requirements, independent of how (or whether) the developer coded it. If the planner sees the code, it risks planning only for what was implemented and missing what was not. |
| **Generator accuracy** | The generator must write real Playwright code. It needs to see the actual API endpoints (`DELETE /api/items/:id` vs `POST /api/cart/remove`), how the DOM updates (reload vs inline), error message text, and timing behavior. Without the code, it guesses — and guesses become failing tests. |
| **Missing feature detection** | When the planner plans a test case from an acceptance criterion that was not implemented, the generator writes a test that correctly fails at runtime. The heal loop triages it as `product-bug` and escalates it — surfacing the gap to the developer. If the planner had seen the code and known the feature was missing, it might have silently dropped the test case instead. |

### Token Cost Comparison

| Approach | Tokens per Plan Call | Tokens per Generate Call | Cost at 100 runs/day |
|---|---|---|---|
| **Current** (full locator map + code diff in plan) | ~50,000 | ~30,000 | ~$24/day |
| **Route-scoped filtering only** | ~5,000 | ~15,000 | ~$6/day |
| **Full proposal (Index + US + Filter)** | ~2,500 | ~8,000 | ~$3/day |

### Coverage Comparison

| Scenario | Current System | Proposed System |
|---|---|---|
| Feature works correctly | ✅ Tests pass | ✅ Tests pass |
| Code regression breaks existing feature | ✅ Tests catch it | ✅ Tests catch it |
| Developer forgets to implement a requirement | ❌ Not detected | ✅ Planner plans from US, test fails, triage escalates as product-bug |
| Shared component change breaks another page | ❌ Only tests changed file | ✅ Dependency map identifies all affected pages |
| Large app with many pages | ⚠️ High token cost | ✅ Minimal token cost |

---

## Implementation Priority

| Priority | Change | Effort | Impact |
|---|---|---|---|
| **P0** | Per-route locator splitting (Catalog 3) | Low — split existing `locator-map.json` output | Immediate token savings |
| **P0** | Route-scoped filtering in `_build_prompt()` | Low — filter locators before embedding in prompt | Immediate token savings |
| **P1** | User Story input to Phase 2 | Medium — new CLI arg, prompt rewrite, schema update | Closes the requirement-coverage gap |
| **P1** | Component-to-Route Map (Catalog 2) | Medium — import parsing + transitive resolution | Enables accurate impact analysis |
| **P2** | Route Registry (Catalog 1) | Low — regex parsing of router file | Foundation for Catalog 2 |
| **P2** | API Contract Index (Catalog 4) | Low — regex parsing of backend routes | Enriches test planning context |
| **P2** | `plan.schema.json` updates | Low — add optional fields | Enables requirement traceability |

---

## Relationship to Existing Architecture

These changes **do not alter** the core architectural principles documented in
`HOW_IT_WORKS.md`:

- **The AI is never the referee of its own work.** — Unchanged. All validation,
  gating, and checkpointing remain in deterministic Python.
- **Deterministic control plane + swappable AI adapter.** — Unchanged. The indexing
  pipeline is entirely deterministic. The planner prompt changes are in
  `orchestrator.py`, not in the adapter layer.
- **Bounded heal loop with diff-guard.** — Unchanged. Phases 3–6 are not affected.
- **Schema-validated envelopes.** — Enhanced, not changed. New fields are additive and
  optional.
- **Vendor-neutral except the adapter.** — Unchanged. The indexing pipeline and
  route-scoped filtering are pure Python with no Claude-specific code.

The indexing pipeline is a **new deterministic layer** that sits *before* the existing
pipeline, providing better inputs to the same guardrailed AI workers.
