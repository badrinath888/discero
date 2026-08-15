import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CashFlowForecast, FinancialResilience } from "../lib/api";
import ForecastPage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  getCashFlowForecast: vi.fn(),
  getFinancialResilience: vi.fn(),
  getUserId: vi.fn(),
  getToken: vi.fn(),
  clearSession: vi.fn(),
}));

const routerMock = { replace: mocks.replace };

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
      getCashFlowForecast: mocks.getCashFlowForecast,
      getFinancialResilience: mocks.getFinancialResilience,
    },
    session: {
      ...actual.session,
      getUserId: mocks.getUserId,
      getToken: mocks.getToken,
      clear: mocks.clearSession,
    },
  };
});

const forecastResult: CashFlowForecast = {
  as_of: "2026-08-04",
  month_end: "2026-08-31",
  days_remaining: 27,
  liquid_balance_cents: 500_000,
  income_received_cents: 100_000,
  expected_income_cents: 200_000,
  upcoming_bills_cents: 50_000,
  projected_end_balance_cents: 650_000,
  low_balance_risk: false,
  upcoming_cash_flows: [
    {
      merchant: "Netflix",
      amount_cents: 1500,
      expected_date: "2026-08-10",
      kind: "expense",
      confidence_score: 92,
    },
  ],
  confidence: {
    score: 78.4,
    level: "medium",
    factors: [
      {
        key: "transaction_history",
        label: "Transaction history depth",
        weight: 16,
        score: 90,
        impact: "positive",
        detail:
          "180 days of transaction history (180+ days is treated as a mature baseline).",
      },
      {
        key: "recent_coverage",
        label: "Recent transaction coverage",
        weight: 13,
        score: 30,
        impact: "negative",
        detail:
          "3 transaction(s) in the last 30 days (10+ is treated as healthy coverage).",
      },
      {
        key: "linked_accounts",
        label: "Linked liquid accounts",
        weight: 13,
        score: 50,
        impact: "neutral",
        detail: "1 linked liquid account(s) (2+ is treated as well covered).",
      },
    ],
    recommendations: [
      "Sync recent activity so the forecast reflects your latest spending.",
    ],
    monthly_confidence: [
      { month: "2026-06", score: 75, transaction_count: 6 },
      { month: "2026-07", score: 90, transaction_count: 9 },
    ],
    drivers: [
      {
        code: "TRANSACTION_HISTORY_STRONG",
        direction: "positive",
        message:
          "180 days of transaction history (180+ days is treated as a mature baseline).",
      },
      {
        code: "RECENT_COVERAGE_WEAK",
        direction: "negative",
        message:
          "3 transaction(s) in the last 30 days (10+ is treated as healthy coverage).",
      },
    ],
    data_quality: {
      history_days: 180,
      transaction_count: 42,
      recognized_recurring_items: 3,
      uncategorized_share: 0.12,
    },
  },
  horizon_outlook: [
    {
      horizon_days: 30,
      through_date: "2026-09-03",
      expected_income_cents: 200_000,
      known_obligations_cents: 50_000,
      projected_balance_cents: 650_000,
      shortfall_cents: 0,
      confidence_score: 88,
    },
    {
      horizon_days: 60,
      through_date: "2026-10-03",
      expected_income_cents: 400_000,
      known_obligations_cents: 50_000,
      projected_balance_cents: 850_000,
      shortfall_cents: 0,
      confidence_score: 85,
    },
    {
      horizon_days: 90,
      through_date: "2026-11-02",
      expected_income_cents: 600_000,
      known_obligations_cents: 50_000,
      projected_balance_cents: 1_050_000,
      shortfall_cents: 0,
      confidence_score: 82,
    },
  ],
};

