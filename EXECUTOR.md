# Phase Invocation & Debugging Reference

This document is the operator's quick-reference for running individual pipeline phases,
understanding what files each phase reads and writes, verifying the audit trail, and debugging
failures. For the full architectural explanation, see `HOW_IT_WORKS.md`. For the implementation
history and design rationale behind each piece, see `IMPLEMENTATION_STRATEGY.md`.

---

## Prerequisites

```bash
# Terminal 1 — dummy app must be running before execute/heal/locate (browser crawl) phases
cd dummy-app && npm run start

# Terminal 2 — all phase commands run from here
cd control-plane
```

---

## Architecture Overview — How Calls Flow

There are **no hooks, no event bus, no middleware**. The wiring is pure Python function calls
plus two kinds of subprocess:

```
orchestrator.py::run_pipeline()
  │
  ├── locate()
  │     ├── testability_check._default_paths()      → hash source files
  │     ├── browser_crawler.crawl()                  → subprocess: node crawl.js
  │     │     └── crawl.js                           → Playwright browser (visits each page,
  │     │                                               reads rendered DOM — not AI)
  │     └── invoke("qa-locator-explorer")            → subprocess: claude -p ...
  │
  ├── run_phase("plan")
  │     ├── traceability.resolve_routes_for_files()  → page-scoped prompt filter (Stage 9)
  │     ├── project_context_block()                  → config-driven context (Stage 6)
  │     └── invoke("qa-test-planner")                → subprocess: claude -p ...
  │
  ├── run_phase("generate") → _run_generate_phase()
  │     ├── manifest.pending_case_ids()              → resume support (skip done cases)
  │     ├── traceability.derive_routes_for_case()    → page-scoped prompt filter
  │     ├── invoke("qa-test-generator")              → subprocess: claude -p ...
  │     └── traceability.record_generate()           → write state/traceability.json (Stage 8)
  │
  ├── heal_loop.run()
  │     ├── executor.run_playwright()                → subprocess: npx playwright test
  │     ├── quarantine_flaky()                       → re-run N times, detect flake
  │     ├── invoke("qa-failure-triage")              → subprocess: claude -p ...
  │     ├── invoke("qa-test-healer")                 → subprocess: claude -p ...
  │     └── diff_guard.assertions_changed()          → pure Python file diff
  │
  ├── run_phase("review")
  │     └── invoke("qa-reviewer")                    → subprocess: claude -p ...
  │
  └── qa_gate.decide()                               → pure Python, no subprocess, no AI
```

Every `invoke()` call goes through the same path:
1. `load_pipeline_config()` → reads `config/pipeline.json` (timeout, adapter, budget)
2. `get_adapter("claude")` → picks `ClaudeAdapter`
3. `_run_adapter_bounded()` → semaphore-gated `subprocess.run(["claude", "-p", ...])`
4. `_parse_envelope()` → two-level JSON unwrap (CLI wrapper → model reply)
5. `validate()` → `jsonschema` check against `schemas/envelope.schema.json` + role-specific schema
6. `ledger.record()` → append to `state/ledger.jsonl`

The Claude CLI itself uses its own internal tool calls (file read/write) — the control plane
doesn't see these; it only sees the final JSON on stdout.

---

## Adapter-Agnostic Portability — Switching AI Providers

This system is designed around a single, narrow adapter seam so the entire control plane can
be ported to a different AI provider (Factory AI, OpenAI Codex, a custom LLM wrapper, etc.)
by changing **one file** and **one config value**. This section documents exactly where the
boundary is, what's coupled, and what to do to port it.

### The adapter interface — the only contract a provider must satisfy

```python
# adapters/base.py — the entire interface is 4 fields and 1 method:

@dataclass
class RawResult:
    stdout: str       # the agent's full output (any format — invoke.py parses it)
    stderr: str       # diagnostic output
    exit_code: int    # 0 = success, 124 = timeout (convention)
    timed_out: bool   # True → invoke.py records BLOCKED, never retries silently

class Adapter:
    def run(self, *, role: str, prompt: str, cwd: str, timeout_s: int) -> RawResult:
        """Invoke the agent for one role/prompt, wrapped in a wall-clock timeout.
        Must NEVER raise on timeout — return RawResult(timed_out=True) instead."""
```

