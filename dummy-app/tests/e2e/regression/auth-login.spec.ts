// @plan baseline
// @case baseline-auth-01
// @tags @regression @smoke
//
// P0: a valid user can sign in and reach the items area. Hand-written baseline (mirrors
// .factory/droids/qa-regression-bootstrapper.md's convention: one P0 case per module,
// minimal by design) — the generator/healer roles are exercised against NEW cases, this one
// exists so there's a known-good spec to sanity-check the executor script against first.
import { test, expect } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  await request.post("/api/__test__/reset");
});

test("auth: a valid user can sign in @regression @smoke", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("login-email").fill("user@example.com");
  await page.getByTestId("login-password").fill("password123");
  await page.getByTestId("login-submit").click();

  await expect(page.getByTestId("current-user-indicator")).toBeVisible();
  await expect(page.getByTestId("item-list")).toBeVisible();
});