const resilienceResult: FinancialResilience = {
  as_of: "2026-08-04",
  liquid_balance_cents: 480_000,
  liquid_account_count: 1,
  monthly_essential_cents: 120_000,
  essential_spending_source: "derived",
  spending_basis_label: "Monthly spending baseline",
  months_of_spending_data: 3,
  runway_months: 4.0,
  runway_days: 120,
  resilience_status: "fair",
  horizons: [
    {
      horizon_days: 30,
      required_essential_cents: 120_000,
      remaining_liquid_cents: 360_000,
      shortfall_cents: 0,
      coverage_percent: 100.0,
    },
    {
      horizon_days: 60,
      required_essential_cents: 240_000,
      remaining_liquid_cents: 240_000,
      shortfall_cents: 0,
      coverage_percent: 100.0,
    },
    {
      horizon_days: 90,
      required_essential_cents: 360_000,
      remaining_liquid_cents: 120_000,
      shortfall_cents: 0,
      coverage_percent: 100.0,
    },
  ],
  confidence_score: 95,
  data_quality_note: null,
  headline: "Your spending coverage is fair",
  why: "Your liquid cash ($4,800.00) covers approximately 4.0 month(s) at your recent spending pace of $1,200.00/month, estimated from your total spending because Discero does not yet classify essential vs. discretionary expenses.",
  what_this_means:
    "You have a moderate buffer at your recent spending pace, but it would not comfortably cover an extended income gap.",
  suggested_actions: [
    "Keep building your buffer toward 6 months of spending coverage.",
  ],
  warnings: [],
};

async function renderPage() {
  render(<ForecastPage />);
  await screen.findByText("Projected month-end balance");
  await screen.findByText("Your spending coverage is fair");
}

beforeEach(() => {
  mocks.replace.mockReset();
  mocks.getMe.mockReset();
  mocks.getCashFlowForecast.mockReset();
  mocks.getFinancialResilience.mockReset();
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({
    id: 1,
    email: "user@example.com",
    email_verified: true,
  });
  mocks.getCashFlowForecast.mockResolvedValue(forecastResult);
  mocks.getFinancialResilience.mockResolvedValue(resilienceResult);
});

describe("forecast confidence", () => {
  it("shows the overall confidence score and level prominently", async () => {
    await renderPage();

    expect(
      screen.getByText("78% · Medium confidence")
    ).toBeInTheDocument();
  });

  it("explains 'why this confidence' with factors when expanded", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: /why this confidence/i })
    );

    expect(
      screen.getByText("Transaction history depth")
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(
        "180 days of transaction history (180+ days is treated as a mature baseline)."
      ).length
    ).toBeGreaterThan(0);
    expect(screen.getByText("Strength")).toBeInTheDocument();
    expect(screen.getByText("Weak spot")).toBeInTheDocument();
    expect(screen.getByText("Neutral")).toBeInTheDocument();
  });

  it("shows recommendations when the confidence panel is expanded", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: /why this confidence/i })
    );

    expect(screen.getByText("Recommendations")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Sync recent activity so the forecast reflects your latest spending."
      )
    ).toBeInTheDocument();
  });

  it("shows monthly confidence alongside the forecast period", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: /why this confidence/i })
    );

    expect(screen.getByText("Monthly confidence")).toBeInTheDocument();
    expect(screen.getByText("June 2026")).toBeInTheDocument();
    expect(screen.getByText("July 2026")).toBeInTheDocument();
    expect(screen.getByText("6 transactions")).toBeInTheDocument();
    expect(screen.getByText("9 transactions")).toBeInTheDocument();
  });

  it("hides confidence details until expanded, and toggles them", async () => {
    await renderPage();

    expect(
      screen.queryByText("Transaction history depth")
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /why this confidence/i })
    );
    expect(
      screen.getByText("Transaction history depth")
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /hide details/i })
    );
    expect(
      screen.queryByText("Transaction history depth")
    ).not.toBeInTheDocument();
  });

  it("omits the recommendations panel when there are none", async () => {
    mocks.getCashFlowForecast.mockResolvedValue({
      ...forecastResult,
      confidence: {
        ...forecastResult.confidence,
        recommendations: [],
      },
    });

    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: /why this confidence/i })
    );

    expect(screen.queryByText("Recommendations")).not.toBeInTheDocument();
  });

  it("shows top confidence drivers without requiring the panel to be expanded", async () => {
    await renderPage();

    expect(
      screen.getByText(
        "180 days of transaction history (180+ days is treated as a mature baseline)."
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "3 transaction(s) in the last 30 days (10+ is treated as healthy coverage)."
      )
    ).toBeInTheDocument();
  });

  it("omits the drivers list when there are no drivers", async () => {
    mocks.getCashFlowForecast.mockResolvedValue({
      ...forecastResult,
      confidence: {
        ...forecastResult.confidence,
        drivers: [],
      },
    });

    await renderPage();

    expect(
      screen.queryByText(
        "180 days of transaction history (180+ days is treated as a mature baseline)."
      )
    ).not.toBeInTheDocument();
  });

  it("shows data-quality context when the confidence panel is expanded", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: /why this confidence/i })
    );

    expect(screen.getByText("180 days of history")).toBeInTheDocument();
    expect(screen.getByText("42 transactions")).toBeInTheDocument();
    expect(screen.getByText("3 recurring items recognized")).toBeInTheDocument();
    expect(
      screen.getByText("12% of spending uncategorized")
    ).toBeInTheDocument();
  });

  it("omits the monthly confidence panel when there is no monthly data", async () => {
    mocks.getCashFlowForecast.mockResolvedValue({
      ...forecastResult,
      confidence: {
        ...forecastResult.confidence,
        monthly_confidence: [],
      },
    });

    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: /why this confidence/i })
    );

    expect(
      screen.queryByText("Monthly confidence")
    ).not.toBeInTheDocument();
  });
});

