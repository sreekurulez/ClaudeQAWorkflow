// Shared setup for the US-002 generated specs.
// Isolation + auth strategies come from config/project.json (reset_endpoint / form_login);
// they are NOT invented here — see IMPLEMENTATION_STRATEGY.md §7.1/§7.2.
import { Page, APIRequestContext, expect } from "@playwright/test";

export const SEEDED_ITEM_COUNT = 2;

/** POST /api/__test__/reset — clean slate before every test. */
export async function resetState(request: APIRequestContext) {
  const res = await request.post("/api/__test__/reset");
  expect(res.status()).toBe(204);
}

/** form_login: /login + login-email / login-password / login-submit, lands on /items. */
export async function loginAndGotoItems(page: Page) {
  await page.goto("/login");
  await page.getByTestId("login-email").fill("user@example.com");
  await page.getByTestId("login-password").fill("password123");
  await page.getByTestId("login-submit").click();

  await expect(page).toHaveURL(/\/items$/);
  await expect(page.getByTestId("item-list")).toBeVisible();
  await expect(itemRows(page)).toHaveCount(SEEDED_ITEM_COUNT);
}

/** Rows inside data-testid="item-list" (ProductList renders data-testid="item-row-<id>"). */
export function itemRows(page: Page) {
  return page.getByTestId("item-list").getByTestId(/^item-row-\d+$/);
}

/** The item-name spans inside data-testid="item-list" (data-testid="item-name-<id>"). */
export function itemNames(page: Page) {
  return page.getByTestId("item-list").getByTestId(/^item-name-\d+$/);
}

/** Waits for the GET /api/items refetch carrying exactly this search term. */
export function waitForSearch(page: Page, term: string) {
  const expected = `/api/items?q=${encodeURIComponent(term)}`;
  return page.waitForResponse(
    (res) => res.url().endsWith(expected) && res.request().method() === "GET"
  );
}

/** Waits for the unfiltered GET /api/items refetch (no query string). */
export function waitForUnfiltered(page: Page) {
  return page.waitForResponse(
    (res) => res.url().endsWith("/api/items") && res.request().method() === "GET"
  );
}