A new provider needs exactly one new file (e.g. `adapters/factory_adapter.py`) implementing
this interface, plus registering it in the `ADAPTERS` dict so `get_adapter("factory")` finds it.

### What's above the seam (provider-agnostic — carries over unchanged)

Every file in `control-plane/` except the adapter is provider-agnostic:

| File | Why it's portable |
|---|---|
| `orchestrator.py` | Calls `invoke()` — never touches the adapter directly |
| `invoke.py` | Calls `adapter.run()` via the interface — doesn't know it's Claude |
| `heal_loop.py` | Calls `invoke()` — same |
| `executor.py` | Runs Playwright/Jest subprocesses — no AI involved at all |
| `diff_guard.py` | Pure Python file-diff check — no AI |
| `manifest.py` | JSON checkpoint bookkeeping — no AI |
| `gates/qa_gate.py` | Pure Python decision logic — no AI |
| `traceability.py` | Pure Python traceability index — no AI |
| `browser_crawler.py` | Playwright DOM crawler — no AI |
| `validate.py` | JSON schema validation — no AI |
| `ledger.py` | Append-only audit log — records whatever the adapter returns |
| `util.py` | Shared helpers, config loading, `project_context_block()` |

Also portable, untouched:
- `config/project.json` — all project-specific, zero provider references
- `config/pipeline.json` — the `adapter` field is the only provider reference (change `"claude"` to `"factory"`)
- `schemas/*.json` — define the envelope and role-specific JSON shapes the AI must produce (provider-independent)
- `roles/*.md` — system-prompt instructions for each AI role (**zero Claude-specific references** — verified via grep)

### What's below the seam (provider-specific — changes per provider)

Only **two things** are provider-specific:

| What | File | What it does | Port action |
|---|---|---|---|
| **The adapter itself** | `adapters/claude_adapter.py` | Translates `(role, prompt, cwd, timeout)` into a `claude -p ...` subprocess call | Write a new adapter file (e.g. `factory_adapter.py`) that does the equivalent for the new provider's CLI |
| **The adapter name in config** | `config/pipeline.json` → `"adapter"` field | Currently `"claude"` — tells `invoke.py` which adapter to load | Change to `"factory"` (or whatever the new adapter is named) |

### Two coupling points worth knowing about

While the adapter seam is clean, two things in `invoke.py` are currently shaped around the
Claude CLI's specific output format. They still work for any provider that emits JSON on
stdout, but a provider with a very different output shape may need adjustment:

**1. `_parse_envelope()` — the two-level JSON unwrap**

Currently expects Claude's CLI wrapper format: an outer JSON object with a `"result"` field
containing the model's reply as a string. A different provider that emits the model's reply
directly (not wrapped) would need `_parse_envelope()` adjusted — but the **inner** envelope
shape (`schemas/envelope.schema.json`) stays the same regardless of provider.

```
Claude CLI output:          { "session_id": "...", "result": "{\"schemaVersion\":1,...}" }
                                                       ↑ string, needs unwrapping

A simpler provider might:   { "schemaVersion": 1, "role": "...", ... }
                            ↑ direct JSON, no unwrapping needed
```

**2. `_extract_usage()` — CLI wrapper cost/token fields**

Pulls `total_cost_usd`, `usage.input_tokens`, etc. from Claude's CLI wrapper for the ledger.
A different provider would expose these differently (or not at all). This is best-effort and
returns all-`None` gracefully on any format mismatch — it never blocks a call or causes a
failure, so a new provider works immediately even before its usage extraction is wired up.

### How to port — concrete steps

1. **Write the new adapter** — one file, ~30 lines:

   ```python
   # adapters/factory_adapter.py
   from adapters.base import Adapter, RawResult, run_subprocess_with_timeout
   from util import ROLES_DIR

   class FactoryAdapter(Adapter):
       def run(self, *, role: str, prompt: str, cwd: str, timeout_s: int) -> RawResult:
           role_file = ROLES_DIR / f"{role}.md"
           cmd = [
               "droid", "exec", "--auto", "full",
               "--enabled-tools", "Read,Grep,Glob,Create,Edit",
               "--append-system-prompt-file", str(role_file),
               prompt,
           ]
           return run_subprocess_with_timeout(cmd, cwd=cwd, timeout_s=timeout_s)

   ADAPTERS = {"factory": FactoryAdapter}
   ```

