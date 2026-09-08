import { expect, test } from "./helpers/fixtures";
import { login, requireAuthenticatedEnv } from "./helpers/auth";
import {
  expectMoneyEqual,
  parseMoney,
  readLabeledMoney,
} from "./helpers/money";
import { openDecisionMode, readOverviewSafeToSpend } from "./helpers/surfaces";

// Phase 2 -- Decision Lab purchase journeys.
//
// TEST 3: Major purchase ("E2E Laptop", $2,000).
// TEST 4: Buy now vs wait.
// TEST 5: Scenario comparison ($2,000 vs $3,500).
//
// These verify relationships between values the product itself
// displays. No forecast / affordability algorithm is reproduced.

test.describe("decision lab - purchase journeys", () => {
  test.beforeEach(async ({ page }) => {
    requireAuthenticatedEnv();
    await login(page);
  });

  test("TEST 3 - major purchase deducts the displayed $2,000", async ({
    page,
  }) => {
    // Canonical current Safe-to-Spend, read once from the Overview.
    const canonical = await readOverviewSafeToSpend(page);

    await openDecisionMode(page, "Single purchase");

    await page.getByLabel("Purchase name").fill("E2E Laptop");
    await page.getByLabel("Purchase amount").fill("2000");
    // Match the canonical Safe-to-Spend assumptions so the simulator's
    // "before" baseline is comparable to the Overview figure.
    await page.getByLabel("Safety reserve").fill("0");
    await page.getByLabel("Essential spending").fill("0");
    await page.getByRole("button", { name: "Simulate purchase" }).click();

    const result = page
      .locator("article")
      .filter({ has: page.getByText("Simulation result") });
    await expect(result).toBeVisible({ timeout: 30_000 });

    const safeAfter = await readLabeledMoney(
      result,
      "Safe to spend after purchase"
    );
    const before = await readLabeledMoney(result, "Before purchase");
    const purchaseLine = await readLabeledMoney(result, "Purchase");

    // The result explicitly shows a -$2,000 purchase line...
    expectMoneyEqual(
      purchaseLine,
      -2000,
      `major purchase should display a -$2,000 line, got $${purchaseLine.toFixed(2)}`
    );
    // ...and "safe after" is "before" minus that displayed $2,000.
    expectMoneyEqual(
      safeAfter,
      before - 2000,
      `safe-to-spend after ($${safeAfter.toFixed(2)}) should equal before ($${before.toFixed(2)}) minus the displayed $2,000`
    );

    // The Major Purchase current baseline should equal the canonical
    // current Safe-to-Spend (same assumptions, same "as of now"
    // semantics).
    expectMoneyEqual(
      before,
      canonical,
      `Major Purchase baseline ($${before.toFixed(2)}) should equal the Overview canonical Safe-to-Spend ($${canonical.toFixed(2)})`
    );
  });

  test("TEST 4 - buy now vs wait reconciles the displayed buffer gap", async ({
    page,
  }) => {
    await openDecisionMode(page, "Buy now vs wait");

    await page.getByLabel("Purchase name").fill("E2E Timing Laptop");
    await page.getByLabel("Purchase amount").fill("2000");
    // Keep the form's default deterministic dates (today / +30d).
    await page.getByLabel("Safety reserve").fill("0");
    await page.getByLabel("Essential spending").fill("0");
    await page.getByRole("button", { name: "Compare timing" }).click();

    const recommendation = page
      .locator("article")
      .filter({ has: page.getByText("Recommendation", { exact: true }) });
    await expect(recommendation).toBeVisible({ timeout: 30_000 });

    // A recommendation exists.
    await expect(
      recommendation.getByRole("heading", { level: 2 })
    ).not.toBeEmpty();

    // Both timing outcomes exist, in DOM order: Buy now, then Wait.
    const outcomeCards = page
      .locator("article")
      .filter({ has: page.getByText("Safe to spend after", { exact: true }) });
    await expect(outcomeCards).toHaveCount(2);
    await expect(outcomeCards.nth(0)).toContainText("Buy now");
    await expect(outcomeCards.nth(1)).toContainText("Wait");

    const buyNowAfter = await readLabeledMoney(
      outcomeCards.nth(0),
      "Safe to spend after"
    );
    const waitAfter = await readLabeledMoney(
      outcomeCards.nth(1),
      "Safe to spend after"
    );

    // The recommendation blurb states the buffer gap between the two
    // timings; it must reconcile with the two displayed outcomes.
    const bufferText = await recommendation
      .getByText(/difference in remaining buffer between the two timings/)
      .innerText();
    const bufferDifference = parseMoney(bufferText);

    expectMoneyEqual(
      Math.abs(buyNowAfter - waitAfter),
      Math.abs(bufferDifference),
      [
        "Buy-now vs wait buffer difference did not reconcile with the displayed outcomes.",
        `  Buy now safe-to-spend after: $${buyNowAfter.toFixed(2)}`,
        `  Wait safe-to-spend after:    $${waitAfter.toFixed(2)}`,
        `  Stated buffer difference:    $${bufferDifference.toFixed(2)}`,
      ].join("\n")
    );
  });

  test("TEST 5 - scenario comparison is symmetric ($1,500 apart)", async ({
    page,
  }) => {
    await openDecisionMode(page, "Compare options");

    const groupA = page
      .getByText("Option A", { exact: true })
      .locator("xpath=ancestor::div[1]");
    await groupA.getByLabel("Name").fill("E2E Standard Laptop");
    await groupA.getByLabel("Amount").fill("2000");

    const groupB = page
      .getByText("Option B", { exact: true })
      .locator("xpath=ancestor::div[1]");
    await groupB.getByLabel("Name").fill("E2E Premium Laptop");
    await groupB.getByLabel("Amount").fill("3500");

    await page.getByLabel("Safety reserve").fill("0");
    await page.getByLabel("Essential spending").fill("0");
    await page.getByRole("button", { name: "Run comparison" }).click();

    const cardA = page.locator("article").filter({
      has: page.getByRole("heading", {
        name: "E2E Standard Laptop",
        exact: true,
      }),
    });
    const cardB = page.locator("article").filter({
      has: page.getByRole("heading", {
        name: "E2E Premium Laptop",
        exact: true,
      }),
    });
    await expect(cardA).toBeVisible({ timeout: 30_000 });
    await expect(cardB).toBeVisible();

    const afterA = await readLabeledMoney(cardA, "Safe to spend after");
    const afterB = await readLabeledMoney(cardB, "Safe to spend after");

    // Only comparison symmetry is asserted -- not that either baseline
    // equals the canonical Safe-to-Spend.
    expectMoneyEqual(
      Math.abs(afterA - afterB),
      1500,
      [
        "The $2,000 and $3,500 options should differ by exactly $1,500 in safe-to-spend-after.",
        `  Option A ($2,000): $${afterA.toFixed(2)}`,
        `  Option B ($3,500): $${afterB.toFixed(2)}`,
        `  Difference:        $${Math.abs(afterA - afterB).toFixed(2)}`,
      ].join("\n")
    );
  });
});
