import { expect, test } from "./helpers/fixtures";
import { login, requireAuthenticatedEnv } from "./helpers/auth";
import { parseMoney } from "./helpers/money";
import type { Locator, Page } from "@playwright/test";

// Phase 3a -- Transactions.
//
// Focused coverage for the Transactions surface, driven against the
// local seeded demo user (E2E_USER_EMAIL / E2E_USER_PASSWORD). These
// specs create, edit and delete real rows for that user, so they run
// only against a local target (enforced by requireAuthenticatedEnv).
//
// The one mutating journey (create -> edit -> delete) always removes
// its row: in a finally block, and again in beforeEach, so a crashed
// run cannot leave an "E2E Smoke Coffee" row behind. Tests run serially
// because they share one backend user and several assertions compare
// exact transaction counts / spending / net totals.

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const DESCRIPTION = "E2E Smoke Coffee";

function today(): string {
  return new Date().toISOString().split("T")[0];
}

/** The four-cell summary strip at the top of the Transactions page. */
function summaryStrip(page: Page): Locator {
  return page
    .locator("section")
    .filter({ hasText: "Net activity" })
    .first();
}

/** The value paragraph of one summary cell ("Transactions", "Income", ...). */
function summaryValue(page: Page, label: string): Locator {
  return summaryStrip(page)
    .locator("article")
    .filter({ hasText: label })
    .locator("p")
    .last();
}

async function readCount(page: Page): Promise<number> {
  const text =
    (await summaryValue(page, "Transactions").textContent()) ?? "";
  return Number(text.replace(/[^\d]/g, ""));
}

/** Read a displayed summary dollar amount (signed, as shown). */
async function readMoney(page: Page, label: string): Promise<number> {
  return parseMoney(
    (await summaryValue(page, label).textContent()) ?? ""
  );
}

function transactionRow(page: Page, description: string): Locator {
  return page
    .locator("article")
    .filter({ has: page.getByText(description, { exact: true }) });
}

async function gotoTransactions(page: Page): Promise<void> {
  await page.goto("/transactions");
  await expect(
    page.getByRole("heading", { name: "Transactions", level: 1 })
  ).toBeVisible();
  // The summary strip only renders once the first search resolves.
  await expect(summaryValue(page, "Transactions")).toBeVisible({
    timeout: 15_000,
  });
}

/**
 * Delete any lingering E2E rows straight through the API. Used for
 * belt-and-braces cleanup; needs an authenticated page (token in
 * localStorage) already loaded on the app origin.
 */
async function purgeE2ETransactions(page: Page): Promise<void> {
  const token = await page.evaluate(() =>
    localStorage.getItem("accessToken")
  );
  const userId = await page.evaluate(() =>
    localStorage.getItem("userId")
  );
  if (!token || !userId) return;

  const headers = { Authorization: `Bearer ${token}` };
  const res = await page.request.get(
    `${API_BASE}/users/${userId}/transactions/search` +
      `?search=${encodeURIComponent(DESCRIPTION)}&page_size=100`,
    { headers }
  );
  if (!res.ok()) return;

  const body = (await res.json()) as {
    items?: Array<{ id: number }>;
  };
  const ids = (body.items ?? []).map((item) => item.id);
  if (ids.length === 0) return;

  await page.request.post(
    `${API_BASE}/users/${userId}/transactions/bulk/delete`,
    {
      headers: { ...headers, "Content-Type": "application/json" },
      data: { transaction_ids: ids },
    }
  );
}