describe("existing forecast behavior", () => {
  it("still renders the forecast headline, outlook, and predicted bills", async () => {
    await renderPage();

    expect(
      screen.getAllByText("$6,500.00").length
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("$5,000.00").length
    ).toBeGreaterThan(0);
    expect(screen.getByText("Positive outlook")).toBeInTheDocument();
    expect(screen.getByText("Netflix")).toBeInTheDocument();
    expect(screen.getByText("1 expected")).toBeInTheDocument();
  });

  it("shows a loading skeleton while the forecast is being fetched", async () => {
    let resolveForecast: (value: CashFlowForecast) => void = () => {};
    mocks.getCashFlowForecast.mockReturnValue(
      new Promise((resolve) => {
        resolveForecast = resolve;
      })
    );

    render(<ForecastPage />);

    await waitFor(() =>
      expect(mocks.getCashFlowForecast).toHaveBeenCalled()
    );
    expect(
      screen.queryByText("Projected month-end balance")
    ).not.toBeInTheDocument();

    resolveForecast(forecastResult);

    expect(
      await screen.findByText("Projected month-end balance")
    ).toBeInTheDocument();
  });

  it("renders an error state with retry when the forecast request fails", async () => {
    mocks.getCashFlowForecast.mockRejectedValue(
      new Error("Unable to load forecast")
    );

    render(<ForecastPage />);

    expect(
      await screen.findByText("Unable to load forecast")
    ).toBeInTheDocument();

    mocks.getCashFlowForecast.mockResolvedValue(forecastResult);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(
      await screen.findByText("Projected month-end balance")
    ).toBeInTheDocument();
  });

  it("renders an empty state when no forecast is available", async () => {
    mocks.getCashFlowForecast.mockResolvedValue(null);

    render(<ForecastPage />);

    expect(
      await screen.findByText("Forecast unavailable")
    ).toBeInTheDocument();
  });
});

