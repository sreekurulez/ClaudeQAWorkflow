// Browser-based fact crawler. IMPLEMENTATION_STRATEGY.md §4, "Option B": read the running app
// in a real browser instead of parsing source files. Deterministic — no AI involved; produces
// a per-route element fact list for qa-locator-explorer to rank/interpret, exactly the role
// testability_check.py's file-based facts played before. Only the fact-gathering mechanism
// changes; the actor/judge split (this script finds facts, the AI ranks them) does not.
//
// A Node/Playwright script, not Python, because driving a real browser needs a real browser
// automation engine — reusing the Playwright install the app's own E2E tests already depend on,
// rather than adding a second, duplicate browser-automation dependency to the Python side.
//
// Usage: node crawl.js <config.json>
//   config.json: { baseUrl, pages: [{route, requiresAuth}], auth: {...project.json's auth block} }
// Output: JSON fact list on stdout, one entry per route: {route, elements: [...]}.
// Errors (a page that never loads, a login that never succeeds) go to stderr and exit non-zero
// — loud, not a silently-empty fact list (IMPLEMENTATION_STRATEGY.md's "no silent caps" rule).

const { chromium } = require("@playwright/test");

// Roles whose accessible name computation Playwright's own matching engine already gets right
// (used only to decide which elements are "interactive" at all — the actual name for each is
// still computed by hand below, see computeAccessibleName, because getByRole(role) alone does
// not hand back each individual matched element's own computed name).
const INTERACTIVE_SELECTOR =
  'button, a[href], input, select, textarea, [role="button"], [role="link"], [role="checkbox"], [role="radio"], [role="tab"], [role="menuitem"], [role="switch"], [role="combobox"]';

const IMPLICIT_ROLE_BY_TAG = {
  BUTTON: "button",
  A: "link",
  SELECT: "combobox",
  TEXTAREA: "textbox",
};
const IMPLICIT_ROLE_BY_INPUT_TYPE = {
  checkbox: "checkbox",
  radio: "radio",
  submit: "button",
  button: "button",
  range: "slider",
};

async function computeAccessibleName(handle) {
  return handle.evaluate((el) => {
    const ariaLabel = el.getAttribute("aria-label");
    if (ariaLabel) return ariaLabel.trim();

    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const parts = labelledBy
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.textContent?.trim())
        .filter(Boolean);
      if (parts.length) return parts.join(" ");
    }

    if (el.id) {
      const label = document.querySelector(`label[for="${el.id}"]`);
      if (label && label.textContent) return label.textContent.trim();
    }
    const closestLabel = el.closest("label");
    if (closestLabel && closestLabel.textContent) return closestLabel.textContent.trim();

    if (el.tagName === "IMG" && el.getAttribute("alt")) return el.getAttribute("alt").trim();

    const text = el.textContent ? el.textContent.trim() : "";
    if (text) return text;

    return el.getAttribute("title") || el.getAttribute("placeholder") || null;
  });
}

function computeRole(tag, typeAttr, explicitRole) {
  if (explicitRole) return explicitRole;
  if (tag === "INPUT") return IMPLICIT_ROLE_BY_INPUT_TYPE[typeAttr] || "textbox";
  return IMPLICIT_ROLE_BY_TAG[tag] || tag.toLowerCase();
}

async function crawlOnePage(page) {
  // Navigation already happened in main() (it needs the pre-navigation URL to detect a login
  // bounce) — this just reads the now-settled page.
  await page.waitForTimeout(500); // let client-side render settle (React SPA, no server HTML)

  const handles = await page.locator(INTERACTIVE_SELECTOR).all();
  const elements = [];
  for (const handle of handles) {
    const [tag, typeAttr, explicitRole, testId] = await Promise.all([
      handle.evaluate((el) => el.tagName),
      handle.evaluate((el) => el.getAttribute("type")),
      handle.evaluate((el) => el.getAttribute("role")),
      handle.evaluate((el) => el.getAttribute("data-testid")),
    ]);
    const [name, visible] = await Promise.all([
      computeAccessibleName(handle),
      handle.isVisible(),
    ]);
    elements.push({
      tag: tag.toLowerCase(),
      role: computeRole(tag, typeAttr, explicitRole),
      hasTestId: !!testId,
      testId: testId || null,
      name: name || null,
      visible,
    });
  }
  return elements;
}

