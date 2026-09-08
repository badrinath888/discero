import { expect, test } from "./helpers/fixtures";
import { login, requireAuthenticatedEnv } from "./helpers/auth";

// Phase 3C -- Accounts (read-only).
//
// Verifies the seeded demo portfolio renders: institution, per-account
// balances, aggregate figures, the demo connection state, and that
// "Sync now" is not offered for a demo (non-syncable) connection.
// Nothing is connected, mutated, or synced.

const CHECKING = "Demo Checking";
const SAVINGS = "Demo Savings";
const REWARDS = "Demo Rewards Card";

test.describe("accounts - seeded demo portfolio", () => {
  test.beforeEach(async ({ page }) => {
    requireAuthenticatedEnv();
    await login(page);
  });

  test("renders demo bank, balances, totals and demo state", async ({
    page,
  }) => {
    // 1. Open Accounts.
    await page.goto("/accounts");
    await expect(
      page.getByRole("heading", { name: "Accounts", level: 1 })
    ).toBeVisible();

    // 2. Portfolio Demo Bank renders.
    await expect(
      page.getByText("Portfolio Demo Bank").first()
    ).toBeVisible({ timeout: 30_000 });

    // 3. Seeded per-account balances (each shown on its account row).
    const rowBalances: Array<[string, string]> = [
      [CHECKING, "$8,500.00"],
      [SAVINGS, "$22,000.00"],
      [REWARDS, "-$420.00"],
    ];
    for (const [name, balance] of rowBalances) {
      const row = page.locator("article").filter({ hasText: name }).first();
      await expect(row).toBeVisible();
      await expect(row).toContainText(balance);
    }

    // 4. Aggregate values in the summary list.
    const stat = (label: string) =>
      page
        .locator("dl > div")
        .filter({ has: page.getByText(label, { exact: true }) });
    await expect(stat("Assets")).toContainText("$30,500.00");
    await expect(stat("Liabilities")).toContainText("-$420.00");
    await expect(stat("Net position")).toContainText("$30,080.00");

    // 5. Demo connection state.
    await expect(
      page.getByText("Demo data — no live bank connection").first()
    ).toBeVisible();

    // 6. "Sync now" is not offered for the demo connection.
    await expect(
      page.getByRole("button", { name: "Sync now" })
    ).toHaveCount(0);
  });
});
