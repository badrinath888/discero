import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  FinancialStressTestResult,
  ScenarioComparisonResult,
} from "../lib/api";
import DecisionsPage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  simulateMajorPurchase: vi.fn(),
  compareMajorPurchaseScenarios: vi.fn(),
  runFinancialStressTest: vi.fn(),
  saveDecision: vi.fn(),
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
      simulateMajorPurchase: mocks.simulateMajorPurchase,
      compareMajorPurchaseScenarios: mocks.compareMajorPurchaseScenarios,
      runFinancialStressTest: mocks.runFinancialStressTest,
      saveDecision: mocks.saveDecision,
    },
    session: {
      ...actual.session,
      getUserId: mocks.getUserId,
      getToken: mocks.getToken,
      clear: mocks.clearSession,
    },
  };
});

const comparisonResult: ScenarioComparisonResult = {
  recommended_option: "option_a",
  recommendation:
    "Option A (New laptop) is recommended because it is affordable while Used laptop is caution.",
  reasons: [
    "It is affordable while Used laptop is caution.",
    "It has a lower impact on safe-to-spend (40.0% vs 24.0%).",
  ],
  scorecard: {
    option_a_score: 96.0,
    option_b_score: 31.0,
    max_score: 127.0,
    criteria: [
      {
        key: "affordability",
        label: "Financial safety",
        weight: 64.0,
        winner: "option_a",
      },
      {
        key: "shortfall",
        label: "Shortfall risk",
        weight: 32.0,
        winner: "tie",
      },
      {
        key: "safe_to_spend_after",
        label: "Remaining safe-to-spend",
        weight: 16.0,
        winner: "option_b",
      },
      {
        key: "impact_percent",
        label: "Safe-to-spend impact",
        weight: 8.0,
        winner: "option_b",
      },
      {
        key: "goal_impact",
        label: "Goal savings pace",
        weight: 4.0,
        winner: "tie",
      },
      {
        key: "confidence",
        label: "Confidence",
        weight: 2.0,
        winner: "tie",
      },
      {
        key: "purchase_cost",
        label: "Purchase cost",
        weight: 1.0,
        winner: "option_b",
      },
    ],
  },
  safe_to_spend_difference_cents: 800_00,
  purchase_cost_difference_cents: 800_00,
  impact_difference_percent: -16.0,
  option_a: {
    option_key: "option_a",
    affordability_rank: 3,
    simulation: {
      purchase_name: "New laptop",
      purchase_amount_cents: 200_000,
      purchase_date: "2026-08-11",
      as_of: "2026-08-04",
      through_date: "2026-09-03",
      affordability_status: "affordable",
      safe_to_spend_before_purchase_cents: 500_000,
      safe_to_spend_after_purchase_cents: 300_000,
      shortfall_after_purchase_cents: 0,
      recommended_max_purchase_cents: 375_000,
      purchase_impact_percent: 40.0,
      goal_monthly_savings_required_cents: 0,
      goal_impact_months: 0,
      confidence_score: 85,
      explanation: "New laptop is within the recommended purchase range.",
      alternatives: [],
      goal_impacts: [],
      safe_to_spend: {
        as_of: "2026-08-04",
        through_date: "2026-09-03",
        horizon_days: 30,
        safe_to_spend_cents: 500_000,
        shortfall_cents: 0,
        status: "safe",
        confidence_score: 85,
        breakdown: {
          liquid_balance_cents: 500_000,
          upcoming_obligations_cents: 0,
          essential_spending_cents: 0,
          safety_reserve_cents: 0,
        },
        obligations: [],
        warnings: [],
      },
    },
  },
  option_b: {
    option_key: "option_b",
    affordability_rank: 2,
    simulation: {
      purchase_name: "Used laptop",
      purchase_amount_cents: 120_000,
      purchase_date: "2026-08-11",
      as_of: "2026-08-04",
      through_date: "2026-09-03",
      affordability_status: "caution",
      safe_to_spend_before_purchase_cents: 500_000,
      safe_to_spend_after_purchase_cents: 380_000,
      shortfall_after_purchase_cents: 0,
      recommended_max_purchase_cents: 375_000,
      purchase_impact_percent: 24.0,
      goal_monthly_savings_required_cents: 0,
      goal_impact_months: 0,
      confidence_score: 85,
      explanation: "Used laptop is technically affordable.",
      alternatives: [],
      goal_impacts: [],
      safe_to_spend: {
        as_of: "2026-08-04",
        through_date: "2026-09-03",
        horizon_days: 30,
        safe_to_spend_cents: 500_000,
        shortfall_cents: 0,
        status: "safe",
        confidence_score: 85,
        breakdown: {
          liquid_balance_cents: 500_000,
          upcoming_obligations_cents: 0,
          essential_spending_cents: 0,
          safety_reserve_cents: 0,
        },
        obligations: [],
        warnings: [],
      },
    },
  },
};

