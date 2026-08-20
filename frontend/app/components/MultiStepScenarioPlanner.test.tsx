import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MultiStepScenarioPlanResult } from "../lib/api";
import MultiStepScenarioPlanner from "./MultiStepScenarioPlanner";

const mocks = vi.hoisted(() => ({
  runMultiStepScenarioPlan: vi.fn(),
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      runMultiStepScenarioPlan: mocks.runMultiStepScenarioPlan,
    },
  };
});

const baseResult: MultiStepScenarioPlanResult = {
  name: "Laptop + rent increase",
  as_of: "2026-08-20",
  horizon_days: 90,
  through_date: "2026-11-18",
  starting_safe_to_spend_cents: 500_000,
  final_safe_to_spend_cents: 250_000,
  final_shortfall_cents: 0,
  total_impact_cents: -250_000,
  minimum_safe_to_spend_cents: 250_000,
  worst_checkpoint_sequence: 2,
  worst_checkpoint_label: "Rent increase",
  worst_checkpoint_date: "2026-09-19",
  overall_status: "comfortable",
  checkpoints: [
    {
      sequence: 1,
      step_type: "one_time_expense",
      label: "Laptop",
      effective_date: "2026-08-20",
      is_recurring: false,
      is_temporary: false,
      expires_on: null,
      safe_to_spend_before_cents: 500_000,
      safe_to_spend_after_cents: 300_000,
      impact_cents: 200_000,
      cumulative_impact_cents: 200_000,
      status: "comfortable",
    },
    {
      sequence: 2,
      step_type: "monthly_expense_increase",
      label: "Rent increase",
      effective_date: "2026-09-19",
      is_recurring: true,
      is_temporary: false,
      expires_on: null,
      safe_to_spend_before_cents: 300_000,
      safe_to_spend_after_cents: 250_000,
      impact_cents: 50_000,
      cumulative_impact_cents: 250_000,
      status: "comfortable",
    },
  ],
  goal_impacts: [],
  goal_conflict_intelligence: {
    supported: true,
    goals: [],
    most_affected_goal_id: null,
    conflict_count: 0,
  },
  confidence_score: 88,
  confidence_level: "high",
  warnings: [],
};

beforeEach(() => {
  mocks.runMultiStepScenarioPlan.mockReset();
  mocks.runMultiStepScenarioPlan.mockResolvedValue(baseResult);
});

