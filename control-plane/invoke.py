"""The bounded-invocation primitive. docs/control-flow-guardrails.md §3.0.

Every agent call in this project goes through invoke(), never a raw adapter call. This is
what reconnects the dead config the Factory analysis found (timeouts_seconds.subagent,
timeouts_seconds.unattended_run) from day one instead of retrofitting it.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

import ledger
from adapters.claude_adapter import get_adapter
from util import load_pipeline_config
from validate import SchemaValidationError, validate

# Role -> the schema its envelope's "result" field must satisfy.
ROLE_RESULT_SCHEMA = {
    "qa-test-planner": "plan.schema.json",
    "qa-test-generator": "generate.schema.json",
    "qa-test-healer": "heal.schema.json",
    "qa-reviewer": "review.schema.json",
    "qa-locator-explorer": "locator-map.schema.json",
    "qa-failure-triage": None,  # small ad-hoc payload, envelope-level fields suffice
}


class InvocationBlocked(Exception):
    """Raised when the invocation could not produce a usable result at all (timeout or
    schema-invalid after JSON_REPAIR_ATTEMPTS). Callers must treat this as BLOCKED, never retry
    silently (docs §2 downside: 'fix your JSON' must not become its own retry loop)."""

    def __init__(self, reason: str, envelope: dict[str, Any] | None = None):
        self.reason = reason
        self.envelope = envelope
        super().__init__(reason)


JSON_REPAIR_ATTEMPTS = 1  # exactly one self-repair attempt on invalid JSON, then fail (docs §2)

# config/pipeline.json's budget.max_concurrent_invocations, made real (docs §3.0's "reconnect
# dead config" applies here too — this was declared with no code behind it, same class of gap
# the Factory source analysis flagged for timeouts_seconds). Nothing in this codebase calls
# invoke() concurrently today (orchestrator.py and heal_loop.py are both sequential), so this
# guardrail is dormant until something does — that's the point: enforced from day one rather
# than added reactively the first time someone parallelizes a call site and forgets the cap.
# Sized lazily from config on first use and cached: the number of concurrent `claude` processes
# this control plane will ever run is a process-wide property, not something that should change
# mid-run just because a later invoke() call re-reads a since-edited config file.
_invocation_semaphore: threading.BoundedSemaphore | None = None
_invocation_semaphore_lock = threading.Lock()


def _get_invocation_semaphore(max_concurrent: int) -> threading.BoundedSemaphore:
    global _invocation_semaphore
    if _invocation_semaphore is None:
        with _invocation_semaphore_lock:
            if _invocation_semaphore is None:
                _invocation_semaphore = threading.BoundedSemaphore(max_concurrent)
    return _invocation_semaphore


def _run_adapter_bounded(adapter, *, role: str, prompt: str, cwd: str, timeout_s: int, max_concurrent: int):
    """Every actual `claude` subprocess launch goes through here — the semaphore gates the
    concurrent-process count specifically, not the bookkeeping (ledger/schema-validation)
    around it, since that bookkeeping isn't the resource being budgeted."""
    semaphore = _get_invocation_semaphore(max_concurrent)
    semaphore.acquire()
    try:
        return adapter.run(role=role, prompt=prompt, cwd=cwd, timeout_s=timeout_s)
    finally:
        semaphore.release()


def invoke(
    *,
    task_id: str,
    role: str,
    phase: str,
    prompt: str,
    cwd: str,
    attempt: int = 1,
    timeout_s: int | None = None,
) -> dict[str, Any]:
    config = load_pipeline_config()
    timeout_s = timeout_s or config["timeouts_seconds"]["per_call"]
    adapter = get_adapter(config.get("adapter", "claude"))
    max_concurrent = config.get("budget", {}).get("max_concurrent_invocations") or 1

    start = time.monotonic()
    raw = _run_adapter_bounded(
        adapter, role=role, prompt=prompt, cwd=cwd, timeout_s=timeout_s, max_concurrent=max_concurrent
    )
    duration_s = time.monotonic() - start

    if raw.timed_out:
        ledger.record(
            task_id=task_id, role=role, phase=phase, attempt=attempt,
            duration_s=duration_s, exit_code=124, status="blocked",
        )
        raise InvocationBlocked(f"{role} timed out after {timeout_s}s")

    envelope, original_error = _parse_envelope(raw.stdout)
    parse_error = original_error

    repair_error: str | None = None
    for _ in range(JSON_REPAIR_ATTEMPTS if original_error else 0):
        # One narrow repair pass (docs §2): ask the SAME role to reformat its own broken
        # output, nothing else — never a retry of the original task, and this call goes
        # straight to the adapter (not invoke()), so a repair that also fails can't itself
        # trigger another repair. Record the original failed attempt first so ledger.jsonl
        # shows the true cost of getting here, not just the eventual outcome.
        ledger.record(
            task_id=task_id, role=role, phase=phase, attempt=attempt,
            duration_s=duration_s, exit_code=raw.exit_code, status="repair_attempted",
        )
        repair_prompt = _repair_prompt(raw.stdout, original_error)
        repair_start = time.monotonic()
        repair_raw = _run_adapter_bounded(
            adapter, role=role, prompt=repair_prompt, cwd=cwd, timeout_s=timeout_s,
            max_concurrent=max_concurrent,
        )
        duration_s += time.monotonic() - repair_start
        raw = repair_raw
        if raw.timed_out:
            repair_error = f"repair attempt timed out after {timeout_s}s"
            break
        envelope, repair_error = _parse_envelope(raw.stdout)
        if envelope is not None:
            break
        parse_error = repair_error  # what invoke() ultimately failed with, if repair also failed

    if envelope is None:
        ledger.record(
            task_id=task_id, role=role, phase=phase, attempt=attempt,
            duration_s=duration_s, exit_code=raw.exit_code, status="failed",
        )
        detail = (
            f"{original_error} (after one repair attempt: {repair_error})"
            if repair_error is not None
            else parse_error
        )
        raise InvocationBlocked(f"{role} produced invalid JSON: {detail}")

    try:
        validate(envelope, "envelope.schema.json")
        result_schema = ROLE_RESULT_SCHEMA.get(role)
        if result_schema and "result" in envelope:
            validate(envelope["result"], result_schema)
    except SchemaValidationError as exc:
        ledger.record(
            task_id=task_id, role=role, phase=phase, attempt=attempt,
            duration_s=duration_s, exit_code=raw.exit_code, status="failed",
        )
        raise InvocationBlocked(f"{role} schema-invalid: {exc}", envelope=envelope) from exc

    ledger.record(
        task_id=task_id, role=role, phase=phase, attempt=attempt,
        duration_s=duration_s, exit_code=raw.exit_code, status=envelope["status"],
        verdict=envelope.get("verdict"), tokens=envelope.get("metrics", {}).get("tokens"),
    )
    return envelope


