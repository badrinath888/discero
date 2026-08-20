import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type {
  WhatIfComparisonResult,
  WhatIfSimulationResult,
} from "../lib/api";
import WhatIfSimulator from "./WhatIfSimulator";

const mocks = vi.hoisted(() => ({
  simulateWhatIf: vi.fn(),
  compareWhatIfScenarios: vi.fn(),
  getDecisionAdaptiveIntelligence: vi.fn(),
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      simulateWhatIf: mocks.simulateWhatIf,
      compareWhatIfScenarios: mocks.compareWhatIfScenarios,
      getDecisionAdaptiveIntelligence: mocks.getDecisionAdaptiveIntelligence,
    },
  };
});

const baseResult: WhatIfSimulationResult = {
  scenario_type: "one_time_expense",
  scenario_name: "New laptop",
  as_of: "2026-08-11",
  through_date: "2026-09-10",
  horizon_days: 90,
  baseline: {
    safe_to_spend_cents: 500_000,
    shortfall_cents: 0,
    confidence_score: 88,
    confidence_level: "high",
  },
  scenario: {
    safe_to_spend_cents: 300_000,
    shortfall_cents: 0,
    confidence_score: 88,
    confidence_level: "high",
  },
  impact: {
    safe_to_spend_delta_cents: -200_000,
    shortfall_delta_cents: 0,
    confidence_delta: 0,
    level: "caution",
  },
  explanation: [
    {
      code: "SCENARIO_COST",
      amount_cents: 200_000,
      message: "A $2,000.00 one-time expense reduces safe-to-spend by $2,000.00.",
    },
  ],
  goal_impacts: [],
  goal_conflict_intelligence: { supported: true, goals: [], most_affected_goal_id: null, conflict_count: 0 },
  safe_to_spend: {
    as_of: "2026-08-11",
    through_date: "2026-09-10",
    horizon_days: 90,
    safe_to_spend_cents: 500_000,
    shortfall_cents: 0,
    status: "safe",
    confidence_score: 88,
    confidence_level: "high",
    confidence_drivers: [],
    breakdown: {
      liquid_balance_cents: 500_000,
      projected_income_cents: 0,
      upcoming_obligations_cents: 0,
      essential_spending_cents: 0,
      goal_reserve_cents: 0,
      safety_reserve_cents: 0,
    },
    obligations: [],
    explanation: [],
    warnings: [],
  },
};

const baseComparisonResult: WhatIfComparisonResult = {
  as_of: "2026-08-11",
  through_date: "2026-11-09",
  horizon_days: 90,
  baseline: {
    safe_to_spend_cents: 500_000,
    shortfall_cents: 0,
    confidence_score: 88,
    confidence_level: "high",
  },
  scenarios: [
    {
      label: "Buy now",
      scenario_type: "one_time_expense",
      safe_to_spend_cents: 300_000,
      shortfall_cents: 0,
      safe_to_spend_delta_cents: -200_000,
      shortfall_delta_cents: 0,
      confidence_score: 88,
      confidence_level: "high",
      impact_level: "caution",
      goal_impacts: [],
      explanation: [],
    },
    {
      label: "Wait 3 months",
      scenario_type: "one_time_expense",
      safe_to_spend_cents: 400_000,
      shortfall_cents: 0,
      safe_to_spend_delta_cents: -100_000,
      shortfall_delta_cents: 0,
      confidence_score: 88,
      confidence_level: "high",
      impact_level: "caution",
      goal_impacts: [],
      explanation: [],
    },
  ],
  recommended_label: "Wait 3 months",
  recommendation_reason:
    "Wait 3 months is recommended because it preserves $1,000.00 more safe-to-spend than Buy now.",
  key_driver: "safe_to_spend",
  key_tradeoff: null,
  ranking: ["Wait 3 months", "Buy now"],
  is_tie: false,
};

beforeEach(() => {
  mocks.simulateWhatIf.mockReset();
  mocks.simulateWhatIf.mockResolvedValue(baseResult);
  mocks.compareWhatIfScenarios.mockReset();
  mocks.compareWhatIfScenarios.mockResolvedValue(baseComparisonResult);
  mocks.getDecisionAdaptiveIntelligence.mockReset();
  mocks.getDecisionAdaptiveIntelligence.mockResolvedValue({
    status: "insufficient_data",
  });
});

function switchToCompareMode() {
  render(<WhatIfSimulator userId={1} />);
  fireEvent.click(screen.getByRole("button", { name: "Compare scenarios" }));
}