2. **Register it** — add `"factory": FactoryAdapter` to the `ADAPTERS` dict in `get_adapter`,
   or restructure the import in `invoke.py` to a dynamic loader.

3. **Flip the config** — change `config/pipeline.json`:
   ```json
   "adapter": "factory"
   ```

4. **Adjust `_parse_envelope()`** if the new provider's CLI wrapper format differs from
   Claude's (see coupling point 1 above). If the provider emits the role's JSON reply directly,
   this simplifies.

5. **Adjust `_extract_usage()`** if the new provider reports cost/tokens differently. Optional —
   the pipeline works without it; only the ledger's cost columns will be `null`.

6. **Re-run `tests/golden/run_all.py`** against the new adapter — diff results against the
   Claude baseline. Architecture-level behavior (schemas, gate decisions, manifest/resume) will
   be identical. Any gap is prompt/model quality drift, not a control-plane issue.

### What this portability means in practice

| Layer | Porting effort | Example |
|---|---|---|
| **Control plane** (orchestrator, invoke, heal loop, gates, manifests, traceability, diff-guard, executor) | **Zero changes** | These files are the same for Claude, Factory, OpenAI, or any other provider |
| **Role prompts** (`roles/*.md`) | **Zero changes** — no provider references | May need prompt *tuning* for a weaker model, but the files carry over as-is |
| **Schemas** (`schemas/*.json`) | **Zero changes** | The AI's output contract is provider-independent |
| **Config** (`config/project.json`) | **Zero changes** | All project-specific, nothing provider-related |
| **Config** (`config/pipeline.json`) | **One field** — change `"adapter": "claude"` to the new name | Everything else (timeouts, cycle limits, budgets) carries over |
| **Adapter** (`adapters/`) | **One new file** (~30 lines) | Translate `(role, prompt)` into the new provider's CLI call |
| **invoke.py** parsing | **Maybe** adjust `_parse_envelope()` + `_extract_usage()` | Only if the new provider's stdout format differs from Claude's wrapper |

> **See `MIGRATION_TO_FACTORY.md`** for the complete, step-by-step guide to porting this
> specifically to Factory AI, including the role-to-droid translation table and how Factory's
> `--enabled-tools` maps to the role boundaries.

---

## Configuration Files

### `config/project.json` — "where things live and how the app works"

| Field | Purpose |
|---|---|
| `e2e_test_commands` | Shell command(s) to run Playwright tests |
| `e2e_generated_dir` | Where AI-generated `.spec.ts` files are written |
| `e2e_baseline_dir` | Hand-written regression tests — AI never touches these |
| `e2e_results_path` | Where Playwright writes its JSON report |
| `locator_map_path` | Where the locator map is stored |
| `app_root` | Root directory of the app being tested |
| `app_source_dir` | Where the app's real source lives (for `testability_check.py` scanning) |
| `base_url` | Where the running app is served (for the browser crawler) |
| `crawl_pages` | Explicit page list the browser crawler visits (route, requiresAuth, navLinkName) |
| `test_isolation` | `strategy` + details — how AI-written specs get a clean slate (`reset_endpoint` / `self_contained` / `external_seed`) |
| `auth` | `strategy` + details — how specs establish a logged-in session (`form_login` / `storage_state`) |
| `route_source_files` | Impact map: route → source files (for page-scoped prompt filtering and traceability) |
| `traceability_path` | Where the requirement→test→module traceability index lives |
| `component_test_*` | Component-test track (Jest) — `app_root`, `command`, `results_path` |

### `config/pipeline.json` — "how cautious to be"

| Field | Purpose | Wired up? |
|---|---|---|
| `timeouts_seconds.per_call` | Max wait per AI call | **Yes** |
| `timeouts_seconds.per_loop_cycle` / `per_run` | Outer time budgets | No — declared, not enforced |
| `review.qa.max_heal_cycles` | Max heal loop iterations | **Yes** |
| `review.qa.flake_recheck_runs` | Re-runs before declaring flaky | **Yes** |
| `review.qa.on_refactor` / `on_failure` | Policy after REFACTOR/failure | No — declared, not enforced |
| `budget.max_concurrent_invocations` | Max parallel AI calls (semaphore) | **Yes** (dormant — nothing runs concurrent yet) |
| `budget.max_credits_per_task` | Per-task spending cap | No — declared, not enforced |
| `adapter` | AI backend (`"claude"`) | **Yes** |