const stressTestResult: FinancialStressTestResult = {
  scenario_type: "temporary_income_loss",
  scenario_name: "Job loss buffer",
  event_date: "2026-08-15",
  duration_days: 14,
  as_of: "2026-08-04",
  through_date: "2026-10-03",
  risk_level: "strained",
  severity: "moderate",
  safe_to_spend_before_stress_cents: 500_000,
  safe_to_spend_after_stress_cents: 200_000,
  total_financial_impact_cents: 300_000,
  shortfall_cents: 0,
  baseline_projected_balance_cents: 500_000,
  stressed_projected_balance_cents: 200_000,
  balance_change_cents: -300_000,
  balance_change_percent: -60,
  cash_flow_positive: true,
  resilience_score: 65,
  resilience_factors: [
    {
      key: "liquidity_remaining",
      label: "Liquidity remaining after stress",
      weight: 35,
      score: 40,
    },
    {
      key: "monthly_cash_flow_margin",
      label: "Monthly cash-flow margin",
      weight: 20,
      score: 70,
    },
    {
      key: "safe_to_spend_reduction",
      label: "Safe-to-spend reduction",
      weight: 20,
      score: 40,
    },
    {
      key: "goal_disruption",
      label: "Goal disruption",
      weight: 15,
      score: 100,
    },
    {
      key: "recurring_obligation_pressure",
      label: "Recurring-obligation pressure",
      weight: 10,
      score: 90,
    },
  ],
  affected_goals: [],
  confidence_score: 83.8,
  estimated_recovery_days: 14,
  explanation:
    "Job loss buffer would cost $3,000.00, using more than half of your " +
    "$5,000.00 safe-to-spend and leaving only $2,000.00 available. Your " +
    "finances would be strained but would not go negative.",
  recommendations: [
    "Look into short-term income sources or unemployment support to bridge the gap.",
    "Pause discretionary purchases until your safe-to-spend balance recovers.",
    "Build a safety reserve so future stress events are easier to absorb.",
  ],
  data_disclaimer:
    "This is a simulation based on your current FinSight data, not a probabilistic forecast or financial advice.",
  safe_to_spend: {
    as_of: "2026-08-04",
    through_date: "2026-10-03",
    horizon_days: 60,
    safe_to_spend_cents: 500_000,
    shortfall_cents: 0,
    status: "safe",
    confidence_score: 88,
    breakdown: {
      liquid_balance_cents: 500_000,
      upcoming_obligations_cents: 0,
      essential_spending_cents: 0,
      safety_reserve_cents: 0,
    },
    obligations: [],
    warnings: [],
  },
  goal_impacts: [],
};

const emergencyStressResult: FinancialStressTestResult = {
  scenario_type: "emergency_expense",
  scenario_name: "Car repair",
  event_date: "2026-08-15",
  duration_days: null,
  as_of: "2026-08-04",
  through_date: "2026-09-03",
  risk_level: "resilient",
  severity: "low",
  safe_to_spend_before_stress_cents: 500_000,
  safe_to_spend_after_stress_cents: 400_000,
  total_financial_impact_cents: 100_000,
  shortfall_cents: 0,
  baseline_projected_balance_cents: 500_000,
  stressed_projected_balance_cents: 400_000,
  balance_change_cents: -100_000,
  balance_change_percent: -20,
  cash_flow_positive: true,
  resilience_score: 92,
  resilience_factors: [
    {
      key: "liquidity_remaining",
      label: "Liquidity remaining after stress",
      weight: 35,
      score: 80,
    },
    {
      key: "monthly_cash_flow_margin",
      label: "Monthly cash-flow margin",
      weight: 20,
      score: 100,
    },
    {
      key: "safe_to_spend_reduction",
      label: "Safe-to-spend reduction",
      weight: 20,
      score: 80,
    },
    {
      key: "goal_disruption",
      label: "Goal disruption",
      weight: 15,
      score: 100,
    },
    {
      key: "recurring_obligation_pressure",
      label: "Recurring-obligation pressure",
      weight: 10,
      score: 100,
    },
  ],
  affected_goals: [],
  confidence_score: 88,
  estimated_recovery_days: 0,
  explanation:
    "Car repair would cost $1,000.00. Your finances are resilient to " +
    "this event, leaving $4,000.00 of your $5,000.00 safe-to-spend " +
    "available afterward.",
  recommendations: [
    "Keep an emergency fund earmarked specifically for unexpected costs like this.",
    "Maintain your current safety reserve; it is sufficient to absorb this scenario.",
  ],
  data_disclaimer:
    "This is a simulation based on your current FinSight data, not a probabilistic forecast or financial advice.",
  safe_to_spend: {
    as_of: "2026-08-04",
    through_date: "2026-09-03",
    horizon_days: 30,
    safe_to_spend_cents: 500_000,
    shortfall_cents: 0,
    status: "safe",
    confidence_score: 88,
    breakdown: {
      liquid_balance_cents: 500_000,
      upcoming_obligations_cents: 0,
      essential_spending_cents: 0,
      safety_reserve_cents: 0,
    },
    obligations: [],
    warnings: [],
  },
  goal_impacts: [],
};

