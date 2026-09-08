# Implementation strategy — risk-ordered, in plain language

**For review only. Nothing has been built.**

## What changed in this revision (and what I got wrong before)

This document has been restructured twice. Both times, the driver was noticing that the plan was
optimising the wrong thing. The current revision makes three corrections to my own earlier
advice:

1. **Locator discovery is no longer the centrepiece.** Earlier drafts spent most of their length
   on *how to find clickable elements* (parse source code vs. read the browser). But your own
   acceptance suite already shows selector mistakes get fixed automatically in one heal cycle
   (golden scenario 2: *"hand-planted selector typo; healed in 1 cycle"*). So a more accurate
   element list mostly saves heal cycles **that already work**. It's an optimisation, and it now
   sits late in the plan instead of first.
2. **Graphify is dropped.** I previously recommended it fairly strongly. That was premature —
   reasons in §5.
3. **The plan is now ordered by risk**, not by which proposal came first. The three biggest risks
   to "use this on real projects" were absent from earlier drafts entirely. They're now §2.

Superseded documents: `PROPOSED_ENHANCEMENTS.md` (Change 2's four catalogues are largely dropped
or deferred here) and `PROPOSED_DUMMY_APP_UPGRADE.md` (already built).

---

## 0. Status right now — pending work and immediate next step

**One item below is done. Everything else in this document is still pending — not started.**

✅ **DONE (2026-09-08) — the `testability_check.py` dead-code bug, part of Stage 0.**
`dummy-app` was rebuilt as a React/TypeScript SPA (`dummy-app/src/**/*.tsx`), and `server.js` now
serves the built `dist/` output. But the scanner only understood `.html`/`.js`, so it was
silently reading the **old, no-longer-served** `dummy-app/public/app.js` + `index.html` —
producing a full, valid-looking locator map built entirely from files the app no longer uses,
with no error and no warning. Confirmed live by running the actual code, then fixed:

- `testability_check.py::_default_paths()` now points at `dummy-app/src/**/*` (the real source),
  and deliberately globs a wider set of extensions (`.html/.htm/.js/.jsx/.ts/.tsx`) than the
  scanner can parse, so unsupported files reach `scan_paths()` instead of being invisibly
  filtered out one directory earlier.
- `scan_paths()` now prints a loud, specific warning to stderr for every file it can't handle,
  naming the file and stating its elements are *missing, not confirmed absent*.
- `main()` adds a summary warning when every scanned file was skipped, so an empty result can't
  be mistaken for "the app has no testable elements."
- `orchestrator.py::locate()`'s prompt to `qa-locator-explorer` — which was still telling the AI
  to crawl `dummy-app/public/` — now points at `dummy-app/src/` and tells the AI to read the real
  source itself when the deterministic scan comes back empty.
- Verified: running it now produces an honest `[]` on stdout plus 20 explicit per-file warnings
  on stderr, instead of a silent wrong result. Explicit `.html`/`.js` paths still parse exactly
  as before (no regression).

**What this fix is *not*:** it does not add JSX/TSX parsing. `testability_check.py` still cannot
read `dummy-app`'s real UI source — it now says so loudly instead of lying about it. Real JSX/TSX
support (or, better, replacing source scanning entirely) is the substantially bigger Stage 7 work
below (Option B, the browser-snapshot approach), and remains fully pending, gated on Stage 2's
go/no-go spike.

✅ **DONE (2026-09-08) — prompt-truncation warning, the rest of Stage 0.**
`orchestrator.py`'s `_artifact_block()` and `_changed_files_block()` cap embedded content at
`_MAX_EMBED_CHARS` (20,000 chars) so one huge file can't blow out a prompt — but used to just
append `"... <truncated>"` and continue with no warning at all. On the small test app nothing
ever hit the cap, so this was invisible; on a real app, a file over the cap would be silently cut
mid-sentence and an AI role would plan/generate/review against a partial file with no one able to
tell "it worked" from "the cut-off hid the problem."

- Both functions now route through a shared `_truncate()` helper that prints a specific stderr
  warning whenever the cap is actually hit — naming which file/label, the original size, and
  exactly how many characters were dropped.
- **Verified no false positives:** normal-sized files (checked against `dummy-app/server.js`,
  well under the cap) produce no warning and no output change — this only fires when the cap is
  genuinely exceeded.
- **Verified it fires correctly:** a synthetic 25,000-char input triggers the warning and
  truncates to the same 20,016-char result the old code produced — the *content* behavior is
  unchanged, only the silence is fixed.
- **Out of scope, noted but not touched:** `invoke.py`'s separate `_MAX_REPAIR_ECHO_CHARS` cap
  (echoing a model's own already-broken JSON back to it for one repair attempt) is a different
  mechanism — it caps a diagnostic echo of known-bad output, not a role's actual task input, so
  the "silently misinforms the AI about real content" risk this fix addresses doesn't apply there.

**Stage 0 is now fully done** — both its items (skipped file types, prompt truncation) warn
loudly instead of failing silently.

✅ **DONE (2026-09-08) — Stage 1 (generated-test quality).** 4 of 5 deliberately-introduced bugs
were caught by the real, pipeline-generated suite. Full method, results table, and five findings
(one real defense-in-depth gap, one systematic 33%-of-specs navigation defect, two positive
signals, and two tooling robustness gaps — a manifest checkpoint that doesn't survive a total
invocation failure, and a generate call that can outrun its own turn budget) are in §2.1.

**New, not-yet-triaged items surfaced by Stage 1** (none of the existing stages below cover
these; they need a decision on where they fit before being built):
- The `ITEMS-E02`-style defense-in-depth gap — frontend-guard tests and backend-validation tests
  are currently conflated as one planned case.
- The `page.goto()`-to-protected-route navigation defect affecting `ORDERS-*` (33% of one real
  generate run) — likely a `qa-test-generator.md` role-file fix, possibly also an app-side one
  (persist the auth token).
- The manifest-doesn't-checkpoint-on-total-invocation-failure gap in
  `orchestrator.py::_run_generate_phase`.
- The generate call's turn budget not scaling with batch size (a 20-case single call failed
  outright; a 5-case resume succeeded normally).

✅ **DONE (2026-09-08) — Stage 2 (real-app feasibility spike).** Result: **NO-GO as things
stand.** No local backend, no docker-compose, no seed/reset mechanism, and login goes through a
real hosted Keycloak realm (`finbook-auth`) with no working local/test path — confirmed by
checking the target repo directly, not assumed. Full evidence chain in §2.2. **This is now
blocked on organisational input, not on more investigation** — specifically, whether a test
account and a safe-to-use dev/staging environment already exist, or need to be requested.

⏸️ **PAUSED (2026-09-08) — Stage 3, on request.** Not started. Checked what pausing 2 and 3
actually affects before moving on:

- **Stages 4, 5, 8, 9 are unaffected** — all are dummy-app/ledger-scoped and don't depend on
  Stage 2 or 3 in any way.
- **Stage 6 (portability work) can still be built**, since the *mechanism* (config-driven reset
  strategy, config-driven auth handling, paths out of the hardcoded role instructions) doesn't
  need live Finbook access to design — only its real-world proof does, which stays deferred.
- **Stage 7 was already blocked**, independent of this pause — it's explicitly gated on Stage
  2 returning viable, and Stage 2 already returned NO-GO. Pausing changes nothing there.

