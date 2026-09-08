import { expect } from "./fixtures";
import type { Page } from "@playwright/test";
import { parseMoney } from "./money";

const MONEY_TEXT = /^-?\$[\d,]+\.\d{2}$/;

/**
 * The canonical current "Safe to spend" figure as shown on the
 * Overview. This is the number the whole app treats as authoritative;
 * other surfaces are checked for consistency against it. The value is
 * read straight from the rendered counter -- nothing is recomputed.
 *
 * Assumes an already-authenticated page context.
 */
export async function readOverviewSafeToSpend(page: Page): Promise<number> {
  await page.goto("/dashboard");
  await expect(
    page.getByRole("heading", { name: "Overview", level: 1 })
  ).toBeVisible();

  const card = page
    .locator("section")
    .filter({ has: page.getByText("Safe to spend", { exact: true }) })
    .first();

  // The Overview counter animates on mount; with reduced motion
  // emulation (playwright.config.ts) it renders its settled value
  // immediately. The only element inside the card whose entire text is
  // a currency string is that counter.
  const amount = card.getByText(MONEY_TEXT).first();
  await expect(amount).toBeVisible({ timeout: 15_000 });
  await expect(amount).toHaveText(MONEY_TEXT);

  return parseMoney((await amount.textContent()) ?? "");
}

/**
 * Open the Decision Lab and switch to one of its mode tabs. Returns
 * once the tab's form is on screen.
 */
export async function openDecisionMode(
  page: Page,
  mode:
    | "Single purchase"
    | "Compare options"
    | "Buy now vs wait"
    | "Financial stress test"
    | "What-if simulator"
    | "Multi-step plan"
): Promise<void> {
  await page.goto("/decisions");
  const tab = page.getByRole("button", { name: mode, exact: true });
  await expect(tab).toBeVisible();
  await tab.click();
}
