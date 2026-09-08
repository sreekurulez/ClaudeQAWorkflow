"""Deterministic testability-check script (docs/control-flow-guardrails.md G4/LP1).

Testability auditing — does an interactive element have a stable selector — is a grep/AST-level
fact, not LLM judgment. This script computes that fact list mechanically; `qa-locator-explorer`
ranks/interprets it (assigns confidence tiers, groups by route) but never re-derives it by
reading source itself.

Scope, deliberately narrow for this POC: static HTML interactive elements (input/button/select/
textarea/a[href]), plus a best-effort heuristic for elements created dynamically via
`document.createElement(...)` in JS. Not a full AST/DOM analysis; a real port should replace the
JS heuristic with an actual parser (e.g. an acorn/esprima AST walk), and — see
IMPLEMENTATION_STRATEGY.md — add real JSX/TSX support (or, per that doc's Option B, replace
source scanning with a browser-based accessibility-tree snapshot instead).

**No JSX/TSX support exists yet.** `dummy-app` was rebuilt as a React/TypeScript SPA
(`dummy-app/src/**/*.tsx`); this scanner cannot read those files. Rather than silently returning
an empty (or, worse, stale) result, `scan_paths()` reports every file it was asked to scan but
couldn't handle, loudly, on stderr — see `_UNHANDLED_WARNING` below. Do not treat a quiet, empty
`locate` result as confirmation the app has no testable elements; check stderr first.

Output is a flat fact list per source file — NOT a locator-map. It says nothing about routes or
confidence tiers; that interpretation is qa-locator-explorer's job (docs §1.4/G4: "you rank/
interpret these facts, you do not re-derive them").
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from util import ROOT, hash_files, load_project_config

INTERACTIVE_TAGS = {"input", "button", "select", "textarea", "a"}


@dataclass
class ElementFact:
    tag: str
    hasTestId: bool
    testId: str | None = None
    id: str | None = None
    name: str | None = None
    text: str | None = None
    ariaLabel: str | None = None
    labelText: str | None = None
    dynamic: bool = False
    sourceLine: int | None = None


@dataclass
class FileFacts:
    file: str
    sourceHash: str
    elements: list[ElementFact] = field(default_factory=list)


class _InteractiveElementParser(HTMLParser):
    """Two things a regex can't do reliably: track element text content, and associate a
    <label for="x"> with the input it labels (label can appear before OR after in source order,
    so labels are collected in a first pass, elements resolved against them in a second)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.labels_by_for: dict[str, str] = {}
        self._pending_label_for: str | None = None
        self._label_text_parts: list[str] = []
        self.elements: list[ElementFact] = []
        self._open_interactive: dict | None = None  # tag currently accumulating text
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: (v or "") for k, v in attrs}
        if tag == "label" and "for" in attr_map:
            self._pending_label_for = attr_map["for"]
            self._label_text_parts = []
            return
        if tag in INTERACTIVE_TAGS:
            if tag == "a" and "href" not in attr_map:
                return  # non-navigational <a>, e.g. used purely as a JS hook — not in scope here
            test_id = attr_map.get("data-testid")
            fact = ElementFact(
                tag=tag,
                hasTestId=bool(test_id),
                testId=test_id or None,
                id=attr_map.get("id") or None,
                name=attr_map.get("name") or None,
                ariaLabel=attr_map.get("aria-label") or None,
                sourceLine=self.getpos()[0],
            )
            self.elements.append(fact)
            if tag in ("button", "a"):
                self._open_interactive = fact
                self._text_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._pending_label_for is not None:
            self.labels_by_for[self._pending_label_for] = "".join(self._label_text_parts).strip()
            self._pending_label_for = None
            return
        if tag in ("button", "a") and self._open_interactive is not None:
            self._open_interactive.text = "".join(self._text_parts).strip() or None
            self._open_interactive = None

    def handle_data(self, data: str) -> None:
        if self._pending_label_for is not None:
            self._label_text_parts.append(data)
        if self._open_interactive is not None:
            self._text_parts.append(data)

    def resolve_labels(self) -> None:
        for fact in self.elements:
            if fact.id and fact.id in self.labels_by_for:
                fact.labelText = self.labels_by_for[fact.id]


def scan_html(path: Path) -> list[ElementFact]:
    parser = _InteractiveElementParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.resolve_labels()
    return parser.elements