**Net effect of the pause: no real-app validation for now** — the project stays dummy-app-only
until Stage 3 (or Stage 2's organisational question) is revisited. That's a strategic delay, not
a technical blocker on anything else in this plan.

✅ **DONE (2026-09-08) — Stage 4 (measuring tape + baseline).** `invoke.py`/`ledger.py` now
record real cost/token/turn data from the CLI wrapper instead of the AI's own unreliable
self-report, plus deterministic `prompt_chars`. Also checked (and confirmed correct, not
broken) an earlier assumption of mine about `verdict` — full details and a baseline data table
in §8.

✅ **DONE (2026-09-08) — Stage 5 (two-call US-001 experiment).** Result: Idea 1's core premise
did not hold — a code-aware planner still correctly planned the AC-4 case a no-code planner
would, rather than silently dropping it. **Recommendation: don't build the "hide code from the
planner" architecture on this justification.** Also found, while designing the experiment, that
the plan format's `gap` flag only covers missing *selectors*, not missing *behaviour* — corrects
an earlier recommendation of mine. Full method, results, and both findings in §8.

✅ **DONE (2026-09-08) — Stage 6 (portability mechanism).** Config now declares
`test_isolation.strategy` and `auth.strategy`; a new shared `util.py::project_context_block()`
injects paths/strategy into every AI-facing prompt (including `heal_loop.py`'s healer prompt,
which needed a real fix, not just an addition — see §7's full writeup); all four hardcoded role
files plus one deterministic-code equivalent (`testability_check.py`) now read from config
instead of a literal `dummy-app/...` string. Verified live with one real, cheap plan-phase call.
**Not built:** the actual Keycloak `storage_state` mechanism and a real reset-alternative
implementation — both need a real second project to build against, not a speculative shape.

✅ **DONE (2026-09-08) — Stage 7 (browser-based element crawler), built against `dummy-app` on
explicit request, ahead of Stage 2's real-app resolution.** `control-plane/crawl.js` +
`browser_crawler.py`, wired into `orchestrator.py::locate()`. Found and fixed two real bugs by
actually running it (a redirect-check that ran before the redirect happened; this app's
in-memory auth not surviving `page.goto()` even immediately after a successful login — fixed by
navigating via real nav-link clicks instead). Verified live end-to-end, including a genuinely
good AI judgment call on an ambiguous duplicate-name element. Full writeup in §4.

✅ **DONE (2026-09-08) — Stage 8 (traceability capture).** `control-plane/traceability.py`,
wired into `orchestrator.py::_run_generate_phase`. Both trust tiers built and verified against
real data from both tracks: "derived" against the real 20-case dummy-app batch (found and fixed
a real string-matching bug, documented a genuine AI-naming-mismatch structural limit rather than
chasing it with fuzzier heuristics), "measured" against Stage 3's real `Accordion.test.tsx` via
Jest's own coverage reporter. The live audit report correctly answered real questions this
section exists for: `CART-*`'s 5 never-generated cases, `ProfilePage.tsx`'s zero coverage, and
which cases are honestly unmapped rather than silently guessed at. Full writeup in §6.

✅ **DONE (2026-09-08) — Stage 9 (page-scoped prompt filtering), the last item in the stage
table.** Real, measured 53% `prompt_chars` reduction on byte-identical input (18,979 → 8,965),
plus a real fail-open correctness bug found and fixed by testing against the messy real
stage1-quality plan rather than a clean hypothetical one. Full writeup in §5.

**Every stage in the recommended order is now done except the Stage 2 organisational
question** (real Finbook Keycloak/environment access — needs your input, not more building).
Nothing left is blocking on this side: Stage 7's crawler no longer needs Stage 2 resolved to
exist, since it's already built and proven against `dummy-app`; re-verifying it against a real
Keycloak-backed target once Stage 2 resolves is the natural follow-up, not a new stage. There is
no further stage to pick up without either that resolution or a new direction from you.

---

## 1. What's being planned

Two ideas were proposed originally:

- **Idea 1 — "Plan tests from the ticket, not the code."** Give the planner the user story rather
  than the code diff, so it can also catch what a developer *forgot to build*.
- **Idea 2 — "Stop sending the AI the whole app."** Send only the parts of the element list
  relevant to the current task.

Both are still in this plan. Neither is at the top of it any more.

---

## 2. The three questions that matter more than either idea

These were missing from earlier drafts. They're the actual risks to the stated goal.

### 2.1 Are the generated tests any good? ✅ DONE (2026-09-08) — yes, mostly, with one real gap.

There is **no coverage measurement, no mutation testing, and no objective quality measure of any
kind** in this repo. And the reviewer role is given `plan.json`, `generate.json`, the heal result
and the element list — that is, **metadata about** the tests. It never objectively assesses
whether the test code would actually catch a regression. So "golden scenario 1 passes with 13
generated cases" only proved the pipeline **ran** — it didn't prove the output was valuable.

**Method:** ran the real pipeline (`locate` → `plan` → `generate`) against the current
`dummy-app`, producing a genuine 20-case plan and real generated specs — no mocking, no
hand-authored plan. Confirmed a clean baseline, then applied 5 realistic single-behaviour bugs to
`server.js` one at a time, each fully reverted and re-confirmed green before the next, and
recorded whether the generated suite caught each one.

**Result: 4 of 5 mutations caught (80%).**

| # | Mutation | Target test | Result |
|---|---|---|---|
| 1 | `DELETE /api/items/:id` silently does nothing | `ITEMS-E06` (confirm delete) | ✅ Caught |
| 2 | `POST /api/items` server-side name validation removed | `ITEMS-E02` (empty-name guard) | ❌ **Missed** |
| 3 | Login accepts any password for a valid email (auth bypass) | `LOGIN-E02` (invalid creds rejected) | ✅ Caught |
| 4 | `PUT /api/items/:id` silently stops persisting the name change | `ITEMS-E03` (edit) | ✅ Caught |
| 5 | `GET /api/items` search query silently ignored | `ITEMS-E04` (search filter) | ✅ Caught |

**The one miss is a real, security-relevant gap, not a fluke.** `ITEMS-E02` asserts the POST
request is **never even sent** when the name field is empty (a frontend guard) — so a backend
validation regression is completely unexercised by this test. This is a genuine defense-in-depth
blind spot: nothing in the generated suite would catch a backend validation regression on that
endpoint. Worth a role-file note for `qa-test-planner`/`qa-test-generator`: a frontend-guard test
and a backend-validation test are two different cases, and only the former gets planned today.

**A second, bigger, unplanned finding — a systematic test-authoring defect, found while
establishing the baseline (not from a mutation):** 5 of the 15 generated specs (all `ORDERS-*`,
33%) **failed even on the unmodified app.** Root cause, verified against the real source
(`OrdersPage.tsx:26-31`, `AuthContext.tsx`): this app's auth is deliberately in-memory-only (no
token persistence), and every `ORDERS-*` spec navigates with `page.goto("/orders"...)` — a full
page reload. The reload wipes the in-memory auth state, so `OrdersPage`'s
`if (!isAuthenticated) navigate("/login")` guard fires before the intended flow ever runs. This
is not a selector typo (which the healer already fixes) — it's a **navigation-strategy defect**
that would recur on every future generated spec touching a protected nested route, because the
generator has no way to know this app's auth doesn't survive a reload. Real fix is either
app-side (persist the token) or role-file guidance (prefer in-app client-side navigation over
`page.goto` for already-authenticated flows) — not evaluated further here, logged as a finding.

**Two positive signals, also found while establishing the baseline:**
- The generator correctly **refused** to write the 5 `CART-*` specs, citing a real, verified app
  defect (`ProductList`'s `showCartButton` prop is never passed `true` anywhere — confirmed via
  `grep`; the "Add to Cart" button is genuinely unreachable dead code) — rather than inventing a
  workaround or a broken test. Exactly the honest-skip behaviour the schema's `status: "skipped"`
  + `reason` exists for.
- `ITEMS-E08` (testing US-001's deliberately unimplemented AC-4) correctly **fails**, proving the
  generated suite does catch a genuinely missing requirement when one exists — direct supporting
  evidence for Idea 1 (§8), independent of the two-call experiment there.

**A process/robustness gap, found by accident, not by design:** the first `generate` call
actually wrote 15 of 20 real spec files to disk, then failed when its final summary JSON didn't
parse (a distinct, separate bug — see below). Because `orchestrator.py::_run_generate_phase`
only calls `manifest.upsert()` after `invoke()` returns successfully, **zero manifest entries
were recorded despite 15 real files existing on disk** — contradicting `manifest.py`'s own
docstring claim ("checkpoints per spec written"). In practice, checkpointing only survives a
partial *result*, not a total *invocation* failure. Worked around manually here (hand-seeded the
manifest from the files that existed) to continue the experiment; not fixed. **Logged as a new
item, not yet triaged into a stage** — see the note at the end of this subsection.

**Also found and fixed along the way (blocking, not optional):** `qa-test-planner` emitted
`"caseId": null` in a `findings` entry — `envelope.schema.json` requires `caseId` to be a string
when present and rejects `null`. Same class of gap `TODO.md` documents repeatedly (an enum/shape
under-specified in the role file, model fills the gap with something plausible-but-invalid).
Fixed `roles/qa-test-planner.md` to state explicitly: omit the key, never null it.

**Separately, the very first `generate` call (20 cases in one invocation) failed entirely** —
`InvocationBlocked: ... CLI stdout JSON has no 'result' field to unwrap` — most likely
`--max-turns 20` exhausted by a 20-file batch (each write is at least one turn). Worked around
by resuming with only the 5 pending cases once the manifest was seeded (see above), which
succeeded normally. **Not yet fixed**, and it's the direct cause of the manifest gap above:
a real generate batch of realistic size can currently outrun its own turn budget with no
graceful degradation. Candidate fixes (not evaluated in depth): raise `--max-turns` for the
generate role specifically, or have `_run_generate_phase` submit cases in smaller chunks.

**Net assessment:** the generated tests are meaningfully good — real assertions, correct honest
skips, a genuine gap correctly caught — but not uniformly reliable, and the two robustness gaps
found in the tooling (manifest-vs-total-failure, turn-budget-vs-batch-size) are more concerning
long-term than the one test-quality miss, since they'd get worse, not better, at real-app scale.

### 2.2 Can this even run against a real app? ✅ SPIKE DONE (2026-09-08) — current answer: NO.

Every generated and baseline test starts by calling a special "reset to known data" endpoint, and
logs in through a simple in-app form. Neither exists on the real target. This spike investigated
how blocking that actually is — not by trying to build a workaround, but by checking what
infrastructure genuinely exists to build one on. Four converging findings, each verified directly
against the real repo, not assumed:

1. **There is no local backend or database at all.** The target app's own repo is
   frontend-only — no server code, no `docker-compose`, nothing to run or seed locally.
   `.env.development`/`.env.staging`/`.env.production` all point `REACT_APP_API_URL` at real,
   remote, hosted services (`api.dev.finbooks.app`, `api.stage.finbooks.app`,
   `api.finbooks.app`). There is no environment where "reset to known data" could even be
   implemented without write access to a live, shared, remote system.
2. **Login is a real, hosted, external identity provider — not something to spin up.**
   `public/keycloak-{dev,staging,prod}.json` all point at real hosted Keycloak servers
   (`auth.dev.finbooks.app`, `auth.stage.finbooks.app`, `auth.finbooks.app`), all under one real
   realm, `finbook-auth`. The only non-remote option, `keycloak-local.json`, points at
   `192.168.1.22` — a specific developer's own machine on their local network, not something
   reachable or reproducible from here. The project's own `README.md` lists **"Keycloak server
   access"** as a prerequisite, i.e. something you must be granted, not something available by
   default.
3. **No test-account or seed-data convention exists anywhere in the repo** — checked
   `.factory/`, `docs/`, and a repo-wide search for test-credential patterns. Nothing.
4. **The existing hand-written regression specs confirm this gap is real and unresolved, not
   just theoretical.** `tests/e2e/regression/admin/destructive-action-confirmation.spec.ts`'s own
   comment says *"Requires Keycloak session"* and simply assumes one already exists —
   `critical-happy-path.spec.ts` does the same. Neither spec, nor `playwright.config.ts`, nor
   anything else in the repo contains a `storageState`, `globalSetup`, or any other mechanism
   that actually **establishes** that session. And there is no `.github/workflows/` directory at
   all — the CI pipeline the QA template's own docs describe (`README _qa.md`'s "Phase 3 — PR
   Review") was never actually installed in this repo. So even the app's own existing tests have
   no verified, working, automated way to run — this isn't a gap specific to this workflow.

**Conclusion: this spike is a NO-GO as things stand, not a "medium effort, proceed."** Getting
a working authenticated session and a safe test-data strategy here depends on things outside
this codebase entirely: being granted real Keycloak credentials against a real dev/staging
realm, and an organisational decision about what's safe to create/modify in that shared
environment (which is real product infrastructure, not a sandbox). **This needs input only you
can provide** — do a test account and a safe-to-use dev/staging environment already exist
somewhere, or would this need to be requested/set up first? Until that's answered, the
end-to-end track (Stage 7, browser-crawler locator discovery included) has no environment to run
against at all.

#### Revisit (2026-09-08) — live check against real infrastructure, credentials provided

A test account was provided and the flow tested live (Playwright, direct browser navigation, no
credentials or session data written to this repo). Two **independent, concrete infrastructure
bugs** on Finbook's own dev environment, found before the credential could even be tested:

1. **The deployed dev app itself cannot log anyone in right now.** Navigating to
   `https://accounting.dev.finbooks.app/` and observing real console/network traffic shows it
   redirecting to `https://auth.dev.finbooks.app/...` — the same dead host `.env.development`
   points at (finding 2 above) — and that request fails outright (`net::ERR_ABORTED`; that host
   doesn't resolve/respond at all, confirmed separately via a plain reachability check). The
   live Keycloak has moved to a different host, **`auth.dev.gcp.finbooks.app`** (confirmed
   live and responding), but the deployed frontend bundle wasn't updated to match — this is a
   real, current outage on the dev environment, not something specific to this workflow.
2. **Working around finding 1 (navigating the correct host directly, reusing the app's own
   exact `client_id`/`redirect_uri` values captured from its failed request) hits a second,
   different wall**: Keycloak returns `"Invalid parameter: redirect_uri"` **before ever showing
   a login form** — even though the redirect URI used was byte-for-byte identical to what the
   app itself generates. This points at the `finbook-react` client's registered redirect URIs
   not having been carried over correctly when Keycloak moved to the `gcp` host.

**As a result, the credential itself was never actually tested** — both failures happen before
a login form is ever reachable. This doesn't reopen the "is this feasible" question (still NO —
if anything, it's now confirmed harder: even manually working around one broken layer surfaces
another), but it does sharpen exactly what's blocking it: **this needs someone with Keycloak
admin access to fix the client's registered redirect URIs and the dev deployment's stale auth
host — a Finbook infrastructure fix, not something buildable from this repo.** Stopped here
deliberately rather than continuing to guess at Keycloak client configuration against real
infrastructure.

**Security note:** the credential was shared directly in chat. Treated as sensitive throughout —
never written to any file in this repo, never printed in any output, passed only as an inline,
single-command environment variable, no `storageState`/session artifact retained anywhere. Flagged
to the user to rotate it regardless of this outcome, since pasting it into a chat interface is
itself an exposure independent of anything done with it here.

#### Second revisit (2026-09-08) — a plausible alternative explanation: VPN

The user's read: both live-test failures may simply be because the sandbox this workflow runs
in isn't connected to Finbook's VPN — plausible for both findings above (an internal-only
hostname would just fail to resolve off-VPN; split-horizon DNS could route an off-VPN request
to a differently-configured public-facing Keycloak instance, producing exactly the misleading
`redirect_uri` error seen).

**Important constraint, stated plainly so it isn't silently assumed away:** the tool-execution
environment here has its own general internet access and is **not tunneled through anyone's
VPN** — connecting to VPN on a local machine does not extend reachability to this sandbox. So
this explanation can't be verified from here regardless of which machine connects to VPN.

**Also worth being precise about, even in the best case:** VPN access would only resolve one of
Stage 2's four original findings (real Keycloak requiring granted access) — the other three
(no local backend, no test-data/seed convention, no working session-establishment mechanism in
the existing specs) are unaffected by network reachability and remain fully open regardless.

**Decision (2026-09-08): the user will test the login manually on a VPN-connected machine and
report the real result back, rather than have this workflow guess further from an environment
that structurally cannot reach the target either way.** Stage 7 (browser-based crawler) stays
**not started**, still gated on Stage 2, pending that report. If login succeeds over VPN, Stage
2's Keycloak-access finding is resolved — but §7.1's test-data isolation problem would still
need solving before Stage 7 has a safe environment to actually run against.

**This is exactly the scenario §2.3 exists for.** The component-test track has zero dependency
on any of the four findings above — no login, no backend, no shared environment. Recommend
picking that up next (Stage 3) rather than waiting on this.

### 2.3 There's a lower-risk way to deliver value, and earlier drafts left it out

✅ **PROOF OF CONCEPT DONE (2026-09-08) — core hypothesis confirmed with real evidence.** Built
`executor.py::run_jest()`/`parse_jest_results()` (verified against real Jest JSON output, not
assumed), added `component_test_app_root`/`component_test_command`/`component_test_results_path`
to config, then ran the **existing, completely unmodified** `qa-test-planner` and
`qa-test-generator` roles — via `invoke()` directly, bypassing the orchestrator's dummy-app-bound
`project_context_block()` — against a real, previously-untested Finbook component
(`src/components/Accordion/Accordion.tsx`, chosen for zero external dependencies: no API calls,
no Redux, so no mocking complexity to navigate on a first attempt).

**Result:** the planner produced 20 well-reasoned cases (controlled/uncontrolled state, keyboard
nav, disabled items, edge cases) with zero role-file changes. Generated a real test file for 6 of
them; **5 of 6 passed on the first try against real, unmodified Finbook code.** The one failure
is a genuine test-authoring subtlety, not a product defect: `getByRole("region", {name: ...})`
correctly can't find a panel hidden via the `hidden` attribute (RTL excludes hidden elements from
the accessibility tree) — a `test-defect` the existing heal loop is designed to fix (switch to
`hidden: true` or a different query), not a component bug. This is real, strong support for the
plan's central hypothesis: **the planner and generator need no role-file rewrite at all** — only
correct context (which files, which framework, where to write) got them there.

**What this proof of concept did NOT cover, left for a real rollout:** the ad-hoc custom context
block bypassed `orchestrator.py` entirely (direct `invoke()` calls, matching how the Stage 5
experiment worked) — a real integration needs either a second config profile or a `--mode
component` flag so this is a repeatable `--phase` invocation, not a one-off script. Heal loop and
diff-guard were not exercised against a real Jest failure (the one failing case was diagnosed by
hand, not healed through the pipeline) — no reason to expect they wouldn't work, since both
operate on file diffs and triage classification agnostic to Playwright vs. Jest, but that's an
assumption, not yet verified the way this session verifies everything else. And this was one
simple, dependency-free component — Finbook's harder components (§1's `DeleteQuote.test.tsx`
example: heavy `jest.mock()` of API modules, Redux hooks, and child components) are a real step
up in difficulty the generator hasn't been tested against yet.

