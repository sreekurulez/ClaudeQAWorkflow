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
) -> None:
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
    }
    with LEDGER_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, sort_keys=True) + "\n")
