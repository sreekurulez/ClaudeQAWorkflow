"""Browser-based locator crawler (IMPLEMENTATION_STRATEGY.md §4/Stage 7, "Option B").

Replaces testability_check.py's role in locate() — NOT its staleness-hash check, which stays a
source-file hash (browser crawling is much more expensive than hashing files, so skipping it
when nothing changed matters even more here). Deterministic, no AI: this produces a per-route
fact list; qa-locator-explorer still ranks/interprets it (same actor/judge split as before —
only the fact-gathering mechanism changed, from parsing source to reading a real rendered page).

The actual browser automation is control-plane/crawl.js (Node/Playwright), not Python — driving
a real browser needs a real browser-automation engine, and reusing the Playwright install the
app's own E2E tests already depend on (via app_root's node_modules) avoids adding a second,
duplicate browser-automation dependency to the Python side.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

from util import ROOT, load_project_config

CRAWL_JS_PATH = Path(__file__).resolve().parent / "crawl.js"


class CrawlFailed(Exception):
    """Raised on anything that would otherwise produce a silently-empty or silently-wrong fact
    list: the app never became reachable, crawl.js itself errored, or its output didn't parse.
    Never caught and downgraded to an empty list — that's exactly the silent-failure pattern
    this project has spent most of its effort eliminating elsewhere (testability_check.py's
    unsupported-extension warning, orchestrator.py's prompt-truncation warning)."""


def _is_up(url: str, timeout_s: float = 1.0) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout_s)
        return True
    except OSError:
        return False


def _wait_until_up(url: str, *, timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _is_up(url):
            return
        time.sleep(0.5)
    raise CrawlFailed(f"app never became reachable at {url} within {timeout_s}s")


def _build_crawl_config(project: dict[str, Any]) -> dict[str, Any]:
    auth = project.get("auth", {})
    return {
        "baseUrl": project["base_url"],
        "pages": [
            {
                "route": p["route"],
                "requiresAuth": p.get("requiresAuth", False),
                "navLinkName": p.get("navLinkName"),
            }
            for p in project["crawl_pages"]
        ],
        "auth": {
            "strategy": auth.get("strategy"),
            "loginRoute": auth.get("login_route"),
            "emailTestid": auth.get("email_testid"),
            "passwordTestid": auth.get("password_testid"),
            "submitTestid": auth.get("submit_testid"),
            "testCredentials": auth.get("test_credentials", {}),
        },
    }


def crawl() -> list[dict[str, Any]]:
    """Starts the app if it isn't already running (and stops only what it started — never
    kills a server the operator was already running for their own purposes), runs crawl.js,
    and returns its per-route fact list. Raises CrawlFailed on any failure rather than
    returning an empty/partial list silently."""
    project = load_project_config()
    base_url = project["base_url"]
    app_root = ROOT / project["app_root"]

    started_server = False
    server_proc: subprocess.Popen | None = None
    if not _is_up(base_url):
        server_proc = subprocess.Popen(
            ["node", "server.js"], cwd=app_root,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        started_server = True
        try:
            _wait_until_up(base_url)
        except CrawlFailed:
            server_proc.terminate()
            raise

    try:
        config_path = ROOT / "state" / "_crawl_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(_build_crawl_config(project)))

        result = subprocess.run(
            ["node", str(CRAWL_JS_PATH), str(config_path)],
            cwd=app_root,
            env={**os.environ, "NODE_PATH": str(app_root / "node_modules")},
            capture_output=True, text=True, timeout=120,
        )
        config_path.unlink(missing_ok=True)

        if result.returncode != 0:
            raise CrawlFailed(f"crawl.js exited {result.returncode}: {result.stderr.strip()}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise CrawlFailed(f"crawl.js produced non-JSON output: {exc}\n{result.stdout[:500]}") from exc
    finally:
        if started_server and server_proc is not None:
            server_proc.terminate()
            server_proc.wait(timeout=5)


def facts_to_json(facts: list[dict[str, Any]]) -> str:
    return json.dumps(facts, indent=2)


if __name__ == "__main__":
    print(facts_to_json(crawl()))