---

## Phase Invocation Reference

### Phase 1 — `locate`

| | |
|---|---|
| **What it does** | Browser-crawls each page in `crawl_pages`, reads the rendered DOM for interactive elements; AI tags each element's selector reliability tier |
| **Mechanism** | `browser_crawler.py` → `crawl.js` (Node/Playwright subprocess, not AI) → `qa-locator-explorer` (AI) |
| **Skipped if** | App source hasn't changed since last run (hash in `state/locator-map.hash`) |

```bash
python orchestrator.py <task-id> --phase locate
```

**Inputs consumed:**

| File / Source | How used |
|---|---|
| `config/project.json` — `base_url`, `crawl_pages`, `auth` | Tells the crawler what pages to visit and how to log in |
| `dummy-app/src/**/*` | Hashed to decide skip/run (staleness check) |
| `state/locator-map.hash` | Compared against current source hash |

**Outputs written:**

| File | Contents |
|---|---|
| `state/locator-map.json` | Locator map — every interactive element tagged `stable-testid` / `role-fallback` / `flagged-unstable` |
| `state/locator-map.hash` | SHA fingerprint of scanned source files |
| `state/ledger.jsonl` | One line: `role=qa-locator-explorer`, `phase=locate` |

> **Implementation note:** This was originally a source-code scanner (`testability_check.py`);
> it now uses a real browser crawl (`crawl.js`) that reads the rendered DOM directly — giving
> exact route attribution, real accessibility computation, and dynamically-created elements
> without framework-specific parsing. `testability_check.py` is kept as a fallback/reference.

---

### Phase 2 — `plan`

| | |
|---|---|
| **What it does** | Reads changed file(s) + locator map → writes test scenarios |
| **AI Role** | `qa-test-planner` |
| **Prompt filtering** | Locator map is page-scoped: only routes matching the changed files are included (Stage 9 — 53% prompt reduction measured) |

```bash
python orchestrator.py <task-id> --phase plan --changed-files ../dummy-app/server.js

# Multiple changed files:
python orchestrator.py <task-id> --phase plan \
  --changed-files ../dummy-app/server.js \
              ../dummy-app/src/components/Header.tsx
```

**Inputs consumed:**

| File / Source | How used |
|---|---|
| Changed file(s) via `--changed-files` | Full text embedded in prompt (capped at 20,000 chars; **warns on stderr** if truncated — Stage 0 fix) |
| `state/locator-map.json` | Page-scoped via `traceability.resolve_routes_for_files()` using `route_source_files` config |
| `config/project.json` | `project_context_block()` injected — paths, isolation strategy, auth strategy (Stage 6 portability) |

**Outputs written:**

| File | Contents |
|---|---|
| `state/<task-id>/plan.json` | Array of test-case objects: `caseId`, `priority`, `type`, `steps`, `expectedResult`, `selectors` |
| `state/ledger.jsonl` | One line: `role=qa-test-planner`, `phase=plan` |

---

### Phase 3 — `generate`

| | |
|---|---|
| **What it does** | Reads plan.json + locator map → writes real Playwright `.spec.ts` files |
| **AI Role** | `qa-test-generator` |
| **Resumable** | Yes — `generate.manifest.json` tracks done cases; auto-invalidated on `plan.json` change |
| **Prompt filtering** | Locator map scoped to routes matched by each case's selectors; fails open if any case is unmatched (Stage 9) |

```bash
python orchestrator.py <task-id> --phase generate
```

**Inputs consumed:**

| File / Source | How used |
|---|---|
| `state/<task-id>/plan.json` | Cases to generate specs for |
| `state/locator-map.json` | Page-scoped per case via `traceability.derive_routes_for_case()` |
| `state/<task-id>/generate.manifest.json` | Resume checkpoint — done cases skipped |
| `config/project.json` | `project_context_block()` + `route_source_files` for traceability |

**Outputs written:**

| File | Contents |
|---|---|
| `dummy-app/tests/e2e/generated/<case-id>.spec.ts` | One Playwright spec per case |
| `state/<task-id>/generate.json` | Summary: `[{caseId, specPath, status}]` |
| `state/<task-id>/generate.manifest.json` | Checkpoint per caseId under this plan's hash |
| `state/traceability.json` | Traceability entries per case: `caseId → {specPath, routes, modules, source}` (Stage 8) |
| `state/ledger.jsonl` | One line: `role=qa-test-generator`, `phase=generate` |

