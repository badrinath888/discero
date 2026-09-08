import { expect, test } from "./helpers/fixtures";

// Phase 1 smoke check: the public landing page renders and its primary
// call-to-action opens the authentication dialog. Fully client-rendered
// -- exercises no backend, needs no credentials, mutates no data.
//
// This spec must run signed OUT even when the rest of the suite reuses
// a shared authenticated storageState, so it verifies the Sign in CTA.
test.use({ storageState: { cookies: [], origins: [] } });

test.describe("smoke", () => {
  test("landing page renders", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveTitle(/Discero/);
    await expect(
      page.getByRole("heading", { name: "Discern before you decide." })
    ).toBeVisible();
  });

  test("sign-in call-to-action opens the auth dialog", async ({ page }) => {
    await page.goto("/");

    await page
      .getByRole("navigation")
      .getByRole("button", { name: "Sign in" })
      .click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByRole("heading", { name: "Welcome back" })
    ).toBeVisible();
    await expect(
      dialog.getByLabel("Email address", { exact: true })
    ).toBeVisible();
    await expect(
      dialog.getByLabel("Password", { exact: true })
    ).toBeVisible();
  });
});
