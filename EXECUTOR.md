# Phase Invocation & Ledger Verification Reference

This document is the operator's quick-reference for running individual pipeline phases,
understanding what files each phase reads and writes, and verifying the audit trail in
`state/ledger.jsonl`. For the full architectural explanation of how the phases work, see
`HOW_IT_WORKS.md`. For config knobs (timeouts, cycle limits), see `config/pipeline.json`.

---

## Prerequisites

```bash
# Terminal 1 — dummy app must be running before execute/heal phases
cd dummy-app && npm run start

# Terminal 2 — all phase commands run from here
cd control-plane
```

---

## Phase Invocation Reference

### Phase 1 — `locate`

| | |
|---|---|
| **What it does** | Scans app HTML/JS for interactive elements; AI tags each element's selector reliability |
| **AI Role** | `qa-locator-explorer` |
| **Skipped if** | App source hasn't changed since last run (hash stored in `state/locator-map.hash`) |

```bash
python orchestrator.py <task-id> --phase locate
```

**Inputs consumed:**

| File / Source | How used |
|---|---|
| `dummy-app/public/*.html`, `dummy-app/**/*.js` | Scanned by `testability_check.py` to build the fact list sent to the AI |
| `state/locator-map.hash` | Compared against current source hash to decide whether to skip |

**Outputs written:**

| File | Contents |
|---|---|
| `state/locator-map.json` | Locator map — every interactive element tagged `stable-testid` / `role-fallback` / `flagged-unstable` |
| `state/locator-map.hash` | SHA fingerprint of the scanned source files (used for the skip check next run) |
| `state/ledger.jsonl` | One appended line: `role=qa-locator-explorer`, `phase=locate` |

---

### Phase 2 — `plan`

| | |
|---|---|
| **What it does** | Reads changed file(s) + locator map → writes a list of test scenarios |
| **AI Role** | `qa-test-planner` |

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
| Changed file(s) passed via `--changed-files` | Full text embedded directly in the prompt |
| `state/locator-map.json` | Embedded in the prompt so the planner knows which selectors are reliable |

**Outputs written:**

| File | Contents |
|---|---|
| `state/<task-id>/plan.json` | Array of test-case objects — `caseId`, `priority`, `steps`, `expectedResult`, selector requirements |
| `state/ledger.jsonl` | One appended line: `role=qa-test-planner`, `phase=plan` |

---

### Phase 3 — `generate`

| | |
|---|---|
| **What it does** | Reads plan.json + locator map → writes real Playwright `.spec.ts` files |
| **AI Role** | `qa-test-generator` |
| **Resumable** | Yes — if the process crashed mid-run, re-running the same phase skips cases already in `generate.manifest.json` |

```bash
python orchestrator.py <task-id> --phase generate
```

**Inputs consumed:**

| File / Source | How used |
|---|---|
| `state/<task-id>/plan.json` | The list of cases to generate specs for |
| `state/locator-map.json` | Embedded so the generator uses the correct, validated selectors |
| `state/<task-id>/generate.manifest.json` | Resume checkpoint — cases recorded here are skipped (stale if `plan.json` changed) |

**Outputs written:**

| File | Contents |
|---|---|
| `dummy-app/tests/e2e/generated/<case-id>.spec.ts` | One Playwright spec file per test case |
| `state/<task-id>/generate.json` | Summary: `[{caseId, specPath, status}]` — what was written or skipped |
| `state/<task-id>/generate.manifest.json` | Checkpoint: which `caseId`s are done under this `plan.json` hash |
| `state/ledger.jsonl` | One appended line: `role=qa-test-generator`, `phase=generate` |

> **Note:** If you change `plan.json` between runs, `generate.manifest.json` is automatically
> invalidated (input-hash mismatch) and generation restarts from scratch.

---

### Phase 4 — `execute`

| | |
|---|---|
| **What it does** | Runs Playwright, parses the JSON report — **no AI involved** |
| **AI Role** | None — pure `executor.py` (deterministic) |

```bash
python orchestrator.py <task-id> --phase execute

# Or run Playwright directly (writes test-results/results.json):
cd ../dummy-app && npx playwright test
```

**Inputs consumed:**

| File / Source | How used |
|---|---|
| All `.spec.ts` files under `dummy-app/tests/e2e/` | Executed by Playwright |
| `config/project.json` — `e2e_test_commands` | The exact shell command used to run tests |
| `config/project.json` — `e2e_results_path` | Where Playwright writes its JSON report |