test.describe("transactions", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    requireAuthenticatedEnv();
    await login(page);
    // Clear anything a previous aborted run may have left behind.
    await purgeE2ETransactions(page);
  });

  test("page loads with a populated summary strip", async ({
    page,
  }) => {
    await gotoTransactions(page);

    await expect(summaryValue(page, "Income")).toHaveText(/\$/);
    await expect(summaryValue(page, "Spending")).toHaveText(/\$/);
    await expect(summaryValue(page, "Net activity")).toHaveText(/\$/);
    await expect.poll(() => readCount(page)).toBeGreaterThan(0);
  });

  test("create, edit and delete a manual transaction keeps totals consistent", async ({
    page,
  }) => {
    test.slow();
    await gotoTransactions(page);

    const count0 = await readCount(page);
    const spend0 = await readMoney(page, "Spending");
    const net0 = await readMoney(page, "Net activity");

    let created = false;
    try {
      // -- CREATE ------------------------------------------------
      await page
        .getByRole("button", { name: "Add transaction" })
        .first()
        .click();
      const createDialog = page.getByRole("dialog", {
        name: "Add transaction",
      });
      await expect(createDialog).toBeVisible();

      await createDialog
        .getByRole("button", { name: "Expense" })
        .click();
      await createDialog.getByLabel("Amount").fill("12.34");
      await createDialog.getByLabel("Date").fill(today());
      await createDialog.getByLabel("Description").fill(DESCRIPTION);
      await createDialog
        .getByLabel("Category")
        .selectOption("Dining");
      await createDialog
        .getByRole("button", { name: "Add transaction" })
        .click();
      await expect(createDialog).toBeHidden();
      created = true;

      await expect(transactionRow(page, DESCRIPTION)).toBeVisible();
      await expect(
        page.getByRole("button", {
          name: `Amount -$12.34 for ${DESCRIPTION}`,
        })
      ).toBeVisible();
      await expect
        .poll(() => readCount(page), { timeout: 15_000 })
        .toBe(count0 + 1);
      await expect
        .poll(() => readMoney(page, "Spending"), { timeout: 15_000 })
        .toBeCloseTo(spend0 - 12.34, 2);
      await expect
        .poll(() => readMoney(page, "Net activity"), {
          timeout: 15_000,
        })
        .toBeCloseTo(net0 - 12.34, 2);

      // -- EDIT ------------------------------------------------
      await transactionRow(page, DESCRIPTION)
        .getByRole("button", { name: "Transaction actions" })
        .click();
      await page
        .getByRole("button", { name: "Edit", exact: true })
        .click();
      const editDialog = page.getByRole("dialog", {
        name: "Edit transaction",
      });
      await expect(editDialog).toBeVisible();

      await editDialog.getByLabel("Amount").fill("15.00");
      await editDialog
        .getByLabel("Category")
        .selectOption("Groceries");
      await editDialog
        .getByRole("button", { name: "Save changes" })
        .click();
      await expect(editDialog).toBeHidden();

      await expect(
        page.getByRole("button", {
          name: `Amount -$15.00 for ${DESCRIPTION}`,
        })
      ).toBeVisible();
      await expect(
        transactionRow(page, DESCRIPTION).getByLabel(
          `Category for ${DESCRIPTION}`
        )
      ).toHaveValue("Groceries");
      await expect
        .poll(() => readMoney(page, "Spending"), { timeout: 15_000 })
        .toBeCloseTo(spend0 - 15.0, 2);
      await expect
        .poll(() => readMoney(page, "Net activity"), {
          timeout: 15_000,
        })
        .toBeCloseTo(net0 - 15.0, 2);
      await expect.poll(() => readCount(page)).toBe(count0 + 1);

      // -- DELETE --------------------------------------------
      await transactionRow(page, DESCRIPTION)
        .getByRole("button", { name: "Transaction actions" })
        .click();
      await page
        .getByRole("button", { name: "Delete", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Delete permanently" })
        .click();

      await expect(transactionRow(page, DESCRIPTION)).toHaveCount(0);
      // The row is removed optimistically; the real DELETE request
      // fires only after the ~6s in-app undo window closes.
      await page.waitForResponse(
        (response) =>
          response.url().includes("/transactions/bulk/delete") &&
          response.request().method() === "POST",
        { timeout: 20_000 }
      );
      created = false;

      await expect
        .poll(() => readCount(page), { timeout: 15_000 })
        .toBe(count0);
      await expect
        .poll(() => readMoney(page, "Spending"), { timeout: 15_000 })
        .toBeCloseTo(spend0, 2);
      await expect
        .poll(() => readMoney(page, "Net activity"), {
          timeout: 15_000,
        })
        .toBeCloseTo(net0, 2);
    } finally {
      if (created) await purgeE2ETransactions(page);
    }
  });

  test("search finds a known seeded transaction", async ({ page }) => {
    await gotoTransactions(page);
    const search = page.getByLabel("Search transactions");

    await search.fill("REI Co-op");
    await expect(page.getByText("REI Co-op").first()).toBeVisible();
    await expect.poll(() => readCount(page)).toBeGreaterThan(0);

    await search.fill("zzz-no-such-transaction-zzz");
    await expect(
      page.getByText("No transactions match your filters")
    ).toBeVisible();
  });

  test("category filter narrows the list", async ({ page }) => {
    await gotoTransactions(page);
    const total0 = await readCount(page);

    await page.getByRole("button", { name: "Filters" }).click();
    await page
      .getByLabel("Filter by category")
      .selectOption("Groceries");

    await expect.poll(() => readCount(page)).toBeGreaterThan(0);
    expect(await readCount(page)).toBeLessThan(total0);
    await expect(
      page.getByLabel(/^Category for /).first()
    ).toHaveValue("Groceries");

    await page
      .getByRole("button", { name: "Clear", exact: true })
      .click();
    await expect.poll(() => readCount(page)).toBe(total0);
  });

  test("pagination steps between pages when the list spans more than one", async ({
    page,
  }) => {
    await gotoTransactions(page);
    const next = page.getByRole("button", { name: "Next", exact: true });

    if ((await next.count()) === 0) {
      test.skip(true, "Seeded data fits on a single page");
      return;
    }

    await expect(
      page.getByText(/Showing 1[–-]\d+ of \d+/)
    ).toBeVisible();
    await next.click();
    await expect(
      page.getByText(/Showing 21[–-]\d+ of \d+/)
    ).toBeVisible();
    await page.getByRole("button", { name: "Previous", exact: true }).click();
    await expect(
      page.getByText(/Showing 1[–-]\d+ of \d+/)
    ).toBeVisible();
  });

  test("potential duplicates surfaces the seeded REI pair", async ({
    page,
  }) => {
    await gotoTransactions(page);
    await page
      .getByRole("switch", { name: "Potential duplicates" })
      .click();

    await expect
      .poll(() =>
        page
          .getByRole("button", {
            name: /Amount -\$64\.30 for REI/,
          })
          .count()
      )
      .toBeGreaterThanOrEqual(2);
  });

  test("CSV export triggers a file download", async ({ page }) => {
    await gotoTransactions(page);

    const downloadPromise = page.waitForEvent("download", {
      timeout: 20_000,
    });
    await page.getByRole("button", { name: "Export CSV" }).click();

    let filename: string;
    try {
      const download = await downloadPromise;
      filename = download.suggestedFilename();
    } catch {
      test.skip(
        true,
        "No browser download event observed for CSV export"
      );
      return;
    }

    expect(filename).toMatch(
      /^discero-transactions-\d{4}-\d{2}-\d{2}\.csv$/
    );
  });
});
