// Minimal in-memory app: auth + item CRUD. Just enough surface to plan/generate/execute/heal
// real E2E cases against (see ../README.md). Not production code — no password hashing, no
// persistence; that's out of scope for what this project is testing.
const express = require("express");
const path = require("path");

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

const USERS = [{ email: "user@example.com", password: "password123" }];
let ITEMS = [
  { id: 1, name: "First item" },
  { id: 2, name: "Second item" },
];
let nextId = 3;

app.post("/api/login", (req, res) => {
  const { email, password } = req.body || {};
  const ok = USERS.some((u) => u.email === email && u.password === password);
  if (!ok) return res.status(401).json({ error: "invalid credentials" });
  res.json({ token: "dummy-session-token" });
});

app.post("/api/logout", (req, res) => {
  res.json({ message: "logged out" });
});

app.get("/api/items", (req, res) => {
  const q = req.query.q;
  let result = ITEMS;
  if (q) {
    result = result.filter(i => i.name.toLowerCase().includes(q.toLowerCase()));
  }
  
  if (process.env.SEED_BUG === "1" && result.length > 0) {
    // Intentional bug: drop the last matching item
    result = result.slice(0, -1);
  }
  
  res.json(result);
});

app.put("/api/items/:id", (req, res) => {
  const id = Number(req.params.id);
  const { name } = req.body || {};
  if (!name) return res.status(400).json({ error: "name required" });
  
  const item = ITEMS.find(i => i.id === id);
  if (!item) return res.status(404).json({ error: "not found" });
  
  item.name = name;
  res.json(item);
});

app.post("/api/items", (req, res) => {
  const { name } = req.body || {};
  if (!name) return res.status(400).json({ error: "name required" });
  const item = { id: nextId++, name };
  ITEMS.push(item);
  res.status(201).json(item);
});

app.delete("/api/items/:id", (req, res) => {
  const id = Number(req.params.id);
  ITEMS = ITEMS.filter((i) => i.id !== id);
  res.status(204).end();
});

// Test-only reset so E2E specs get isolated state without reusing another test's leftovers
// (mirrors the isolation rule in .factory/skills/qa-playwright/SKILL.md).
app.post("/api/__test__/reset", (_req, res) => {
  ITEMS = [
    { id: 1, name: "First item" },
    { id: 2, name: "Second item" },
  ];
  nextId = 3;
  res.status(204).end();
});

const PORT = process.env.PORT || 4000;
if (require.main === module) {
  app.listen(PORT, () => console.log(`dummy-app listening on :${PORT}`));
}
module.exports = app;
