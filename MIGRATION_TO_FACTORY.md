# Migration guide — porting this back to Factory

**Precondition:** all six `tests/golden/` scenarios pass against the Claude adapter, and
`state/ledger.jsonl` shows a real distribution of durations/heal-cycle counts — don't start
this migration to calibrate Factory's limits from a guess (see `TODO.md` #11).

This assumes the reader has `finbook-web-application/.factory/docs/control-flow-guardrails.md`
open — every step below cites the finding/step ID it implements from that analysis.

## Step 1 — confirm what does *not* change

`config/`, `schemas/`, and everything in `control-plane/` **except**
`adapters/claude_adapter.py` carries over unchanged. That's the entire point of keeping them
vendor-neutral: `invoke.py`, `manifest.py`, `executor.py`, `heal_loop.py`, `gates/qa_gate.py`,
and `orchestrator.py` don't know or care which agent runtime is behind them.

## Step 2 — write the Factory adapter

New file: `control-plane/adapters/factory_adapter.py`, implementing `adapters/base.py`'s
`Adapter` interface. Model its invocation shape on the one already working in
`.factory/scripts/prepush_qa_droids.sh` (the framework's one correctly-bounded loop):

```
droid exec --auto "$AUTO" --model "$MODEL" --reasoning-effort "$EFFORT" --cwd "$ROOT" \
  --enabled-tools "Read,Grep,Glob,Create,Edit" \
  --append-system-prompt-file ".factory/droids/<role>.md" \
  --tag '{"name":"...","stage":"...","cycle":"..."}' \
  "<prompt>"
```

The `--enabled-tools` value must come from each droid's own `tools:` frontmatter (see the
table in Step 3), not be hardcoded per adapter call.

## Step 3 — translate each role into a Factory droid

| This project | Factory target | Notes |
|---|---|---|
| `roles/qa-test-planner.md` | `.factory/droids/qa-test-planner.md` (exists) | Update its output contract from the current prose `QA_PLAN=` block to the JSON envelope + `plan.schema.json` shape built here. |
| `roles/qa-test-generator.md` | `.factory/droids/qa-test-generator.md` (exists) | Same JSON-envelope update; add the "compose from `locator-map.json`, don't freehand" rule (`G3`/`§3.6`) — not present in the current droid. |
| `roles/qa-test-healer.md` | `.factory/droids/qa-test-healer.md` (exists, `tools: ["Read","Grep","Glob","Create","Edit"]`) | Add the explicit assertion-line boundary and per-`caseId` single-invocation contract (`QP7`, `§3.3b`) — the current droid doesn't separate actor from judge this way. |
| `roles/qa-reviewer.md` | `.factory/droids/qa-reviewer.md` (exists, `tools: read-only`) | Add the `confidenceTier` P2-flagging rule for fallback-locator cases (`§3.6`). |
| `roles/qa-locator-explorer.md` | `.factory/droids/flow-inventory.md` (exists) | This **supersedes** `flow-inventory`'s output format per `LP2` — keep its crawl/ranking logic, change its output from a human-readable markdown report to `locator-map.schema.json`, and make it callable automatically (delta mode) rather than "run once, by hand" only. |
| `roles/qa-failure-triage.md` | new droid, or a narrowed `qa-test-executor.md` | Per `XP1`/`XP2`: the *mechanical* parts of the current `qa-test-executor.md` (`tools: ["Read","Grep","Glob","Execute"]`, `reasoningEffort: low`) become `control-plane/executor.py` — no LLM, no `Execute` grant. Only the test-defect-vs-product-bug judgment survives as an LLM call, and it should run at a higher reasoning effort than the current droid's `low`, since it's now the only thing that role does. |

For each, translate this project's plain-English "Boundaries" section into the droid's
`tools:`/`--enabled-tools` frontmatter — the enforcement mechanism differs (Claude Code's
permission model vs. Factory's `--enabled-tools` flag) but the intent transfers directly.

## Step 4 — point Factory's own call sites at this control plane

Don't leave Factory's existing prose-driven sequencing in place next to a working
`orchestrator.py`/`heal_loop.py` — that's exactly the "two implementations that can drift"
problem the source analysis flagged (`QP1`). Concretely:

- Replace `prepush_qa_droids.sh`'s inline `droid exec` calls and bash `while` loop with calls
  into `heal_loop.py` (using `factory_adapter` instead of `claude_adapter`).
- Have the stage-3.5 QA path call `orchestrator.py` instead of the orchestrator LLM improvising
  sequencing from prose in `orchestrator-system.md`/`SKILL.md`.

Doing this makes `QP1`–`QP10` and `XP1`–`XP4` land as a side effect of the migration, not a
separate follow-up task.

## Step 5 — map config

`config/pipeline.json`'s `review.qa.max_heal_cycles` and `timeouts_seconds` merge into
`.factory/config/pipeline.json`'s **existing** (currently dead — findings `F2`/`F3`) keys of
the same name. This is reconnection, not new config.

## Step 6 — re-run the golden-task suite against the Factory adapter

Diff results against the recorded Claude run. Expect the architecture-level behavior (schemas,
gate decisions, manifest/resume logic) to be identical, since none of that code changes between
adapters. A behavior gap here is prompt/model-quality drift — Factory's droids run on
`deepseek-v4-flash-0731` per their current frontmatter, which may reason differently than
Claude on the same prompt — so re-tune the specific role prompt that shows a gap, not the
control plane.

## Step 7 — decommission the old prose-driven loop paths

Once Steps 4 and 6 are verified, remove the prompt-embedded retry/heal instructions this
migration supersedes in `.factory/context/orchestrator-system.md` and
`.factory/skills/task-development/SKILL.md` (the same instructions flagged as findings `Q1`
and `D6`), and update `control-flow-guardrails.md`'s status line from "proposed" to
"implemented (ported from Claude POC on \<date\>)".

## Rollback, at every step

`review.qa.enabled: false` in `.factory/config/pipeline.json` remains the kill switch
(finding `V5`) throughout this migration, exactly as it did before — no step here should ever
require it to be unavailable.
