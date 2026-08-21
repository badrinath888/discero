import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// Any value prefixed NEXT_PUBLIC_ is compiled directly into the client
// JS bundle and readable by any Internet visitor -- nothing secret may
// ever use that prefix. Scans actual source files rather than trusting
// a fixed list, so a future accidental `NEXT_PUBLIC_*_KEY`/`_SECRET`/
// `_TOKEN` addition fails this test instead of shipping silently.
const SOURCE_DIRS = ["."];
const SOURCE_EXTENSIONS = [".ts", ".tsx"];
const SKIP_DIRS = new Set([
  "node_modules",
  ".next",
  ".git",
  "test",
]);

const SECRET_SHAPED = /_(KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)\b/i;

function collectSourceFiles(dir: string, root: string): string[] {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const files: string[] = [];

  for (const entry of entries) {
    if (entry.name.startsWith(".") && entry.name !== ".") continue;
    if (SKIP_DIRS.has(entry.name)) continue;

    const fullPath = path.join(dir, entry.name);

    if (entry.isDirectory()) {
      files.push(...collectSourceFiles(fullPath, root));
    } else if (
      SOURCE_EXTENSIONS.some((ext) => entry.name.endsWith(ext)) &&
      !entry.name.endsWith(".test.ts") &&
      !entry.name.endsWith(".test.tsx")
    ) {
      files.push(fullPath);
    }
  }

  return files;
}

describe("NEXT_PUBLIC_ env boundary", () => {
  it("no NEXT_PUBLIC_ variable name looks secret-shaped", () => {
    const root = path.resolve(__dirname);
    const files = SOURCE_DIRS.flatMap((dir) =>
      collectSourceFiles(path.join(root, dir), root)
    );

    const offenders: string[] = [];

    for (const file of files) {
      const content = fs.readFileSync(file, "utf-8");
      const matches = content.matchAll(/NEXT_PUBLIC_[A-Z0-9_]+/g);

      for (const match of matches) {
        if (SECRET_SHAPED.test(match[0])) {
          offenders.push(`${file}: ${match[0]}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });

  it("the only NEXT_PUBLIC_ variable actually used is the backend base URL", () => {
    const root = path.resolve(__dirname);
    const files = SOURCE_DIRS.flatMap((dir) =>
      collectSourceFiles(path.join(root, dir), root)
    );

    const found = new Set<string>();

    for (const file of files) {
      const content = fs.readFileSync(file, "utf-8");
      for (const match of content.matchAll(/NEXT_PUBLIC_[A-Z0-9_]+/g)) {
        found.add(match[0]);
      }
    }

    expect([...found]).toEqual(["NEXT_PUBLIC_API_URL"]);
  });
});