**Also found, a genuine environment fact worth recording:** `finbook-web-application`'s own
`node_modules` had never been installed in this environment — the README's documented
`npm install -f` (peer-dependency conflicts are real and expected) succeeded cleanly once retried
past an unrelated corrupted-global-npm-cache error. Its **existing** 1,471 Jest tests were then
run as a real baseline: **1,413 pass, 58 fail** — pre-existing failures, unrelated to anything
here, recorded so they're never mistaken for something this work broke.

**Left in place, not cleaned up:** the generated `src/components/Accordion/Accordion.test.tsx` in
the Finbook working tree (uncommitted) — a real, mostly-passing test adding coverage to a
previously-untested component. Worth knowing it's there before committing/reviewing that repo's
changes; fix the one `hidden: true` query or delete the file, whichever's preferred.

A **component-test track** (Jest + React Testing Library, generating component tests instead of
end-to-end tests) avoids every blocker in §2.2:

| | End-to-end track | Component track |
|---|---|---|
| Needs the app running | Yes | **No** |
| Needs a reset endpoint | **Yes — real apps lack one** | No |
| Needs real login/SSO | **Yes** | No |
| Needs seeded test data | **Yes** | No — props are the input |
| Runtime per test | Seconds | **Milliseconds** |
| Flake risk | Real | **Near zero** |
| Catches integration/wiring bugs | **Yes** | No |