async function renderPage() {
  render(<DecisionsPage />);
  await screen.findByText("Major purchase simulator");
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date(2026, 7, 4));
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({
    id: 1,
    email: "user@example.com",
    email_verified: true,
  });
  mocks.compareMajorPurchaseScenarios.mockResolvedValue(comparisonResult);
  mocks.runFinancialStressTest.mockResolvedValue(stressTestResult);
});

describe("decisions mobile layout", () => {
  it("allows the mode toggle buttons to wrap instead of overflowing narrow screens", async () => {
    await renderPage();

    const toggleContainer = screen.getByRole("button", {
      name: "Compare options",
    }).parentElement;

    expect(toggleContainer?.className).toContain("flex-wrap");
  });
});

describe("decisions comparison mode", () => {
  it("sends the comparison payload with shared assumptions", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Compare options" })
    );

    const nameInputs = screen.getAllByLabelText(/^Name$/i);
    fireEvent.change(nameInputs[0], {
      target: { value: "Premium laptop" },
    });
    fireEvent.change(nameInputs[1], {
      target: { value: "Budget laptop" },
    });

    fireEvent.change(screen.getByDisplayValue("2000"), {
      target: { value: "2500" },
    });
    fireEvent.change(screen.getByDisplayValue("1200"), {
      target: { value: "900" },
    });

    fireEvent.change(screen.getByDisplayValue("1000"), {
      target: { value: "1500" },
    });
    fireEvent.change(screen.getByDisplayValue("500"), {
      target: { value: "600" },
    });
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "60" },
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Run comparison" })
    );

    await waitFor(() =>
      expect(mocks.compareMajorPurchaseScenarios).toHaveBeenCalledWith(1, {
        option_a: {
          purchase_name: "Premium laptop",
          purchase_amount_cents: 250_000,
          purchase_date: "2026-08-11",
          safety_reserve_cents: 150_000,
          essential_spending_cents: 60_000,
          horizon_days: 60,
        },
        option_b: {
          purchase_name: "Budget laptop",
          purchase_amount_cents: 90_000,
          purchase_date: "2026-08-11",
          safety_reserve_cents: 150_000,
          essential_spending_cents: 60_000,
          horizon_days: 60,
        },
      })
    );
  });

  it("renders the recommended option and comparison cards", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Compare options" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Run comparison" })
    );

    expect(
      await screen.findByText("Option A: New laptop")
    ).toBeInTheDocument();
    expect(screen.getByText(comparisonResult.recommendation)).toBeInTheDocument();
    expect(screen.getByText("Recommended")).toBeInTheDocument();
    expect(screen.getByText("Used laptop")).toBeInTheDocument();
    expect(screen.getAllByText("Affordable").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Proceed with caution").length).toBeGreaterThan(
      0
    );
  });

  it("renders the winner banner with a 'why this wins' reasons list", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Compare options" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Run comparison" })
    );

    expect(
      await screen.findByText("Option A: New laptop")
    ).toBeInTheDocument();
    expect(screen.getByText("Why this wins")).toBeInTheDocument();

    for (const reason of comparisonResult.reasons) {
      expect(screen.getByText(reason)).toBeInTheDocument();
    }
  });

  it("renders both options side by side with tradeoff details", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Compare options" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Run comparison" })
    );

    await screen.findByText("Option A: New laptop");

    const optionACard = screen.getByText("New laptop").closest("article");
    const optionBCard = screen.getByText("Used laptop").closest("article");

    expect(optionACard).not.toBeNull();
    expect(optionBCard).not.toBeNull();

    const withinA = within(optionACard as HTMLElement);
    const withinB = within(optionBCard as HTMLElement);

    expect(withinA.getByText("Recommended")).toBeInTheDocument();
    expect(withinB.getByText("Alternative")).toBeInTheDocument();

    expect(withinA.getByText("Purchase amount")).toBeInTheDocument();
    expect(withinA.getByText("Safe to spend after")).toBeInTheDocument();
    expect(withinA.getByText("Shortfall")).toBeInTheDocument();
    expect(withinA.getByText("Impact")).toBeInTheDocument();
    expect(withinA.getByText("Goal savings pace")).toBeInTheDocument();
    expect(withinA.getByText("Confidence")).toBeInTheDocument();
    expect(withinA.getByText("No active goals")).toBeInTheDocument();
    expect(withinB.getByText("No active goals")).toBeInTheDocument();
  });

  it("renders the comparison scorecard with per-factor winners", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Compare options" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Run comparison" })
    );

    await screen.findByText("Option A: New laptop");

    const scorecardCard = screen
      .getByText("Comparison scorecard")
      .closest("article") as HTMLElement;
    const withinScorecard = within(scorecardCard);

    expect(withinScorecard.getByText("96 / 127")).toBeInTheDocument();
    expect(withinScorecard.getByText("31 / 127")).toBeInTheDocument();

    for (const criterion of comparisonResult.scorecard.criteria) {
      expect(
        withinScorecard.getByText(criterion.label)
      ).toBeInTheDocument();
    }

    const financialSafetyRow = withinScorecard
      .getByText("Financial safety")
      .closest("div");
    expect(
      within(financialSafetyRow as HTMLElement).getByText("Option A")
    ).toBeInTheDocument();

    const shortfallRow = withinScorecard
      .getByText("Shortfall risk")
      .closest("div");
    expect(
      within(shortfallRow as HTMLElement).getByText("Tie")
    ).toBeInTheDocument();
  });

  it("renders API errors from comparison requests", async () => {
    mocks.compareMajorPurchaseScenarios.mockRejectedValue(
      new Error("purchase date cannot be before the calculation date (422)")
    );

    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Compare options" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Run comparison" })
    );

    expect(
      await screen.findByText(
        "purchase date cannot be before the calculation date (422)"
      )
    ).toBeInTheDocument();
  });
});