_MAX_REPAIR_ECHO_CHARS = 4_000  # cap how much of the broken output we echo back


def _repair_prompt(raw_stdout: str, parse_error: str | None) -> str:
    """The one narrow repair pass docs §2 allows: show the model its own broken output and
    the exact parse error, ask for only the corrected JSON. Never a retry of the original
    task — the model isn't told what the task was, only asked to fix the JSON shape."""
    broken = raw_stdout.strip()
    try:
        # Prefer echoing just the model's own text (the CLI wrapper's "result" field), not
        # the surrounding session-metadata noise — cleaner for the model to work from.
        cli_wrapper = json.loads(broken)
        if isinstance(cli_wrapper, dict) and isinstance(cli_wrapper.get("result"), str):
            broken = cli_wrapper["result"].strip()
    except json.JSONDecodeError:
        pass  # outer CLI JSON itself didn't parse — fall back to echoing raw stdout as-is
    if len(broken) > _MAX_REPAIR_ECHO_CHARS:
        broken = broken[:_MAX_REPAIR_ECHO_CHARS] + "\n... <truncated>"
    return (
        "Your previous response could not be parsed as valid JSON.\n\n"
        f"Parse error: {parse_error}\n\n"
        "Your previous raw output was:\n"
        f"{broken}\n\n"
        "Re-emit ONLY the corrected JSON object matching your output contract — no prose, "
        "no markdown fence, nothing else."
    )


def _strip_fence(text: str) -> str:
    """Extract JSON from a model reply that may carry prose before/after a fenced code block
    (verified against live output: models don't reliably honor "no prose outside the JSON").
    Falls back to the whole trimmed text when no fence is present.
    """
    stripped = text.strip()
    start = stripped.find("```")
    if start == -1:
        return stripped
    end = stripped.find("```", start + 3)
    if end == -1:
        return stripped
    body = stripped[start + 3 : end]
    first_newline = body.find("\n")
    if first_newline != -1 and body[:first_newline].strip().isalpha():
        body = body[first_newline + 1 :]  # drop a language tag line, e.g. "json"
    return body.strip()


def _parse_envelope(stdout: str) -> tuple[dict[str, Any] | None, str | None]:
    """Unwrap `claude -p --output-format json`'s CLI envelope, then parse the model's own
    role envelope out of its `result` field.

    Real shape (verified against a live `claude -p --output-format json` call, not assumed):
    the CLI emits one top-level JSON object with session metadata (session_id, usage,
    total_cost_usd, is_error, ...) whose "result" field is a STRING holding the model's actual
    reply — often itself fenced in ```json — which is the role's envelope per
    schemas/envelope.schema.json. The two "result" keys are unrelated: the outer one is the
    CLI's transcript text, the inner one (once parsed) is the role-specific payload.
    """
    try:
        cli_wrapper = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return None, f"CLI stdout was not valid JSON at all: {exc}"

    if not isinstance(cli_wrapper, dict) or "result" not in cli_wrapper:
        return None, "CLI stdout JSON has no 'result' field to unwrap"

    if cli_wrapper.get("is_error"):
        return None, f"CLI reported is_error: {cli_wrapper.get('api_error_status') or cli_wrapper.get('result')}"

    model_text = cli_wrapper["result"]
    if not isinstance(model_text, str):
        return None, f"CLI 'result' field was not a string: {type(model_text).__name__}"

    try:
        return json.loads(_strip_fence(model_text)), None
    except json.JSONDecodeError as exc:
        return None, f"model 'result' text was not valid JSON: {exc}"