That last row is the honest catch — component tests can't catch a broken API contract, which is
where end-to-end earns its keep. They're complements, not substitutes.

But the target app **already has the toolchain** (`jest`, `@testing-library/react`,
`user-event`) and **76 existing component test files**. So this may be the fastest route to real
value on a real repo, while §2.2's environment problems get solved in parallel.

My read (needs verification, not asserted): the planner, generator, heal loop, diff-guard and
gates carry over unchanged; mainly the executor and one role instruction file would differ.

---

## 3. Recommended order — by risk

| # | Stage | Size | Why here |
|---|---|---|---|
| 0 | **Fix silent failures** — skipped file types ✅ **done**, prompt truncation ✅ **done** (both 2026-09-08) | Small | Pure correctness. Needs no measurement, no debate, no prerequisites. **Complete.** |
| 1 | **Assess generated-test quality** (§2.1) ✅ **done** — 4/5 mutations caught; found a real defense-in-depth gap, a systematic navigation defect (33% of specs), and two tooling robustness gaps | Small | Biggest unknown. Can invalidate everything downstream. |
| 2 | **Timeboxed real-app feasibility spike** (§2.2) ✅ **done — result: NO-GO** as things stand (no local backend, real hosted Keycloak realm, no seed/session mechanism anywhere in the repo). Blocked on input only you can provide. | Medium, **timeboxed** | **Go/no-go gate.** Decided the E2E track is not viable *yet* — routes to Stage 3. |
| 3 | **Component-test track** (§2.3) ✅ **proof of concept done** — 5/6 generated tests passed on first try against real Finbook code, zero role-file changes needed. Full rollout (orchestrator wiring, heal-loop verification, harder components) still open | Medium | Only path with no environment blockers. Possibly fastest real value. |
| 4 | **Fix the measuring tape** + take a baseline (§8) ✅ **done** (2026-09-08) — real cost/tokens/prompt_chars now recorded; `verdict` checked and confirmed already working | Small | Needed to calibrate heal cycles/timeouts. Not needed to justify stage 0. |
| 5 | **The two-call experiment on US-001** (§8) ✅ **done — result: premise not supported.** Code-aware planner still planned AC-4 correctly; also found `gap` doesn't generalise to behaviour gaps | Tiny | Decided Idea 1's fate for 2 real AI calls. |
| 6 | **Portability work** (§7) ✅ **done (mechanism)** — config-driven strategy fields + prompt injection for reset/isolation, auth, and all hardcoded paths. Real Keycloak `storage_state` and reset-alternative implementations still need a real second project to build against | Medium | Required before any second target project. |
| 7 | **Browser-based element crawler** (§4) ✅ **done, built against dummy-app on request** — found and fixed two real bugs (a redirect-timing check that ran too early, and this app's auth not surviving `page.goto()` even right after login) by actually running it. Full golden-suite regression pass still recommended | Medium | Replaces per-framework source scanning. |
| 8 | **Traceability capture** (§6) ✅ **done** — both tiers (derived, measured) built and verified against real data from both tracks; found and fixed a real string-matching bug, documented a genuine structural naming-mismatch limit, live audit report answered real "no coverage"/"never generated" questions | Small | Cheap to record now while test volume is low; expensive to retrofit later. |
| 9 | **Page-scoped filtering / prompt optimisation** (§5) ✅ **done** — real measured 53% prompt-size reduction on identical input; found and fixed a real fail-open bug (one unmapped case in a batch must fail the whole batch open, not just its own share) | Small | An optimisation. Deliberately last. |

Stages 0, 1 and 5 are roughly a day combined and need nothing new built.

---

## 4. Locator discovery: read the running app, don't parse source (Option B)

✅ **IMPLEMENTED AND VERIFIED (2026-09-08) — built against `dummy-app`, on request, ahead of
Stage 2's real-app resolution.** `control-plane/crawl.js` (Node/Playwright — driving a real
browser needs a real browser-automation engine, reusing the Playwright install `dummy-app`'s own
E2E tests already depend on rather than adding a second one to the Python side) +
`control-plane/browser_crawler.py` (Python: server lifecycle, config translation, invocation).
Wired into `orchestrator.py::locate()`, replacing `testability_check.py`'s role in the pipeline
(kept as a fallback/reference, no longer in the critical path) — the staleness-hash check that
skips re-crawling when nothing changed is untouched, since a browser launch is far more
expensive than hashing files and that caching matters more here, not less.