describe("decisions financial stress test mode", () => {
  it("sends the stress test payload with scenario details", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Financial stress test" })
    );

    fireEvent.change(
      screen.getByRole("combobox", { name: "Scenario type" }),
      { target: { value: "temporary_income_loss" } }
    );
    fireEvent.change(screen.getByLabelText(/^Scenario name$/i), {
      target: { value: "Job loss buffer" },
    });
    fireEvent.change(screen.getByDisplayValue("1500"), {
      target: { value: "3000" },
    });
    fireEvent.change(screen.getByLabelText(/^Event date$/i), {
      target: { value: "2026-08-15" },
    });
    fireEvent.change(screen.getByLabelText(/^Duration \(days\)$/i), {
      target: { value: "14" },
    });
    fireEvent.change(screen.getByDisplayValue("1000"), {
      target: { value: "1200" },
    });
    fireEvent.change(screen.getByDisplayValue("500"), {
      target: { value: "300" },
    });
    fireEvent.change(
      screen.getByRole("combobox", { name: "Decision horizon" }),
      { target: { value: "60" } }
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Run stress test" })
    );

    await waitFor(() =>
      expect(mocks.runFinancialStressTest).toHaveBeenCalledWith(1, {
        scenario_type: "temporary_income_loss",
        scenario_name: "Job loss buffer",
        stress_amount_cents: 300_000,
        income_reduction_percent: null,
        recurring_expense_increase_percent: null,
        event_date: "2026-08-15",
        duration_days: 14,
        safety_reserve_cents: 120_000,
        essential_spending_cents: 30_000,
        horizon_days: 60,
      })
    );
  });

  it("renders the stress test results", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Financial stress test" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Run stress test" })
    );

    expect(
      await screen.findByText("Job loss buffer")
    ).toBeInTheDocument();
    expect(screen.getByText("Strained")).toBeInTheDocument();
    expect(
      screen.getByText(stressTestResult.explanation)
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Look into short-term income sources or unemployment support to bridge the gap."
      )
    ).toBeInTheDocument();
  });

  it("shows severity, resilience score, and the data disclaimer", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Financial stress test" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Run stress test" })
    );

    expect(await screen.findByText("Job loss buffer")).toBeInTheDocument();
    expect(screen.getByText("Moderate severity")).toBeInTheDocument();
    expect(screen.getByText("65 / 100")).toBeInTheDocument();
    expect(
      screen.getByText(stressTestResult.data_disclaimer)
    ).toBeInTheDocument();
  });

  it("renders affected goals when present", async () => {
    mocks.runFinancialStressTest.mockResolvedValue({
      ...stressTestResult,
      affected_goals: [
        {
          goal_id: 1,
          name: "Vacation",
          status_before: "on_track",
          status_after: "at_risk",
          monthly_shortfall_before_cents: 0,
          monthly_shortfall_after_cents: 5_000,
          estimated_delay_months: 2,
        },
      ],
    });

    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Financial stress test" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Run stress test" })
    );

    expect(await screen.findByText("Vacation")).toBeInTheDocument();
    expect(
      screen.getByText(/on_track → at_risk/)
    ).toBeInTheDocument();
  });

  it("validates the income reduction percent before submitting", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Financial stress test" })
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "Scenario type" }),
      { target: { value: "income_reduction" } }
    );
    fireEvent.change(screen.getByLabelText(/Income reduction/i), {
      target: { value: "150" },
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Run stress test" })
    );

    expect(
      await screen.findByText(
        "Income reduction must be between 0 and 100 percent."
      )
    ).toBeInTheDocument();
    expect(mocks.runFinancialStressTest).not.toHaveBeenCalled();
  });

  it("validates the recurring expense increase percent before submitting", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Financial stress test" })
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "Scenario type" }),
      { target: { value: "recurring_expense_increase" } }
    );
    fireEvent.change(
      screen.getByLabelText(/Recurring expense increase/i),
      { target: { value: "600" } }
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Run stress test" })
    );

    expect(
      await screen.findByText(
        "Recurring expense increase must be between 0 and 500 percent."
      )
    ).toBeInTheDocument();
    expect(mocks.runFinancialStressTest).not.toHaveBeenCalled();
  });

  it("sends derived percent inputs for the combined scenario", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Financial stress test" })
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "Scenario type" }),
      { target: { value: "combined" } }
    );
    fireEvent.change(screen.getByLabelText(/Income reduction/i), {
      target: { value: "20" },
    });
    fireEvent.change(
      screen.getByLabelText(/Recurring expense increase/i),
      { target: { value: "15" } }
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Run stress test" })
    );

    await waitFor(() =>
      expect(mocks.runFinancialStressTest).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          scenario_type: "combined",
          income_reduction_percent: 20,
          recurring_expense_increase_percent: 15,
        })
      )
    );
  });

  it("shows the recovery duration caption for scenarios where a duration was entered", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Financial stress test" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Run stress test" })
    );

    expect(await screen.findByText("Job loss buffer")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Reflects the scenario duration entered, not a guaranteed recovery timeline."
      )
    ).toBeInTheDocument();
  });

  it("omits the recovery duration caption for scenarios with no duration input", async () => {
    mocks.runFinancialStressTest.mockResolvedValue(emergencyStressResult);

    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Financial stress test" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Run stress test" })
    );

    expect(await screen.findByText("Car repair")).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Reflects the scenario duration entered, not a guaranteed recovery timeline."
      )
    ).not.toBeInTheDocument();
  });

  it("renders API errors from stress test requests", async () => {
    mocks.runFinancialStressTest.mockRejectedValue(
      new Error(
        "duration_days is required for the delayed paycheck scenario (422)"
      )
    );

    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Financial stress test" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Run stress test" })
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "duration_days is required for the delayed paycheck scenario (422)"
    );
  });

  it("shows a disabled loading state while the request is pending", async () => {
    let resolveRequest!: (value: FinancialStressTestResult) => void;
    mocks.runFinancialStressTest.mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve;
      })
    );

    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Financial stress test" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Run stress test" })
    );

    expect(
      screen.getByRole("button", { name: "Running stress test..." })
    ).toBeDisabled();

    resolveRequest(stressTestResult);

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Run stress test" })
      ).not.toBeDisabled()
    );
  });

  it("only shows the duration field for scenario types that require it, and clears it on switch", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Financial stress test" })
    );

    expect(
      screen.queryByLabelText(/^Duration \(days\)$/i)
    ).not.toBeInTheDocument();

    fireEvent.change(
      screen.getByRole("combobox", { name: "Scenario type" }),
      { target: { value: "temporary_income_loss" } }
    );

    fireEvent.change(screen.getByLabelText(/^Duration \(days\)$/i), {
      target: { value: "21" },
    });
    expect(screen.getByLabelText(/^Duration \(days\)$/i)).toHaveValue(21);

    fireEvent.change(
      screen.getByRole("combobox", { name: "Scenario type" }),
      { target: { value: "emergency_expense" } }
    );

    expect(
      screen.queryByLabelText(/^Duration \(days\)$/i)
    ).not.toBeInTheDocument();

    fireEvent.change(
      screen.getByRole("combobox", { name: "Scenario type" }),
      { target: { value: "delayed_paycheck" } }
    );

    expect(screen.getByLabelText(/^Duration \(days\)$/i)).toHaveValue(null);
  });

  it("clears the stress result when switching back to another mode", async () => {
    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Financial stress test" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Run stress test" })
    );

    expect(
      await screen.findByText("Job loss buffer")
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Single purchase" })
    );

    expect(screen.queryByText("Job loss buffer")).not.toBeInTheDocument();
    expect(
      screen.getByText("See the impact before you spend")
    ).toBeInTheDocument();
  });
});

