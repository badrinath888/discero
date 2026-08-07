import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MonthlyInsights } from "../lib/api";
import InsightsPage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  getMonthlyInsights: vi.fn(),
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
      getMonthlyInsights: mocks.getMonthlyInsights,
    },
    session: {
      ...actual.session,
      getUserId: mocks.getUserId,
      getToken: mocks.getToken,
      clear: mocks.clearSession,
    },
  };
});

const insights: MonthlyInsights = {
  month: "2026-08",
  previous_month: "2026-07",
  income_cents: 500_000,
  spending_cents: 200_000,
  net_cents: 300_000,
  savings_rate_percent: 60,
  spending_change_cents: 0,
  spending_change_percent: 0,
  insights: [],
};

beforeEach(() => {
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({
    id: 1,
    email: "user@example.com",
    email_verified: true,
  });
  mocks.getMonthlyInsights.mockResolvedValue(insights);
});

describe("insights month change performance", () => {
  it("does not re-check the session on every month change", async () => {
    render(<InsightsPage />);

    await waitFor(() =>
      expect(mocks.getMonthlyInsights).toHaveBeenCalledTimes(1)
    );
    expect(mocks.getMe).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText("Select month"), {
      target: { value: "2026-07" },
    });

    await waitFor(() =>
      expect(mocks.getMonthlyInsights).toHaveBeenCalledTimes(2)
    );
    expect(mocks.getMonthlyInsights).toHaveBeenLastCalledWith(1, "2026-07");
    expect(mocks.getMe).toHaveBeenCalledTimes(1);
  });
});
