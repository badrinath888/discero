import { expect, test } from "./helpers/fixtures";
import { login, requireAuthenticatedEnv } from "./helpers/auth";
import { allMoney } from "./helpers/money";
import { readOverviewSafeToSpend } from "./helpers/surfaces";

// Phase 2 -- authenticated core journeys.
//
// TEST 1: sign in -> authenticated Overview renders real content.
// TEST 2: the canonical current Safe-to-Spend is consistent between the
//         surfaces that claim that exact semantics (Overview and Ask
//         Discero). Recommendations is intentionally excluded: that
//         surface does not display a canonical current Safe-to-Spend.
//
// No financial value is recomputed here -- amounts are read from the
// rendered UI and only normalised for presentation ($ / commas /
// whitespace) before comparison.

test.describe("authenticated overview", () => {
  test.beforeEach(async ({ page }) => {
    requireAuthenticatedEnv();
    await login(page);
  });

  test("TEST 1 - login lands on a populated Overview", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: "Overview", level: 1 })
    ).toBeVisible();

    // A meaningful authenticated element, not merely HTTP 200: the
    // Safe-to-Spend card resolves to a real currency figure.
    const card = page
      .locator("section")
      .filter({ has: page.getByText("Safe to spend", { exact: true }) })
      .first();
    await expect(card.getByText(/^-?\$[\d,]+\.\d{2}$/).first()).toBeVisible({
      timeout: 15_000,
    });

    // Authenticated shell: the main navigation (absent on the public
    // landing page) is present with its app links.
    await expect(
      page
        .getByRole("navigation", { name: "Main navigation" })
        .getByRole("link", { name: "Ask Discero" })
        .first()
    ).toBeVisible();
  });

  test("TEST 2 - canonical Safe-to-Spend matches across Overview and Ask Discero", async ({
    page,
  }) => {
    const overviewValue = await readOverviewSafeToSpend(page);
    expect(
      overviewValue,
      "Overview Safe-to-Spend should be a real figure"
    ).not.toBeNaN();

    await page.goto("/copilot");
    await expect(
      page.getByRole("heading", { name: "Ask Discero" })
    ).toBeVisible();

    const thread = page.getByTestId("copilot-thread");
    await page
      .getByRole("textbox", { name: "Message", exact: true })
      .fill("How much can I safely spend right now?");
    await page.getByRole("button", { name: "Send message" }).click();

    // A grounded answer renders as an <article>; clarifying / unavailable
    // responses render as <div>. Wait for a real answer or fail with the
    // full thread text captured.
    await expect(async () => {
      const count = await thread.locator("article").count();
      expect(
        count,
        `Ask Discero did not return a grounded answer.\nThread:\n${await thread.innerText()}`
      ).toBeGreaterThan(0);
    }).toPass({ timeout: 60_000 });

    const answerText = await thread.locator("article").last().innerText();
    const amountsShown = allMoney(answerText);

    // Consistency: Ask Discero, answering the canonical current
    // question, must surface the same current Safe-to-Spend the
    // Overview shows.
    expect(
      amountsShown.some((v) => Math.abs(v - overviewValue) < 0.01),
      [
        "Ask Discero's current Safe-to-Spend did not match the Overview.",
        `  Overview:      $${overviewValue.toFixed(2)}`,
        `  Ask Discero:   ${amountsShown.map((v) => `$${v.toFixed(2)}`).join(", ") || "(no currency shown)"}`,
        `  Prompt:        "How much can I safely spend right now?"`,
        `  Answer:\n${answerText}`,
      ].join("\n")
    ).toBe(true);
  });
});
