import { expect, test } from "./helpers/fixtures";
import { login, requireAuthenticatedEnv } from "./helpers/auth";
import { openDecisionMode } from "./helpers/surfaces";

// Phase 3B -- saved decision lifecycle.
//
// Covers persistence + lifecycle UI only (no financial math is
// re-validated here):
//   save a What-if decision -> it appears in Decision History
//   -> "I made this decision" (acted on) -> "Check outcome"
//   -> lifecycle timeline shows analyzed/saved, acted on, outcome checked
//   -> delete the E2E-created decision.
//
// The decision name carries a per-run suffix so the card is uniquely
// targetable even if a previous run's cleanup did not complete. Inputs
// ($123.45 one-time purchase, zero reserve/essential) stay deterministic.
const RUN_ID = Date.now();
const DECISION_NAME = `E2E Decision Lifecycle ${RUN_ID}`;

test.describe("decision history - saved decision lifecycle", () => {
  test.beforeEach(async ({ page }) => {
    requireAuthenticatedEnv();
    await login(page);
  });

  test("save -> acted on -> outcome -> timeline -> delete", async ({ page }) => {
    // 1. Create + save a deterministic What-if decision.
    await openDecisionMode(page, "What-if simulator");

    // Sub-tab "Single scenario" and scenario type "One-time purchase"
    // are the defaults.
    await page.getByLabel("Scenario name").fill(DECISION_NAME);
    await page.getByLabel("Amount").fill("123.45");
    await page.getByLabel("Safety reserve").fill("0");
    await page.getByLabel("Essential spending").fill("0");
    await page.getByRole("button", { name: "Run simulation" }).click();

    const result = page
      .locator("article")
      .filter({ has: page.getByText("What-if result") });
    await expect(result).toBeVisible({ timeout: 30_000 });

    // The save control is a sibling of the result panel, not inside it.
    await page.getByRole("button", { name: "Save this scenario" }).click();
    await expect(
      page.getByText("Saved to your decision history.")
    ).toBeVisible({ timeout: 30_000 });

    // 2. It appears in Decision History.
    await page.goto("/decisions/history");
    await expect(
      page.getByRole("heading", { name: "Your decision record.", level: 1 })
    ).toBeVisible();

    const heading = page.getByRole("heading", {
      name: DECISION_NAME,
      level: 2,
      exact: true,
    });
    await expect(heading).toBeVisible({ timeout: 30_000 });

    const card = page
      .getByTestId("decision-history-card")
      .filter({ has: heading });

    await expect(card.getByText(/Analyzed/)).toBeVisible();

    // 3. Mark it acted on.
    await card
      .getByRole("button", { name: "I made this decision" })
      .click();

    // 4. Acted-on state + date appear.
    await expect(card.getByText(/^Acted on/)).toBeVisible({ timeout: 30_000 });

    // 5. Check the outcome.
    await card.getByRole("button", { name: "Check outcome" }).click();

    // 6. Outcome / calibration screen renders.
    await expect(
      page.getByTestId("decision-outcome-panel")
    ).toBeVisible({ timeout: 30_000 });
    await expect(
      page.getByTestId("decision-calibration-section")
    ).toBeVisible({ timeout: 30_000 });

    // 7. Lifecycle timeline lists the three lifecycle events using the
    // current UI wording.
    await card.getByRole("button", { name: "View timeline" }).click();
    const timeline = card.getByTestId("decision-timeline-panel");
    await expect(timeline).toBeVisible({ timeout: 30_000 });
    await expect(timeline.getByText("Analyzed & saved")).toBeVisible();
    await expect(timeline.getByText("Acted on", { exact: true })).toBeVisible();
    await expect(timeline.getByText("Outcome checked")).toBeVisible();

    // 8. Clean up the E2E-created decision (deletion is supported).
    await card.getByRole("button", { name: "Delete" }).click();
    await expect(heading).toHaveCount(0, { timeout: 30_000 });
  });
});