async function login(page, baseUrl, auth) {
  if (auth.strategy !== "form_login") {
    throw new Error(
      `crawl.js only implements the 'form_login' auth strategy; config declares '${auth.strategy}'. ` +
        "Refusing to guess a login flow — see IMPLEMENTATION_STRATEGY.md §7.2."
    );
  }
  await page.goto(new URL(auth.loginRoute, baseUrl).toString(), { waitUntil: "load" });
  await page.getByTestId(auth.emailTestid).fill(auth.testCredentials.email);
  await page.getByTestId(auth.passwordTestid).fill(auth.testCredentials.password);
  await page.getByTestId(auth.submitTestid).click();
  // Hard rule (§7.2): a login that doesn't visibly succeed must stop loudly, never silently
  // crawl whatever page it landed on (e.g. an error-flashed login page).
  await page.waitForFunction(
    (loginRoute) => !window.location.pathname.startsWith(loginRoute),
    auth.loginRoute,
    { timeout: 10000 }
  );
}

async function main() {
  const configPath = process.argv[2];
  if (!configPath) {
    console.error("usage: node crawl.js <config.json>");
    process.exit(1);
  }
  const config = JSON.parse(require("fs").readFileSync(configPath, "utf-8"));
  const { baseUrl, pages, auth } = config;

  const browser = await chromium.launch();
  const page = await browser.newPage();

  let authenticated = false;
  const results = [];
  try {
    for (const { route, requiresAuth, navLinkName } of pages) {
      if (!requiresAuth) {
        // Only the unauthenticated pages (e.g. /login itself) ever get a real page.goto() —
        // see the big comment below for why authenticated pages can't.
        await page.goto(new URL(route, baseUrl).toString(), { waitUntil: "load", timeout: 20000 });
        await page.waitForTimeout(500);
        results.push({ route, elements: await crawlOnePage(page) });
        continue;
      }

      // Real, live-verified hazard (dummy-app): page.goto() is ALWAYS a hard reload, and this
      // app's auth is in-memory-only (React useState) — it does NOT survive a reload, even to
      // an already-authenticated route immediately after a successful login. So every
      // authenticated page after the first must be reached via a real client-side navigation
      // (clicking an in-app <Link>, exactly like a real user would), never page.goto(). This
      // isn't a hypothetical edge case — it's how this app actually behaves, confirmed by
      // hitting it directly while building this crawler (see IMPLEMENTATION_STRATEGY.md's
      // Stage 7 writeup and the identical root cause found independently in Stage 1's
      // ORDERS-* test failures).
      if (!authenticated) {
        await login(page, baseUrl, auth);
        authenticated = true;
      }
      // Always navigate via the nav link, even right after login — don't assume login's own
      // post-login redirect happens to land on this particular route (fragile, order-dependent
      // if crawl_pages ever lists routes in a different order).
      if (navLinkName) {
        await page.getByRole("link", { name: navLinkName }).click();
        await page.waitForTimeout(500);
      }

      // Hard rule (§4.2/§7.2): never silently report the login page's elements as if they
      // belonged to the page we meant to crawl. If we're not where we should be, stop loudly
      // rather than guess.
      const onLoginPage = new URL(page.url()).pathname.startsWith(auth.loginRoute);
      if (onLoginPage) {
        throw new Error(
          `route '${route}' landed on the login page instead — the '${navLinkName}' nav link ` +
            "either doesn't exist, doesn't lead there, or the session didn't actually stick. " +
            "Refusing to report the login page's elements as this route's facts."
        );
      }

      results.push({ route, elements: await crawlOnePage(page) });
    }
  } catch (err) {
    console.error(`crawl.js: FAILED — ${err.message}`);
    await browser.close();
    process.exit(1);
  }

  await browser.close();
  process.stdout.write(JSON.stringify(results, null, 2) + "\n");
}

main();
