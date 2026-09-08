// @plan us002-full
// @case US-002-E03
// P0 negative: a term matching nothing leaves an empty-but-present item-list, no error UI,
// and no navigation away from /items.
import { test, expect } from "@playwright/test";
import {
  itemRows,
  loginAndGotoItems,
  resetState,
  waitForSearch,
} from "./_helpers";

test.beforeEach(async ({ request }) => {
  await resetState(request);
});

test("US-002-E03: a search term matching no item yields an empty list, not an error", async ({
  page,
}) => {
  await loginAndGotoItems(page);

  const term = "zzzznomatch";
  const search = waitForSearch(page, term);
  await page.getByTestId("search-input").fill(term);
  const response = await search;

  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual([]);

  await expect(page.getByTestId("item-list")).toBeVisible();
  await expect(itemRows(page)).toHaveCount(0);

  // No error banner / toast / alert surfaced, and we are still on /items.
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByRole("status")).toHaveCount(0);
  await expect(page).toHaveURL(/\/items$/);
});
