"""Append-only invocation ledger. One line per invocation, both tracks, from day one.

docs/control-flow-guardrails.md §3.3 step 0: instrument BEFORE calibrating any cap. This
file is what "calibrate max_heal_cycles from observed data" actually reads from.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from util import STATE_DIR, now_iso

LEDGER_PATH = STATE_DIR / "ledger.jsonl"


def record(
    *,
    task_id: str,
    role: str,
    phase: str,
    attempt: int,
    duration_s: float,
    exit_code: int,
    status: str,
    verdict: str | None = None,
    tokens: int | None = None,
    prompt_chars: int | None = None,
    cost_usd: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_input_tokens: int | None = None,
    cache_creation_input_tokens: int | None = None,
    num_turns: int | None = None,
) -> None:
    """`tokens` is the AI's own self-reported figure from its envelope's `metrics.tokens` —
    kept for backward compatibility, but IMPLEMENTATION_STRATEGY.md §8 flags it as unreliable
    (the AI grading its own resource use). `cost_usd`/`input_tokens`/`output_tokens`/
    `cache_read_input_tokens`/`cache_creation_input_tokens`/`num_turns` come from the `claude`
    CLI's own wrapper (`total_cost_usd`/`usage`/`num_turns` — verified against a real live call,
    not assumed), independent of anything the model claims about itself. `prompt_chars` is
    deterministic and always available — the direct, tokenizer-independent measure of what any
    future prompt-filtering work actually changes."""
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    line: dict[str, Any] = {
        "ts": now_iso(),
        "task_id": task_id,
        "role": role,
        "phase": phase,
        "attempt": attempt,
        "duration_s": duration_s,
        "exit_code": exit_code,
        "status": status,
        "verdict": verdict,
        "tokens": tokens,
        "prompt_chars": prompt_chars,
        "cost_usd": cost_usd,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_read_input_tokens,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "num_turns": num_turns,
    }
    with LEDGER_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, sort_keys=True) + "\n")
