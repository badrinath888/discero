import { expect, test } from "./fixtures";
import type { Page } from "@playwright/test";

// Phase 2 introduces the first authenticated E2E journeys. Credentials
// are never committed -- they come only from the environment:
//
//   E2E_USER_EMAIL / E2E_USER_PASSWORD
//
// against a local/test backend (or a dedicated demo user). When they
// are missing, authenticated specs skip with a clear reason rather than
// failing obscurely deep inside a sign-in form.
export const E2E_USER_EMAIL = process.env.E2E_USER_EMAIL ?? "";
export const E2E_USER_PASSWORD = process.env.E2E_USER_PASSWORD ?? "";

export const hasE2ECredentials = Boolean(
  E2E_USER_EMAIL && E2E_USER_PASSWORD
);

const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
// Phase 2 tests sign in and drive decision-simulation endpoints. They
// are for local/test data only -- never a production-like target.
export const isLocalTarget =
  baseURL.includes("localhost") || baseURL.includes("127.0.0.1");

/**
 * Gate an authenticated Phase 2 describe block. Skips (visibly, with a
 * reason) when credentials are absent or the target is not local.
 */
export function requireAuthenticatedEnv(): void {
  test.skip(
    !hasE2ECredentials,
    "Set E2E_USER_EMAIL and E2E_USER_PASSWORD to run authenticated Phase 2 specs"
  );
  test.skip(
    !isLocalTarget,
    `Authenticated Phase 2 specs mutate/simulate against user data; they run only against a local target (E2E_BASE_URL=${baseURL})`
  );
}

/**
 * Sign in through the real landing-page dialog and land on the
 * authenticated Overview. Leaves the browser context authenticated for
 * subsequent same-context navigations (token lives in localStorage).
 */
export async function login(page: Page): Promise<void> {
  // Reused storageState (see e2e/auth.setup.ts) means the context is
  // usually already signed in. Detect that from the persisted access
  // token and skip the form entirely, so the full suite issues at most
  // one login POST and never trips the backend rate limiter.
  await page.goto("/dashboard");
  const alreadyAuthenticated = await page
    .evaluate(() => {
      try {
        return Boolean(window.localStorage.getItem("accessToken"));
      } catch {
        return false;
      }
    })
    .catch(() => false);
  if (alreadyAuthenticated) {
    await expect(
      page.getByRole("heading", { name: "Overview", level: 1 })
    ).toBeVisible();
    return;
  }

  await page.goto("/");

  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Sign in" })
    .click();

  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "Welcome back" })
  ).toBeVisible();

  await dialog
    .getByLabel("Email address", { exact: true })
    .fill(E2E_USER_EMAIL);
  await dialog
    .getByLabel("Password", { exact: true })
    .fill(E2E_USER_PASSWORD);

  await dialog
    .getByRole("button", { name: "Sign in to Discero" })
    .click();

  // A failed sign-in keeps the dialog open and shows an inline alert;
  // surface that as the failure reason instead of a bare URL timeout.
  await Promise.race([
    page.waitForURL("**/dashboard"),
    dialog
      .getByRole("alert")
      .waitFor({ state: "visible" })
      .then(async () => {
        const message = (await dialog.getByRole("alert").textContent())?.trim();
        throw new Error(`Sign-in failed: ${message ?? "unknown error"}`);
      }),
  ]);

  await expect(
    page.getByRole("heading", { name: "Overview", level: 1 })
  ).toBeVisible();
}
