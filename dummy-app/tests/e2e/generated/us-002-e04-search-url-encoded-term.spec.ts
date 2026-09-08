// @plan us002-full
// @case US-002-E04
// P1 edge: a term with characters requiring URL encoding is sent as GET /api/items?q=<encoded>,
// returns 200, and clearing restores the full seeded list.
import { test, expect } from "@playwright/test";
import {
  SEEDED_ITEM_COUNT,
  itemRows,
  loginAndGotoItems,
  resetState,
  waitForSearch,
  waitForUnfiltered,
} from "./_helpers";

test.beforeEach(async ({ request }) => {
  await resetState(request);
});

test("US-002-E04: a term needing URL encoding is sent encoded and does not break the page", async ({
  page,
}) => {
  await loginAndGotoItems(page);

  // Step 1/2 — type a term whose characters must be percent-encoded in the query string.
  const term = "a&b";
  const search = waitForSearch(page, term);
  await page.getByTestId("search-input").fill(term);
  const response = await search;

  expect(response.status()).toBe(200);
  expect(response.url()).toContain("/api/items?q=a%26b");
  // The server round-trips the decoded term, so nothing matches — but the page stays healthy.
  await expect(page.getByTestId("item-list")).toBeVisible();
  await expect(itemRows(page)).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page).toHaveURL(/\/items$/);

  // Step 3 — clearing restores the full seeded list.
  const restored = waitForUnfiltered(page);
  await page.getByTestId("search-input").fill("");
  await restored;
  await expect(itemRows(page)).toHaveCount(SEEDED_ITEM_COUNT);
});
