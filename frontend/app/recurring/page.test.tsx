import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RecurringItem, RecurringPayment } from "../lib/api";
import RecurringPage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  getRecurringPayments: vi.fn(),
  getRecurringItems: vi.fn(),
  createRecurringItem: vi.fn(),
  getUserId: vi.fn(),
  getToken: vi.fn(),
  clearSession: vi.fn(),
}));

const routerMock = { replace: mocks.replace, push: vi.fn() };

vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
}));

vi.mock("framer-motion", async () => {
  const { createElement } = await import("react");
  const ignored = new Set([
    "animate",
    "exit",
    "initial",
    "layout",
    "transition",
    "whileHover",
  ]);
  const motion = new Proxy(
    {},
    {
      get: (_target, tag: string) =>
        ({ children, ...props }: Record<string, unknown>) =>
          createElement(
            tag,
            Object.fromEntries(
              Object.entries(props).filter(([name]) => !ignored.has(name))
            ),
            children as ReactNode
          ),
    }
  );

  return {
    AnimatePresence: ({ children }: { children: ReactNode }) => children,
    motion,
    useReducedMotion: () => true,
  };
});

vi.mock("../components/AppSidebar", () => ({
  default: () => null,
}));

vi.mock("../components/PremiumMotion", () => ({
  AnimatedNumber: ({
    value,
    format,
  }: {
    value: number;
    format: (value: number) => string;
  }) => <span>{format(value)}</span>,
  PageReveal: ({ children }: { children: ReactNode }) => children,
  Reveal: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();

  return {
    ...actual,
    api: {
      ...actual.api,
      getMe: mocks.getMe,
      getRecurringPayments: mocks.getRecurringPayments,
      getRecurringItems: mocks.getRecurringItems,
      createRecurringItem: mocks.createRecurringItem,
    },
    session: {
      ...actual.session,
      getUserId: mocks.getUserId,
      getToken: mocks.getToken,
      clear: mocks.clearSession,
    },
  };
});

const detectedPayment: RecurringPayment = {
  merchant: "Streamflix",
  amount_cents: 1_599,
  frequency: "Monthly",
  last_payment: "2026-07-01",
  next_payment: "2026-08-01",
  days_until_due: 5,
  occurrences: 3,
  confidence_score: 90,
  price_change_percent: 0,
  price_change_warning: false,
};

const createdItem: RecurringItem = {
  id: 1,
  merchant: "Streamflix",
  normalized_merchant: "STREAMFLIX",
  category: "Subscriptions",
  amount_cents: 1_599,
  frequency: "Monthly",
  last_payment: "2026-07-01",
  next_payment: "2026-08-01",
  status: "active",
  confidence_score: 90,
  price_change_percent: 0,
  price_change_warning: false,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

beforeEach(() => {
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({
    id: 1,
    email: "user@example.com",
    email_verified: true,
  });
  mocks.getRecurringPayments.mockResolvedValue([detectedPayment]);
  mocks.getRecurringItems.mockResolvedValue([]);
  mocks.createRecurringItem.mockResolvedValue(createdItem);
});

describe("recurring confirm-detected performance", () => {
  it("adds the confirmed item locally instead of reloading both lists", async () => {
    render(<RecurringPage />);

    await screen.findByText("Streamflix");
    expect(mocks.getRecurringPayments).toHaveBeenCalledTimes(1);
    expect(mocks.getRecurringItems).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() =>
      expect(mocks.createRecurringItem).toHaveBeenCalledOnce()
    );

    // The detected suggestion should disappear once it's confirmed
    // as a managed item, without a fresh reload of either list.
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Confirm" })
      ).not.toBeInTheDocument()
    );
    expect(mocks.getRecurringPayments).toHaveBeenCalledTimes(1);
    expect(mocks.getRecurringItems).toHaveBeenCalledTimes(1);
  });
});
