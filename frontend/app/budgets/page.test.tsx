import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Budget, BudgetProgress } from "../lib/api";
import BudgetsPage from "./page";


const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  getBudgets: vi.fn(),
  getBudgetProgress: vi.fn(),
  saveBudget: vi.fn(),
  deleteBudget: vi.fn(),
  copyBudgets: vi.fn(),
  getUserId: vi.fn(),
  getToken: vi.fn(),
  clearSession: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace }),
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
      getBudgets: mocks.getBudgets,
      getBudgetProgress: mocks.getBudgetProgress,
      saveBudget: mocks.saveBudget,
      deleteBudget: mocks.deleteBudget,
      copyBudgets: mocks.copyBudgets,
    },
    session: {
      ...actual.session,
      getUserId: mocks.getUserId,
      getToken: mocks.getToken,
      clear: mocks.clearSession,
    },
  };
});

const budget: Budget = {
  id: 7,
  category: "Dining",
  month: "2026-08",
  limit_cents: 10_000,
};

const progress: BudgetProgress = {
  category: "Dining",
  month: "2026-08",
  limit_cents: 10_000,
  spent_cents: 12_500,
  remaining_cents: -2_500,
  percent_used: 125,
  over_budget_cents: 2_500,
  overspent: true,
};

async function renderPage() {
  render(<BudgetsPage />);
  await screen.findAllByText("Over budget");
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date(2026, 7, 3));
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({ id: 1, email: "user@example.com" });
  mocks.getBudgets.mockResolvedValue([budget]);
  mocks.getBudgetProgress.mockResolvedValue([progress]);
  mocks.deleteBudget.mockResolvedValue(undefined);
  mocks.copyBudgets.mockResolvedValue({
    source_month: "2026-07",
    target_month: "2026-08",
    copied: 1,
    updated: 0,
    skipped: 0,
    budgets: [budget],
  });
});

describe("monthly budgets", () => {
  it("deletes only the edited budget month after confirmation", async () => {
    await renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(
      screen.getByText("Other months are unchanged.", { exact: false })
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Delete budget" })
    );

    await waitFor(() =>
      expect(mocks.deleteBudget).toHaveBeenCalledWith(1, "Dining", "2026-08")
    );
    expect(
      await screen.findByText("Dining budget deleted for August 2026.")
    ).toBeInTheDocument();
  });

  it("copies the previous plan into the selected month", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Copy July 2026" })
    );

    await waitFor(() =>
      expect(mocks.copyBudgets).toHaveBeenCalledWith(
        1,
        "2026-07",
        "2026-08"
      )
    );
  });
});
