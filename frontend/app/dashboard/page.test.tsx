import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  CashFlowForecast,
  FinancialResilience,
  Overview,
  Recommendation,
  SavingsGoal,
} from "../lib/api";
import Dashboard from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  push: vi.fn(),
  getMe: vi.fn(),
  overview: vi.fn(),
  getSavingsGoals: vi.fn(),
  getCashFlowForecast: vi.fn(),
  getRecommendations: vi.fn(),
  getFinancialResilience: vi.fn(),
  uploadTransactions: vi.fn(),
  getUserId: vi.fn(),
  getToken: vi.fn(),
  clearSession: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace, push: mocks.push }),
}));

vi.mock("framer-motion", async () => {
  const { createElement } = await import("react");
  return {
    useReducedMotion: () => true,
    motion: new Proxy({}, {
      get: (_target, tag: string) => ({ children, ...props }: Record<string, unknown>) =>
        createElement(tag, props, children as ReactNode),
    }),
  };
});

vi.mock("../components/AppSidebar", () => ({ default: () => null }));
vi.mock("../components/SafeToSpendCard", () => ({
  default: () => <section>Safe to spend</section>,
}));
vi.mock("../components/PremiumMotion", () => ({
  PageReveal: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getMe: mocks.getMe,
      overview: mocks.overview,
      getSavingsGoals: mocks.getSavingsGoals,
      getCashFlowForecast: mocks.getCashFlowForecast,
      getRecommendations: mocks.getRecommendations,
      getFinancialResilience: mocks.getFinancialResilience,
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
  horizon_outlook: [
    {
      horizon_days: 30,
      through_date: "2026-09-05",
      expected_income_cents: 100_000,
      known_obligations_cents: 20_000,
      projected_balance_cents: 380_000,
      shortfall_cents: 0,
      confidence_score: 90,
    },
  ],
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
  headline: "Coverage is strong",
  why: "Liquid balance exceeds recent spending pace.",
  what_this_means: "Several months of spending are covered.",
  suggested_actions: [],
  warnings: [],
};

const goals: SavingsGoal[] = [{
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
}];

const recommendation: Recommendation = {
  id: "budget-overage",
  category: "budget",
  severity: "warning",
  priority: 1,
  title: "Utilities is over plan",
  summary: "Utilities reached 108% of plan.",
  why: "Spending exceeded the current budget.",
  recommended_action: "Review utilities spending.",
  impact: "$26.75 over",
  confidence: null,
  source_signals: [],
  deep_link: "/budgets",
  evaluated_at: "2026-08-09",
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({ id: 1, email: "user@example.com", email_verified: true });
  mocks.overview.mockResolvedValue(overview);
  mocks.getSavingsGoals.mockResolvedValue(goals);
  mocks.getCashFlowForecast.mockResolvedValue(cashFlow);
  mocks.getFinancialResilience.mockResolvedValue(resilience);
  mocks.getRecommendations.mockResolvedValue({ as_of: "2026-08-09", recommendations: [] });
});

describe("Dashboard redesign", () => {
  it("renders the light executive hierarchy with a single financial strip", async () => {
    render(<Dashboard />);

    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByText("August 2026")).toBeInTheDocument();
    expect(screen.getByText("Safe to spend")).toBeInTheDocument();

    const strip = await screen.findByLabelText("Executive financial summary");
    expect(within(strip).getByText("Liquid cash")).toBeInTheDocument();
    expect(within(strip).getByText("Cash outlook")).toBeInTheDocument();
    expect(within(strip).getByText("Runway")).toBeInTheDocument();
    expect(within(strip).getByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByText("Cash trajectory")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("shows compact actionable recommendations and follows their existing deep links", async () => {
    mocks.getRecommendations.mockResolvedValue({ as_of: "2026-08-09", recommendations: [recommendation] });
    render(<Dashboard />);

    const item = await screen.findByText("Utilities is over plan");
    expect(screen.getByText("$26.75 over")).toBeInTheDocument();
    fireEvent.click(item);
    expect(mocks.push).toHaveBeenCalledWith("/budgets");
  });

  it("keeps CSV upload functional but secondary", async () => {
    mocks.uploadTransactions.mockResolvedValue({ imported: 2, duplicates: 1, rejected: 0 });
    const { container } = render(<Dashboard />);
    await screen.findByText("Cash trajectory");

    const file = new File(["a,b"], "transactions.csv", { type: "text/csv" });
    fireEvent.change(container.querySelector('input[type="file"]') as HTMLInputElement, { target: { files: [file] } });
    expect(await screen.findByText("2 imported, 1 duplicates skipped.")).toBeInTheDocument();
  });
});