**Outputs written:**

| File | Contents |
|---|---|
| `dummy-app/test-results/results.json` | Playwright's raw JSON reporter output |
| `state/<task-id>/execute.json` | Parsed: `[{caseId, specPath, result, errorSignature, category, durationMs}]` |

> **No ledger entry** — no AI call is made in this phase.

---

### Phase 4b — `heal` loop

| | |
|---|---|
| **What it does** | For each failing case: quarantine flaky → triage → heal → diff-guard → re-run. Bounded by `max_heal_cycles` in `config/pipeline.json` |
| **AI Roles** | `qa-failure-triage` + `qa-test-healer` |
| **Invocation** | Not available as `--phase`. Run directly from Python (see below) or via `run_pipeline()` |

```bash
# Run the heal loop standalone from Python:
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
| `dummy-app/test-results/results.json` | Identifies which cases are failing |
| `.spec.ts` files (failing cases only) | Read before heal (snapshot), edited in-place by healer, diff-checked after |
| `state/<task-id>/heal.manifest.json` | Resume — cases already escalated in a prior crashed run are not re-triaged |

**Outputs written:**

| File | Contents |
|---|---|
| Modified `.spec.ts` files | Healer may update selectors/waits — **assertions are protected by diff-guard and auto-reverted if touched** |
| `state/<task-id>/heal.manifest.json` | Per-case decisions: `escalated` / `fixed` / `reverted`, with `diffSummary` |
| `state/<task-id>/heal.json` | Final loop summary: `heal_cycle`, `still_failing`, `quarantined`, `escalated`, `no_progress` |
| `state/ledger.jsonl` | One line per triage call + one line per heal call |

> **Safety rules enforced in code (not just in the prompt):**
> - A case classified as `product-bug` or `unclear` by triage **never reaches the healer**.
> - A case that flips pass/fail on identical code (flaky) is **quarantined before triage**.
> - If the healer edits any `expect(...)` assertion line, the file is **reverted unconditionally** — `diff_guard.py` does this independently of the AI's own `touchedAssertionLine` self-report.

---

### Phase 5 — `review`

| | |
|---|---|
| **What it does** | Reads all prior artifacts → gives a final verdict: `PASS` / `REFACTOR` / `BLOCKED`, plus findings |
| **AI Role** | `qa-reviewer` |

```bash
python orchestrator.py <task-id> --phase review
```

**Inputs consumed:**

| File / Source | How used |
|---|---|
| `state/<task-id>/plan.json` | What was planned |
| `state/<task-id>/generate.json` | What was generated (including any skipped cases) |
| `state/<task-id>/heal.json` | Heal loop history — escalations, quarantines, still-failing cases |
| `state/locator-map.json` | So the reviewer can flag cases relying on `flagged-unstable` or `role-fallback` selectors |

**Outputs written:**

| File | Contents |
|---|---|
| `state/<task-id>/review.json` | `{verdict: "PASS"|"REFACTOR"|"BLOCKED", findings: [...]}` |
| `state/ledger.jsonl` | One appended line: `role=qa-reviewer`, `phase=review`, `verdict=<value>` |

---

### Phase 6 — `gate` (automatic, no `--phase` option)

Called internally by `run_pipeline()` immediately after review. Not independently invokable
via the CLI, but can be tested directly in Python:

```python
from gates.qa_gate import decide

verdict = decide(
    heal_cycle=1,
    max_heal_cycles=2,
    no_progress=False,
    review_envelope={"verdict": "PASS", "status": "completed"},
)
print(verdict)  # → "PASS"

# Force BLOCKED regardless of reviewer verdict:
verdict = decide(heal_cycle=2, max_heal_cycles=2, no_progress=False,
                 review_envelope={"verdict": "PASS", "status": "completed"})