**Two real bugs found and fixed by actually running it, not by reasoning about it in advance —
both are the exact hazard §4.2/§7.2 warned about (silently reporting the wrong page):**

1. **A timing bug.** The check for "did we land back on the login page" ran immediately after
   `page.goto()`, but this app's auth redirect fires from a `useEffect` *after* React mounts —
   later than the `load` event. The check ran before the redirect happened, so it passed, and by
   the time the element-reading code ran (after its own settle-wait) the page had already
   silently redirected. Fixed by waiting before checking, not just before reading.
2. **A deeper, real architectural fact about this app, not a bug to code around lightly:** its
   auth is in-memory-only (`useState`, no persistence) and `page.goto()` is *always* a hard
   reload — so even a **fresh, successful login followed immediately by `page.goto()` to an
   already-authenticated route bounces back to the login page.** This isn't a transient flake;
   confirmed by hitting it directly, and it's the identical root cause independently found in
   Stage 1's `ORDERS-*` test failures (33% of that generated suite). Fixed by never calling
   `page.goto()` again after the first login — every subsequent page is reached by **clicking a
   real in-app nav `<Link>`** (`page.getByRole("link", {name: ...}).click()`), exactly like a
   real user would, which preserves the client-side React state a full navigation would wipe.

**A third finding, a genuine capability gain, not a bug:** verified `ariaSnapshot()` does **not**
expose `data-testid` (resolves the open question flagged earlier), and the legacy
`page.accessibility.snapshot()` API isn't available in the installed Playwright version either.
Facts are computed via direct per-element DOM queries instead — `getAttribute("data-testid")`,
a small accessible-name computation chain (aria-label → aria-labelledby → associated `<label>` →
own text content), and Playwright's own `.isVisible()` for real visibility — giving full control
per element rather than trying to merge two different data sources.

**Real, verified output quality:** the full crawl → `qa-locator-explorer` → `locator-map.json`
pipeline ran live end-to-end. Notably, the AI correctly noticed the item list's "Delete" button
(no `data-testid`) has its role+name **duplicated across rows** and downgraded it to
`flagged-unstable` with an accurate note explaining why a role-based fallback can't disambiguate
which row it targets — a real quality improvement the old static-scan facts couldn't have
supported at all (they carried no "is this name unique on the page" signal).

