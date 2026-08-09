import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GoalContribution, GoalIntelligence, SavingsGoal } from "../lib/api";
import GoalsPage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  getSavingsGoals: vi.fn(),
  getGoalContributions: vi.fn(),
  createGoalContribution: vi.fn(),
  getGoalIntelligence: vi.fn(),
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
      getGoalIntelligence: mocks.getGoalIntelligence,
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

describe("goal intelligence panel", () => {
  it("shows per-goal urgency, gap, and feasible target date after analyzing", async () => {
    await renderPage();

    const intelligence: GoalIntelligence = {
      as_of: "2026-08-08",
      conflict_status: "conflict",
      total_capacity_cents: 50_000,
      total_required_cents: 200_000,
      total_shortfall_cents: 150_000,
      largest_pressure_goal_id: 1,
      confidence_score: 90,
      explanation: "Your goals require more than your current capacity.",
      suggestions: ["Increase monthly savings by $1,500.00."],
      goals: [
        {
          goal_id: 1,
          name: "Emergency fund",
          target_amount_cents: 500_000,
          saved_amount_cents: 100_000,
          remaining_amount_cents: 400_000,
          target_date: "2026-12-08",
          months_remaining: 4,
          required_monthly_cents: 100_000,
          allocated_monthly_cents: 50_000,
          monthly_gap_cents: 50_000,
          status: "conflict",
          projected_completion_date: "2027-02-08",
          suggested_feasible_target_date: "2027-02-08",
          urgency_rank: 1,
          confidence_score: 90,
          explanation: "Emergency fund needs $1,000.00/month.",
        },
      ],
    };
    mocks.getGoalIntelligence.mockResolvedValue(intelligence);

    fireEvent.change(screen.getByPlaceholderText("1000.00"), {
      target: { value: "500" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analyze my goals" }));

    expect(await screen.findByText("Most urgent")).toBeInTheDocument();
    expect(
      screen.getByText("Largest contributor to shortfall")
    ).toBeInTheDocument();
    expect(mocks.getGoalIntelligence).toHaveBeenCalledWith(1, 50_000);
  });
});

describe("goals drawer mobile layout", () => {
  it("renders full-width form fields instead of browser-default-sized inputs", async () => {
    await renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Funds" }));
    const amountInput = await screen.findByLabelText("Amount");

    expect(amountInput.className).toContain("w-full");
    expect(screen.getByLabelText("Date").className).toContain("w-full");
    expect(screen.getByLabelText("Note").className).toContain("w-full");
  });
});