describe("WhatIfSimulator", () => {
  it("shows the one-time-expense fields by default and an empty state", () => {
    render(<WhatIfSimulator userId={1} />);

    expect(screen.getByLabelText(/^Amount/)).toBeInTheDocument();
    expect(screen.getByLabelText("Date")).toBeInTheDocument();
    expect(screen.queryByLabelText("Duration")).not.toBeInTheDocument();
    expect(
      screen.getByText("See what changes before it happens")
    ).toBeInTheDocument();
  });

  it("shows only the fields relevant to the selected scenario type", () => {
    render(<WhatIfSimulator userId={1} />);

    fireEvent.change(screen.getByLabelText("Scenario type"), {
      target: { value: "temporary_income_loss" },
    });

    expect(
      screen.getByLabelText(/^Monthly income loss/)
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Duration")).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Amount/)).not.toBeInTheDocument();
  });

  it("rejects a zero monthly amount without calling the API", () => {
    render(<WhatIfSimulator userId={1} />);

    fireEvent.change(screen.getByLabelText("Scenario type"), {
      target: { value: "monthly_expense_change" },
    });
    fireEvent.change(screen.getByLabelText(/^Monthly amount change/), {
      target: { value: "0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run simulation" }));

    expect(
      screen.getByText(/Enter a non-zero monthly amount/)
    ).toBeInTheDocument();
    expect(mocks.simulateWhatIf).not.toHaveBeenCalled();
  });

  it("submits the scenario and renders baseline, scenario, and impact", async () => {
    render(<WhatIfSimulator userId={1} />);

    fireEvent.click(screen.getByRole("button", { name: "Run simulation" }));

    await waitFor(() => expect(mocks.simulateWhatIf).toHaveBeenCalledTimes(1));

    const [, payload] = mocks.simulateWhatIf.mock.calls[0];
    expect(payload.scenario_type).toBe("one_time_expense");
    expect(payload.amount_cents).toBe(200_000);

    expect(await screen.findByText("$5,000.00")).toBeInTheDocument();
    expect(screen.getByText("$3,000.00")).toBeInTheDocument();
    expect(screen.getByText("Reduces your buffer")).toBeInTheDocument();
    expect(
      screen.getByText(
        "A $2,000.00 one-time expense reduces safe-to-spend by $2,000.00."
      )
    ).toBeInTheDocument();
  });

  it("shows the shortfall amount when the scenario creates one", async () => {
    mocks.simulateWhatIf.mockResolvedValue({
      ...baseResult,
      scenario: {
        ...baseResult.scenario,
        safe_to_spend_cents: 0,
        shortfall_cents: 150_000,
      },
      impact: {
        ...baseResult.impact,
        safe_to_spend_delta_cents: -500_000,
        shortfall_delta_cents: 150_000,
        level: "negative",
      },
    });

    render(<WhatIfSimulator userId={1} />);
    fireEvent.click(screen.getByRole("button", { name: "Run simulation" }));

    expect(await screen.findByText("Creates financial risk")).toBeInTheDocument();
    expect(screen.getByText("Shortfall $1,500.00")).toBeInTheDocument();
  });

  it("shows an error state when the API call fails", async () => {
    mocks.simulateWhatIf.mockRejectedValue(new Error("simulation failed"));

    render(<WhatIfSimulator userId={1} />);
    fireEvent.click(screen.getByRole("button", { name: "Run simulation" }));

    expect(await screen.findByText("simulation failed")).toBeInTheDocument();
  });

  it("shows a loading state while the request is in flight", async () => {
    let resolveRequest: (value: WhatIfSimulationResult) => void = () => {};
    mocks.simulateWhatIf.mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve;
      })
    );

    render(<WhatIfSimulator userId={1} />);
    fireEvent.click(screen.getByRole("button", { name: "Run simulation" }));

    expect(
      await screen.findByRole("button", { name: "Running simulation..." })
    ).toBeInTheDocument();

    resolveRequest(baseResult);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Run simulation" })
      ).toBeInTheDocument()
    );
  });

  it("shows restrained historical context alongside the single scenario result", async () => {
    mocks.getDecisionAdaptiveIntelligence.mockResolvedValue({
      status: "available",
      calibration_label: "balanced",
      tracked_decisions: 3,
      outcome_checks: 4,
      directional_observations: 3,
      favorable_rate: 0.5,
      unfavorable_rate: 0.5,
      narrative: "Your tracked outcomes have been mixed.",
      metric_patterns: [],
    });

    render(<WhatIfSimulator userId={1} />);
    fireEvent.click(screen.getByRole("button", { name: "Run simulation" }));

    const section = await screen.findByTestId(
      "adaptive-intelligence-section"
    );
    expect(
      within(section).getByText("Your tracked outcomes have been mixed.")
    ).toBeInTheDocument();

    // The deterministic result itself is unaffected by this section.
    expect(screen.getByText("$5,000.00")).toBeInTheDocument();
  });
});

