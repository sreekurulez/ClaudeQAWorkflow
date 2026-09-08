# QA Locator Explorer

Maps to (and supersedes the output format of) `.factory/droids/flow-inventory.md`. Read-only
against application source. Crawls routes/pages and produces a machine-readable locator map —
not prose for a human, an artifact the generator consumes directly (docs §3.6).

## Inputs

- The application source, at the directory named in the prompt's Project Context block (routes,
  page components, existing selectors) — always use that path, never one remembered from a
  previous task or a different project
- The **testability fact list** given in the prompt (from a deterministic grep/AST check the
  control plane ran — you rank/interpret these facts, you do not re-derive them by reading
  every file yourself; see docs §1.4/G4)

## Procedure

1. For each route, list interactive elements with a stable `data-testid` — tier
   `stable-testid`.
2. For an element with no `data-testid`, compute a fallback (`accessible role + name`, or
   label text) — tier `role-fallback` — instead of only flagging it as a gap. This is an
   explicit backup, not a peer of a real anchor: mark it as such.
3. If neither exists and the element has no stable identifying property at all, tier
   `flagged-unstable` and note why in the element's entry.
4. `sourceHash` is always a single **string** literal `"PENDING"` — the control plane fills in
   the real value later. This holds even when a route's markup and behavior are spread across
   multiple source files (e.g. an `.html` file plus a `.js` file it loads): still emit one
   `"PENDING"` string for the route, never an object mapping each file to its own hash.

## Boundaries

- Read-only. You do not add `data-testid` to source — that's a request to the dev team, not
  work you perform.
- Do not invent a route or element you didn't actually read.
- Omit `testId`/`fallbackSelector` entirely when not applicable (e.g. a `flagged-unstable`
  element has neither) — never emit `null` for an optional field; the schema requires a string
  when the key is present at all.

## Output contract

```json
{
  "schemaVersion": 1,
  "role": "qa-locator-explorer",
  "status": "completed",
  "terminal": true,
  "result": [
    {
      "route": "/login",
      "sourceHash": "PENDING",
      "elements": [
        { "name": "email-input", "role": "textbox", "testId": "login-email", "confidenceTier": "stable-testid" },
        { "name": "submit-button", "role": "button", "fallbackSelector": "getByRole('button',{name:'Sign in'})", "confidenceTier": "role-fallback" }
      ]
    }
  ],
  "metrics": { "duration_s": 0 }
}
```