print(verdict)  # → "BLOCKED" (heal_cycle >= max_heal_cycles)
```

**No files read or written. No ledger entry.**

---

### Full Pipeline (all phases in sequence)

```bash
cd control-plane
python orchestrator.py <task-id> --changed-files ../dummy-app/server.js
# Exit code 0 = PASS or REFACTOR
# Exit code 1 = BLOCKED
```

---

## Complete Input → Output Map

| Phase | `--phase` flag | Key Inputs | Key Outputs |
|---|---|---|---|
| locate | `--phase locate` | app HTML/JS source | `state/locator-map.json`, `locator-map.hash` |
| plan | `--phase plan --changed-files ...` | changed files, `locator-map.json` | `state/<id>/plan.json` |
| generate | `--phase generate` | `plan.json`, `locator-map.json`, `generate.manifest.json` | `tests/e2e/generated/*.spec.ts`, `generate.json`, `generate.manifest.json` |
| execute | `--phase execute` | `*.spec.ts` files | `test-results/results.json`, `execute.json` |
| heal | *(Python only)* | `results.json`, spec files, `heal.manifest.json` | modified `.spec.ts`, `heal.manifest.json`, `heal.json` |
| review | `--phase review` | `plan.json`, `generate.json`, `heal.json`, `locator-map.json` | `review.json` |
| gate | *(automatic)* | heal result + review envelope (in memory) | *(none — returns final verdict string)* |

---

## Verifying `state/ledger.jsonl`

The ledger is an append-only audit trail — one line per AI invocation. It is **never used to
make runtime decisions** (only `manifest.json` files are used for that), but it is the primary
source of truth for debugging failures and calibrating config limits.

### Step 1 — Summarised view of all entries

```bash
cd /Users/sreekanth.s/Documents/Projects/QAWorkflowClaudeCode

cat state/ledger.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if line:
        d = json.loads(line)
        print(f\"{d['ts'][:19]}  {d['phase']:<10} {d['role']:<25} {d['status']:<18} task={d['task_id']}\")
"
```

Expected output shape:
```
2026-09-08T01:51:30  locate     qa-locator-explorer       completed          task=_locator
2026-09-08T01:52:40  plan       qa-test-planner           failed             task=stage1-quality
2026-09-08T01:54:10  plan       qa-test-planner           completed          task=stage1-quality
```

---

### Step 2 — Find all failures and repair attempts

```bash
grep -E '"status": "(failed|blocked|repair_attempted)"' state/ledger.jsonl | \
  python3 -c "import sys,json; [print(json.dumps(json.loads(l), indent=2)) for l in sys.stdin]"
```

**What each status means:**

| `status` | Meaning |
|---|---|
| `completed` | AI replied with valid JSON that passed schema validation |
| `repair_attempted` | First call produced malformed JSON; a self-repair call was triggered |
| `failed` | JSON parsing or schema validation still failed after the one repair attempt |
| `blocked` | Call timed out (`exit_code: 124`) |

---

### Step 3 — Check cost per task

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

### Step 4 — Verify all phases of a specific task ran

```bash
TASK_ID="us002-full"
grep "\"task_id\": \"$TASK_ID\"" state/ledger.jsonl | \
  python3 -c "
import sys, json
for l in sys.stdin:
    d = json.loads(l.strip())
    print(f\"{d['phase']:<12} {d['role']:<25} {d['status']}\")
"
```

---

### Step 5 — Watch live during a run

```bash
tail -f state/ledger.jsonl
```

---

### Step 6 — Detect timeouts (`exit_code: 124`)

```bash
grep '"exit_code": 124' state/ledger.jsonl
```

A `124` exit code means `timeouts_seconds.per_call` (default 900s) was hit. Fix options:
- Reduce the prompt size (trim `--changed-files` to fewer / smaller files).
- Raise `timeouts_seconds.per_call` in `config/pipeline.json`.

---

### Step 7 — Count repair attempts (JSON quality signal)

```bash
grep '"status": "repair_attempted"' state/ledger.jsonl | wc -l
```

A high count means a role is frequently generating malformed JSON. Check the corresponding
`roles/<role-name>.md` file — the most common cause is an enum field where not all allowed
values are spelled out explicitly (the AI invents plausible-sounding but invalid values).

---

### Reading a `BLOCKED` result

When `orchestrator.py` exits with code `1`, its JSON output names the reason:

| `"reason"` in JSON output | Where to investigate |
|---|---|
| `"planning failed"` | `state/ledger.jsonl` — find `phase=plan`, `status=failed`; check `errorSignature` |
| `"generation failed"` | Same — find `phase=generate`; look for preceding `repair_attempted` |
| `"heal loop exhausted or no-progress"` | `state/<task-id>/heal.json` → `still_failing`, `escalated`, `no_progress` |
| `InvocationBlocked` message text | A specific role timed out or produced schema-invalid output — `exit_code: 124` = timeout |

```bash
# Full structured output of the last run's BLOCKED reason:
python orchestrator.py <task-id> --changed-files ../dummy-app/server.js 2>&1 | python3 -m json.tool
```
