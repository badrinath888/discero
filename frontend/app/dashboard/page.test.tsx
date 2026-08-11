import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  Budget,
  CashFlowForecast,
  CategoryTotal,
  FinancialAccount,
  FinancialResilience,
  Overview,
  Recommendation,
  SafeToSpendResult,
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
  getRecommendations: vi.fn(),
  getSafeToSpend: vi.fn(),
  getFinancialResilience: vi.fn(),
  getAccounts: vi.fn(),
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
      getRecommendations: mocks.getRecommendations,
      getSafeToSpend: mocks.getSafeToSpend,
      getFinancialResilience: mocks.getFinancialResilience,
      getAccounts: mocks.getAccounts,
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

const safeToSpend: SafeToSpendResult = {
  as_of: "2026-08-09",
  through_date: "2026-09-08",
  horizon_days: 30,
  safe_to_spend_cents: 120_000,
  shortfall_cents: 0,
  status: "safe",
  confidence_score: 82,
  breakdown: {
    liquid_balance_cents: 400_000,
    upcoming_obligations_cents: 20_000,
    essential_spending_cents: 0,
    safety_reserve_cents: 0,
  },
  obligations: [],
  warnings: [],
};

const resilience: FinancialResilience = {
  as_of: "2026-08-09",
  liquid_balance_cents: 400_000,
  liquid_account_count: 2,
  monthly_essential_cents: 150_000,
  essential_spending_source: "derived",
  spending_basis_label: "Recent spending pace",
  months_of_spending_data: 3,
  runway_months: 4,
  runway_days: 122,
  resilience_status: "strong",
  horizons: [],
  confidence_score: 70,
  data_quality_note: null,
  headline: "Your spending coverage is strong",
  why: "Liquid balance comfortably exceeds recent spending pace.",
  what_this_means: "You could cover several months of spending.",
  suggested_actions: [],
  warnings: [],
};

function resolveEverythingSuccessfully() {
  mocks.overview.mockResolvedValue(overview);
  mocks.byCategory.mockResolvedValue(categories);
  mocks.getBudgets.mockResolvedValue(budgets);
  mocks.getTransactions.mockResolvedValue(transactions);
  mocks.getSavingsGoals.mockResolvedValue(goals);
  mocks.getCashFlowForecast.mockResolvedValue(cashFlow);
  mocks.getRecommendations.mockResolvedValue({
    as_of: "2026-08-09",
    recommendations: [],
  });
  mocks.getSafeToSpend.mockResolvedValue(safeToSpend);
  mocks.getFinancialResilience.mockResolvedValue(resilience);
  mocks.getAccounts.mockResolvedValue([]);
}

