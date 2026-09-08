import { expect, test } from "./helpers/fixtures";
import { login, requireAuthenticatedEnv } from "./helpers/auth";
import {
  allMoney,
  expectMoneyEqual,
  readLabeledMoney,
} from "./helpers/money";
import { openDecisionMode } from "./helpers/surfaces";

// Phase 2 -- Decision Lab scenario journeys.
//
// TEST 6: Multi-step plan (one-time expense + monthly expense increase).
// TEST 7: Financial stress test ($4,321 emergency expense).
// TEST 8: What-if simulator ($3,000 one-time purchase).
//
// Each asserts a relationship between values the product displays. No
// projection / stress / what-if algorithm is reproduced. The decision
// is never saved (persistence is Phase 3).

test.describe("decision lab - scenario journeys", () => {
  test.beforeEach(async ({ page }) => {
    requireAuthenticatedEnv();
    await login(page);
  });

  test("TEST 6 - multi-step: each expense step reduces the position", async ({
    page,
  }) => {
    await openDecisionMode(page, "Multi-step plan");

    await page.getByLabel("Plan name (optional)").fill("E2E Multi-Step Plan");

    // Step 1 defaults to a one-time expense; Step 2 to a monthly
    // expense increase -- exactly the two step types under test.
    // The "Step N" caption sits in a flex wrapper inside the step
    // card, so the card itself is the caption's 2nd div ancestor.
    const step1 = page
      .getByText("Step 1", { exact: true })
      .locator("xpath=ancestor::div[2]");
    await step1.getByLabel("Label").fill("E2E Laptop");
    await step1.getByLabel("Amount").fill("2000");

    const step2 = page
      .getByText("Step 2", { exact: true })
      .locator("xpath=ancestor::div[2]");
    await step2.getByLabel("Label").fill("E2E Rent Increase");
    await step2.getByLabel("Monthly amount").fill("250");

    await page.getByRole("button", { name: "Run analysis" }).click();

    const panel = page
      .locator("article")
      .filter({ has: page.getByText("Multi-step result") });
    await expect(panel).toBeVisible({ timeout: 30_000 });

    // Every checkpoint row shows: <before> -> <after> (<impact>).
    for (const label of ["E2E Laptop", "E2E Rent Increase"] as const) {
      const row = panel.getByRole("listitem").filter({ hasText: label });
      await expect(row).toBeVisible();

      const amounts = allMoney(await row.innerText());
      expect(
        amounts.length,
        `expected before/after amounts on the "${label}" checkpoint, saw ${JSON.stringify(amounts)}`
      ).toBeGreaterThanOrEqual(2);

      const [before, after] = amounts;
      expect(
        after,
        [
          `"${label}" should REDUCE the financial position (an expense, not income).`,
          `  before: $${before.toFixed(2)}`,
          `  after:  $${after.toFixed(2)}`,
        ].join("\n")
      ).toBeLessThan(before);
    }
  });

  test("TEST 7 - financial stress: displayed impact is -$4,321", async ({
    page,
  }) => {
    await openDecisionMode(page, "Financial stress test");

    // Scenario type defaults to "Emergency expense".
    await page.getByLabel("Scenario name").fill("E2E Stress Test");
    await page.getByLabel("Stress amount").fill("4321");
    await page.getByLabel("Safety reserve").fill("0");
    await page.getByLabel("Essential spending").fill("0");
    await page.getByRole("button", { name: "Run stress test" }).click();

    const panel = page
      .locator("article")
      .filter({ has: page.getByText("Stress test result") });
    await expect(panel).toBeVisible({ timeout: 30_000 });

    const before = await readLabeledMoney(panel, "Before stress");
    const after = await readLabeledMoney(panel, "Safe to spend after stress");
    const totalImpact = await readLabeledMoney(panel, "Total impact");

    expectMoneyEqual(
      totalImpact,
      -4321,
      `displayed total impact should be -$4,321, got $${totalImpact.toFixed(2)}`
    );
    expectMoneyEqual(
      after,
      before - 4321,
      `safe-to-spend after stress ($${after.toFixed(2)}) should equal before ($${before.toFixed(2)}) minus $4,321`
    );
  });

  test("TEST 8 - what-if: displayed impact is -$3,000", async ({ page }) => {
    await openDecisionMode(page, "What-if simulator");

    // Sub-tab "Single scenario" and scenario type "One-time purchase"
    // are the defaults. Horizon stays at its default (90 days).
    await page.getByLabel("Scenario name").fill("E2E New Phone");
    await page.getByLabel("Amount").fill("3000");
    await page.getByLabel("Safety reserve").fill("0");
    await page.getByLabel("Essential spending").fill("0");
    await page.getByRole("button", { name: "Run simulation" }).click();

    const panel = page
      .locator("article")
      .filter({ has: page.getByText("What-if result") });
    await expect(panel).toBeVisible({ timeout: 30_000 });

    const baseline = await readLabeledMoney(panel, "Baseline");
    const after = await readLabeledMoney(panel, "After this change");
    const impact = await readLabeledMoney(panel, "Safe-to-spend impact");

    expectMoneyEqual(
      impact,
      -3000,
      `displayed safe-to-spend impact should be -$3,000, got $${impact.toFixed(2)}`
    );
    expectMoneyEqual(
      after,
      baseline - 3000,
      `after ($${after.toFixed(2)}) should equal baseline ($${baseline.toFixed(2)}) minus $3,000`
    );

    // Phase 2 does not persist the decision.
    await expect(
      panel.getByText("Saved to your decision history.")
    ).toHaveCount(0);
  });
});
