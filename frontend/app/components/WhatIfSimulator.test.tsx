import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { WhatIfSimulationResult } from "../lib/api";
import WhatIfSimulator from "./WhatIfSimulator";

const mocks = vi.hoisted(() => ({ simulateWhatIf: vi.fn() }));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return { ...actual, api: { ...actual.api, simulateWhatIf: mocks.simulateWhatIf } };
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

beforeEach(() => {
  mocks.simulateWhatIf.mockReset();
  mocks.simulateWhatIf.mockResolvedValue(baseResult);
});

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
});
