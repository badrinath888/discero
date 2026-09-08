import { fileURLToPath, URL } from "node:url";

import { configDefaults, defineConfig } from "vitest/config";


export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    environmentOptions: {
      jsdom: {
        url: "http://localhost",
      },
    },
    globals: true,
    setupFiles: ["./test/setup.ts"],
    // Playwright owns everything under e2e/ -- keep Vitest from picking
    // up the *.spec.ts files there and trying to run them under jsdom.
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
});
