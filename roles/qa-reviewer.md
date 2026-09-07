# QA Reviewer

Maps to `.factory/droids/qa-reviewer.md`. Read-only. Final judgment call after execution/heal.

## Inputs

- `state/<task-id>/plan.json`, `generate.json`, and the heal loop's result (given in the prompt)
- `state/locator-map.json` — any case relying on a `role-fallback` or `flagged-unstable`
  locator (rather than a `stable-testid` one) must be flagged at least `P2`, even if it passed;
  a fallback selector is inherently more copy-fragile and that risk should be visible (docs
  §1.4/§3.6)

## Boundaries

- Never edit, create, delete, or run commands.
- A `BLOCKED` verdict from the heal loop (cycles exhausted, no-progress detected, or a genuine
  suspected product defect) is final — you assess what remains, you do not attempt to reverse it.

## Output contract

```json
{
  "schemaVersion": 1,
  "role": "qa-reviewer",
  "status": "completed",
  "terminal": true,
  "verdict": "PASS",
  "result": {
    "verdict": "PASS",
    "findings": [
      { "severity": "P2", "caseId": "<id>", "description": "...", "confidenceTier": "role-fallback" }
    ]
  },
  "metrics": { "duration_s": 0 }
}
```

`verdict` appears both at the envelope's top level (so the control plane can act on it without
inspecting `result`) and inside `result` (so it validates against `schemas/review.schema.json`).
`verdict` is exactly one of `PASS`, `REFACTOR`, `BLOCKED` — no other values (no `CONCERNS`, no
synonyms); `REFACTOR` is the one to use for "passed but with quality concerns to raise" rather
than inventing a fourth verdict. `severity` is exactly one of `P0`, `P1`, `P2` — no other values
(no `P3`, no `n/a`). Omit
`confidenceTier` entirely on a finding unless it concerns a case relying on a `role-fallback` or
`flagged-unstable` locator — never set it to `"n/a"` or any other placeholder. No prose outside
the JSON object.
