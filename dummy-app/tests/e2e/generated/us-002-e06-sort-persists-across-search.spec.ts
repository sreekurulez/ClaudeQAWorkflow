// @plan us002-full
// @case US-002-E06
// P2 regression-impact: the A–Z sort toggle stays applied while a search filters the list, and
// after the search is cleared.
//
// TESTABILITY GAP (plan marked this case gap:true): the sort toggle button has no data-testid.
// This spec composes the role-fallback locator already recorded for it in state/locator-map.json
// ("sort-az-button" → getByRole('button',{name:'Sort A–Z'})); no new selector strategy is
// invented here. It is brittle against label changes — the button's accessible name is also its
// state ("Sort A–Z" ⇄ "Unsort"). Adding data-testid="sort-toggle" to ItemsPage.tsx removes this.
import { test, expect } from "@playwright/test";
import {
  SEEDED_ITEM_COUNT,
  itemNames,
  loginAndGotoItems,
  resetState,
  waitForSearch,
  waitForUnfiltered,
} from "./_helpers";

test.beforeEach(async ({ request }) => {
  await resetState(request);
});

test("US-002-E06: the A–Z sort stays applied while searching and after clearing", async ({
  page,
}) => {
  await loginAndGotoItems(page);

  const sortedNames = (await itemNames(page).allTextContents()).sort((a, b) =>
    a.localeCompare(b)
  );

  // Step 1 — turn the sort on (role-fallback locator, see header note).
  const sortToggle = page.getByRole("button", { name: "Sort A–Z" });
  const sortRefetch = waitForUnfiltered(page);
  await sortToggle.click();
  await sortRefetch;
  await expect(page.getByRole("button", { name: "Unsort" })).toBeVisible();

  // Step 2/3 — search for a term matching more than one seeded item; order stays alphabetical.
  const term = "item";
  const narrowed = waitForSearch(page, term);
  await page.getByTestId("search-input").fill(term);
  await narrowed;
  await expect(itemNames(page)).toHaveCount(SEEDED_ITEM_COUNT);
  await expect(itemNames(page)).toHaveText(sortedNames);
  await expect(page.getByRole("button", { name: "Unsort" })).toBeVisible();

  // Step 4 — clearing the search shows the full list, still sorted.
  const restored = waitForUnfiltered(page);
  await page.getByTestId("search-input").fill("");
  await restored;
  await expect(itemNames(page)).toHaveText(sortedNames);
});
