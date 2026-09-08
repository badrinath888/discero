import { test as setup } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import {
  hasE2ECredentials,
  isLocalTarget,
  login,
} from "./helpers/auth";

// One-time authentication for the whole run. Every authenticated spec
// reuses the storageState this writes, so the backend login rate
// limiter is hit at most once per invocation instead of once per spec.
//
// Credentials still come only from E2E_USER_EMAIL / E2E_USER_PASSWORD
// and the resulting state file is git-ignored (playwright/.auth/).
export const STORAGE_STATE = path.join(
  __dirname,
  "..",
  "playwright",
  ".auth",
  "user.json"
);

setup("authenticate", async ({ page }) => {
  setup.skip(
    !hasE2ECredentials,
    "Set E2E_USER_EMAIL and E2E_USER_PASSWORD to run authenticated specs"
  );
  setup.skip(
    !isLocalTarget,
    "Authenticated specs run only against a local target"
  );

  await login(page);

  fs.mkdirSync(path.dirname(STORAGE_STATE), { recursive: true });
  await page.context().storageState({ path: STORAGE_STATE });
});
