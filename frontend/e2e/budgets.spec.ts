import { expect, test } from "./helpers/fixtures";
import type { Locator, Page } from "@playwright/test";
import { login, requireAuthenticatedEnv } from "./helpers/auth";
import { parseMoney } from "./helpers/money";

// Phase 4A -- Budgets CRUD + UI recalculation / persistence.
//
// Budgets are keyed by a fixed category list (no free-form name), so
// the test picks a category that currently has NO budget, exercises
// create -> edit -> delete on it, and restores the original state.
// "Copy previous month" is only checked for availability -- clicking it
// would clone every previous-month budget over the seeded demo data.
//
// Deterministic amounts: create $123.45, edit $150.00.

const CATEGORIES = [
  "Dining",
  "Groceries",
  "Health",
  "Housing",
  "Shopping",
  "Subscriptions",
  "Transport",
  "Utilities",
] as const;

function categoryRow(page: Page, category: string): Locator {
  return page
    .locator("article")
    .filter({ has: page.getByText(category, { exact: true }) });
}

function budgetedTotal(page: Page): Locator {
  return page
    .locator("dl > div")
    .filter({ has: page.getByText("Budgeted", { exact: true }) })
    .locator("dd");
}

async function readBudgeted(page: Page): Promise<number> {
  return parseMoney((await budgetedTotal(page).innerText()).trim());
}

async function deleteBudget(page: Page, category: string): Promise<void> {
  const row = categoryRow(page, category);
  // Nothing to do if the category has no budget.
  if ((await row.getByRole("button", { name: "Edit" }).count()) === 0) return;
  await row.getByRole("button", { name: "Edit" }).click();
  await page.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("button", { name: "Delete budget" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(row.getByRole("button", { name: "Set" })).toBeVisible();
}

test.describe("budgets - CRUD and recalculation", () => {
  test.beforeEach(async ({ page }) => {
    requireAuthenticatedEnv();
    await login(page);
  });

  test("create, edit, copy-availability, delete with totals restored", async ({
    page,
  }) => {
    // 1. Open Budgets.
    await page.goto("/budgets");
    await expect(
      page.getByRole("heading", { name: "Budgets", level: 1 })
    ).toBeVisible();
    await expect(budgetedTotal(page)).toBeVisible({ timeout: 30_000 });

    // 2. Record restoration state and pick an unconfigured category.
    const originalBudgeted = await readBudgeted(page);

    let target: string | null = null;
    for (const category of CATEGORIES) {
      const row = categoryRow(page, category);
      if ((await row.getByRole("button", { name: "Set" }).count()) > 0) {
        target = category;
        break;
      }
    }
    expect(
      target,
      "expected at least one category without a budget to test create/delete safely"
    ).not.toBeNull();
    const category = target as string;
    const row = categoryRow(page, category);

    try {
      // 3. CREATE a $123.45 budget for that category.
      await row.getByRole("button", { name: "Set" }).click();
      await page.getByLabel("Monthly amount").fill("123.45");
      await page.getByRole("button", { name: "Create budget" }).click();
      await expect(page.getByRole("dialog")).toBeHidden();

      // 4. Budget appears; row + totals recalculate.
      await expect(row).toContainText("$123.45");
      await expect(row.getByRole("button", { name: "Edit" })).toBeVisible();
      await expect
        .poll(() => readBudgeted(page))
        .toBeCloseTo(originalBudgeted + 123.45, 2);

      // 5. EDIT the amount to $150.00.
      await row.getByRole("button", { name: "Edit" }).click();
      await page.getByLabel("Monthly amount").fill("150.00");
      await page.getByRole("button", { name: "Update budget" }).click();
      await expect(page.getByRole("dialog")).toBeHidden();

      await expect(row).toContainText("$150.00");
      await expect(row).not.toContainText("$123.45");
      await expect
        .poll(() => readBudgeted(page))
        .toBeCloseTo(originalBudgeted + 150, 2);

      // 6. COPY PREVIOUS MONTH -- availability only. Clicking it would
      // clone every previous-month budget onto the seeded demo data, so
      // the mutation is intentionally skipped.
      await expect(
        page.getByRole("button", { name: /^Copy / })
      ).toBeEnabled();

      // 7. DELETE the E2E budget; verify it disappears and totals reset.
      await deleteBudget(page, category);
      await expect(row).toContainText("Not set");
      await expect
        .poll(() => readBudgeted(page))
        .toBeCloseTo(originalBudgeted, 2);
    } finally {
      // Cleanup even if an assertion above failed.
      await page.goto("/budgets");
      await expect(budgetedTotal(page)).toBeVisible({ timeout: 30_000 });
      await deleteBudget(page, category);
    }
  });
});