describe("MultiStepScenarioPlanner", () => {
  it("starts with two steps and an empty state", () => {
    render(<MultiStepScenarioPlanner userId={1} />);

    expect(screen.getAllByText(/^Step \d$/)).toHaveLength(2);
    expect(
      screen.getByText("See how events add up over time")
    ).toBeInTheDocument();
  });

  it("adds and removes steps within the 2-5 bound", () => {
    render(<MultiStepScenarioPlanner userId={1} />);

    fireEvent.click(screen.getByRole("button", { name: "Add step" }));
    fireEvent.click(screen.getByRole("button", { name: "Add step" }));
    fireEvent.click(screen.getByRole("button", { name: "Add step" }));

    expect(screen.getAllByText(/^Step \d$/)).toHaveLength(5);
    expect(
      screen.queryByRole("button", { name: "Add step" })
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: /^Remove/ })[0]);
    fireEvent.click(screen.getAllByRole("button", { name: /^Remove/ })[0]);
    fireEvent.click(screen.getAllByRole("button", { name: /^Remove/ })[0]);

    expect(screen.getAllByText(/^Step \d$/)).toHaveLength(2);
    expect(
      screen.queryByRole("button", { name: /^Remove/ })
    ).not.toBeInTheDocument();
  });

  it("shows only the fields relevant to the selected step type", () => {
    render(<MultiStepScenarioPlanner userId={1} />);

    const stepTypeSelects = screen.getAllByLabelText("Step type");
    fireEvent.change(stepTypeSelects[0], {
      target: { value: "temporary_income_loss" },
    });

    const firstStepCard = stepTypeSelects[0].closest("div") as HTMLElement;
    expect(
      within(firstStepCard).getByLabelText(/^Monthly income loss/)
    ).toBeInTheDocument();
    expect(
      within(firstStepCard).getByLabelText("Duration (months)")
    ).toBeInTheDocument();
    expect(
      within(firstStepCard).queryByLabelText(/^Amount/)
    ).not.toBeInTheDocument();
  });

  it("rejects submission when a step is missing an amount", () => {
    render(<MultiStepScenarioPlanner userId={1} />);

    const amountInputs = screen.getAllByLabelText(/^Amount/);
    fireEvent.change(amountInputs[0], { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    expect(
      screen.getByText(/Enter an amount greater than zero for step 1/)
    ).toBeInTheDocument();
    expect(mocks.runMultiStepScenarioPlan).not.toHaveBeenCalled();
  });

  it("serializes the plan and steps into cents on submit", async () => {
    render(<MultiStepScenarioPlanner userId={1} />);

    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    await waitFor(() =>
      expect(mocks.runMultiStepScenarioPlan).toHaveBeenCalledTimes(1)
    );

    const [, payload] = mocks.runMultiStepScenarioPlan.mock.calls[0];
    expect(payload.steps).toHaveLength(2);
    expect(payload.steps[0].step_type).toBe("one_time_expense");
    expect(payload.steps[0].amount_cents).toBe(200_000);
    expect(payload.horizon_days).toBe(90);
    expect(payload.safety_reserve_cents).toBe(0);
  });

  it("shows a loading state while the request is pending", async () => {
    let resolvePromise: (value: MultiStepScenarioPlanResult) => void = () => {};
    mocks.runMultiStepScenarioPlan.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePromise = resolve;
        })
    );

    render(<MultiStepScenarioPlanner userId={1} />);
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    expect(
      await screen.findByRole("button", { name: "Running plan..." })
    ).toBeDisabled();

    resolvePromise(baseResult);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Run analysis" })
      ).toBeInTheDocument()
    );
  });

  it("renders the starting, final, and worst position summary", async () => {
    render(<MultiStepScenarioPlanner userId={1} />);
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    const startingLabel = await screen.findByText("Starting position");
    expect(startingLabel.parentElement).toHaveTextContent("$5,000.00");

    const finalLabel = screen.getByText("Final position");
    expect(finalLabel.parentElement).toHaveTextContent("$2,500.00");

    const worstLabel = screen.getByText("Worst point");
    expect(worstLabel.parentElement).toHaveTextContent("$2,500.00");
    expect(worstLabel.parentElement).toHaveTextContent("Rent increase");
  });

  it("renders checkpoints in chronological order with recurring labels", async () => {
    render(<MultiStepScenarioPlanner userId={1} />);
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    const timeline = await screen.findByText("Timeline");
    const list = timeline.closest("div")?.parentElement as HTMLElement;
    const items = within(list).getAllByRole("listitem");

    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Laptop");
    expect(items[1]).toHaveTextContent("Rent increase");
    expect(within(items[1]).getByText("Recurring")).toBeInTheDocument();
  });

  it("renders deterministic warnings when present", async () => {
    mocks.runMultiStepScenarioPlan.mockResolvedValue({
      ...baseResult,
      warnings: ["'Rent increase' occurs within the final 7 days..."],
    });

    render(<MultiStepScenarioPlanner userId={1} />);
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    expect(await screen.findByText("Warnings")).toBeInTheDocument();
    expect(
      screen.getByText(/occurs within the final 7 days/)
    ).toBeInTheDocument();
  });

  it("renders goal effects when goal impacts are present", async () => {
    mocks.runMultiStepScenarioPlan.mockResolvedValue({
      ...baseResult,
      goal_impacts: [
        {
          goal_id: 1,
          goal_name: "Emergency fund",
          target_date: "2027-01-01",
          target_amount_cents: 1_000_000,
          saved_amount_cents: 200_000,
          remaining_amount_cents: 800_000,
          current_required_monthly_contribution_cents: 50_000,
          baseline_monthly_allocation_cents: 50_000,
          adjusted_monthly_allocation_cents: 20_000,
          monthly_allocation_change_cents: -30_000,
          baseline_estimated_completion_date: "2026-12-01",
          adjusted_estimated_completion_date: "2027-03-01",
          delay_months: 3,
          funding_shortfall_cents: 0,
          status: "delayed",
          explanation: "This plan delays the goal by 3 months.",
        },
      ],
    });

    render(<MultiStepScenarioPlanner userId={1} />);
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    expect(await screen.findByText("Emergency fund")).toBeInTheDocument();
  });

  it("shows an error message without crashing when the API call fails", async () => {
    mocks.runMultiStepScenarioPlan.mockRejectedValue(
      new Error("plan step dates must fall within the selected horizon")
    );

    render(<MultiStepScenarioPlanner userId={1} />);
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));

    expect(
      await screen.findByText(
        "plan step dates must fall within the selected horizon"
      )
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Run analysis" })
    ).toBeInTheDocument();
  });
});
