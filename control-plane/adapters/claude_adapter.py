"""Claude Code adapter. Vendor-specific — this is the file a Factory port replaces.

Invocation shape decided in docs/control-flow-guardrails.md's setup guide:
  claude -p --max-turns N --output-format json --permission-mode acceptEdits
         --append-system-prompt-file <role.md> "<prompt>"

`--permission-mode acceptEdits` is required, not optional: verified live that without it a
write-capable role (qa-test-generator, qa-test-healer) never emits its envelope at all — the
CLI's default permission handler is "host", which doesn't exist in non-interactive `-p` mode, so
the model just asks for permission in plain-text prose and invoke.py's parser correctly rejects
that as invalid JSON. acceptEdits auto-approves file edits/writes while still gating shell
commands; each role's own prompt boundaries (e.g. "write only under .../generated/") are the
actual scope enforcement, same as before.
"""
from __future__ import annotations

from pathlib import Path

from adapters.base import Adapter, RawResult, run_subprocess_with_timeout
from util import ROLES_DIR

DEFAULT_MAX_TURNS = 20


class ClaudeAdapter(Adapter):
    def __init__(self, max_turns: int = DEFAULT_MAX_TURNS):
        self.max_turns = max_turns

    def run(self, *, role: str, prompt: str, cwd: str, timeout_s: int) -> RawResult:
        role_file = ROLES_DIR / f"{role}.md"
        if not role_file.is_file():
            raise FileNotFoundError(f"no role prompt for {role}: {role_file}")

        cmd = [
            "claude",
            "-p",
            "--max-turns",
            str(self.max_turns),
            "--output-format",
            "json",
            "--permission-mode",
            "acceptEdits",
            "--append-system-prompt-file",
            str(role_file),
            prompt,
        ]
        return run_subprocess_with_timeout(cmd, cwd=cwd, timeout_s=timeout_s)


ADAPTERS = {
    "claude": ClaudeAdapter,
}


def get_adapter(name: str) -> Adapter:
    if name not in ADAPTERS:
        raise ValueError(f"unknown adapter: {name} (known: {list(ADAPTERS)})")
    return ADAPTERS[name]()