describe("financial resilience section", () => {
  it("renders the hero runway, supporting metrics, and status badge", async () => {
    await renderPage();

    expect(screen.getByText("4 months")).toBeInTheDocument();
    expect(
      screen.getByText("covered by liquid cash at your recent spending pace")
    ).toBeInTheDocument();
    expect(screen.getByText("Fair")).toBeInTheDocument();
    expect(screen.getByText("$4,800.00")).toBeInTheDocument();
    expect(screen.getByText("$1,200.00/mo")).toBeInTheDocument();
    expect(screen.getByText("95%")).toBeInTheDocument();
  });

  it("renders 30/60/90-day essential coverage", async () => {
    await renderPage();

    expect(screen.getByText("30-day coverage")).toBeInTheDocument();
    expect(screen.getByText("60-day coverage")).toBeInTheDocument();
    expect(screen.getByText("90-day coverage")).toBeInTheDocument();
    expect(screen.getAllByText("100%").length).toBe(3);
  });

  it("discloses that spending was estimated, not classified as essential", async () => {
    await renderPage();

    expect(
      screen.getByText(
        "Monthly spending baseline: estimated from your recent total spending (Discero doesn't yet classify essential vs. discretionary expenses)."
      )
    ).toBeInTheDocument();
    // The hero and section headers must not claim "essential" for an
    // uncategorized spending baseline.
    expect(screen.getByText("Spending coverage")).toBeInTheDocument();
    expect(screen.queryByText("Emergency runway")).not.toBeInTheDocument();
  });

  it("labels essential spending as user-provided after a simulation", async () => {
    await renderPage();

    mocks.getFinancialResilience.mockResolvedValueOnce({
      ...resilienceResult,
      monthly_essential_cents: 400_000,
      essential_spending_source: "user_provided",
      spending_basis_label: "Monthly essential spending",
      runway_months: 1.2,
      resilience_status: "weak",
      headline: "Your emergency runway is weak",
    });

    const input = screen.getByPlaceholderText("4000.00");
    fireEvent.change(input, { target: { value: "4000" } });
    fireEvent.click(screen.getByRole("button", { name: "Simulate" }));

    await waitFor(() =>
      expect(mocks.getFinancialResilience).toHaveBeenLastCalledWith(
        1,
        400_000
      )
    );

    expect(
      await screen.findByText(
        "Monthly essential spending: your stated amount."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("Emergency runway")).toBeInTheDocument();
    expect(
      screen.getByText(/Showing your scenario at \$4,000\.00\/month\./)
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Monthly spending baseline: estimated from your recent total spending (Discero doesn't yet classify essential vs. discretionary expenses)."
      )
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Reset to estimated" })
    );

    await waitFor(() =>
      expect(mocks.getFinancialResilience).toHaveBeenLastCalledWith(
        1,
        undefined
      )
    );
  });

  it("rejects an invalid scenario amount without calling the API", async () => {
    await renderPage();

    mocks.getFinancialResilience.mockClear();

    const input = screen.getByPlaceholderText("4000.00");
    fireEvent.change(input, { target: { value: "-5" } });
    fireEvent.click(screen.getByRole("button", { name: "Simulate" }));

    expect(
      await screen.findByText(
        "Enter a valid monthly essential-spending amount."
      )
    ).toBeInTheDocument();
    expect(mocks.getFinancialResilience).not.toHaveBeenCalled();
  });

  it("shows a loading skeleton while resilience is being fetched", async () => {
    let resolveResilience: (value: FinancialResilience) => void = () => {};
    mocks.getFinancialResilience.mockReturnValue(
      new Promise((resolve) => {
        resolveResilience = resolve;
      })
    );

    render(<ForecastPage />);
    await screen.findByText("Projected month-end balance");

    expect(
      screen.queryByText("Your spending coverage is fair")
    ).not.toBeInTheDocument();

    resolveResilience(resilienceResult);

    expect(
      await screen.findByText("Your spending coverage is fair")
    ).toBeInTheDocument();
  });

  it("renders an error state with retry when resilience fails to load", async () => {
    mocks.getFinancialResilience.mockRejectedValue(
      new Error("Unable to load financial resilience")
    );

    render(<ForecastPage />);
    await screen.findByText("Projected month-end balance");

    expect(
      await screen.findByText("Unable to load financial resilience")
    ).toBeInTheDocument();

    mocks.getFinancialResilience.mockResolvedValue(resilienceResult);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(
      await screen.findByText("Your spending coverage is fair")
    ).toBeInTheDocument();
  });

  it("never affirmatively claims the runway or income pace is guaranteed", async () => {
    await renderPage();

    const bodyText = (document.body.textContent ?? "").toLowerCase();
    // "not a guaranteed forecast" is the required disclosure and is
    // fine; an affirmative "is guaranteed" claim would not be.
    expect(bodyText).not.toContain("is guaranteed");
    expect(bodyText).not.toContain("will last exactly");
    expect(bodyText).toContain("not a guaranteed forecast");
    expect(bodyText).toContain("pace-based estimate");
  });
});
