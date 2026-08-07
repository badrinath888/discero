import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GoalImpact } from "../lib/api";
import GoalImpactList from "./GoalImpactList";

function makeImpact(overrides: Partial<GoalImpact> = {}): GoalImpact {
  return {
    goal_id: 1,
    goal_name: "Vacation",
    target_date: "2026-11-06",
    target_amount_cents: 90_000,
    saved_amount_cents: 0,
    remaining_amount_cents: 90_000,
    current_required_monthly_contribution_cents: 30_000,
    baseline_monthly_allocation_cents: 80_000,
    adjusted_monthly_allocation_cents: 80_000,
    monthly_allocation_change_cents: 0,
    baseline_estimated_completion_date: "2026-10-06",
    adjusted_estimated_completion_date: "2026-10-06",
    delay_months: 0,
    funding_shortfall_cents: 0,
    status: "unaffected",
    explanation: "Vacation is not affected by this scenario.",
    ...overrides,
  };
}

describe("GoalImpactList", () => {
  it("renders an empty state when there are no active goals", () => {
    render(<GoalImpactList goalImpacts={[]} />);

    expect(
      screen.getByText(/don't have any active savings goals/i)
    ).toBeInTheDocument();
  });

  it("renders each goal with its name and baseline/adjusted allocation", () => {
    render(
      <GoalImpactList
        goalImpacts={[
          makeImpact({
            goal_id: 1,
            goal_name: "Vacation",
            baseline_monthly_allocation_cents: 80_000,
            adjusted_monthly_allocation_cents: 50_000,
            monthly_allocation_change_cents: -30_000,
          }),
        ]}
      />
    );

    expect(screen.getByText("Vacation")).toBeInTheDocument();
    expect(screen.getByText("$800.00/mo")).toBeInTheDocument();
    expect(screen.getByText("$500.00/mo")).toBeInTheDocument();
    expect(screen.getByText("-$300.00/mo")).toBeInTheDocument();
  });

  it("renders an unaffected goal with a clear unaffected state", () => {
    render(
      <GoalImpactList
        goalImpacts={[
          makeImpact({
            status: "unaffected",
            goal_name: "Emergency fund",
            explanation: "Emergency fund is not affected by this scenario.",
          }),
        ]}
      />
    );

    expect(screen.getByText("Unaffected")).toBeInTheDocument();
    expect(
      screen.getByText("Emergency fund is not affected by this scenario.")
    ).toBeInTheDocument();
  });

  it("renders a reduced goal", () => {
    render(
      <GoalImpactList
        goalImpacts={[
          makeImpact({
            status: "reduced",
            goal_name: "Reduced goal",
            baseline_monthly_allocation_cents: 80_000,
            adjusted_monthly_allocation_cents: 50_000,
            monthly_allocation_change_cents: -30_000,
          }),
        ]}
      />
    );

    expect(screen.getByText("Reduced")).toBeInTheDocument();
  });

  it("renders a delayed goal with its delay in months", () => {
    render(
      <GoalImpactList
        goalImpacts={[
          makeImpact({
            status: "delayed",
            goal_name: "Delayed goal",
            delay_months: 2,
          }),
        ]}
      />
    );

    expect(screen.getByText("Delayed")).toBeInTheDocument();
    expect(
      screen.getByText(/Delayed by ~2 month\(s\)/)
    ).toBeInTheDocument();
  });

  it("renders an at-risk goal with its funding shortfall", () => {
    render(
      <GoalImpactList
        goalImpacts={[
          makeImpact({
            status: "at_risk",
            goal_name: "At risk goal",
            funding_shortfall_cents: 30_000,
          }),
        ]}
      />
    );

    expect(screen.getByText("At risk")).toBeInTheDocument();
    expect(
      screen.getByText(/Expected shortfall of \$300\.00 by the target date/)
    ).toBeInTheDocument();
  });

  it("renders an impossible goal", () => {
    render(
      <GoalImpactList
        goalImpacts={[
          makeImpact({
            status: "impossible",
            goal_name: "No funding goal",
            adjusted_monthly_allocation_cents: 0,
            monthly_allocation_change_cents: -80_000,
            adjusted_estimated_completion_date: null,
            funding_shortfall_cents: 90_000,
          }),
        ]}
      />
    );

    expect(screen.getByText("Impossible")).toBeInTheDocument();
    expect(screen.getByText("Not determinable")).toBeInTheDocument();
  });

  it("renders multiple goals independently", () => {
    render(
      <GoalImpactList
        goalImpacts={[
          makeImpact({ goal_id: 1, goal_name: "Goal one" }),
          makeImpact({
            goal_id: 2,
            goal_name: "Goal two",
            status: "at_risk",
            funding_shortfall_cents: 10_000,
          }),
        ]}
      />
    );

    expect(screen.getByText("Goal one")).toBeInTheDocument();
    expect(screen.getByText("Goal two")).toBeInTheDocument();
  });
});
