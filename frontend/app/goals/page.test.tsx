import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GoalContribution, SavingsGoal } from "../lib/api";
import GoalsPage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  getSavingsGoals: vi.fn(),
  getGoalContributions: vi.fn(),
  createGoalContribution: vi.fn(),
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
      getSavingsGoals: mocks.getSavingsGoals,
      getGoalContributions: mocks.getGoalContributions,
      createGoalContribution: mocks.createGoalContribution,
    },
    session: {
      ...actual.session,
      getUserId: mocks.getUserId,
      getToken: mocks.getToken,
      clear: mocks.clearSession,
    },
  };
});

const goal: SavingsGoal = {
  id: 1,
  name: "Emergency fund",
  target_cents: 500_000,
  saved_cents: 100_000,
  remaining_cents: 400_000,
  progress_percent: 20,
  target_date: null,
  status: "active",
  created_at: "2026-01-01",
  updated_at: "2026-01-01",
};

const contribution: GoalContribution = {
  id: 1,
  goal_id: 1,
  amount_cents: 100_000,
  contribution_type: "deposit",
  contributed_on: "2026-01-01",
  note: null,
  created_at: "2026-01-01",
  updated_at: "2026-01-01",
};

async function renderPage() {
  render(<GoalsPage />);
  await screen.findByText("Emergency fund");
}

beforeEach(() => {
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({
    id: 1,
    email: "user@example.com",
    email_verified: true,
  });
  mocks.getSavingsGoals.mockResolvedValue([goal]);
  mocks.getGoalContributions.mockResolvedValue([contribution]);
});

describe("goals loading and error states", () => {
  it("shows a retryable error instead of an empty state when the initial load fails", async () => {
    mocks.getSavingsGoals.mockRejectedValueOnce(new Error("network down"));

    render(<GoalsPage />);

    expect(await screen.findByText("network down")).toBeInTheDocument();
    expect(
      screen.queryByText("No savings goals yet")
    ).not.toBeInTheDocument();

    mocks.getSavingsGoals.mockResolvedValue([goal]);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Emergency fund")).toBeInTheDocument();
  });
});

describe("goals contribution submission", () => {
  it("keeps the success message when the save succeeds but the follow-up refresh fails", async () => {
    await renderPage();
    mocks.createGoalContribution.mockResolvedValue(contribution);
    mocks.getSavingsGoals.mockRejectedValueOnce(
      new Error("refresh failed")
    );

    fireEvent.click(screen.getByRole("button", { name: "Funds" }));
    await screen.findByLabelText("Amount");

    // Wait for the contribution-history fetch to fully settle first —
    // its resolution re-renders the drawer, which would otherwise
    // discard an in-progress edit made while it was still in flight.
    await waitFor(() =>
      expect(
        screen.queryByText("Loading contribution history...")
      ).not.toBeInTheDocument()
    );

    const amountInput = screen.getByLabelText("Amount");
    fireEvent.change(amountInput, {
      target: { value: "50" },
    });

    await waitFor(() => expect(amountInput).toHaveValue(50));

    fireEvent.click(screen.getByRole("button", { name: /Add deposit/ }));

    await waitFor(() =>
      expect(mocks.createGoalContribution).toHaveBeenCalled()
    );

    expect(
      await screen.findByText("$50.00 deposited.")
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Unable to save contribution")
    ).not.toBeInTheDocument();
  });
});
