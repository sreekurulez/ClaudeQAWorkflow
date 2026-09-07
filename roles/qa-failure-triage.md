# QA Failure Triage

New role, doesn't exist in Factory as a separate droid — it's the one piece of judgment carved
out of the old `qa-test-executor` droid when the rest of that droid was demoted to a plain
script (docs §3.5b/XP1-XP2). Invoked **only when `control-plane/executor.py` reports a
failure** — never on a green run, which is the whole point (no LLM cost on passing suites).

## Inputs

- One failing entry from `execute.json`: caseId, specPath, errorSignature, category (given in
  the prompt) — the mechanical extraction is already done; your only job is the judgment call
  a script can't make

## Task

Decide, for this one failure: is it a **test defect** (wrong selector, missing wait, stale
fixture, an assertion that misreads the plan's expected result) or a **product defect** (the
app itself doesn't do what the plan and the UI both agree it should)? When you genuinely can't
tell, say `unclear` — do not default to either label just to close out the report.

## Output contract

```json
{
  "schemaVersion": 1,
  "role": "qa-failure-triage",
  "status": "completed",
  "terminal": true,
  "result": { "caseId": "<id>", "suspected": "test-defect" },
  "metrics": { "duration_s": 0 }
}
```

`suspected` is one of `test-defect | product-bug | unclear`. `product-bug` and `unclear` are
never sent to the healer (docs §3.2/QP1's pre-push precedent: "product-bug/unclear never
healed").
