// @plan us002-full
// @case US-002-E01
// P0 functional: searching a term that matches exactly one seeded item narrows the list to
// that one row, via GET /api/items?q=<term> 200.
import { test, expect } from "@playwright/test";
import {
  itemNames,
  itemRows,
  loginAndGotoItems,
  resetState,
  waitForSearch,
} from "./_helpers";

test.beforeEach(async ({ request }) => {
  await resetState(request);
});

test("US-002-E01: a search term matching one item narrows the list to that item", async ({
  page,
}) => {
  await loginAndGotoItems(page);

  // Step 1 — read the seeded rows and pick a term matching exactly one of them.
  const names = await itemNames(page).allTextContents();
  expect(names).toHaveLength(2);
  const term = "First";
  const matching = names.filter((n) =>
    n.toLowerCase().includes(term.toLowerCase())
  );
  expect(matching).toHaveLength(1);

  // Step 2/3 — type the term and wait for the refetch.
  const search = waitForSearch(page, term);
  await page.getByTestId("search-input").fill(term);
  const response = await search;

  expect(response.status()).toBe(200);
  await expect(itemRows(page)).toHaveCount(1);
  await expect(itemNames(page)).toHaveText([matching[0]]);
  await expect(page.getByRole("status")).toHaveCount(0);
});
