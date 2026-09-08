import { expect, test } from "./helpers/fixtures";
import type { Locator, Page } from "@playwright/test";
import { login, requireAuthenticatedEnv } from "./helpers/auth";
import { parseMoney } from "./helpers/money";

// Phase 4B -- Savings Goals CRUD + contribution/withdrawal persistence.
//
// Verifies create -> contribute -> withdraw -> edit target -> delete,
// plus simple displayed arithmetic on the saved amount. No goal
// intelligence / forecast math is re-tested. The goal name carries a
// per-run suffix so a previous run's failed cleanup cannot collide.

const GOAL_NAME = `E2E Savings Goal ${Date.now()}`;

function goalCard(page: Page): Locator {
  return page
    .locator("article")
    .filter({ has: page.getByText(GOAL_NAME, { exact: true }) });
}

async function readSaved(page: Page): Promise<number> {
  // The first currency token in the card is the saved amount.
  const text = (await goalCard(page).innerText()).trim();
  const match = text.match(/-?\$[\d,]+\.\d{2}/);
  if (!match) throw new Error(`no currency found in goal card: ${text}`);
  return parseMoney(match[0]);
}

async function closeDrawer(page: Page): Promise<void> {
  const dialog = page.getByRole("dialog");
  if (!(await dialog.isVisible().catch(() => false))) return;
  // Two elements expose "Close drawer" (backdrop + header X); the
  // backdrop is first in the DOM and always hit-testable.
  await page.getByRole("button", { name: "Close drawer" }).first().click();
  await expect(dialog).toBeHidden();
}

async function deleteGoalIfPresent(page: Page): Promise<void> {
  const card = goalCard(page);
  if ((await card.count()) === 0) return;
  await page.getByRole("button", { name: `Delete ${GOAL_NAME}` }).click();
  await page.getByRole("button", { name: "Delete permanently" }).click();
  await expect(card).toHaveCount(0);
}

// Sweep any "E2E Savings Goal ..." rows left by this or an earlier run.
async function sweepE2EGoals(page: Page): Promise<void> {
  const del = page.getByRole("button", { name: /^Delete E2E Savings Goal / });
  for (let i = 0; i < 20 && (await del.count()) > 0; i++) {
    await del.first().click();
    await page.getByRole("button", { name: "Delete permanently" }).click();
    await expect(page.getByRole("dialog")).toBeHidden();
  }
}

test.describe("savings goals - CRUD and contributions", () => {
  test.beforeEach(async ({ page }) => {
    requireAuthenticatedEnv();
    await login(page);
  });

  test("create, contribute, withdraw, edit target, delete", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    // 1. Open Goals.
    await page.goto("/goals");
    await expect(
      page.getByRole("heading", { name: /goals/i, level: 1 })
    ).toBeVisible();

    try {
      // 2 + 3. CREATE a deterministic goal (opening balance left at its
      // smallest valid value, 0).
      await page.getByRole("button", { name: "Create goal" }).click();
      const editor = page
        .locator("section")
        .filter({
          has: page.getByRole("heading", { name: "Create a savings goal" }),
        });
      await editor.getByLabel("Goal name").fill(GOAL_NAME);
      await editor.getByLabel("Target amount").fill("1000");
      await editor.getByRole("button", { name: "Create goal" }).click();

      const card = goalCard(page);
      await expect(card).toBeVisible({ timeout: 30_000 });
      await expect(card).toContainText("of $1,000.00");
      await expect(card).toContainText("0% complete");
      expect(await readSaved(page)).toBeCloseTo(0, 2);

      // 4. CONTRIBUTION: deposit $123.45.
      const before = await readSaved(page);
      await card.getByRole("button", { name: "Funds" }).click();
      await page.getByRole("button", { name: "deposit", exact: true }).click();
      await page.getByLabel("Amount", { exact: true }).fill("123.45");
      await page.getByRole("button", { name: "Add deposit" }).click();
      await expect(page.getByText("$123.45 deposited.")).toBeVisible({
        timeout: 20_000,
      });
      await closeDrawer(page);
      await expect
        .poll(() => readSaved(page), { timeout: 20_000 })
        .toBeCloseTo(before + 123.45, 2);

      // 5. WITHDRAWAL: withdraw $23.45.
      const afterDeposit = await readSaved(page);
      await card.getByRole("button", { name: "Funds" }).click();
      await page.getByRole("button", { name: "withdrawal", exact: true }).click();
      await page.getByLabel("Amount", { exact: true }).fill("23.45");
      await page.getByRole("button", { name: "Add withdrawal" }).click();
      await expect(page.getByText("$23.45 withdrawn.")).toBeVisible({
        timeout: 20_000,
      });
      await closeDrawer(page);
      await expect
        .poll(() => readSaved(page), { timeout: 20_000 })
        .toBeCloseTo(afterDeposit - 23.45, 2);

      // 6. EDIT: change target to $1,200.
      await page.getByRole("button", { name: `Edit ${GOAL_NAME}` }).click();
      const editForm = page
        .locator("section")
        .filter({
          has: page.getByRole("heading", { name: "Edit savings goal" }),
        });
      await editForm.getByLabel("Target amount").fill("1200");
      await editForm.getByRole("button", { name: "Save changes" }).click();
      await closeDrawer(page);
      await expect(card).toContainText("of $1,200.00");

      // 7. DELETE.
      await deleteGoalIfPresent(page);
      await expect(goalCard(page)).toHaveCount(0);
    } finally {
      await page.goto("/goals");
      await page
        .getByRole("heading", { name: /goals/i, level: 1 })
        .waitFor()
        .catch(() => {});
      await sweepE2EGoals(page).catch(() => {});
    }
  });
});
