import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  Budget,
  CashFlowForecast,
  CategoryTotal,
  Overview,
  SavingsGoal,
  Transaction,
} from "../lib/api";
import Dashboard from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  overview: vi.fn(),
  byCategory: vi.fn(),
  getBudgets: vi.fn(),
  getTransactions: vi.fn(),
  getSavingsGoals: vi.fn(),
  getCashFlowForecast: vi.fn(),
  uploadTransactions: vi.fn(),
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

vi.mock("../components/SafeToSpendCard", () => ({
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
      overview: mocks.overview,
      byCategory: mocks.byCategory,
      getBudgets: mocks.getBudgets,
      getTransactions: mocks.getTransactions,
      getSavingsGoals: mocks.getSavingsGoals,
      getCashFlowForecast: mocks.getCashFlowForecast,
      uploadTransactions: mocks.uploadTransactions,
    },
    session: {
      ...actual.session,
      getUserId: mocks.getUserId,
      getToken: mocks.getToken,
      clear: mocks.clearSession,
    },
  };
});

const overview: Overview = {
  total_income_cents: 500_000,
  total_spending_cents: 200_000,
  net_cents: 300_000,
  transaction_count: 42,
};

const categories: CategoryTotal[] = [
  { category: "Groceries", total_cents: 50_000, count: 5 },
];

const budgets: Budget[] = [
  { id: 1, category: "Groceries", month: "2026-08", limit_cents: 60_000 },
];

const transactions: Transaction[] = [
  {
    id: 1,
    posted_on: "2026-08-01",
    description: "Store",
    merchant_name: "Store",
    amount_cents: -1_000,
    category: "Groceries",
    source: "manual",
    pending: false,
    financial_account_id: null,
    account_name: null,
    institution_name: null,
  },
];

const goals: SavingsGoal[] = [
  {
    id: 1,
    name: "Emergency fund",
    target_cents: 100_000,
    saved_cents: 50_000,
    remaining_cents: 50_000,
    progress_percent: 50,
    target_date: null,
    status: "active",
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
  },
];

const cashFlow: CashFlowForecast = {
  as_of: "2026-08-06",
  month_end: "2026-08-31",
  days_remaining: 25,
  liquid_balance_cents: 400_000,
  income_received_cents: 300_000,
  expected_income_cents: 100_000,
  upcoming_bills_cents: 20_000,
  projected_end_balance_cents: 380_000,
  low_balance_risk: false,
  upcoming_cash_flows: [],
  confidence: {
    score: 90,
    level: "high",
    factors: [],
    recommendations: [],
    monthly_confidence: [],
  },
  horizon_outlook: [],
};

function resolveEverythingSuccessfully() {
  mocks.overview.mockResolvedValue(overview);
  mocks.byCategory.mockResolvedValue(categories);
  mocks.getBudgets.mockResolvedValue(budgets);
  mocks.getTransactions.mockResolvedValue(transactions);
  mocks.getSavingsGoals.mockResolvedValue(goals);
  mocks.getCashFlowForecast.mockResolvedValue(cashFlow);
}

beforeEach(() => {
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({
    id: 1,
    email: "user@example.com",
    email_verified: true,
  });
});

describe("dashboard loading vs empty distinction", () => {
  it("shows loading placeholders instead of misleading zero values or empty-state CTAs while data is still loading", async () => {
    let resolveOverview!: (value: Overview) => void;
    mocks.overview.mockReturnValue(
      new Promise((resolve) => {
        resolveOverview = resolve;
      })
    );
    mocks.byCategory.mockResolvedValue([]);
    mocks.getBudgets.mockResolvedValue([]);
    mocks.getTransactions.mockResolvedValue([]);
    mocks.getSavingsGoals.mockResolvedValue([]);
    mocks.getCashFlowForecast.mockResolvedValue(cashFlow);

    render(<Dashboard />);

    await screen.findByText("Net financial position");

    // No premature zero-value flash and no premature "empty" CTA copy.
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
    expect(
      screen.queryByText("No budgets configured")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("No savings goals yet")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("No recent transactions available.")
    ).not.toBeInTheDocument();

    resolveOverview(overview);

    expect(
      await screen.findByText("No budgets configured")
    ).toBeInTheDocument();
  });

  it("renders real values once the initial load succeeds", async () => {
    resolveEverythingSuccessfully();

    render(<Dashboard />);

    expect(await screen.findByText("$3,000.00")).toBeInTheDocument();
    expect(screen.getByText("1 active goal")).toBeInTheDocument();
    expect(screen.getByText("42 transactions")).toBeInTheDocument();
  });
});

describe("dashboard load failure", () => {
  it("shows a retryable error instead of zero values when the initial load fails, and retry reloads the data", async () => {
    mocks.overview.mockRejectedValueOnce(new Error("network down"));
    mocks.byCategory.mockResolvedValue(categories);
    mocks.getBudgets.mockResolvedValue(budgets);
    mocks.getTransactions.mockResolvedValue(transactions);
    mocks.getSavingsGoals.mockResolvedValue(goals);
    mocks.getCashFlowForecast.mockResolvedValue(cashFlow);

    render(<Dashboard />);

    expect(await screen.findByText("network down")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();

    resolveEverythingSuccessfully();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("$3,000.00")).toBeInTheDocument();
    expect(screen.queryByText("network down")).not.toBeInTheDocument();
  });

  it("shows an upload error without a stray retry button, and keeps already-loaded content visible", async () => {
    resolveEverythingSuccessfully();
    mocks.uploadTransactions.mockRejectedValueOnce(
      new Error("csv upload failed")
    );

    const { container } = render(<Dashboard />);
    await screen.findByText("$3,000.00");

    const file = new File(["a,b"], "transactions.csv", {
      type: "text/csv",
    });
    const input = container.querySelector(
      'input[type="file"]'
    ) as HTMLInputElement;

    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByText("csv upload failed")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Try again" })
    ).not.toBeInTheDocument();

    // Content that already loaded successfully must remain visible;
    // an upload failure must not wipe out unrelated successful data.
    expect(screen.getByText("1 active goal")).toBeInTheDocument();
    expect(screen.getByText("$3,000.00")).toBeInTheDocument();
  });
});
