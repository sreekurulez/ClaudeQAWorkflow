"""Adapter interface. This is the ONLY seam that changes when porting to Factory (or any
other agent runtime) — see docs/control-flow-guardrails.md, the "agent-agnostic" discussion.

A Factory port adds `factory_adapter.py` implementing this same interface by shelling out to
`droid exec` instead of `claude -p`. Nothing else in control-plane/ should need to change.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class RawResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


class Adapter:
    def run(self, *, role: str, prompt: str, cwd: str, timeout_s: int) -> RawResult:
        """Invoke the agent for one role/prompt, wrapped in a wall-clock timeout.

        Must NEVER raise on timeout — return RawResult(timed_out=True) instead, so invoke.py
        can turn that into a `blocked` envelope (docs §3.0) rather than a crash.
        """
        raise NotImplementedError


def run_subprocess_with_timeout(cmd: list[str], *, cwd: str, timeout_s: int) -> RawResult:
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return RawResult(
            stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode, timed_out=False
        )
    except subprocess.TimeoutExpired as exc:
        return RawResult(
            stdout=(exc.stdout or ""), stderr=(exc.stderr or ""), exit_code=124, timed_out=True
        )