describe("decisions save to history", () => {
  const singlePurchaseResult = {
    purchase_name: "New laptop",
    purchase_amount_cents: 200_000,
    purchase_date: "2026-08-11",
    as_of: "2026-08-04",
    through_date: "2026-09-03",
    affordability_status: "affordable" as const,
    safe_to_spend_before_purchase_cents: 500_000,
    safe_to_spend_after_purchase_cents: 300_000,
    shortfall_after_purchase_cents: 0,
    recommended_max_purchase_cents: 375_000,
    purchase_impact_percent: 40.0,
    goal_monthly_savings_required_cents: 0,
    goal_impact_months: 0,
    confidence_score: 85,
    explanation: "New laptop is within the recommended purchase range.",
    alternatives: [],
    goal_impacts: [],
    safe_to_spend: {
      as_of: "2026-08-04",
      through_date: "2026-09-03",
      horizon_days: 30,
      safe_to_spend_cents: 500_000,
      shortfall_cents: 0,
      status: "safe" as const,
      confidence_score: 85,
      breakdown: {
        liquid_balance_cents: 500_000,
        upcoming_obligations_cents: 0,
        essential_spending_cents: 0,
        safety_reserve_cents: 0,
      },
      obligations: [],
      warnings: [],
    },
  };

  it("shows a Save button after simulating a purchase and saves it", async () => {
    mocks.simulateMajorPurchase.mockResolvedValue(singlePurchaseResult);
    mocks.saveDecision.mockResolvedValue({
      id: 1,
      decision_type: "major_purchase",
      title: "New laptop",
      input_snapshot: {},
      result_snapshot: {},
      created_at: "2026-08-04T00:00:00Z",
    });

    await renderPage();

    fireEvent.click(
      screen.getByRole("button", { name: "Simulate purchase" })
    );

    await waitFor(() =>
      expect(mocks.simulateMajorPurchase).toHaveBeenCalled()
    );

    const saveButton = await screen.findByRole("button", {
      name: "Save this decision",
    });
    fireEvent.click(saveButton);

    await waitFor(() =>
      expect(mocks.saveDecision).toHaveBeenCalledWith(1, {
        decision_type: "major_purchase",
        title: "New laptop",
        input: {
          purchase_name: "New laptop",
          purchase_amount_cents: 200_000,
          purchase_date: "2026-08-11",
          safety_reserve_cents: 100_000,
          essential_spending_cents: 50_000,
          horizon_days: 30,
        },
      })
    );

    expect(
      await screen.findByText("Saved to your decision history.")
    ).toBeInTheDocument();
  });

  it("links to the saved decision history page", async () => {
    await renderPage();

    expect(
      screen.getByRole("link", { name: /view saved decisions/i })
    ).toHaveAttribute("href", "/decisions/history");
  });
});