> **Traceability (Stage 8):** `traceability.record_generate()` runs automatically after
> generation. It derives `case → selectors → crawled route → source files` using
> `route_source_files` config. Entries are tagged `derived` (has modules) or `unmapped`
> (selector not found on any crawled route). A later coverage-instrumented run can promote
> entries to `measured` (ground truth) — measured entries are never regressed by a re-derive.

---

### Phase 4 — `execute`

| | |
|---|---|
| **What it does** | Runs Playwright, parses JSON report — **no AI involved** |
| **AI Role** | None — pure `executor.py` (deterministic) |

```bash
python orchestrator.py <task-id> --phase execute

# Or run Playwright directly:
cd ../dummy-app && npx playwright test
```

**Inputs consumed:**

| File / Source | How used |
|---|---|
| All `.spec.ts` under `dummy-app/tests/e2e/` | Executed by Playwright |
| `config/project.json` — `e2e_test_commands`, `e2e_results_path` | Command and report location |

**Outputs written:**

| File | Contents |
|---|---|
| `dummy-app/test-results/results.json` | Playwright's raw JSON report |
| `state/<task-id>/execute.json` | Parsed: `[{caseId, specPath, result, errorSignature, category, durationMs}]` |

> **No ledger entry** — no AI call is made.

---

### Phase 4b — `heal` loop

| | |
|---|---|
| **What it does** | For each failing case: quarantine flaky → triage → heal → diff-guard → re-run |
| **AI Roles** | `qa-failure-triage` + `qa-test-healer` |
| **Bounded by** | `max_heal_cycles` (config) + no-progress circuit breaker |
| **Invocation** | Not a `--phase`. Run from Python or via `run_pipeline()` |

```bash
cd control-plane
python3 -c "
import heal_loop, json
result = heal_loop.run(
    task_id='<task-id>',
    cwd='/Users/sreekanth.s/Documents/Projects/QAWorkflowClaudeCode',
    plan_input_hash='any-string',
)
print(json.dumps(result, indent=2))
"
```

**Inputs consumed:**

| File / Source | How used |
|---|---|
| `dummy-app/test-results/results.json` | Identifies failing cases |
| `.spec.ts` files (failing only) | Snapshot before heal, edited by healer, diff-checked after |
| `state/<task-id>/heal.manifest.json` | Resume — already-escalated cases skip re-triage |
| `config/project.json` | `project_context_block()` injected into healer prompt (Stage 6 — was missing, caused a real fix) |

**Outputs written:**

| File | Contents |
|---|---|
| Modified `.spec.ts` files | Healer edits selectors/waits — **assertions protected by diff-guard** |
| `state/<task-id>/heal.manifest.json` | Per-case: `escalated` / `fixed` / `reverted`, with `diffSummary` |
| `state/<task-id>/heal.json` | Final summary: `heal_cycle`, `still_failing`, `quarantined`, `escalated`, `no_progress` |
| `state/ledger.jsonl` | One line per triage call + one per heal call |

> **Safety rules enforced in code:**
> - `product-bug` or `unclear` triage → **never reaches the healer**
> - Flaky (flips pass/fail on identical code) → **quarantined before triage**
> - Healer edits any `expect(...)` line → **file reverted unconditionally** by `diff_guard.py`, independent of the AI's self-report

---

### Phase 5 — `review`

| | |
|---|---|
| **What it does** | Reads all artifacts → final verdict: `PASS` / `REFACTOR` / `BLOCKED` + findings |
| **AI Role** | `qa-reviewer` |
| **Prompt filtering** | Locator map is sent **unfiltered** — review is holistic, not per-change |

```bash
python orchestrator.py <task-id> --phase review
```

**Inputs consumed:**

| File / Source | How used |
|---|---|
| `state/<task-id>/plan.json` | What was planned |
| `state/<task-id>/generate.json` | What was generated/skipped |
| `state/<task-id>/heal.json` | Heal history |
| `state/locator-map.json` | Full map — so reviewer can flag `role-fallback`/`flagged-unstable` reliance |

**Outputs written:**

