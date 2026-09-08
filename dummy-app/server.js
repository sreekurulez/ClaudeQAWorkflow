// server.js — Express backend for qa-workflow-dummy-app (v0.2).
// Serves the built React SPA from dist/ as static files, plus all API routes.
// The integration contract (port 4000, node server.js, POST /api/__test__/reset,
// SEED_BUG=1 flag) is unchanged from v0.1 — golden scenarios continue to pass.
//
// API surface (Catalog 4 — API contract index):
//   Auth group:
//     POST   /api/login                    200, 401
//     POST   /api/logout                   200
//   Items group:
//     GET    /api/items?q=&sort=           200, 401
//     GET    /api/items/:id               200, 404
//     POST   /api/items                   201, 400
//     PUT    /api/items/:id               200, 400, 404
//     DELETE /api/items/:id               204, 403  ← 403 if pending order (see US-001 AC-4)
//   Orders group:
//     GET    /api/orders                   200, 401
//     GET    /api/orders/:id              200, 404
//     POST   /api/orders                  201, 400
//     PUT    /api/orders/:id/cancel       200, 400, 404
//   Test-only:
//     POST   /api/__test__/reset          204

const express = require("express");
const path = require("path");

const app = express();
app.use(express.json());

// ── Static files ─────────────────────────────────────────────────────────────
// Serve the built React SPA. dist/ is produced by `npm run build` (vite build).
app.use(express.static(path.join(__dirname, "dist")));

// ── In-memory state ──────────────────────────────────────────────────────────
const USERS = [{ email: "user@example.com", password: "password123" }];

let ITEMS = [
  { id: 1, name: "First item", price: 9.99 },
  { id: 2, name: "Second item", price: 14.99 },
];
let nextItemId = 3;

// Orders: each references an item by id. Used for the US-001 AC-4 "pending order" check.
let ORDERS = [];
let nextOrderId = 1;

function seedState() {
  ITEMS = [
    { id: 1, name: "First item", price: 9.99 },
    { id: 2, name: "Second item", price: 14.99 },
  ];
  nextItemId = 3;
  ORDERS = [];
  nextOrderId = 1;
}

// ── Auth ─────────────────────────────────────────────────────────────────────

app.post("/api/login", (req, res) => {
  const { email, password } = req.body || {};
  const ok = USERS.some((u) => u.email === email && u.password === password);
  if (!ok) return res.status(401).json({ error: "invalid credentials" });
  res.json({ token: "dummy-session-token" });
});

app.post("/api/logout", (_req, res) => {
  res.json({ message: "logged out" });
});

// ── Items ────────────────────────────────────────────────────────────────────

// GET /api/items?q=<search>&sort=<asc|desc>
app.get("/api/items", (req, res) => {
  const { q, sort } = req.query;
  let result = [...ITEMS];

  if (q) {
    result = result.filter((i) =>
      i.name.toLowerCase().includes(String(q).toLowerCase())
    );
  }

  // SEED_BUG=1 — intentional: drops the last matching item.
  // Golden scenario 3 (no-progress breaker) depends on this remaining unfixed.
  if (process.env.SEED_BUG === "1" && result.length > 0) {
    result = result.slice(0, -1);
  }

  if (sort === "asc") {
    result.sort((a, b) => a.name.localeCompare(b.name));
  } else if (sort === "desc") {
    result.sort((a, b) => b.name.localeCompare(a.name));
  }

  res.json(result);
});

// GET /api/items/:id
app.get("/api/items/:id", (req, res) => {
  const id = Number(req.params.id);
  const item = ITEMS.find((i) => i.id === id);
  if (!item) return res.status(404).json({ error: "not found" });
  res.json(item);
});

// POST /api/items
app.post("/api/items", (req, res) => {
  const { name, price } = req.body || {};
  if (!name) return res.status(400).json({ error: "name required" });
  const item = { id: nextItemId++, name, price: price || 0 };
  ITEMS.push(item);
  res.status(201).json(item);
});

// PUT /api/items/:id
app.put("/api/items/:id", (req, res) => {
  const id = Number(req.params.id);
  const { name, price } = req.body || {};
  if (!name) return res.status(400).json({ error: "name required" });
  const item = ITEMS.find((i) => i.id === id);
  if (!item) return res.status(404).json({ error: "not found" });
  item.name = name;
  if (price !== undefined) item.price = price;
  res.json(item);
});

// DELETE /api/items/:id
// NOTE: deliberately does NOT check for pending orders before deleting.
// This is the unimplemented feature for US-001 AC-4 (see dummy-app/user-stories/US-001.md).
// AC-4 requires: "Deleting an item that is referenced by a pending order must be blocked."
// The endpoint currently deletes unconditionally — this is the intentional gap.
app.delete("/api/items/:id", (req, res) => {
  const id = Number(req.params.id);
  ITEMS = ITEMS.filter((i) => i.id !== id);
  res.status(204).end();
});

// ── Orders ───────────────────────────────────────────────────────────────────

// GET /api/orders
app.get("/api/orders", (_req, res) => {
  res.json(ORDERS);
});

// GET /api/orders/:id
app.get("/api/orders/:id", (req, res) => {
  const id = Number(req.params.id);
  const order = ORDERS.find((o) => o.id === id);
  if (!order) return res.status(404).json({ error: "not found" });
  res.json(order);
});

// POST /api/orders — creates a new order for an item
app.post("/api/orders", (req, res) => {
  const { itemId, quantity } = req.body || {};
  if (!itemId || !quantity) {
    return res.status(400).json({ error: "itemId and quantity required" });
  }
  const item = ITEMS.find((i) => i.id === Number(itemId));
  if (!item) return res.status(400).json({ error: "item not found" });
  const order = {
    id: nextOrderId++,
    itemId: Number(itemId),
    itemName: item.name,
    quantity: Number(quantity),
    status: "pending",
  };
  ORDERS.push(order);
  res.status(201).json(order);
});

// PUT /api/orders/:id/cancel
app.put("/api/orders/:id/cancel", (req, res) => {
  const id = Number(req.params.id);
  const order = ORDERS.find((o) => o.id === id);
  if (!order) return res.status(404).json({ error: "not found" });
  if (order.status !== "pending") {
    return res.status(400).json({ error: "only pending orders can be cancelled" });
  }
  order.status = "cancelled";
  res.json(order);
});

// ── Test-only reset ──────────────────────────────────────────────────────────
// Called by every E2E spec's beforeEach for test isolation (see auth-login.spec.ts).
// Must return 204. Must restore the exact seed data above.
app.post("/api/__test__/reset", (_req, res) => {
  seedState();
  res.status(204).end();
});

// ── History-API fallback ─────────────────────────────────────────────────────
// For any non-API GET, serve the SPA's index.html so React Router handles routing.
// This must come after all /api/* routes.
app.get("*", (req, res) => {
  if (!req.path.startsWith("/api")) {
    res.sendFile(path.join(__dirname, "dist", "index.html"));
  }
});

// ── Start ─────────────────────────────────────────────────────────────────────
const PORT = process.env.PORT || 4000;
if (require.main === module) {
  app.listen(PORT, () => console.log(`dummy-app listening on :${PORT}`));
}
module.exports = app;