**Not done as part of this:** the full golden-task suite (`tests/golden/run_all.py`) was not
re-run against this change — `locate()` was verified thoroughly standalone, live, but a full
regression pass against all 7 scenarios is a recommended follow-up before treating this as fully
proven for the whole pipeline, not just the locate phase in isolation. Also not built: this
implementation is dummy-app-specific in one respect beyond config — `crawl.js` only knows the
`form_login` auth strategy (matching Stage 6's config field), so it cannot itself attempt
anything against a `storage_state`/Keycloak-style target; that remains exactly where Stage 2 left
it.

**Decision unchanged, mechanism now real — the choice itself was demoted to stage 7 and
conditional on stage 2, then built anyway on request ahead of that resolving.**

Three approaches were weighed:

- **Option A — a source-code scanner per framework/app.** Rejected. "Any web framework" means a
  separate reader for React/JSX, Vue SFCs, Angular templates, Svelte, *plus* every server-rendered
  flavour (Django/Jinja, ERB, Blade, JSP, Thymeleaf, Razor), *plus* older code that builds elements
  in JavaScript at runtime. A dozen jobs, permanently behind whatever the next project picks.
- **Option B — one-shot browser snapshot per page. ✅ Recommended.** Every framework ends up as
  ordinary HTML in a browser. Visit each page with Playwright (already a dependency, already how
  tests run) and read what's actually there. One mechanism, every framework, no
  framework-specific code.
- **Option C — an AI drives a live browser to author each test.** Rejected for now on cost: it
  turns one prompt into a long tool loop, needs the app running with real data and a real login
  *during authoring*, and trades determinism for accuracy. Its one real advantage — verifying a
  locator resolves *before* writing it — is worth revisiting **only if stage 1/7 data shows
  selector failures are common**.

### Why Option B is better, not just cheaper

- **Page attribution is exact and free.** You navigated to `/cart`, so what you found is on
  `/cart`. This deletes the original proposal's "route registry" catalogue entirely.
- **The browser computes accessibility for real**, rather than the current approach of inferring
  it from source. That's what the "has a test ID / has a reliable label / can't be targeted"
  tiering depends on.
- **Dynamically-created elements stop being a special case** — today's guessing heuristic exists
  only because static reading can't see them.
- **Server-rendered apps get easier, not harder.**

### Honest trade-offs

- **Needs the app running** — already true; the test config starts it.
- **Needs a list of pages to visit** — a small hand-written config (~10 lines), far cheaper than
  parsing every framework's router.
- **Only sees the state you drive it to** — modals, error and empty states need explicit steps.
  (Source-reading has the mirror flaw: sees everything, knows nothing about reachability.)
- **Needs a working login** — see §7.2. On the real target this is a hard wall, not a detail.
- **Slower** — seconds per page, not milliseconds. Still no AI cost, and only re-run for changed
  pages.
- **Loses source-file attribution** per element — §5 deals with that.

### Unverified technical assumption — spike before relying on it

Playwright's `ariaSnapshot()` (needs **≥1.49**; test app pins `^1.47`, real target `^1.62`)
returns an accessibility tree. I do **not** believe it includes `data-testid`, so capturing test
IDs likely needs a second DOM query, and `aria-hidden` elements won't appear at all. **Half-hour
spike to confirm** before treating this as settled.

### Reference: how alike are the test app and the real target?

| | Test app | Real target |
|---|---|---|
| React / Router / TypeScript | 18.2.0 / 6.3.0 / 4.6.4 | **identical** |
| Build tool | Vite | react-scripts (CRA) |
| State management | React Context | Redux Toolkit |
| UI library | none | MUI |
| **Auth** | in-app form, in-memory | **Keycloak SSO** — see §7.2 |

The framework match validates the crawler mechanics. Build tool, state library and UI kit
differences don't matter to a browser-based approach — that's the point of Option B. **Auth is
the one difference that does.**

---

## 5. Impact mapping: "which pages does this change affect?" — keep it dumb

✅ **STAGE 9 DONE (2026-09-08) — implemented as page-scoped prompt filtering, verified with a
real, directly-comparable before/after measurement.** `traceability.py::resolve_routes_for_files`
(new — the reverse of Stage 8's `route_source_files` lookup) filters the locator map embedded
in the `plan` phase's prompt down to only the routes the changed files actually touch;
`derive_routes_for_case` (already built for Stage 8) does the equivalent for `generate`, scoped
to which routes the plan's own cases reference. `review` deliberately stays unfiltered — it's a
holistic judgment over everything, not a per-change task.

**Real measurement, not an estimate:** re-ran the *exact* input from an earlier verification
call (`--changed-files dummy-app/src/pages/LoginPage.tsx`) before and after this stage.
`prompt_chars` dropped from **18,979 to 8,965 — a 53% reduction** — for byte-identical input,
purely from sending 1 route's locator data instead of 5. Real dollar cost barely moved
($0.1303 → $0.1304), because at this tiny scale (5 routes, one small app) caching and output
tokens dominate cost far more than input size does — but the raw prompt-size number is exactly
the deterministic, tokenizer-independent evidence Stage 4 was built to capture, and it would
matter far more once an app has dozens of routes instead of five.

**A real correctness bug found and fixed by testing this against the actual, messy
stage1-quality plan (20 real cases, several already known-unmapped from Stage 8) — not by
reasoning about it in the abstract:** the initial `generate`-phase filter took the *union* of
routes matched across all cases in a batch, and failed open only if that union came back
empty. But a batch with **some** matched cases (e.g. `LOGIN-*`, `ITEMS-E01-04`) and **some**
genuinely unmapped ones (e.g. `ORDERS-*`, from Stage 8's already-documented crawler gap) would
silently narrow the whole prompt to only the matched cases' routes — stripping locator context
from exactly the cases that most needed it, since they still have to be generated. Fixed: **one
unmatched case fails the entire batch open**, not just its own share of it. Verified both paths
live: a batch with a genuine gap correctly sends the full map; a fully-matched batch (only
`LOGIN-*` cases) still correctly narrows to 1 of 5 routes.

Since Option B doesn't know which source file produced an element, this needs answering another
way. **Recommendation: folder convention plus a small config override. Nothing more.**

```
src/pages/CartPage.tsx    → /cart
src/pages/ItemsPage.tsx   → /items
src/components/Cart*.tsx  → /cart
```

Most apps already encode this in their folder structure. Where convention is wrong, add an
override line.

**Correcting an earlier overstatement:** I previously described a config-declared mapping as
having "nothing to go wrong silently." That was wrong, by this project's own standard. A
hand-maintained map goes stale silently — someone adds a component and forgets the config, the
filter under-selects, and the planner is quietly starved of element information. So it needs:

- **Fail open** — an unmapped changed file means "send everything / run everything," never
  "send nothing."
- **Warn on every unmapped file**, so staleness is visible rather than silent.

**Later upgrade, if needed:** measure it instead of declaring it — record which source files each
page/test actually exercised (coverage instrumentation). That's empirical rather than a guess, and
§6 needs it anyway.

### Why graphify was dropped

I recommended it earlier; that was premature. Four reasons:

1. **Its main job serves two weak consumers.** A dependency graph feeds prompt filtering (now
   stage 9, an optimisation) and test selection (worthless today — the real target has **3
   tests**; selection only pays at hundreds).
2. **Coverage beats a graph for the job that matters.** A dependency graph says what a page
   *could* reach; coverage says what a test *actually* exercised. Real test-impact-analysis
   systems use coverage. And §6 needs coverage regardless — at which point the graph is redundant.
3. **It adds real complexity to the layer this project deliberately keeps thin.** The control
   plane's only dependency today is `jsonschema`. That thinness is what makes the deterministic
   layer portable. Also: node IDs derive from file paths, so **renaming a file silently breaks
   traceability** — precisely the silent-failure signature this project keeps eliminating. And you
   still write a query layer, so it's "own a dependency" traded for "write a parser."
4. **No evidence it works here yet.** The one graphify artefact in the target repo is 1.3 KB with
   **zero edges** (a service-topology export, empty for that repo). Adopting it starts with
   debugging it.

**Revisit only when measured, not assumed:** convention+config demonstrably insufficient (with
logged misses); or hundreds of tests plus coverage-based selection still missing impacts; or you
want codebase Q&A for humans — a genuinely good use, but a different project, not this pipeline.

---

## 6. Traceability: requirement → test case → test script → module

✅ **DONE (2026-09-08) — built and verified against real data from both tracks (dummy-app E2E
and Finbook component tests).** `control-plane/traceability.py` — control-plane-owned, like
`manifest.py`, never AI-written. Wired into `orchestrator.py::_run_generate_phase` so capture
happens automatically as each test is born, per this section's own "why record it now."

**"Derived" tier — real problems found and fixed by running it against real `plan.json` data,
not by designing it in the abstract:**

1. **Exact string matching was too brittle for real data.** `plan.json`'s `selectors` are
   frequently not a clean literal testId — templated patterns like `item-edit-{id}` (the
   planner describing a per-row element abstractly) and messy descriptive entries like
   `item-delete-button (flagged-unstable: getByRole(...))` (explaining a role-fallback case
   inline) both appeared in real output. Fixed with a prefix match (cut at the first
   `{`/`(`/whitespace) checked in both directions against the crawled map's `testId` **and**
   `name` fields.
2. **A genuine, structural limitation, found rather than assumed — not something to chase with
   fuzzier heuristics.** `plan.json` (from `qa-test-planner`) and `locator-map.json` (from
   `qa-locator-explorer`) are two *independent* AI calls, and for role-fallback elements with no
   `testId` to anchor them, each is free to invent its own semantic name for the same real
   element — confirmed live: the planner wrote `sort-toggle-button`, the locator map recorded
   `sort-az-button`, for the identical button. No shared naming authority exists between the two
   calls. Documented as a real limit of the "derived" tier rather than papered over — this is
   exactly why "measured" exists as the stronger, self-correcting layer above it.
3. **Real output, live-verified against 20 real planned cases:** `ITEMS-E01/02/03/04` and
   `LOGIN-E01/02` correctly derived their real modules (`ItemsPage.tsx`, `server.js`, etc.);
   several `ITEMS-*`/`ORDERS-*` cases were honestly reported `unmapped` — not a bug, but the
   direct, correctly-surfaced consequence of Stage 7's own documented limitation (the crawler's
   one-shot default-state snapshot never saw populated order rows or an open delete-confirm
   dialog, so those testids never entered the locator map at all to match against).

**"Measured" tier — demonstrated for real, not just designed.** Added
`executor.py::run_jest(with_coverage=True)` and `parse_jest_coverage()` (Jest's own
`--collectCoverage --coverageReporters=json-summary`, verified live: the summary lists every
instrumented file in the whole project — thousands — almost all at zero; filtering
`statements.covered > 0` cleanly isolates exactly the one real file a test touches, no further
heuristics needed). Ran a real coverage-instrumented pass of Stage 3's `Accordion.test.tsx` and
called `record_measured()`: all 6 cases correctly promoted from `unmapped` (dummy-app's
route-based "derived" tier doesn't apply to Finbook at all — no locator-map exists for it) to
`measured`, with the real, single correct file (`Accordion.tsx`). Also verified the "prefer
measured thereafter" self-correction rule holds: re-running `record_generate()` afterward does
**not** regress a measured entry back to derived/unmapped.

**Real, live audit output** (`traceability.py`'s `report()`, run against the real 20-case
dummy-app batch): correctly flagged **all 5 `CART-*` cases as never generated** (the real app
defect Stage 1 found — the Add-to-Cart button is unreachable), **9 `ITEMS-*`/`ORDERS-*` cases
as unmapped** (Stage 7's default-state crawl limitation, honestly surfaced rather than hidden),
and **`ProfilePage.tsx` as a module with zero test coverage at all** in this batch — exactly the
"which modules have no coverage" question this section set out to answer, with a real, concrete
answer instead of a hypothetical one.

**Not done:** selection was not switched on (per this section's own reasoning — the real target
has too few tests for it to pay off yet); the safety rails below remain designed, not built,
since there's nothing yet to gate.

Worth capturing, and it's the strongest of the newer ideas — but **build the recording now,
switch the payoff on later.**

**The chain:** already half-built. `generate.json` records `caseId → specPath`. The missing edge
is `test case → module/files`.

**How to establish that edge — and this matters:**

| How | Trust | Available |
|---|---|---|
| The planner asserts it | AI's word about its own work — weakest | Plan time |
| **Derived** — case → its `selectors` → page → files (via §5's mapping) | Plain code | Before the test runs |
| **Measured** — record coverage when the test runs | **Ground truth** | After first run |

**Recommendation: derive at creation, measure at first run, prefer measured thereafter.** Same
"declare, then verify" pattern the diff-guard and manifests already use — so the mapping
self-corrects instead of decaying.

**Architecture rule:** keep the traceability index as the control plane's **own** artefact
(`state/traceability.json`), never written by an AI, and referencing external IDs rather than
being stored inside another tool's graph. Same principle as the existing manifests.

**Why record it now:** capturing traceability as each test is *born* is cheap; retrofitting it
onto hundreds of already-generated specs is not.

**Why not switch on selective test runs yet:** the real target has 3 tests. Selection saves
nothing until the suite is large. Good news — `executor.run_playwright(spec_paths=...)` **already
runs a subset** (it's how heal cycles re-run only failing specs), so the plumbing exists.

**Safety rails, when selection is eventually enabled** — because the failure mode is *silently
skipping a test that would have caught a bug*:

- **Fail open** — anything unmappable runs everything.
- **An always-on core suite** regardless of impact analysis.
- **Explicit fail-open triggers:** new/renamed files, dependency or lockfile changes, config
  changes, migrations.
- **Periodic full runs that grade the selector** — did the full run catch anything the subset
  missed? That comparison is the only thing that earns trust in selection.
- **Report every skip**, never silently.

**Possibly worth more than the time saved:** the target is a finance app, so
requirement→test→code traceability may carry audit value — plus it answers questions you can't
answer today: which acceptance criteria have no test, which modules have no coverage, and "this
PR touches a module covered only by low-priority tests."

---

## 7. Portability blockers (required before a second target project)

✅ **STAGE 6 DONE (2026-09-08) — the generic mechanism for all three, built and verified against
`dummy-app`.** As flagged when Stage 3 was paused: this could be *built* without live Finbook
access — only its real-world proof against Finbook stays deferred. What actually shipped:

- **`config/project.json` gained two new declarative sections**, `test_isolation` and `auth`,
  each with a `strategy` field plus the details that strategy needs (a `reset_call` for
  `reset_endpoint`; a `login_route` + three testids for `form_login`). For `auth`, credential
  *values* are separated from the strategy shape via a `test_credentials` sub-object, with a
  comment noting a real project should point these at env var names instead of committing real
  credentials — dummy-app's are fine as literals since they're already public fixture data.
- **A new shared `util.py::project_context_block()`** renders these config facts as a plain-text
  block, and is now injected into **every** AI-facing prompt in the pipeline: `_build_prompt()`'s
  `plan`/`generate`/`review` branches, `locate()`'s prompt, and — the one that needed a real
  fix, not just an addition — `heal_loop.py`'s healer prompt, which previously named only the
  one spec path to fix and relied entirely on the role file's own (hardcoded) text for the
  never-touch-baseline boundary.

  Lives in `util.py`, not `orchestrator.py`, specifically because `orchestrator.py` imports
  `heal_loop`, so `heal_loop.py` importing back from `orchestrator.py` would be circular — first
  version of this lived in `orchestrator.py` and had to be moved once the healer-prompt gap was
  found.
- **All four role files that hardcoded `dummy-app/...`** (`qa-test-planner.md`,
  `qa-test-generator.md`, `qa-locator-explorer.md`, `qa-test-healer.md`) now reference "the
  [generated tests / baseline / source] directory named in the Project Context block" instead of
  a literal path — verified clean via `grep -rni "dummy-app" roles/*.md` (zero matches).
- **Bonus fix, same root cause, different layer:** `testability_check.py::_default_paths()` had
  the identical hardcode in deterministic code (not a role file) — `ROOT / "dummy-app" / "src"`.
  Now reads `config/project.json`'s new `app_source_dir` field instead. Verified: still finds
  exactly the same 20 files as before the refactor.
- **Verified end-to-end with one real, live call** (`--phase plan` against a throwaway task,
  cleaned up after) — schema-valid plan produced successfully with the new context block in
  place and the rewritten role file in effect, not just a static/offline check.

**What Stage 6 deliberately did NOT build:** an actual working Keycloak `storageState`
mechanism, or a real reset-endpoint alternative implementation. Those need a real second project
to build *against* (Finbook, once Stage 2/3's pause lifts) — building them speculatively against
no real target would be guessing at a shape that might not fit. What shipped here is the
*plumbing* a real integration would plug into: pointing this at a second project is now a config
edit (`test_isolation.strategy`, `auth.strategy`, the four path fields), not a role-file rewrite.

### 7.1 No reset endpoint on real apps

Replacements, declared per project in config (the `test_isolation.strategy` field, now real):
- Each test creates its own uniquely-marked data and cleans up (most portable; needs creation
  APIs).
- A dedicated test environment with a seeded database, reset per run rather than per test.
- Setup via the app's own APIs before each test.

The AI role instructions no longer hardcode a reset call — they reference whatever
`test_isolation.strategy` says, and are told explicitly to report a finding rather than guess
when the strategy isn't `reset_endpoint`.

### 7.2 Real logins — and this can block the crawl, not just inconvenience it

The real target uses external SSO (§2.2). Without handling it, the crawler visits a protected
page, gets redirected to the identity provider's login screen, and **silently reports that page's
fields as if they belonged to the app** — a wrong answer that looks right.

**Standard fix** (Playwright's own recommended pattern): log in once against a test account, save
the authenticated session to a file, reuse it for every later visit. One-time setup per app, not
per page or per run. **Not yet built** — the config `strategy` field and role-file fallback text
exist (say so as a finding, don't guess, when the strategy isn't `form_login`), but a real
`storage_state`-based implementation needs a real target to build against.

**This is unavoidably per-app work under any locator approach** — a source scanner can't tell what's
reachable without a working login either. So it argues for treating "can we reliably reach a
logged-in state" as its own explicit, verified setup step — never assumed.

**Hard rule:** if the saved session is missing, expired, or fails, the crawl **stops loudly**. It
never falls back to crawling whatever page it landed on.

### 7.3 Project paths are hardcoded into the AI instructions

✅ Fixed above — all four role files plus one deterministic-code equivalent
(`testability_check.py`) now read paths from `config/project.json` via the shared
`project_context_block()`, instead of a literal `dummy-app/...` string.

---

## 8. Kept from the original proposal

- **Fix the measuring tape.** ✅ **DONE (2026-09-08).** The log meant to prove all this works was
  recording **the AI's own guess** at its token usage (`envelope.metrics.tokens`), while the
  real figures the CLI wrapper actually reports (`total_cost_usd`, `usage.*`, `num_turns`) were
  parsed in `invoke.py::_parse_envelope` and then discarded. Prompt size wasn't recorded at all.

  Fixed: `invoke.py::_extract_usage()` (new) pulls the real `cost_usd`, `input_tokens`,
  `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, and `num_turns`
  straight from the CLI wrapper — verified field names against a real live `claude -p
  --output-format json` call first, not assumed. `ledger.record()` gained those fields plus
  `prompt_chars` (deterministic, always available — the direct measure of what any future
  prompt-filtering work would actually change), wired into all five `ledger.record()` call sites
  in `invoke.py` (success, schema-invalid, JSON-parse-failed, repair-attempted, timeout). The old
  `tokens` field is kept for backward compatibility but its docstring now says plainly it's
  unreliable — confirmed live: a real call's `tokens` came back `null` while its real `cost_usd`
  was `$0.1322` and `output_tokens` was `2310`. The AI simply doesn't populate its own metric.

  **A correction to an earlier assumption of mine, checked rather than left as "fixed":** I had
  flagged `envelope.get("verdict")` as "likely always null" in an earlier draft. Checked
  `roles/qa-reviewer.md` — it explicitly instructs the model to duplicate `verdict` at both the
  envelope's top level and inside `result` — then verified live: a real review call correctly
  produced `"verdict": "REFACTOR"` in the ledger. **Not a bug. Left alone**, since it already
  worked and "fixing" it would have been pure risk for no benefit.

  **Baseline reading:** rather than run several full, costly pipeline passes purely to pad the
  ledger, used the real calls Stage 1 already made today as the dataset, plus one fresh `review`
  call (against Stage 1's existing `plan.json`/`generate.json` — no new pipeline run needed) to
  get one fully-fielded example post-fix:

  | Phase | Role | Status | Duration | Cost | Prompt chars |
  |---|---|---|---|---|---|
  | locate | qa-locator-explorer | completed | 99.3s | *(pre-fix)* | *(pre-fix)* |
  | plan | qa-test-planner | failed → completed | 62.3s / 61.3s | *(pre-fix)* | *(pre-fix)* |
  | generate | qa-test-generator | repair→failed→completed | 271.7s / 349.2s / 82.7s | *(pre-fix)* | *(pre-fix)* |
  | review | qa-reviewer | completed | 28.0s | **$0.1322** | **30,669** |

  The six pre-fix rows lack the new fields (recorded before this fix landed today) — left as-is
  rather than backfilled, since they're genuine historical data, not broken. Going forward, every
  new invocation gets the real figures automatically. This is a start, not a finished calibration
  data set — deferred item 11 (tune `max_heal_cycles`/timeouts from real history) still needs
  many more real runs to accumulate before it's trustworthy; this stage only fixed the instrument.
- **Make silent failures loud.** An over-long prompt is currently **cut off mid-sentence with no
  warning**. On a real app the element list would be halved invisibly. This reframes Idea 2 from
  "saves money" to "the planning step is quietly broken on real apps."
- **Test Idea 1's assumption before building it.** ✅ **DONE (2026-09-08) — the assumption did
  not hold in this experiment.** Idea 1's premise: a planner shown the code will silently skip
  planning tests for requirements that aren't implemented yet. Tested for real: built two
  otherwise-identical prompts to `qa-test-planner` from a sanitised version of
  `user-stories/US-001.md` (its ✅/❌ status markers and meta-commentary stripped, so neither
  variant was told outright which ACs were implemented) — Variant A included the real
  `server.js` + `ItemsPage.tsx` source, Variant B did not. Both called via `invoke()` directly
  (bypassing the orchestrator, so no pipeline state was touched — only two real, isolated
  ledger entries).

  **Result: Variant A (with code) planned essentially the same AC-4 case as Variant B (no
  code)** — both a P0 `negative` case expecting `DELETE /api/items/:id` to return `403` with the
  "cannot delete" message, and both a `regression-impact` follow-up case. **Despite being shown
  the real `server.js` handler that deletes unconditionally with no order check at all**, the
  code-aware planner still wrote a test asserting the *requirement's* behaviour, not the code's
  actual behaviour. It did not silently drop or water down AC-4.

  **This is real evidence against Idea 1's core justification, at least for this model and this
  scale of task** — not proof it never happens, but the specific failure mode motivating "hide
  the code from the planner" did not occur when tested. Cost was comparable either way
  (Variant A $0.1478 / 29,542 prompt chars vs. Variant B $0.1075 / 18,345 prompt chars, 1 turn
  each — real figures, courtesy of Stage 4's fix). **Recommendation: don't build the
  hide-the-code architecture on the strength of the original justification.** If US-001-style
  gaps turn out to matter for a different reason (e.g. traceability, or keeping the planner's
  attention on requirements at real-app scale where the code is much larger), that's a different
  argument and should be tested on its own terms, not assumed from this premise.

- **A second, more important finding, found while designing the experiment:** the plan format's
  `gap` boolean does **not** work for AC-4-style requirement gaps at all, which corrects an
  earlier recommendation of mine below. Its own schema description is scoped narrowly to *"true
  if a required selector does not exist yet"* — and it worked exactly as designed for AC-5's
  missing `cart-price-summary` UI element (both variants correctly set `gap: true` for that
  case). But AC-4's gap is a **missing backend behaviour**, not a missing selector — every
  selector AC-4's test needs (`item-delete-button`, `confirm-delete-button`, `toast-notification`)
  already exists — so both variants correctly, per the schema's actual definition, set
  `gap: false` on their AC-4 case even though the feature itself is unimplemented. **`gap` cannot
  be the general "requirement not built" signal** — it only covers one narrow sub-case (missing
  UI anchor) of a broader problem. The "forgot to build it" bullet immediately below needs
  revising in light of this.
- **Don't hide the code from the planner completely.** The system's own test-type list includes
  "this change might have broken something else" — unplannable if the planner knows nothing about
  what changed. Give it the story **plus a short factual summary** of changed files and affected
  pages, not the code itself. (Somewhat moot now — the experiment above found no evidence the
  code needs hiding at all.)
- **Corrected: "use the `gap` flag for 'forgot to build it'" doesn't generalise.** ~~The plan
  format already has a boolean meaning "this test needs something that doesn't exist yet."~~ As
  the finding above shows, `gap` only fires for a missing *selector*, not a missing *behaviour* —
  AC-4 proves the two are different things and `gap` only covers the first. For a backend-behaviour
  gap like AC-4, the original proposal's slower path (plan → generate a real test → execute → it
  fails → `qa-failure-triage` classifies it `product-bug` → escalate, never healed) is the
  mechanism that actually works, and Stage 1 already demonstrated it live (`ITEMS-E08` against
  the same AC-4). Recommend keeping that as the one mechanism for missing-requirement detection,
  rather than trying to extend `gap`'s scope to cover something its schema wasn't built for.

---

## 9. What I'd deliberately not build

| Not building | Why |
|---|---|
| A source-code scanner per UI framework/app | Doesn't survive "any framework," and doesn't dodge the login problem either. Reconsidered once and still rejected: login is per-app work under *either* approach, so a scanner solves a problem you needn't have while leaving the real one untouched. |
| Route/router config parser | Redundant — crawling a page tells you the page (§4). |
| Import-dependency tracer | Least portable part of the original plan; convention or coverage does the job (§5). |
| **Graphify integration** | Reversed from an earlier recommendation — see §5. Premature for this pipeline; genuinely useful as a separate codebase-comprehension tool. |
| Guessing which pages a story is about from its wording | Fails dangerously: under-guess and the planner is quietly starved of element info. |
| API-contract catalogue | Lowest value, and the real target appears frontend-only — its backend may not be in that repo. |

---

## 10. Rules to hold throughout

- **Never touch the AI-vendor adapter layer** — that's what keeps switching AI backends cheap.
- **All crawling, mapping and filtering stays plain code, no AI** — free, repeatable, reviewable.
- **The seven acceptance tests stay green at every stage.** They're the only proof the safety
  mechanisms work. *Check early:* some reference the old plain-HTML app, which has now been
  replaced by a React SPA.
- **Nothing may fail quietly.** A skipped page, an unmapped file, a truncated prompt, a dropped
  test. Every bug found in this project so far was something that failed silently.
- **Don't build ahead of a consumer that exists today.** This has now caught three proposals
  (the locator map's importance, the four catalogues, graphify). Worth asking of every stage.

---

## 11. Open items

1. **Scope confirmed:** web applications only. Native mobile/desktop would need different
   automation, a different test format, and a different runner — a separate project.
2. **Where is the real target's backend?** Decides whether an API-contract catalogue is even
   possible. Its `src/` is frontend-only.
3. **Does `ariaSnapshot()` expose `data-testid`?** Half-hour spike (§4).
4. **Is the component-test track worth pursuing first?** The biggest open strategic question
   (§2.3) — it sidesteps every environment blocker.