describe("WhatIfSimulator comparison mode", () => {
  it("shows two scenario cards by default with an add option", () => {
    switchToCompareMode();

    expect(screen.getAllByLabelText("Label")).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: "Add scenario C" })
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText(/^Remove/)
    ).not.toBeInTheDocument();
  });

  it("adds a third scenario and hides the add option at the max", () => {
    switchToCompareMode();

    fireEvent.click(screen.getByRole("button", { name: "Add scenario C" }));

    expect(screen.getAllByLabelText("Label")).toHaveLength(3);
    expect(
      screen.queryByRole("button", { name: "Add scenario C" })
    ).not.toBeInTheDocument();
    expect(screen.getAllByLabelText(/^Remove/)).toHaveLength(3);
  });

  it("shows scenario type-specific fields per card", () => {
    switchToCompareMode();

    const typeSelects = screen.getAllByLabelText("Scenario type");
    fireEvent.change(typeSelects[0], {
      target: { value: "temporary_income_loss" },
    });

    expect(
      screen.getByLabelText(/^Monthly income loss/)
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Duration")).toBeInTheDocument();
    // The second card is still a one-time expense.
    expect(screen.getByLabelText(/^Amount/)).toBeInTheDocument();
    expect(screen.getByLabelText("Date")).toBeInTheDocument();
  });

  it("submits the comparison payload for the default two scenarios", async () => {
    switchToCompareMode();

    fireEvent.click(screen.getByRole("button", { name: "Run comparison" }));

    await waitFor(() =>
      expect(mocks.compareWhatIfScenarios).toHaveBeenCalledTimes(1)
    );

    const [, payload] = mocks.compareWhatIfScenarios.mock.calls[0];
    expect(payload.scenarios).toHaveLength(2);
    expect(payload.scenarios[0].label).toBe("Buy now");
    expect(payload.scenarios[0].scenario_type).toBe("one_time_expense");
    expect(payload.scenarios[0].amount_cents).toBe(200_000);
    expect(payload.scenarios[1].label).toBe("Wait 3 months");
  });

  it("renders the recommended scenario and side-by-side metrics", async () => {
    switchToCompareMode();

    fireEvent.click(screen.getByRole("button", { name: "Run comparison" }));

    expect(
      await screen.findByRole("heading", { name: "Wait 3 months" })
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Wait 3 months is recommended because it preserves $1,000.00 more safe-to-spend than Buy now."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("$4,000.00")).toBeInTheDocument();
    expect(screen.getByText("$3,000.00")).toBeInTheDocument();
    expect(screen.getAllByText("Recommended").length).toBeGreaterThan(0);
  });

  it("shows a tie state when scenarios are equivalent", async () => {
    mocks.compareWhatIfScenarios.mockResolvedValue({
      ...baseComparisonResult,
      recommended_label: null,
      recommendation_reason:
        "These scenarios have the same projected financial outcome within the selected horizon.",
      key_driver: "tie",
      is_tie: true,
    });

    switchToCompareMode();
    fireEvent.click(screen.getByRole("button", { name: "Run comparison" }));

    expect(await screen.findByText("No clear winner")).toBeInTheDocument();
    expect(
      screen.getByText("These scenarios are close")
    ).toBeInTheDocument();
    expect(screen.queryByText("Recommended")).not.toBeInTheDocument();
  });

  it("shows an error state when the comparison API call fails", async () => {
    mocks.compareWhatIfScenarios.mockRejectedValue(
      new Error("comparison failed")
    );

    switchToCompareMode();
    fireEvent.click(screen.getByRole("button", { name: "Run comparison" }));

    expect(await screen.findByText("comparison failed")).toBeInTheDocument();
  });

  it("shows a loading state while the comparison request is in flight", async () => {
    let resolveRequest: (value: WhatIfComparisonResult) => void = () => {};
    mocks.compareWhatIfScenarios.mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve;
      })
    );

    switchToCompareMode();
    fireEvent.click(screen.getByRole("button", { name: "Run comparison" }));

    expect(
      await screen.findByRole("button", { name: "Comparing scenarios..." })
    ).toBeInTheDocument();

    resolveRequest(baseComparisonResult);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Run comparison" })
      ).toBeInTheDocument()
    );
  });

  it("shows restrained historical context alongside the comparison result", async () => {
    mocks.getDecisionAdaptiveIntelligence.mockResolvedValue({
      status: "available",
      calibration_label: "balanced",
      tracked_decisions: 3,
      outcome_checks: 4,
      directional_observations: 3,
      favorable_rate: 0.5,
      unfavorable_rate: 0.5,
      narrative: "Your tracked outcomes have been mixed.",
      metric_patterns: [],
    });

    switchToCompareMode();
    fireEvent.click(screen.getByRole("button", { name: "Run comparison" }));

    const section = await screen.findByTestId(
      "adaptive-intelligence-section"
    );
    expect(
      within(section).getByText("Your tracked outcomes have been mixed.")
    ).toBeInTheDocument();
  });
});
