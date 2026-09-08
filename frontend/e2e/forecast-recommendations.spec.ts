import { expect, test } from "./helpers/fixtures";
import { login, requireAuthenticatedEnv } from "./helpers/auth";
import { allMoney } from "./helpers/money";
import { readOverviewSafeToSpend } from "./helpers/surfaces";

// Phase 4D -- Forecast + Recommendations consistency (read-only).
//
// Canonical current Safe-to-Spend is only asserted equal across
// surfaces that CLAIM that exact semantics. As of this codebase:
//   - Overview and Ask Discero claim it  -> compared for equality.
//   - Forecast shows projected month-end / 30-60-90-day horizon
//     BALANCES, never a current Safe-to-Spend -> comparison SKIPPED.
//   - Recommendation cards show scenario/impact figures, never a
//     current canonical Safe-to-Spend -> comparison SKIPPED.
// No financial value is recomputed; amounts are read from the UI.

const MONEY = /-?\$[\d,]+\.\d{2}/;

test.describe("forecast + recommendations consistency", () => {
  test.beforeEach(async ({ page }) => {
    requireAuthenticatedEnv();
    await login(page);
  });

  test("forecast renders horizon + projections; canonical STS consistent Overview<->Ask", async ({
    page,
  }, testInfo) => {
    test.setTimeout(120_000);

    // 1. FORECAST PAGE.
    await page.goto("/forecast");
    await expect(
      page.getByRole("heading", { name: "Forecast", level: 1 })
    ).toBeVisible();

    // Forecast horizon / date renders.
    await expect(
      page.getByText(/Through .+\d{4}.* days/).first()
    ).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/30 . 60 . 90-day/).first()).toBeVisible();

    // Projected values render.
    const projected = page
      .locator("section")
      .filter({ has: page.getByText("Projected month-end balance") })
      .first();
    await expect(projected.getByText(MONEY).first()).toBeVisible();

    // Forecast canonical Safe-to-Spend: NOT exposed here (month-end /
    // horizon balance semantics differ from current canonical STS).
    const forecastExposesSts = await page
      .getByText(/safe.to.spend/i)
      .count();
    expect(
      forecastExposesSts,
      "Forecast unexpectedly shows a Safe-to-Spend label; re-evaluate its semantics before comparing"
    ).toBe(0);
    testInfo.annotations.push({
      type: "note",
      description:
        "Forecast canonical comparison SKIPPED: page exposes projected horizon balances, not current Safe-to-Spend.",
    });

    // 2. CANONICAL SAFE-TO-SPEND CONSISTENCY: Overview <-> Ask Discero.
    const overviewValue = await readOverviewSafeToSpend(page);
    expect(overviewValue, "Overview Safe-to-Spend should be real").not.toBeNaN();

    await page.goto("/copilot");
    await expect(
      page.getByRole("heading", { name: "Ask Discero" })
    ).toBeVisible();
    const thread = page.getByTestId("copilot-thread");
    await page
      .getByRole("textbox", { name: "Message", exact: true })
      .fill("How much can I safely spend right now?");
    await page.getByRole("button", { name: "Send message" }).click();

    await expect(async () => {
      const count = await thread.locator("article").count();
      expect(
        count,
        `Ask Discero did not return a grounded answer.\nThread:\n${await thread.innerText()}`
      ).toBeGreaterThan(0);
    }).toPass({ timeout: 60_000 });

    const answerText = await thread.locator("article").last().innerText();
    const amountsShown = allMoney(answerText);
    expect(
      amountsShown.some((v) => Math.abs(v - overviewValue) < 0.01),
      [
        "Ask Discero's current Safe-to-Spend did not match the Overview.",
        `  Overview:    $${overviewValue.toFixed(2)}`,
        `  Ask Discero: ${amountsShown.map((v) => `$${v.toFixed(2)}`).join(", ") || "(none)"}`,
        `  Answer:\n${answerText}`,
      ].join("\n")
    ).toBe(true);

    // 3. RECOMMENDATIONS surface renders.
    await page.goto("/recommendations");
    await expect(
      page.getByRole("heading", { name: "Recommendations", level: 1 })
    ).toBeVisible();

    const cards = page.getByTestId("recommendation-card");
    const empty = page.getByTestId("recommendations-empty");
    await expect(cards.first().or(empty)).toBeVisible({ timeout: 30_000 });
    const cardCount = await cards.count();

    // Recommendations canonical comparison: SKIPPED -- cards surface
    // impact / scenario figures, never a labelled current canonical
    // Safe-to-Spend.
    testInfo.annotations.push({
      type: "note",
      description:
        "Recommendations canonical comparison SKIPPED: no card claims current canonical Safe-to-Spend semantics.",
    });

    // 4. Seeded REI duplicate recommendation -- verify only if present;
    // never create data to make it appear.
    if (cardCount > 0) {
      const rei = cards.filter({ hasText: /REI/i });
      if ((await rei.count()) > 0) {
        await expect(rei.first()).toBeVisible();
        testInfo.annotations.push({
          type: "note",
          description: `Duplicate REI recommendation present: ${await rei.count()} matching card(s).`,
        });
      } else {
        testInfo.annotations.push({
          type: "note",
          description:
            "Duplicate REI recommendation SKIPPED: not present in this session's seeded data.",
        });
      }
    }
  });
});
