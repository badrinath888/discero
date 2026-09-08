import { expect } from "./fixtures";
import type { Locator } from "@playwright/test";

// Discero renders every currency amount through `formatCents`, which
// emits "$1,234.56" or "-$1,234.56". Phase 2 tests compare amounts
// *across surfaces*, so they only ever normalise presentation
// (dollar sign, grouping commas, whitespace) -- never recompute a
// financial value.

const MONEY_TOKEN = /-?\$\s?[\d,]+(?:\.\d{2})?/g;

/**
 * Parse a single displayed currency string into a number of dollars.
 * "-$1,234.56" -> -1234.56
 */
export function parseMoney(text: string): number {
  const match = text.match(/-?\$\s?[\d,]+(?:\.\d{2})?/);
  if (!match) {
    throw new Error(`No currency value found in ${JSON.stringify(text)}`);
  }
  const negative = match[0].trim().startsWith("-");
  const digits = match[0].replace(/[^\d.]/g, "");
  const value = Number(digits);
  return negative ? -value : value;
}

/** Every currency amount appearing in a blob of text, in order. */
export function allMoney(text: string): number[] {
  return (text.match(MONEY_TOKEN) ?? []).map(parseMoney);
}

/**
 * Read the value paragraph that follows a label inside one of the
 * decision result panels. Panels render as
 *   <p>{label}</p><p>{formatCents(value)}</p>
 * so the value is the next sibling <p>/<span>/<dd>.
 */
export async function readLabeledMoney(
  scope: Locator,
  label: string
): Promise<number> {
  const value = scope
    .getByText(label, { exact: true })
    .locator(
      "xpath=following-sibling::*[self::p or self::span or self::dd][1]"
    )
    .first();
  await expect(value).toBeVisible();
  return parseMoney((await value.textContent()) ?? "");
}

/** Assert two displayed dollar amounts match within half a cent. */
export function expectMoneyEqual(
  actual: number,
  expected: number,
  message?: string
): void {
  expect(
    Math.abs(actual - expected),
    message ??
      `expected ${actual} to equal ${expected} (displayed dollar amounts)`
  ).toBeLessThan(0.005);
}
