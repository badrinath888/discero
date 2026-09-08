import { devices } from "@playwright/test";
import { expect, test } from "./helpers/fixtures";
import { login, requireAuthenticatedEnv } from "./helpers/auth";

// Phase 5A -- mobile responsive smoke (read-only).
//
// One representative mobile viewport (Pixel 7). For each key route:
// reach it via the mobile menu, confirm the primary heading renders,
// confirm the menu closes on navigation, and confirm the document has
// no horizontal overflow that would make the app unusable. No data is
// created or modified.

test.use({ ...devices["Pixel 7"] });

const ROUTES: Array<{ nav: string; path: string; heading: string | null }> = [
  { nav: "Overview", path: "/dashboard", heading: "Overview" },
  { nav: "Ask Discero", path: "/copilot", heading: "Ask Discero" },
  { nav: "Decisions", path: "/decisions", heading: null },
  { nav: "Transactions", path: "/transactions", heading: "Transactions" },
  { nav: "Accounts", path: "/accounts", heading: "Accounts" },
  { nav: "Forecast", path: "/forecast", heading: "Forecast" },
];

test.describe("mobile responsive smoke", () => {
  test.beforeEach(async ({ page }) => {
    requireAuthenticatedEnv();
    await login(page);
  });

  test("key routes render and stay usable on a mobile viewport", async ({
    page,
  }) => {
    test.setTimeout(120_000);

    const openBtn = page.getByRole("button", { name: "Open navigation" });
    const overlay = page.getByRole("button", {
      name: "Close navigation overlay",
    });
    const nav = page.getByRole("navigation", { name: "Main navigation" });

    async function assertNoHorizontalOverflow(label: string) {
      const { scrollWidth, clientWidth } = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(
        scrollWidth,
        `${label}: document overflows horizontally (${scrollWidth}px content in ${clientWidth}px viewport)`
      ).toBeLessThanOrEqual(clientWidth + 1);
    }

    // Land authenticated on Overview; the mobile menu trigger is shown.
    await expect(
      page.getByRole("heading", { name: "Overview", level: 1 })
    ).toBeVisible();
    await expect(openBtn).toBeVisible();

    // Explicit open / close of the mobile navigation.
    await openBtn.click();
    await expect(overlay).toBeVisible();
    await expect(nav.getByRole("link", { name: "Forecast" })).toBeInViewport();
    await page
      .getByRole("button", { name: "Close navigation", exact: true })
      .click();
    await expect(overlay).toHaveCount(0);

    for (const route of ROUTES) {
      await openBtn.click();
      await expect(overlay).toBeVisible();

      const link = nav.getByRole("link", { name: route.nav, exact: true });
      await expect(link).toBeInViewport();
      await link.click();

      // Navigation reached the route and the menu dismissed itself.
      await expect(page).toHaveURL(new RegExp(`${route.path}(\\b|/|$)`));
      await expect(overlay).toHaveCount(0);
      await expect(openBtn).toBeVisible();

      // Primary heading / content is visible.
      const h1 = route.heading
        ? page.getByRole("heading", { name: route.heading, level: 1 })
        : page.getByRole("heading", { level: 1 }).first();
      await expect(h1).toBeVisible({ timeout: 30_000 });
      await expect(h1).not.toBeEmpty();

      await assertNoHorizontalOverflow(route.nav);
    }
  });
});