| File | Contents |
|---|---|
| `state/<task-id>/review.json` | `{verdict, findings}` |
| `state/ledger.jsonl` | One line: `role=qa-reviewer`, `phase=review`, `verdict=<value>` |

---

### Phase 6 — `gate` (automatic, no `--phase`)

Called internally by `run_pipeline()` after review. Tests directly in Python:

```python
from gates.qa_gate import decide

# Normal case — AI verdict passes through:
decide(heal_cycle=1, max_heal_cycles=2, no_progress=False,
       review_envelope={"verdict": "PASS", "status": "completed"})
# → "PASS"

# Gate overrides AI — cycle limit hit:
decide(heal_cycle=2, max_heal_cycles=2, no_progress=False,
       review_envelope={"verdict": "PASS", "status": "completed"})
# → "BLOCKED" (regardless of what the AI said)
```

**No files read or written. No ledger entry.**

---

### Full Pipeline

```bash
cd control-plane
python orchestrator.py <task-id> --changed-files ../dummy-app/server.js
# Exit code 0 = PASS or REFACTOR
# Exit code 1 = BLOCKED
```

---

### Component-Test Track (Jest — Stage 3)

A separate execution path for Jest/RTL component tests, proven against Finbook's
`Accordion.tsx` (5/6 generated tests passed on first try, zero role-file changes):

```python
import executor
# Run Jest (component tests):
executor.run_jest(spec_paths=["src/components/Accordion/Accordion.test.tsx"])
entries = executor.parse_jest_results()

# With coverage (for measured traceability):
executor.run_jest(spec_paths=["..."], with_coverage=True)
touched_files = executor.parse_jest_coverage()

import traceability
traceability.record_measured("src/components/Accordion/Accordion.test.tsx", touched_files)
```

> **Not yet wired into `orchestrator.py`** as a `--phase` — currently invoked via direct Python
> calls. A real integration needs either a `--mode component` flag or a second config profile.

---

## Complete Input → Output Map

| Phase | `--phase` | Key Inputs | Key Outputs |
|---|---|---|---|
| locate | `locate` | app source (hash), `crawl_pages` config | `locator-map.json`, `.hash` |
| plan | `plan --changed-files ...` | changed files, locator map (page-scoped), project context | `plan.json` |
| generate | `generate` | `plan.json`, locator map (page-scoped), `generate.manifest.json` | `*.spec.ts`, `generate.json`, `generate.manifest.json`, `traceability.json` |
| execute | `execute` | `*.spec.ts` files | `results.json`, `execute.json` |
| heal | *(Python only)* | `results.json`, spec files, `heal.manifest.json` | modified `.spec.ts`, `heal.manifest.json`, `heal.json` |
| review | `review` | `plan.json`, `generate.json`, `heal.json`, `locator-map.json` (full) | `review.json` |
| gate | *(automatic)* | heal result + review envelope (in memory) | *(verdict string only)* |

---

## Verifying `state/ledger.jsonl`

The ledger is an append-only audit trail — one JSONL line per AI invocation. It is **never used
for runtime decisions** (manifests are) — it's for debugging and calibrating limits.

### Ledger fields (post-Stage 4)

| Field | Source | Notes |
|---|---|---|
| `ts` | `datetime.utcnow()` | ISO timestamp |
| `task_id`, `role`, `phase`, `attempt` | Call args | Identity of this invocation |
| `duration_s` | `time.monotonic()` | Wall-clock time |
| `exit_code` | subprocess | `124` = timeout |
| `status` | Logic | `completed` / `failed` / `repair_attempted` / `blocked` |
| `verdict` | AI (reviewer only) | `PASS` / `REFACTOR` / `BLOCKED` |
| `prompt_chars` | `len(prompt)` | **Deterministic** — tokenizer-independent prompt size measure |
| `cost_usd` | CLI wrapper `total_cost_usd` | **Real** — from `claude` CLI, not the AI's self-report |
| `input_tokens`, `output_tokens` | CLI wrapper `usage.*` | Real token counts |
| `cache_read_input_tokens`, `cache_creation_input_tokens` | CLI wrapper | Prompt caching breakdown |
| `num_turns` | CLI wrapper | How many tool-use steps the AI took |
| `tokens` | AI's `metrics.tokens` | **Unreliable** — kept for backward compat; often `null` |