# Heuristic for dynamically-created elements in vanilla JS: `const x = document.createElement("tag")`
# followed, within a bounded window of lines, by a data-testid setter (has one) or not (flag it).
_CREATE_RE = re.compile(
    r"""\b(?:const|let|var)\s+(\w+)\s*=\s*document\.createElement\(\s*['"](\w+)['"]\s*\)"""
)
_TESTID_SETTER_RE_TMPL = r"\b{var}\.(?:setAttribute\(\s*['\"]data-testid['\"]|dataset\.testid\s*=)"
_TEXT_SETTER_RE_TMPL = r"\b{var}\.(?:textContent|innerText)\s*=\s*(['\"])(.*?)\1"
_WINDOW_LINES = 15


def scan_js(path: Path) -> list[ElementFact]:
    lines = path.read_text(encoding="utf-8").splitlines()
    facts: list[ElementFact] = []
    for i, line in enumerate(lines):
        match = _CREATE_RE.search(line)
        if not match:
            continue
        var_name, tag = match.group(1), match.group(2)
        if tag not in INTERACTIVE_TAGS | {"li", "span", "div"}:
            continue
        window = "\n".join(lines[i : i + _WINDOW_LINES])
        has_testid = bool(re.search(_TESTID_SETTER_RE_TMPL.format(var=re.escape(var_name)), window))
        text_match = re.search(_TEXT_SETTER_RE_TMPL.format(var=re.escape(var_name)), window)
        # only report tags that are inherently interactive, or non-interactive tags a listener
        # was actually attached to (li/span/div used purely as static wrappers aren't in scope)
        has_listener = bool(re.search(rf"\b{re.escape(var_name)}\.addEventListener\(", window))
        if tag not in INTERACTIVE_TAGS and not has_listener:
            continue
        facts.append(
            ElementFact(
                tag=tag,
                hasTestId=has_testid,
                text=text_match.group(2) if text_match else None,
                dynamic=True,
                sourceLine=i + 1,
            )
        )
    return facts


_UNHANDLED_WARNING = (
    "testability_check: cannot scan {path} — no support for '{suffix}' files yet "
    "(only .html/.htm/.js are handled). This file's elements are MISSING from the fact list, "
    "not confirmed absent. See testability_check.py's module docstring."
)


def scan_paths(paths: list[Path]) -> list[FileFacts]:
    results: list[FileFacts] = []
    for path in paths:
        if path.suffix in (".html", ".htm"):
            elements = scan_html(path)
        elif path.suffix == ".js":
            elements = scan_js(path)
        else:
            # Loud, not silent (docs §"fails quietly"): an unrecognised extension used to be a
            # bare `continue` here, which is exactly how this script ended up scanning
            # dummy-app's old, no-longer-served public/app.js while silently ignoring the real
            # dummy-app/src/**/*.tsx source — a valid-looking but wrong result, with no warning.
            print(
                _UNHANDLED_WARNING.format(path=path, suffix=path.suffix or "<no extension>"),
                file=sys.stderr,
            )
            continue
        results.append(
            FileFacts(
                file=str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                sourceHash=hash_files([path]),
                elements=elements,
            )
        )
    return results


def facts_to_json(facts: list[FileFacts]) -> str:
    return json.dumps([asdict(f) for f in facts], indent=2)


_SCANNABLE_SOURCE_EXTS = (".html", ".htm", ".js", ".jsx", ".ts", ".tsx")


def _default_paths() -> list[Path]:
    """Reads config/project.json's app_source_dir (IMPLEMENTATION_STRATEGY.md §7.3 — the same
    fix as the role-file path injection, applied to this deterministic script too) rather than
    hardcoding a path. dummy-app's actual UI source is dummy-app/src/**/*.tsx (a React SPA) —
    NOT dummy-app/public/, which server.js stopped serving once the app was rebuilt (it now
    serves the built dist/ output instead). This deliberately globs a wider set of frontend
    source extensions than scan_paths() can currently handle, so an unparseable file (.tsx,
    .jsx, .ts) reaches scan_paths() and gets a loud warning — instead of being silently dropped
    here where no warning could ever fire."""
    project = load_project_config()
    src_dir = ROOT / project.get("app_source_dir", "dummy-app/src")
    return sorted(p for p in src_dir.glob("**/*") if p.suffix in _SCANNABLE_SOURCE_EXTS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="*", type=Path,
        help="Files to scan (default: config/project.json's app_source_dir, all recognised extensions)",
    )
    args = parser.parse_args(argv)
    paths = args.paths or _default_paths()
    facts = scan_paths(paths)
    if paths and not facts:
        print(
            f"testability_check: {len(paths)} file(s) were scanned but ZERO produced any "
            "fact list — likely all unsupported (see warnings above). Do not treat this as "
            "\"the app has no testable elements.\"",
            file=sys.stderr,
        )
    json.dump([asdict(f) for f in facts], sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
