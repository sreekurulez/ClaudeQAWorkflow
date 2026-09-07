"""Mechanical enforcement of the healer's assertion-line rule. docs/control-flow-guardrails.md
§3.2/QP7 — actor/judge separation enforced in code, not just requested in the prompt.

roles/qa-test-healer.md tells the model it may never edit an `expect(...)` line and to report
`touchedAssertionLine` honestly. That's a prompt-level request; this module is the code-level
check that doesn't trust it — heal_loop.py diffs the spec's content from before/after the
healer ran and rejects the heal if any assertion statement differs at all, independent of what
the model's own envelope claims.
"""
from __future__ import annotations

import re

_EXPECT_CALL_RE = re.compile(r"\bexpect\s*\(")
_OPENERS = "([{"
_CLOSERS = ")]}"


def extract_assertions(source: str) -> list[str]:
    """Pull out each `expect(...)...;` statement as a whitespace-normalized string, tracking
    paren/bracket/brace depth (not just matching the first close-paren) so a multi-line
    assertion — e.g. `expect(x).toHaveText([\\n /a/,\\n /b/,\\n]);` — is captured whole rather
    than truncated at its first line. Whitespace is collapsed before comparison so a purely
    cosmetic reformat (re-indenting, wrapping a long line) doesn't read as a changed assertion.
    """
    statements = []
    for match in _EXPECT_CALL_RE.finditer(source):
        start = match.start()
        depth = 0
        i = source.index("(", match.start())
        end = len(source)
        while i < len(source):
            char = source[i]
            if char in _OPENERS:
                depth += 1
            elif char in _CLOSERS:
                depth -= 1
            elif char == ";" and depth == 0:
                end = i
                break
            i += 1
        statement = source[start : end + 1]
        statements.append(re.sub(r"\s+", " ", statement).strip())
    return statements


def assertions_changed(before: str, after: str) -> bool:
    """True if the set of assertion statements differs at all between the two versions of a
    spec file — added, removed, or reworded all count. Order doesn't matter (a healer
    reordering interaction code around an untouched assertion is fine); count and content do.

    Deliberately errs toward false positives over false negatives: whitespace immediately
    adjacent to brackets/commas inside a multi-line assertion (e.g. reformatting a `[...]` list
    onto one line) isn't fully normalized away, so a purely cosmetic reformat of that kind would
    register as "changed". A healer editing interaction code only has no legitimate reason to
    touch an assertion's formatting at all, so this is a low-likelihood, low-cost false
    positive (worst case: this heal is rejected and retried next cycle) — the alternative of a
    real assertion change slipping through a too-lenient normalizer is the failure mode this
    module exists to prevent, so it isn't worth trading away for.
    """
    return sorted(extract_assertions(before)) != sorted(extract_assertions(after))