> **Stage 4 fix:** Pre-Stage-4 entries lack the `cost_usd`/`*_tokens`/`num_turns`/`prompt_chars`
> fields. Left as-is (genuine historical data). All new entries have them automatically.

---

### Step 1 — Summarised view

```bash
cat state/ledger.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if line:
        d = json.loads(line)
        cost = f'\${d[\"cost_usd\"]:.4f}' if d.get('cost_usd') else '   n/a  '
        print(f\"{d['ts'][:19]}  {d['phase']:<10} {d['role']:<25} {d['status']:<18} {cost}  task={d['task_id']}\")
"
```

---

### Step 2 — Find failures and repair attempts

```bash
grep -E '"status": "(failed|blocked|repair_attempted)"' state/ledger.jsonl | \
  python3 -c "import sys,json; [print(json.dumps(json.loads(l), indent=2)) for l in sys.stdin]"
```

| `status` | Meaning |
|---|---|
| `completed` | Valid JSON, passed schema validation |
| `repair_attempted` | Bad JSON → self-repair triggered (one attempt only) |
| `failed` | Still bad after repair |
| `blocked` | Timed out (`exit_code: 124`) |

---

### Step 3 — Cost per task

```bash
cat state/ledger.jsonl | python3 -c "
import sys, json
from collections import defaultdict
totals = defaultdict(float)
for line in sys.stdin:
    line = line.strip()
    if line:
        d = json.loads(line)
        totals[d['task_id']] += d.get('cost_usd') or 0.0
for task, cost in sorted(totals.items()):
    print(f'\${cost:.4f}  {task}')
"
```

---

### Step 4 — All phases of a specific task

```bash
TASK_ID="us002-full"
grep "\"task_id\": \"$TASK_ID\"" state/ledger.jsonl | \
  python3 -c "
import sys, json
for l in sys.stdin:
    d = json.loads(l.strip())
    cost = f'\${d[\"cost_usd\"]:.4f}' if d.get('cost_usd') else 'n/a'
    print(f\"{d['phase']:<12} {d['role']:<25} {d['status']:<18} {cost}\")
"
```

---

### Step 5 — Watch live

```bash
tail -f state/ledger.jsonl
```

---

### Step 6 — Detect timeouts

```bash
grep '"exit_code": 124' state/ledger.jsonl
```

Fix: reduce prompt size (`--changed-files` fewer/smaller files) or raise
`timeouts_seconds.per_call` in `config/pipeline.json`.

---

### Step 7 — Repair attempt frequency (JSON quality signal)

```bash
grep '"status": "repair_attempted"' state/ledger.jsonl | wc -l
```

High count → a role's prompt/schema contract is ambiguous. Check the corresponding
`roles/<role-name>.md` for under-specified enums (the AI invents values not in the schema).

---

### Step 8 — Prompt size trend (calibration data)

```bash
cat state/ledger.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if line:
        d = json.loads(line)
        pc = d.get('prompt_chars')
        if pc:
            print(f\"{d['phase']:<10} {d['role']:<25} {pc:>8} chars  task={d['task_id']}\")
"
```

---

## Traceability — `state/traceability.json`

```bash
# View the full traceability report:
cd control-plane && python3 traceability.py
```

Output answers three questions:
- **`neverGenerated`** — cases the generator skipped (e.g. `CART-*`: dead code in the app)
- **`unmappedButGenerated`** — cases with specs but no traceable module (crawler gap)
- **`uncoveredModules`** — source files with zero test cases referencing them

---

## Reading a `BLOCKED` Result

| `"reason"` in output | Where to look |
|---|---|
| `"planning failed"` | Ledger: `phase=plan`, `status=failed` |
| `"generation failed"` | Ledger: `phase=generate`; look for `repair_attempted` preceding it |
| `"heal loop exhausted or no-progress"` | `state/<task-id>/heal.json` → `still_failing`, `escalated`, `no_progress` |
| `InvocationBlocked: ... timed out` | `exit_code: 124` in ledger — timeout |
| `InvocationBlocked: ... schema-invalid` | Bad JSON shape after repair — check `roles/<role>.md` for missing enum values |
| `InvocationBlocked: ... no 'result' field` | The `claude` CLI itself failed — check stderr, network, API key |

```bash
# Full structured BLOCKED output:
python orchestrator.py <task-id> --changed-files ../dummy-app/server.js 2>&1 | python3 -m json.tool
```
