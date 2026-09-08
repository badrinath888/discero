// Central re-export so every spec imports `test` / `expect` from one
// place. Later phases add fixtures here -- a signed-in browser context,
// seeded E2E/demo data -- rather than repeating setup across specs.
export { test, expect } from "@playwright/test";
