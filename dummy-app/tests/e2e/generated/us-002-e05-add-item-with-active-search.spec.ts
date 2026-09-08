// @plan us002-full
// @case US-002-E05
// P1 regression-impact: adding an item while a search term is active succeeds, but the refetch
// keeps the filter applied, so the new non-matching item only appears after the search is cleared.
import { test, expect } from "@playwright/test";
import {
  SEEDED_ITEM_COUNT,
  itemNames,
  itemRows,
  loginAndGotoItems,
  resetState,
  waitForSearch,
  waitForUnfiltered,
} from "./_helpers";

test.beforeEach(async ({ request }) => {
  await resetState(request);
});

test("US-002-E05: adding an item under an active search keeps it hidden until the search clears", async ({
  page,
}) => {
  await loginAndGotoItems(page);

  // Precondition — an active search term matching at least one seeded item.
  const term = "First";
  const narrowed = waitForSearch(page, term);
  await page.getByTestId("search-input").fill(term);
  await narrowed;
  await expect(itemRows(page)).toHaveCount(1);

  // Step 1/2 — add an item whose name does NOT match the active search term.
  const newName = "Zebra gadget";
  const refetch = waitForSearch(page, term);
  await page.getByTestId("item-name-input").fill(newName);
  await page.getByTestId("add-item-submit").click();
  await refetch;

  // Step 3 — the add succeeded and the input cleared...
  await expect(page.getByRole("status")).toHaveText("Item added");
  await expect(page.getByTestId("item-name-input")).toHaveValue("");
  // ...but the still-active filter hides the new item.
  await expect(itemRows(page)).toHaveCount(1);
  await expect(itemNames(page).filter({ hasText: newName })).toHaveCount(0);
  await expect(page.getByTestId("search-input")).toHaveValue(term);

  // Clearing the search reveals it in the full list.
  const restored = waitForUnfiltered(page);
  await page.getByTestId("search-input").fill("");
  await restored;
  await expect(itemRows(page)).toHaveCount(SEEDED_ITEM_COUNT + 1);
  await expect(itemNames(page).filter({ hasText: newName })).toHaveCount(1);
});
