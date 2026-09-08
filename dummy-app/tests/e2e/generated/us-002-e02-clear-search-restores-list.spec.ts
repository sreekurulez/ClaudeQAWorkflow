// @plan us002-full
// @case US-002-E02
// P0 functional: clearing an active search term restores the full seeded list.
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

test("US-002-E02: clearing the search term restores the full item list", async ({
  page,
}) => {
  await loginAndGotoItems(page);

  // Precondition — narrow the list with an active search term.
  const narrowed = waitForSearch(page, "First");
  await page.getByTestId("search-input").fill("First");
  await narrowed;

  // Step 1 — the list is currently narrowed.
  await expect(itemRows(page)).toHaveCount(1);
  expect(1).toBeLessThan(SEEDED_ITEM_COUNT);

  // Step 2/3 — clear the field and wait for the unfiltered refetch.
  const restored = waitForUnfiltered(page);
  await page.getByTestId("search-input").fill("");
  const response = await restored;

  expect(response.status()).toBe(200);
  await expect(itemRows(page)).toHaveCount(SEEDED_ITEM_COUNT);
  await expect(page.getByRole("status")).toHaveCount(0);
});