beforeEach(() => {
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({
    id: 1,
    email: "user@example.com",
    email_verified: true,
  });
  mocks.getRecommendations.mockResolvedValue({
    as_of: "2026-08-09",
    recommendations: [],
  });
  mocks.getSafeToSpend.mockResolvedValue(safeToSpend);
  mocks.getFinancialResilience.mockResolvedValue(resilience);
  mocks.getAccounts.mockResolvedValue([]);
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

const recommendation: Recommendation = {
  id: "recurring-bill-increase",
  category: "recurring",
  severity: "warning",
  priority: 1,
  title: "Netflix increased by $3.00",
  summary: "Netflix now charges $18.00, up from $15.00 (20%).",
  why: "Based on 4 recent charges, the latest amount is meaningfully higher.",
  recommended_action: "Review this bill to confirm the increase is expected.",
  impact: "20% increase",
  confidence: null,
  source_signals: [],
  deep_link: "/recurring",
  evaluated_at: "2026-08-09",
};

describe("dashboard needs-attention section", () => {
  it("shows top recommendation signals when present", async () => {
    resolveEverythingSuccessfully();
    mocks.getRecommendations.mockResolvedValue({
      as_of: "2026-08-09",
      recommendations: [recommendation],
    });

    render(<Dashboard />);

    const heading = await screen.findByText("Needs attention");
    const section = heading.closest("section") as HTMLElement;

    expect(
      within(section).getByText("Netflix increased by $3.00")
    ).toBeInTheDocument();
    expect(within(section).getByText("20% increase")).toBeInTheDocument();
  });

  it("navigates to the signal's deep link when clicked", async () => {
    resolveEverythingSuccessfully();
    mocks.getRecommendations.mockResolvedValue({
      as_of: "2026-08-09",
      recommendations: [recommendation],
    });

    render(<Dashboard />);

    const heading = await screen.findByText("Needs attention");
    const section = heading.closest("section") as HTMLElement;

    fireEvent.click(within(section).getByText("Netflix increased by $3.00"));

    expect(routerMock.push).toHaveBeenCalledWith("/recurring");
  });

  it("stays out of the way entirely when nothing needs attention", async () => {
    resolveEverythingSuccessfully();

    render(<Dashboard />);

    await screen.findByText("$3,000.00");
    expect(screen.queryByText("Needs attention")).not.toBeInTheDocument();
  });
});

describe("dashboard executive intelligence", () => {
  it("surfaces safe-to-spend, cash outlook, and resilience once loaded", async () => {
    resolveEverythingSuccessfully();

    render(<Dashboard />);

    const summary = await screen.findByLabelText(
      "Executive financial summary"
    );

    expect(within(summary).getByText("Safe to spend")).toBeInTheDocument();
    expect(within(summary).getByText("$1,200.00")).toBeInTheDocument();
    expect(within(summary).getByText("82% confidence")).toBeInTheDocument();

    expect(within(summary).getByText("Cash outlook")).toBeInTheDocument();
    expect(within(summary).getByText("$3,800.00")).toBeInTheDocument();

    expect(
      within(summary).getByText("Financial resilience")
    ).toBeInTheDocument();
    expect(within(summary).getByText("4 mo runway")).toBeInTheDocument();
  });

  it("shows a calm fallback for top action when no recommendations exist", async () => {
    resolveEverythingSuccessfully();

    render(<Dashboard />);

    const summary = await screen.findByLabelText(
      "Executive financial summary"
    );

    expect(
      within(summary).getByText("You're all caught up")
    ).toBeInTheDocument();
  });

  it("does not break the summary when a data source fails", async () => {
    resolveEverythingSuccessfully();
    mocks.getFinancialResilience.mockRejectedValue(
      new Error("resilience unavailable")
    );

    render(<Dashboard />);

    const summary = await screen.findByLabelText(
      "Executive financial summary"
    );

    expect(within(summary).getByText("Safe to spend")).toBeInTheDocument();
    expect(
      within(summary).queryByText("Financial resilience")
    ).not.toBeInTheDocument();
  });
});

describe("dashboard data quality banner", () => {
  it("warns when a large share of spending is uncategorized", async () => {
    resolveEverythingSuccessfully();
    mocks.byCategory.mockResolvedValue([
      { category: "Groceries", total_cents: -50_000, count: 5 },
      { category: "Uncategorized", total_cents: -50_000, count: 5 },
    ]);

    render(<Dashboard />);

    expect(
      await screen.findByText(
        "50% of recorded spending ($500.00) is uncategorized."
      )
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Review transactions →" })
    ).toBeInTheDocument();
  });

  it("stays quiet when uncategorized spending is a small share", async () => {
    resolveEverythingSuccessfully();
    mocks.byCategory.mockResolvedValue([
      { category: "Groceries", total_cents: -90_000, count: 9 },
      { category: "Uncategorized", total_cents: -5_000, count: 1 },
    ]);

    render(<Dashboard />);

    await screen.findByText("$3,000.00");
    expect(
      screen.queryByText(/is uncategorized/)
    ).not.toBeInTheDocument();
  });
});

function makeAccount(
  overrides: Partial<FinancialAccount>
): FinancialAccount {
  return {
    id: 1,
    plaid_item_id: 1,
    institution_name: "Chase",
    name: "Checking",
    official_name: null,
    account_type: "depository",
    account_subtype: "checking",
    mask: "1234",
    current_balance_cents: 100_000,
    available_balance_cents: 100_000,
    currency: "USD",
    connection_status: "active",
    sync_status: "succeeded",
    sync_error: null,
    last_sync_attempted_at: null,
    last_synced_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("dashboard connection health", () => {
  it("shows a healthy summary across connected institutions", async () => {
    resolveEverythingSuccessfully();
    mocks.getAccounts.mockResolvedValue([
      makeAccount({ id: 1, plaid_item_id: 1, institution_name: "Chase" }),
      makeAccount({ id: 2, plaid_item_id: 2, institution_name: "Ally" }),
    ]);

    render(<Dashboard />);

    const banner = await screen.findByLabelText("Connection health");
    expect(banner).toHaveTextContent(
      "Connected — 2 accounts across 2 institutions. Synced recently."
    );
  });

  it("flags institutions that need reconnecting", async () => {
    resolveEverythingSuccessfully();
    mocks.getAccounts.mockResolvedValue([
      makeAccount({
        id: 1,
        connection_status: "reconnect_required",
      }),
    ]);

    render(<Dashboard />);

    const banner = await screen.findByLabelText("Connection health");
    expect(banner).toHaveTextContent(
      "Reconnect needed — 1 account across 1 institution. " +
        "One or more institutions need reconnecting to keep data current."
    );
  });

  it("flags a stale connection when the last sync is old", async () => {
    resolveEverythingSuccessfully();
    const fiveDaysAgo = new Date(
      Date.now() - 5 * 24 * 60 * 60 * 1000
    ).toISOString();
    mocks.getAccounts.mockResolvedValue([
      makeAccount({ last_synced_at: fiveDaysAgo }),
    ]);

    render(<Dashboard />);

    const banner = await screen.findByLabelText("Connection health");
    expect(banner).toHaveTextContent("Last successful sync was 5 days ago.");
  });

  it("stays silent when no accounts are connected", async () => {
    resolveEverythingSuccessfully();

    render(<Dashboard />);

    await screen.findByText("$3,000.00");
    expect(screen.queryByText("View accounts →")).not.toBeInTheDocument();
  });
});

function makeTransaction(
  overrides: Partial<Transaction> & Pick<Transaction, "id" | "posted_on" | "amount_cents">
): Transaction {
  return {
    description: "Test transaction",
    merchant_name: "Test Merchant",
    category: "Shopping",
    source: "manual",
    pending: false,
    financial_account_id: null,
    account_name: null,
    institution_name: null,
    ...overrides,
  };
}

describe("dashboard monthly card semantics", () => {
  it("shows only the current calendar month's income/spending, not six months of history", async () => {
    resolveEverythingSuccessfully();

    // Six months of income (Mar-Aug) and spending (Mar-Aug), only one
    // month (August) of which should ever land in the "this month"
    // cards. overview.total_income_cents/total_spending_cents are the
    // all-history sums of all of this -- if the monthly cards were
    // still reading from overview, they'd show the six-month totals
    // below instead of just August's.
    const months = [
      "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08",
    ];
    const sixMonthTransactions: Transaction[] = months.flatMap(
      (month, index) => [
        makeTransaction({
          id: index * 2 + 1,
          posted_on: `${month}-01`,
          amount_cents: 300_000,
          category: "Income",
          description: "Payroll",
        }),
        makeTransaction({
          id: index * 2 + 2,
          posted_on: `${month}-05`,
          amount_cents: -50_000,
          category: "Dining",
          description: "Restaurant",
        }),
      ]
    );

    mocks.getTransactions.mockResolvedValue(sixMonthTransactions);
    mocks.overview.mockResolvedValue({
      total_income_cents: 1_800_000, // six months x $3,000
      total_spending_cents: 300_000, // six months x $500
      net_cents: 1_500_000,
      transaction_count: sixMonthTransactions.length,
    });

    render(<Dashboard />);

    // Scoped to each SoftMetric card specifically -- with six months
    // of identical $3,000/$500 entries, "Recent activity" further down
    // the page legitimately repeats those same amounts, so a bare
    // page-wide text query would be ambiguous for reasons unrelated to
    // the bug under test.
    const incomeCard = (
      await screen.findByText("Income this month")
    ).closest("article") as HTMLElement;
    const spendingCard = screen
      .getByText("Spending this month")
      .closest("article") as HTMLElement;

    expect(within(incomeCard).getByText("$3,000.00")).toBeInTheDocument();
    expect(within(spendingCard).getByText("-$500.00")).toBeInTheDocument();
    expect(
      within(incomeCard).queryByText("$18,000.00")
    ).not.toBeInTheDocument();
    expect(
      within(spendingCard).queryByText("-$3,000.00")
    ).not.toBeInTheDocument();
  });

  it("still shows the all-history net financial position alongside the scoped monthly cards", async () => {
    resolveEverythingSuccessfully();

    const sixMonthTransactions: Transaction[] = [
      makeTransaction({
        id: 1,
        posted_on: "2026-08-01",
        amount_cents: 300_000,
        category: "Income",
      }),
      makeTransaction({
        id: 2,
        posted_on: "2026-02-01",
        amount_cents: 300_000,
        category: "Income",
      }),
    ];

    mocks.getTransactions.mockResolvedValue(sixMonthTransactions);
    mocks.overview.mockResolvedValue({
      total_income_cents: 600_000,
      total_spending_cents: 100_000,
      net_cents: 500_000,
      transaction_count: 2,
    });

    render(<Dashboard />);

    // Net financial position is intentionally all-history (its own
    // copy says "Income minus total recorded spending", not "this
    // month") and must keep showing the full six-month net -- distinct
    // from the all-time income/spending shown right underneath it.
    const netCard = (
      await screen.findByText("Net financial position")
    ).closest("article") as HTMLElement;
    expect(within(netCard).getByText("$5,000.00")).toBeInTheDocument();
    expect(within(netCard).getByText("$6,000.00")).toBeInTheDocument();
    expect(within(netCard).getByText("-$1,000.00")).toBeInTheDocument();
  });
});
