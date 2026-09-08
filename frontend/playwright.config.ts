import { defineConfig, devices } from "@playwright/test";

// Where the E2E run points its browser. Defaults to the local Next.js
// dev server; set E2E_BASE_URL to run the same specs against a deployed
// environment (a Vercel preview, or production for read-only smoke
// checks). No credentials belong here -- any that a spec needs come
// from the environment (e.g. E2E_USER_EMAIL / E2E_USER_PASSWORD) and
// are read inside the spec/fixture, never logged.
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

// Only boot a local dev server when the run targets localhost. When
// E2E_BASE_URL points elsewhere the target is assumed to be already up.
const isLocalTarget =
  baseURL.includes("localhost") || baseURL.includes("127.0.0.1");

// When credentials are present the run authenticates once (the "setup"
// project) and every authenticated spec reuses this storageState, so
// the backend login rate limiter is not hit once per spec. Without
// credentials the authenticated specs skip themselves, so no state
// file is expected and none is required.
const hasE2ECredentials = Boolean(
  process.env.E2E_USER_EMAIL && process.env.E2E_USER_PASSWORD
);
const storageState = "./playwright/.auth/user.json";

export default defineConfig({
  testDir: "./e2e",
  // Authenticated financial E2E specs share one seeded demo user.
  // Keep execution serial so mutating journeys cannot interfere with
  // Safe-to-Spend, forecast, totals, or other shared financial state.
  fullyParallel: false,
  workers: 1,
  // Fail the run if a spec was committed with test.only.
  forbidOnly: !!process.env.CI,
  // Retries only in CI, where flake is likelier to be infrastructural;
  // locally a failure should surface immediately.
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI
    ? [["html", { open: "never" }], ["list"]]
    : "list",
  use: {
    baseURL,
    // Discero honours `prefers-reduced-motion` (framer-motion
    // `useReducedMotion`). Emulating it here makes animated figures --
    // notably the Overview "Safe to spend" counter -- render their
    // final value immediately, so cross-surface amount comparisons read
    // a settled number instead of an in-flight animation frame.
    reducedMotion: "reduce",
    // Artifacts kept only for failures / the retry that follows one,
    // so a green run stays cheap.
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    // Authenticates once; writes storageState consumed below.
    { name: "setup", testMatch: /.*\.setup\.ts/ },
    {
      name: "chromium",
      testIgnore: /.*\.setup\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        // smoke.spec.ts opts back out via test.use(...) because it
        // must verify the unauthenticated Sign in dialog.
        storageState: hasE2ECredentials ? storageState : undefined,
      },
      dependencies: hasE2ECredentials ? ["setup"] : [],
    },
  ],
  webServer: isLocalTarget
    ? {
        command: "npm run dev",
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      }
    : undefined,
});
