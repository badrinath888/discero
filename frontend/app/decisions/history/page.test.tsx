import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../lib/api";
import type {
  DecisionCalibration,
  DecisionMemory,
  DecisionPortfolioResult,
  DecisionReviewQueueItem,
  DecisionTimeline,
  SavedDecision,
} from "../../lib/api";
import DecisionHistoryPage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  getSavedDecisions: vi.fn(),
  deleteSavedDecision: vi.fn(),
  rerunSavedDecision: vi.fn(),
  updateDecisionStatus: vi.fn(),
  evaluateDecisionOutcome: vi.fn(),
  getDecisionOutcomes: vi.fn(),
  getDecisionTimeline: vi.fn(),
  getDecisionMemory: vi.fn(),
  getDecisionCalibration: vi.fn(),
  getDecisionReviewQueue: vi.fn(),
  evaluateDecisionPortfolio: vi.fn(),
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
    "whileInView",
    "viewport",
    "variants",
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

vi.mock("../../components/AppSidebar", () => ({
  default: () => null,
}));

vi.mock("../../components/PremiumMotion", () => ({
  PageReveal: ({ children }: { children: ReactNode }) => children,
  Reveal: ({ children }: { children: ReactNode }) => children,
  Stagger: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();

  return {
    ...actual,
    api: {
      ...actual.api,
      getMe: mocks.getMe,
      getSavedDecisions: mocks.getSavedDecisions,
      deleteSavedDecision: mocks.deleteSavedDecision,
      rerunSavedDecision: mocks.rerunSavedDecision,
      updateDecisionStatus: mocks.updateDecisionStatus,
      evaluateDecisionOutcome: mocks.evaluateDecisionOutcome,
      getDecisionOutcomes: mocks.getDecisionOutcomes,
      getDecisionTimeline: mocks.getDecisionTimeline,
      getDecisionMemory: mocks.getDecisionMemory,
      getDecisionCalibration: mocks.getDecisionCalibration,
      getDecisionReviewQueue: mocks.getDecisionReviewQueue,
      evaluateDecisionPortfolio: mocks.evaluateDecisionPortfolio,
    },
    session: {
      ...actual.session,
      getUserId: mocks.getUserId,
      getToken: mocks.getToken,
      clear: mocks.clearSession,
    },
  };
});

const purchaseDecision: SavedDecision = {
  id: 1,
  decision_type: "major_purchase",
  title: "Laptop Purchase",
  input_snapshot: {
    purchase_name: "Laptop",
    purchase_amount_cents: 200_000,
  },
  result_snapshot: {
    affordability_status: "affordable",
    purchase_amount_cents: 200_000,
    safe_to_spend_after_purchase_cents: 6_056_900,
    confidence_score: 88,
  },
  status: "saved",
  acted_on_at: null,
  created_at: "2026-08-08T00:00:00Z",
  outcome_count: 0,
  latest_outcome_at: null,
};

const buyNowVsWaitDecision: SavedDecision = {
  id: 2,
  decision_type: "buy_now_vs_wait",
  title: "Buy Now vs Wait: New Laptop",
  input_snapshot: {
    purchase_name: "New Laptop",
    purchase_amount_cents: 220_000,
    buy_now_date: "2026-08-08",
    wait_until_date: "2026-09-15",
  },
  result_snapshot: {
    purchase_name: "New Laptop",
    purchase_amount_cents: 220_000,
    recommended_timing: "buy_now",
    reason: "Waiting doesn't meaningfully improve your position.",
    key_driver: "buffer",
    buffer_difference_cents: 45_000,
    confidence_difference: 8.5,
    assumption: "Assumes stable income and no other large purchases.",
  },
  status: "saved",
  acted_on_at: null,
  created_at: "2026-08-08T00:00:00Z",
  outcome_count: 0,
  latest_outcome_at: null,
};

// The exact shape that crashed the page in production: a
// buy_now_vs_wait decision saved without recommended_timing (or any
// of the other real BuyNowVsWaitOut fields).
const buyNowVsWaitDecisionMissingTiming: SavedDecision = {
  id: 3,
  decision_type: "buy_now_vs_wait",
  title: "Buy Now vs Wait: Legacy Decision",
  input_snapshot: {},
  result_snapshot: {
    recommendation: "wait",
    reason: "Waiting improves your buffer.",
  },
  status: "saved",
  acted_on_at: null,
  created_at: "2026-08-08T00:00:00Z",
  outcome_count: 0,
  latest_outcome_at: null,
};

const scenarioDecision: SavedDecision = {
  id: 4,
  decision_type: "scenario_comparison",
  title: "Laptop vs Phone",
  input_snapshot: {},
  result_snapshot: {
    recommended_option: "option_b",
    recommendation: "Option B is more affordable.",
  },
  status: "saved",
  acted_on_at: null,
  created_at: "2026-08-08T00:00:00Z",
  outcome_count: 0,
  latest_outcome_at: null,
};

const stressTestDecision: SavedDecision = {
  id: 5,
  decision_type: "stress_test",
  title: "Job Loss Stress Test",
  input_snapshot: {},
  result_snapshot: {
    risk_level: "strained",
    resilience_score: 62,
    confidence_score: 74,
  },
  status: "saved",
  acted_on_at: null,
  created_at: "2026-08-08T00:00:00Z",
  outcome_count: 0,
  latest_outcome_at: null,
};

const whatIfComparisonDecision: SavedDecision = {
  id: 8,
  decision_type: "what_if_comparison",
  title: "Rent increase vs move",
  input_snapshot: {
    scenarios: [
      { label: "Option A", scenario_type: "one_time_expense" },
      { label: "Option B", scenario_type: "one_time_expense" },
    ],
  },
  result_snapshot: {
    recommended_label: "Option A",
    recommendation_reason: "Option A keeps more safe-to-spend available.",
  },
  status: "saved",
  acted_on_at: null,
  created_at: "2026-08-08T00:00:00Z",
  outcome_count: 0,
  latest_outcome_at: null,
};

const emptyMemory: DecisionMemory = {
  status: "no_history",
  summary: {
    total_saved_decisions: 0,
    acted_on_count: 0,
    dismissed_count: 0,
    unresolved_count: 0,
    earliest_decision_at: null,
    latest_decision_at: null,
    most_used_decision_types: [],
  },
  follow_through: {
    eligible_decisions: 0,
    acted_on_count: 0,
    follow_through_rate: null,
    outcome_eligible_decisions: 0,
    outcome_tracked_decisions: 0,
    outcome_tracking_rate: null,
  },
  outcomes: {
    total_outcome_checks: 0,
    directional_observations: 0,
    favorable_count: 0,
    unfavorable_count: 0,
    unchanged_count: 0,
    most_frequent_metric_paths: [],
  },
  decision_types: [],
  recent_patterns: [],
  needs_follow_up_count: 0,
};

const populatedMemory: DecisionMemory = {
  status: "available",
  summary: {
    total_saved_decisions: 4,
    acted_on_count: 2,
    dismissed_count: 1,
    unresolved_count: 1,
    earliest_decision_at: "2026-07-01T00:00:00Z",
    latest_decision_at: "2026-08-08T00:00:00Z",
    most_used_decision_types: ["major_purchase"],
  },
  follow_through: {
    eligible_decisions: 3,
    acted_on_count: 2,
    follow_through_rate: 0.667,
    outcome_eligible_decisions: 2,
    outcome_tracked_decisions: 1,
    outcome_tracking_rate: 0.5,
  },
  outcomes: {
    total_outcome_checks: 1,
    directional_observations: 1,
    favorable_count: 1,
    unfavorable_count: 0,
    unchanged_count: 0,
    most_frequent_metric_paths: ["safe_to_spend_after_purchase_cents"],
  },
  decision_types: [
    {
      decision_type: "major_purchase",
      saved_count: 4,
      acted_on_count: 2,
      outcome_check_count: 1,
      directional_observation_count: 1,
      calibration_label: "insufficient_data",
    },
  ],
  recent_patterns: [
    {
      text: "Repeated major purchase analysis -- 4 saved decisions.",
      decision_type: "major_purchase",
      count: 4,
    },
  ],
  needs_follow_up_count: 2,
};

const emptyCalibration: DecisionCalibration = {
  tracked_decisions: 0,
  outcome_checks: 0,
  numeric_metrics_compared: 0,
  changed_numeric_metrics: 0,
  directional_metrics_compared: 0,
  favorable_count: 0,
  unfavorable_count: 0,
  unchanged_count: 0,
  favorable_rate: null,
  unfavorable_rate: null,
  calibration_label: "insufficient_data",
  metric_groups: [],
  decision_types: [],
};

function calibrationFixture(
  overrides: Partial<DecisionCalibration>
): DecisionCalibration {
  return { ...emptyCalibration, ...overrides };
}

const savedUnresolvedItem: DecisionReviewQueueItem = {
  decision_id: 1,
  decision_type: "major_purchase",
  title: "Laptop Purchase",
  status: "saved",
  created_at: "2026-08-07T00:00:00Z",
  acted_on_at: null,
  outcome_count: 0,
  latest_outcome_at: null,
  review_reason: "saved_unresolved",
  review_reason_text:
    "Saved 12 days ago. Tell Discero whether you acted on this decision.",
  age_days: 12,
  recommended_action: "mark_acted_or_dismiss",
};

const neverCheckedItem: DecisionReviewQueueItem = {
  decision_id: 2,
  decision_type: "major_purchase",
  title: "Kitchen Remodel",
  status: "acted_on",
  created_at: "2026-07-01T00:00:00Z",
  acted_on_at: "2026-08-09T00:00:00Z",
  outcome_count: 0,
  latest_outcome_at: null,
  review_reason: "acted_on_never_checked",
  review_reason_text:
    "Acted on 10 days ago. Check how this decision compares with your finances today.",
  age_days: 10,
  recommended_action: "check_outcome",
};

const recheckDueItem: DecisionReviewQueueItem = {
  decision_id: 3,
  decision_type: "major_purchase",
  title: "Car Purchase",
  status: "acted_on",
  created_at: "2026-05-01T00:00:00Z",
  acted_on_at: "2026-05-05T00:00:00Z",
  outcome_count: 2,
  latest_outcome_at: "2026-07-16T00:00:00Z",
  review_reason: "acted_on_recheck_due",
  review_reason_text:
    "Last checked 34 days ago. Review this decision again with current data.",
  age_days: 34,
  recommended_action: "recheck_outcome",
};

const whatIfDecision: SavedDecision = {
  id: 6,
  decision_type: "what_if",
  title: "Rent increase",
  input_snapshot: {
    scenario_type: "monthly_expense_change",
    scenario_name: "Rent increase",
    monthly_amount_change_cents: 120_000,
  },
  result_snapshot: {
    impact: { safe_to_spend_delta_cents: -120_000, level: "caution" },
    scenario: { confidence_score: 80 },
  },
  status: "saved",
  acted_on_at: null,
  created_at: "2026-08-08T00:00:00Z",
  outcome_count: 0,
  latest_outcome_at: null,
};

const dismissedPurchaseDecision: SavedDecision = {
  id: 7,
  decision_type: "major_purchase",
  title: "Boat (dismissed)",
  input_snapshot: {
    purchase_name: "Boat",
    purchase_amount_cents: 900_000,
  },
  result_snapshot: {
    affordability_status: "not_affordable",
    purchase_amount_cents: 900_000,
    safe_to_spend_after_purchase_cents: 0,
    confidence_score: 60,
  },
  status: "dismissed",
  acted_on_at: null,
  created_at: "2026-08-08T00:00:00Z",
  outcome_count: 0,
  latest_outcome_at: null,
};

const portfolioResultFixture: DecisionPortfolioResult = {
  as_of: "2026-08-08",
  selected_decisions: [
    {
      decision_id: 1,
      decision_type: "major_purchase",
      title: "New Laptop",
      variant: null,
      variant_label: null,
    },
    {
      decision_id: 6,
      decision_type: "what_if",
      title: "Rent increase",
      variant: null,
      variant_label: null,
    },
  ],
  baseline: { safe_to_spend_cents: 10_000_000, confidence_score: 88 },
  combined: {
    safe_to_spend_cents: 6_660_000,
    safe_to_spend_delta_cents: -3_340_000,
    confidence_score: 88,
    confidence_delta: 0,
  },
  portfolio_status: "comfortable",
  decision_impacts: [
    {
      decision_id: 1,
      title: "New Laptop",
      decision_type: "major_purchase",
      incremental_safe_to_spend_impact_cents: -220_000,
      risk_rank: 1,
      contribution_level: "high",
    },
    {
      decision_id: 6,
      title: "Rent increase",
      decision_type: "what_if",
      incremental_safe_to_spend_impact_cents: -120_000,
      risk_rank: 2,
      contribution_level: "medium",
    },
  ],
  goal_impacts: [
    {
      goal_id: 1,
      goal_name: "House Down Payment",
      target_date: "2027-08-08",
      target_amount_cents: 6_000_000,
      saved_amount_cents: 0,
      remaining_amount_cents: 6_000_000,
      current_required_monthly_contribution_cents: 500_000,
      baseline_monthly_allocation_cents: 500_000,
      adjusted_monthly_allocation_cents: 200_000,
      monthly_allocation_change_cents: -300_000,
      baseline_estimated_completion_date: "2027-08-08",
      adjusted_estimated_completion_date: "2029-02-08",
      delay_months: 0,
      funding_shortfall_cents: 3_600_000,
      status: "at_risk",
      explanation:
        "House Down Payment is expected to fall short of its target by $3,600.00 at the target date under this scenario.",
    },
  ],
  goal_conflict_intelligence: {
    supported: true,
    goals: [
      {
        goal_id: 1,
        goal_name: "House Down Payment",
        baseline_allocation_cents: 500_000,
        adjusted_allocation_cents: 200_000,
        allocation_change_cents: -300_000,
        baseline_completion_date: "2027-08-08",
        adjusted_completion_date: "2029-02-08",
        delay_months: 0,
        funding_shortfall_cents: 3_600_000,
        status: "at_risk",
        conflict: true,
        severity: "high",
        rank: 1,
        attribution: "pre_existing_conflict",
        attribution_text:
          "House Down Payment is already off track before this scenario. This scenario does not materially worsen the goal.",
      },
    ],
    most_affected_goal_id: 1,
    conflict_count: 1,
    scenario_created_conflict_count: 0,
    scenario_worsened_conflict_count: 0,
    pre_existing_conflict_count: 1,
    scenario_improved_count: 0,
  },
  conflicts: {
    as_of: "2026-08-08",
    conflict_status: "conflict",
    monthly_savings_capacity_cents: 200_000,
    total_required_monthly_cents: 500_000,
    monthly_shortfall_cents: 300_000,
    monthly_headroom_cents: 0,
    key_driver: "largest_required_goal",
    confidence_score: 70,
    goals: [],
    explanation:
      "Your goals require $5,000.00 per month, but only $2,000.00 is available, leaving a $3,000.00 monthly shortfall.",
    recommendations: [],
    recommendation: {
      type: "increase_monthly_capacity",
      message: "Increase available monthly savings.",
      goal_id: null,
      amount_cents: null,
      extension_months: null,
      resulting_monthly_gap_cents: 0,
    },
    recommendation_alternatives: [],
    warnings: [],
  },
  warnings: [
    "No active recurring or budget obligations were found for the selected period.",
  ],
  assumptions: [
    "Combined evaluation uses a shared 30-day horizon, the longest horizon among the selected decisions.",
  ],
};

beforeEach(() => {
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({
    id: 1,
    email: "user@example.com",
    email_verified: true,
  });
  mocks.getSavedDecisions.mockReset();
  mocks.deleteSavedDecision.mockReset();
  mocks.rerunSavedDecision.mockReset();
  mocks.updateDecisionStatus.mockReset();
  mocks.evaluateDecisionOutcome.mockReset();
  mocks.getDecisionOutcomes.mockReset();
  mocks.getDecisionTimeline.mockReset();
  mocks.getDecisionMemory.mockReset();
  mocks.getDecisionMemory.mockResolvedValue(emptyMemory);
  mocks.getDecisionCalibration.mockReset();
  mocks.getDecisionCalibration.mockResolvedValue(emptyCalibration);
  mocks.getDecisionReviewQueue.mockReset();
  mocks.getDecisionReviewQueue.mockResolvedValue({
    items: [],
    total_count: 0,
  });
  mocks.evaluateDecisionPortfolio.mockReset();
});

describe("Decision history page", () => {
  it("renders saved decisions with their key result metrics", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);

    render(<DecisionHistoryPage />);

    expect(
      await screen.findByText("Laptop Purchase")
    ).toBeInTheDocument();
    expect(screen.getByText("Major Purchase")).toBeInTheDocument();
    expect(screen.getByText("affordable")).toBeInTheDocument();
    expect(screen.getByText("$2,000.00")).toBeInTheDocument();
    expect(screen.getByText("$60,569.00")).toBeInTheDocument();
  });

  it("shows an empty state when there are no saved decisions", async () => {
    mocks.getSavedDecisions.mockResolvedValue([]);

    render(<DecisionHistoryPage />);

    expect(
      await screen.findByTestId("decisions-history-empty")
    ).toBeInTheDocument();
  });

  it("deletes a saved decision", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.deleteSavedDecision.mockResolvedValue(undefined);

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    fireEvent.click(screen.getByRole("button", { name: /delete/i }));

    await waitFor(() =>
      expect(mocks.deleteSavedDecision).toHaveBeenCalledWith(1, 1)
    );
    await waitFor(() =>
      expect(screen.queryByText("Laptop Purchase")).not.toBeInTheDocument()
    );
  });

  it("re-runs a saved decision and shows a then-vs-now comparison", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.rerunSavedDecision.mockResolvedValue({
      decision_id: 1,
      decision_type: "major_purchase",
      evaluated_at: "2026-08-09",
      result_snapshot: {
        affordability_status: "affordable",
        purchase_amount_cents: 200_000,
        safe_to_spend_after_purchase_cents: 7_000_000,
        confidence_score: 90,
      },
      change_explanation: null,
    });

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    fireEvent.click(screen.getByRole("button", { name: /run again/i }));

    await waitFor(() =>
      expect(mocks.rerunSavedDecision).toHaveBeenCalledWith(1, 1)
    );

    const rerunPanel = await screen.findByTestId("decision-rerun-result");
    expect(rerunPanel).toHaveTextContent("$70,000.00");
  });

  it("renders a Buy Now vs Wait decision with its real result fields", async () => {
    mocks.getSavedDecisions.mockResolvedValue([buyNowVsWaitDecision]);

    render(<DecisionHistoryPage />);

    expect(
      await screen.findByText("Buy Now vs Wait: New Laptop")
    ).toBeInTheDocument();
    // "buy now" legitimately appears twice: the status pill (from
    // statusLabel) and the "Recommendation" chip (from summaryChips).
    expect(screen.getAllByText("buy now").length).toBeGreaterThan(0);
    expect(screen.getByText("$450.00")).toBeInTheDocument();
    expect(screen.getByText("9 pts")).toBeInTheDocument();
    const assumptionValue = screen.getByText(
      "Assumes stable income and no other large purchases."
    );
    expect(assumptionValue).toBeInTheDocument();
    expect(assumptionValue.closest("div")).toHaveClass("sm:col-span-3");
  });

  it("does not crash on a Buy Now vs Wait decision missing recommended_timing, and omits the chip instead of inventing one", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      buyNowVsWaitDecisionMissingTiming,
    ]);

    render(<DecisionHistoryPage />);

    expect(
      await screen.findByText("Buy Now vs Wait: Legacy Decision")
    ).toBeInTheDocument();
    expect(screen.queryByText("Recommendation")).not.toBeInTheDocument();
    expect(screen.queryByText("Buffer difference")).not.toBeInTheDocument();
  });

  it("still renders a saved Scenario Comparison decision", async () => {
    mocks.getSavedDecisions.mockResolvedValue([scenarioDecision]);

    render(<DecisionHistoryPage />);

    expect(await screen.findByText("Laptop vs Phone")).toBeInTheDocument();
    expect(screen.getByText("Scenario Comparison")).toBeInTheDocument();
    expect(screen.getByText("Option B")).toBeInTheDocument();
  });

  it("still renders a saved Stress Test decision", async () => {
    mocks.getSavedDecisions.mockResolvedValue([stressTestDecision]);

    render(<DecisionHistoryPage />);

    expect(
      await screen.findByText("Job Loss Stress Test")
    ).toBeInTheDocument();
    expect(screen.getByText("Stress Test")).toBeInTheDocument();
    expect(screen.getByText("62")).toBeInTheDocument();
    expect(screen.getByText("74%")).toBeInTheDocument();
  });

  it("renders mixed decision types together without crashing", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      buyNowVsWaitDecision,
      buyNowVsWaitDecisionMissingTiming,
      scenarioDecision,
      stressTestDecision,
    ]);

    render(<DecisionHistoryPage />);

    expect(
      await screen.findByText("Job Loss Stress Test")
    ).toBeInTheDocument();
    expect(screen.getAllByTestId("decision-history-card")).toHaveLength(5);
  });

  it("shows lifecycle actions for a saved decision", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");

    expect(
      screen.getByRole("button", { name: /i made this decision/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /dismiss/i })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /check outcome/i })
    ).not.toBeInTheDocument();
  });

  it("marks a decision as acted on and shows the acted-on date plus Check outcome", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.updateDecisionStatus.mockResolvedValue({
      ...purchaseDecision,
      status: "acted_on",
      acted_on_at: "2026-08-10T12:00:00Z",
    });

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    fireEvent.click(
      screen.getByRole("button", { name: /i made this decision/i })
    );

    await waitFor(() =>
      expect(mocks.updateDecisionStatus).toHaveBeenCalledWith(
        1,
        1,
        "acted_on"
      )
    );

    const card = await screen.findByTestId("decision-history-card");
    expect(within(card).getByText(/acted on/i)).toBeInTheDocument();
    expect(
      within(card).getByRole("button", { name: /check outcome/i })
    ).toBeInTheDocument();
    expect(
      within(card).queryByRole("button", { name: /i made this decision/i })
    ).not.toBeInTheDocument();
  });

  it("checking the outcome renders predicted vs current with a delta", async () => {
    const actedOnDecision: SavedDecision = {
      ...purchaseDecision,
      status: "acted_on",
      acted_on_at: "2026-08-09T00:00:00Z",
    };
    mocks.getSavedDecisions.mockResolvedValue([actedOnDecision]);
    mocks.evaluateDecisionOutcome.mockResolvedValue({
      id: 1,
      decision_id: 1,
      evaluated_at: "2026-08-10T00:00:00Z",
      current_result_snapshot: {
        safe_to_spend_after_purchase_cents: 6_500_000,
      },
      comparison_snapshot: {
        changed: true,
        metrics: [
          {
            path: "safe_to_spend_after_purchase_cents",
            before: 6_056_900,
            current: 6_500_000,
            delta: 443_100,
            change_type: "numeric",
          },
          {
            path: "purchase_amount_cents",
            before: 200_000,
            current: 200_000,
            delta: 0,
            change_type: "numeric",
          },
        ],
        summary: { metrics_compared: 2, metrics_changed: 1 },
      },
      created_at: "2026-08-10T00:00:00Z",
    });

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    fireEvent.click(
      screen.getByRole("button", { name: /check outcome/i })
    );

    await waitFor(() =>
      expect(mocks.evaluateDecisionOutcome).toHaveBeenCalledWith(1, 1)
    );

    const panel = await screen.findByTestId("decision-outcome-panel");
    expect(panel).toHaveTextContent("Predicted vs current");
    expect(panel).toHaveTextContent("$60,569.00");
    expect(panel).toHaveTextContent("$65,000.00");
    expect(panel).toHaveTextContent("+$4,431.00");
    // The unchanged purchase_amount_cents metric must not be rendered
    // as a "changed" row.
    expect(panel).not.toHaveTextContent("Purchase amount");
    // No raw JSON dump of the snapshot.
    expect(panel).not.toHaveTextContent("change_type");
    expect(panel).not.toHaveTextContent("{");
  });

  it("shows a quiet dismissed state without active lifecycle actions", async () => {
    const dismissedDecision: SavedDecision = {
      ...purchaseDecision,
      status: "dismissed",
    };
    mocks.getSavedDecisions.mockResolvedValue([dismissedDecision]);

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");

    expect(screen.getByText(/dismissed/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /i made this decision/i })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /check outcome/i })
    ).not.toBeInTheDocument();
  });

  it("shows an error when marking a decision as acted on fails", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.updateDecisionStatus.mockRejectedValue(new Error("network error"));

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    fireEvent.click(
      screen.getByRole("button", { name: /i made this decision/i })
    );

    expect(
      await screen.findByText(/couldn't update that decision/i)
    ).toBeInTheDocument();
  });

  it("shows an error when checking the outcome fails", async () => {
    const actedOnDecision: SavedDecision = {
      ...purchaseDecision,
      status: "acted_on",
      acted_on_at: "2026-08-09T00:00:00Z",
    };
    mocks.getSavedDecisions.mockResolvedValue([actedOnDecision]);
    mocks.evaluateDecisionOutcome.mockRejectedValue(
      new Error("network error")
    );

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    fireEvent.click(
      screen.getByRole("button", { name: /check outcome/i })
    );

    expect(
      await screen.findByText(/couldn't check the outcome/i)
    ).toBeInTheDocument();
  });

  it("shows persisted outcome metadata for an acted-on decision after reload, without fetching detailed history", async () => {
    const actedOnWithHistory: SavedDecision = {
      ...purchaseDecision,
      status: "acted_on",
      acted_on_at: "2026-08-09T12:00:00Z",
      outcome_count: 3,
      latest_outcome_at: "2026-08-10T12:00:00Z",
    };
    mocks.getSavedDecisions.mockResolvedValue([actedOnWithHistory]);

    render(<DecisionHistoryPage />);

    const card = await screen.findByTestId("decision-history-card");
    const historyButton = within(card).getByRole("button", {
      name: /checked 3× outcome history/i,
    });
    expect(historyButton).toBeInTheDocument();
    expect(historyButton).toHaveTextContent(/aug 10, 2026/i);

    // Persisted metadata came from the list response alone -- the
    // detailed per-outcome GET must not have been called just to
    // render the card.
    expect(mocks.getDecisionOutcomes).not.toHaveBeenCalled();
  });

  it("does not eagerly fetch detailed outcome history for every card on load", async () => {
    const first: SavedDecision = {
      ...purchaseDecision,
      id: 101,
      status: "acted_on",
      acted_on_at: "2026-08-09T00:00:00Z",
      outcome_count: 2,
      latest_outcome_at: "2026-08-10T00:00:00Z",
    };
    const second: SavedDecision = {
      ...purchaseDecision,
      id: 102,
      title: "Second Laptop Purchase",
      status: "acted_on",
      acted_on_at: "2026-08-09T00:00:00Z",
      outcome_count: 1,
      latest_outcome_at: "2026-08-11T00:00:00Z",
    };
    mocks.getSavedDecisions.mockResolvedValue([first, second]);

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    await screen.findByText("Second Laptop Purchase");

    expect(mocks.getDecisionOutcomes).not.toHaveBeenCalled();
  });

  it("lazily fetches and renders prior persisted outcomes when history is opened", async () => {
    const actedOnWithHistory: SavedDecision = {
      ...purchaseDecision,
      status: "acted_on",
      acted_on_at: "2026-08-09T00:00:00Z",
      outcome_count: 1,
      latest_outcome_at: "2026-08-10T00:00:00Z",
    };
    mocks.getSavedDecisions.mockResolvedValue([actedOnWithHistory]);
    mocks.getDecisionOutcomes.mockResolvedValue([
      {
        id: 9,
        decision_id: 1,
        evaluated_at: "2026-08-10T00:00:00Z",
        current_result_snapshot: {
          safe_to_spend_after_purchase_cents: 6_500_000,
        },
        comparison_snapshot: {
          changed: true,
          metrics: [
            {
              path: "safe_to_spend_after_purchase_cents",
              before: 6_056_900,
              current: 6_500_000,
              delta: 443_100,
              change_type: "numeric",
            },
          ],
          summary: { metrics_compared: 1, metrics_changed: 1 },
        },
        created_at: "2026-08-10T00:00:00Z",
      },
    ]);

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    expect(mocks.getDecisionOutcomes).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", { name: /checked 1× outcome history/i })
    );

    await waitFor(() =>
      expect(mocks.getDecisionOutcomes).toHaveBeenCalledWith(1, 1)
    );
    expect(mocks.getDecisionOutcomes).toHaveBeenCalledTimes(1);

    const panel = await screen.findByTestId("decision-outcome-panel");
    expect(panel).toHaveTextContent("Predicted vs current");
    expect(panel).toHaveTextContent("$65,000.00");

    // Toggling again hides the panel without a second fetch.
    fireEvent.click(
      screen.getByRole("button", { name: /hide outcome history/i })
    );
    expect(
      screen.queryByTestId("decision-outcome-panel")
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /checked 1× outcome history/i })
    );
    await screen.findByTestId("decision-outcome-panel");
    expect(mocks.getDecisionOutcomes).toHaveBeenCalledTimes(1);
  });

  it("updates the outcome metadata and panel immediately after checking a new outcome, without a reload", async () => {
    const actedOnDecision: SavedDecision = {
      ...purchaseDecision,
      status: "acted_on",
      acted_on_at: "2026-08-09T00:00:00Z",
    };
    mocks.getSavedDecisions.mockResolvedValue([actedOnDecision]);
    mocks.evaluateDecisionOutcome.mockResolvedValue({
      id: 1,
      decision_id: 1,
      evaluated_at: "2026-08-10T00:00:00Z",
      current_result_snapshot: {
        safe_to_spend_after_purchase_cents: 6_500_000,
      },
      comparison_snapshot: {
        changed: true,
        metrics: [
          {
            path: "safe_to_spend_after_purchase_cents",
            before: 6_056_900,
            current: 6_500_000,
            delta: 443_100,
            change_type: "numeric",
          },
        ],
        summary: { metrics_compared: 1, metrics_changed: 1 },
      },
      created_at: "2026-08-10T00:00:00Z",
    });

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    expect(
      screen.queryByRole("button", { name: /outcome history/i })
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /check outcome/i })
    );

    const panel = await screen.findByTestId("decision-outcome-panel");
    expect(panel).toHaveTextContent("$65,000.00");

    // The metadata badge reflects the new persisted count immediately,
    // and the panel is already open (from just checking), so the
    // toggle now reads "Hide" rather than "Checked 1x ...".
    expect(
      screen.getByRole("button", { name: /hide outcome history/i })
    ).toBeInTheDocument();

    // The update was purely local -- no second list fetch/reload.
    expect(mocks.getSavedDecisions).toHaveBeenCalledTimes(1);
  });
});

describe("Decision memory", () => {
  it("renders nothing when there is no decision history", async () => {
    mocks.getSavedDecisions.mockResolvedValue([]);
    mocks.getDecisionMemory.mockResolvedValue(emptyMemory);

    render(<DecisionHistoryPage />);

    await screen.findByText("No saved decisions yet");
    expect(
      screen.queryByTestId("decision-memory-section")
    ).not.toBeInTheDocument();
  });

  it("renders the populated summary, patterns, and follow-up count", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionMemory.mockResolvedValue(populatedMemory);

    render(<DecisionHistoryPage />);

    const section = await screen.findByTestId("decision-memory-section");
    expect(section).toHaveTextContent("4");
    expect(section).toHaveTextContent("2");
    expect(section).toHaveTextContent("1");

    expect(screen.getByTestId("decision-memory-patterns")).toHaveTextContent(
      "Repeated major purchase analysis -- 4 saved decisions."
    );
    expect(
      screen.getByTestId("decision-memory-follow-up")
    ).toHaveTextContent("Needs follow-up: 2 decisions due for review.");
  });

  it("never renders a raw result_snapshot inside the memory section", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionMemory.mockResolvedValue(populatedMemory);

    render(<DecisionHistoryPage />);

    const section = await screen.findByTestId("decision-memory-section");
    expect(section).not.toHaveTextContent("affordability_status");
    expect(section).not.toHaveTextContent("confidence_score");
  });

  it("does not block the decision list when the memory request fails", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionMemory.mockRejectedValue(new Error("network error"));

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    expect(
      screen.queryByTestId("decision-memory-section")
    ).not.toBeInTheDocument();
  });
});

describe("Decision calibration", () => {
  it("shows a quiet empty state when there are no tracked outcomes", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionCalibration.mockResolvedValue(emptyCalibration);

    render(<DecisionHistoryPage />);

    const empty = await screen.findByTestId("calibration-empty");
    expect(empty).toHaveTextContent(
      "Calibration appears after you act on saved decisions and check their outcomes."
    );
    expect(
      screen.queryByTestId("decision-calibration-section")
    ).not.toBeInTheDocument();
  });

  it("shows an insufficient-data message once at least one decision is tracked", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionCalibration.mockResolvedValue(
      calibrationFixture({
        tracked_decisions: 1,
        outcome_checks: 1,
        directional_metrics_compared: 1,
        favorable_count: 1,
        favorable_rate: 1,
        calibration_label: "insufficient_data",
      })
    );

    render(<DecisionHistoryPage />);

    const section = await screen.findByTestId(
      "decision-calibration-section"
    );
    expect(section).toHaveTextContent(
      "More tracked outcomes are needed before Discero can identify a calibration pattern."
    );
    expect(screen.getByTestId("calibration-label")).toHaveTextContent(
      "Insufficient data"
    );
  });

  it("shows a mostly-conservative narrative", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionCalibration.mockResolvedValue(
      calibrationFixture({
        tracked_decisions: 2,
        outcome_checks: 4,
        directional_metrics_compared: 4,
        favorable_count: 3,
        unfavorable_count: 1,
        favorable_rate: 0.75,
        unfavorable_rate: 0.25,
        calibration_label: "mostly_conservative",
      })
    );

    render(<DecisionHistoryPage />);

    const section = await screen.findByTestId(
      "decision-calibration-section"
    );
    expect(section).toHaveTextContent(
      "Discero has been mostly conservative across your tracked outcomes."
    );
    expect(screen.getByTestId("calibration-label")).toHaveTextContent(
      "Mostly conservative"
    );
  });

  it("shows a mostly-optimistic narrative", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionCalibration.mockResolvedValue(
      calibrationFixture({
        tracked_decisions: 2,
        outcome_checks: 4,
        directional_metrics_compared: 4,
        favorable_count: 1,
        unfavorable_count: 3,
        favorable_rate: 0.25,
        unfavorable_rate: 0.75,
        calibration_label: "mostly_optimistic",
      })
    );

    render(<DecisionHistoryPage />);

    const section = await screen.findByTestId(
      "decision-calibration-section"
    );
    expect(section).toHaveTextContent(
      "Discero has been mostly optimistic across your tracked outcomes."
    );
    expect(screen.getByTestId("calibration-label")).toHaveTextContent(
      "Mostly optimistic"
    );
  });

  it("shows a balanced narrative", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionCalibration.mockResolvedValue(
      calibrationFixture({
        tracked_decisions: 2,
        outcome_checks: 4,
        directional_metrics_compared: 4,
        favorable_count: 2,
        unfavorable_count: 2,
        favorable_rate: 0.5,
        unfavorable_rate: 0.5,
        calibration_label: "balanced",
      })
    );

    render(<DecisionHistoryPage />);

    const section = await screen.findByTestId(
      "decision-calibration-section"
    );
    expect(section).toHaveTextContent(
      "Discero has been balanced across your tracked outcomes."
    );
    expect(screen.getByTestId("calibration-label")).toHaveTextContent(
      "Balanced"
    );
  });

  it("renders the summary counts", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionCalibration.mockResolvedValue(
      calibrationFixture({
        tracked_decisions: 3,
        outcome_checks: 7,
        directional_metrics_compared: 5,
        favorable_count: 3,
        unfavorable_count: 2,
        favorable_rate: 0.6,
        unfavorable_rate: 0.4,
        calibration_label: "balanced",
      })
    );

    render(<DecisionHistoryPage />);

    const section = await screen.findByTestId(
      "decision-calibration-section"
    );
    expect(within(section).getByText("3")).toBeInTheDocument();
    expect(within(section).getByText("7")).toBeInTheDocument();
    expect(within(section).getByText("5")).toBeInTheDocument();
  });

  it("renders a decision-type breakdown when data exists", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionCalibration.mockResolvedValue(
      calibrationFixture({
        tracked_decisions: 2,
        outcome_checks: 2,
        directional_metrics_compared: 2,
        favorable_count: 2,
        favorable_rate: 1,
        calibration_label: "insufficient_data",
        decision_types: [
          {
            decision_type: "major_purchase",
            tracked_decisions: 1,
            outcome_checks: 1,
            directional_observations: 1,
            favorable_count: 1,
            unfavorable_count: 0,
            unchanged_count: 0,
            favorable_rate: 1,
            calibration_label: "insufficient_data",
          },
          {
            decision_type: "stress_test",
            tracked_decisions: 1,
            outcome_checks: 1,
            directional_observations: 1,
            favorable_count: 1,
            unfavorable_count: 0,
            unchanged_count: 0,
            favorable_rate: 1,
            calibration_label: "insufficient_data",
          },
        ],
      })
    );

    render(<DecisionHistoryPage />);

    const breakdown = await screen.findByTestId(
      "calibration-type-breakdown"
    );
    expect(within(breakdown).getByText("Major Purchase")).toBeInTheDocument();
    expect(within(breakdown).getByText("Stress Test")).toBeInTheDocument();
  });

  it("humanizes metric paths instead of showing raw snapshot keys", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionCalibration.mockResolvedValue(
      calibrationFixture({
        tracked_decisions: 1,
        outcome_checks: 1,
        directional_metrics_compared: 1,
        favorable_count: 1,
        favorable_rate: 1,
        calibration_label: "insufficient_data",
        metric_groups: [
          {
            path: "safe_to_spend_after_purchase_cents",
            unit: "currency",
            direction: "higher_is_better",
            observations: 4,
            mean_signed_delta: 50_000,
            mean_absolute_delta: 50_000,
            latest_delta: 50_000,
            favorable_count: 4,
            unfavorable_count: 0,
            unchanged_count: 0,
          },
        ],
      })
    );

    render(<DecisionHistoryPage />);

    const metricGroups = await screen.findByTestId(
      "calibration-metric-groups"
    );
    expect(metricGroups).toHaveTextContent("safe to spend after purchase");
    expect(metricGroups).not.toHaveTextContent(
      "safe_to_spend_after_purchase_cents"
    );
  });

  it("never dumps raw JSON in the calibration section", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionCalibration.mockResolvedValue(
      calibrationFixture({
        tracked_decisions: 1,
        outcome_checks: 1,
        directional_metrics_compared: 1,
        favorable_count: 1,
        favorable_rate: 1,
        calibration_label: "insufficient_data",
        metric_groups: [
          {
            path: "safe_to_spend_after_purchase_cents",
            unit: "currency",
            direction: "higher_is_better",
            observations: 1,
            mean_signed_delta: 50_000,
            mean_absolute_delta: 50_000,
            latest_delta: 50_000,
            favorable_count: 1,
            unfavorable_count: 0,
            unchanged_count: 0,
          },
        ],
        decision_types: [
          {
            decision_type: "major_purchase",
            tracked_decisions: 1,
            outcome_checks: 1,
            directional_observations: 1,
            favorable_count: 1,
            unfavorable_count: 0,
            unchanged_count: 0,
            favorable_rate: 1,
            calibration_label: "insufficient_data",
          },
        ],
      })
    );

    render(<DecisionHistoryPage />);

    const section = await screen.findByTestId(
      "decision-calibration-section"
    );
    expect(section.textContent ?? "").not.toMatch(/[{}]/);
  });

  it("degrades gracefully when the calibration request fails, without breaking decision history", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionCalibration.mockRejectedValue(
      new Error("network error")
    );

    render(<DecisionHistoryPage />);

    expect(await screen.findByText("Laptop Purchase")).toBeInTheDocument();
    expect(
      screen.queryByTestId("decision-calibration-section")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("calibration-empty")
    ).not.toBeInTheDocument();
  });
});

describe("Decision portfolio", () => {
  function extraCompatibleDecision(id: number): SavedDecision {
    return {
      ...purchaseDecision,
      id,
      title: `Purchase ${id}`,
    };
  }

  async function selectTwoCompatibleDecisions() {
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));
    fireEvent.click(
      screen.getByTestId(`portfolio-select-${purchaseDecision.id}`)
    );
    fireEvent.click(
      screen.getByTestId(`portfolio-select-${whatIfDecision.id}`)
    );
  }

  it("enters selection mode from Compare decisions together", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);

    render(<DecisionHistoryPage />);

    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));

    expect(
      await screen.findByTestId("portfolio-selection-toolbar")
    ).toBeInTheDocument();
    expect(screen.getByTestId("portfolio-selected-count")).toHaveTextContent(
      "Selected 0 of 5"
    );
  });

  it("allows selecting compatible decisions", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));

    const checkbox = screen.getByTestId(`portfolio-select-${purchaseDecision.id}`);

    expect(checkbox).not.toBeDisabled();
    fireEvent.click(checkbox);

    expect(checkbox).toBeChecked();
    expect(screen.getByTestId("portfolio-selected-count")).toHaveTextContent(
      "Selected 1 of 5"
    );
  });

  it("disables unsupported decision types with a short explanation", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      scenarioDecision,
    ]);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));

    const checkbox = screen.getByTestId(
      `portfolio-select-${scenarioDecision.id}`
    );

    expect(checkbox).toBeDisabled();
    expect(
      screen.getByTestId(`portfolio-unsupported-${scenarioDecision.id}`)
    ).toHaveTextContent("Not available for portfolio analysis yet.");
  });

  it("allows selecting a stress test without requiring a branch", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      stressTestDecision,
    ]);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));

    const checkbox = screen.getByTestId(`portfolio-select-${stressTestDecision.id}`);

    expect(checkbox).not.toBeDisabled();
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
    expect(
      screen.queryByTestId(`portfolio-variant-${stressTestDecision.id}`)
    ).not.toBeInTheDocument();
  });

  it("disables dismissed decisions", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      dismissedPurchaseDecision,
    ]);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));

    const checkbox = screen.getByTestId(
      `portfolio-select-${dismissedPurchaseDecision.id}`
    );

    expect(checkbox).toBeDisabled();
    expect(
      screen.getByTestId(
        `portfolio-unsupported-${dismissedPurchaseDecision.id}`
      )
    ).toHaveTextContent("Dismissed decisions can't be compared.");
  });

  it("requires a branch to be chosen for buy_now_vs_wait before analyzing", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      buyNowVsWaitDecision,
    ]);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));
    fireEvent.click(
      screen.getByTestId(`portfolio-select-${purchaseDecision.id}`)
    );
    fireEvent.click(
      screen.getByTestId(`portfolio-select-${buyNowVsWaitDecision.id}`)
    );

    const analyzeButton = screen.getByTestId("analyze-together");
    expect(analyzeButton).toBeDisabled();

    const variantFieldset = screen.getByTestId(
      `portfolio-variant-${buyNowVsWaitDecision.id}`
    );
    const radios = within(variantFieldset).getAllByRole("radio");
    // WAIT isn't offered: the portfolio has one shared baseline as of
    // today, so it can't honor WAIT's real (time-shifted) meaning.
    expect(radios).toHaveLength(1);
    // Never defaulted to the recommended branch -- the user must
    // explicitly choose.
    radios.forEach((radio) => expect(radio).not.toBeChecked());

    fireEvent.click(within(variantFieldset).getByLabelText("Buy now"));
    expect(analyzeButton).not.toBeDisabled();
  });

  it("shows branch options for what_if_comparison with none preselected", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfComparisonDecision,
    ]);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));
    fireEvent.click(
      screen.getByTestId(`portfolio-select-${whatIfComparisonDecision.id}`)
    );

    const variantFieldset = screen.getByTestId(
      `portfolio-variant-${whatIfComparisonDecision.id}`
    );
    expect(
      within(variantFieldset).getByLabelText("Option A")
    ).toBeInTheDocument();
    expect(
      within(variantFieldset).getByLabelText("Option B")
    ).toBeInTheDocument();
    within(variantFieldset)
      .getAllByRole("radio")
      .forEach((radio) => expect(radio).not.toBeChecked());
    expect(screen.getByTestId("analyze-together")).toBeDisabled();
  });

  it("shows a message when a variant-required decision's persisted data can't support portfolio analysis", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      buyNowVsWaitDecisionMissingTiming,
    ]);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));
    fireEvent.click(
      screen.getByTestId(
        `portfolio-select-${buyNowVsWaitDecisionMissingTiming.id}`
      )
    );

    expect(
      within(
        screen.getByTestId(
          `portfolio-variant-${buyNowVsWaitDecisionMissingTiming.id}`
        )
      ).getByText(/don't support portfolio analysis anymore/)
    ).toBeInTheDocument();
  });

  it("clears the branch selection when a decision is deselected", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      buyNowVsWaitDecision,
    ]);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));

    const bnwCheckbox = screen.getByTestId(`portfolio-select-${buyNowVsWaitDecision.id}`);
    fireEvent.click(bnwCheckbox);
    fireEvent.click(
      within(
        screen.getByTestId(`portfolio-variant-${buyNowVsWaitDecision.id}`)
      ).getByLabelText("Buy now")
    );

    fireEvent.click(bnwCheckbox);
    fireEvent.click(bnwCheckbox);

    const radios = within(
      screen.getByTestId(`portfolio-variant-${buyNowVsWaitDecision.id}`)
    ).getAllByRole("radio");
    radios.forEach((radio) => expect(radio).not.toBeChecked());
  });

  it("serializes the selected buy_now_vs_wait branch in the request", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      buyNowVsWaitDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockResolvedValue(portfolioResultFixture);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));
    fireEvent.click(
      screen.getByTestId(`portfolio-select-${purchaseDecision.id}`)
    );
    fireEvent.click(
      screen.getByTestId(`portfolio-select-${buyNowVsWaitDecision.id}`)
    );
    fireEvent.click(
      within(
        screen.getByTestId(`portfolio-variant-${buyNowVsWaitDecision.id}`)
      ).getByLabelText("Buy now")
    );
    fireEvent.click(screen.getByTestId("analyze-together"));

    await waitFor(() => {
      expect(mocks.evaluateDecisionPortfolio).toHaveBeenCalledWith(
        1,
        [
          { decision_id: purchaseDecision.id },
          { decision_id: buyNowVsWaitDecision.id, variant: "buy_now" },
        ],
        expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/)
      );
    });
  });

  it("serializes the selected what_if_comparison option as a stable key, not the label", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfComparisonDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockResolvedValue(portfolioResultFixture);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));
    fireEvent.click(
      screen.getByTestId(`portfolio-select-${purchaseDecision.id}`)
    );
    fireEvent.click(
      screen.getByTestId(`portfolio-select-${whatIfComparisonDecision.id}`)
    );
    fireEvent.click(
      within(
        screen.getByTestId(
          `portfolio-variant-${whatIfComparisonDecision.id}`
        )
      ).getByLabelText("Option B")
    );
    fireEvent.click(screen.getByTestId("analyze-together"));

    await waitFor(() => {
      expect(mocks.evaluateDecisionPortfolio).toHaveBeenCalledWith(
        1,
        [
          { decision_id: purchaseDecision.id },
          { decision_id: whatIfComparisonDecision.id, variant: "option_b" },
        ],
        expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/)
      );
    });
  });

  it("displays the selected branch label in the portfolio result", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      buyNowVsWaitDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockResolvedValue({
      ...portfolioResultFixture,
      selected_decisions: [
        ...portfolioResultFixture.selected_decisions,
        {
          decision_id: buyNowVsWaitDecision.id,
          decision_type: "buy_now_vs_wait",
          title: "Buy Now vs Wait: New Laptop",
          variant: "buy_now",
          variant_label: "Buy now",
        },
      ],
      decision_impacts: [
        ...portfolioResultFixture.decision_impacts,
        {
          decision_id: buyNowVsWaitDecision.id,
          title: "Buy Now vs Wait: New Laptop",
          decision_type: "buy_now_vs_wait",
          incremental_safe_to_spend_impact_cents: -220_000,
          risk_rank: 3,
          contribution_level: "medium",
        },
      ],
    });

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));
    fireEvent.click(
      screen.getByTestId(`portfolio-select-${purchaseDecision.id}`)
    );
    fireEvent.click(
      screen.getByTestId(`portfolio-select-${buyNowVsWaitDecision.id}`)
    );
    fireEvent.click(
      within(
        screen.getByTestId(`portfolio-variant-${buyNowVsWaitDecision.id}`)
      ).getByLabelText("Buy now")
    );
    fireEvent.click(screen.getByTestId("analyze-together"));

    const section = await screen.findByTestId("decision-portfolio-section");
    expect(within(section).getByText(/Buy now/)).toBeInTheDocument();
  });

  it("requires at least two selections before Analyze together is enabled", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));

    const analyzeButton = screen.getByTestId("analyze-together");
    expect(analyzeButton).toBeDisabled();

    fireEvent.click(
      screen.getByTestId(`portfolio-select-${purchaseDecision.id}`)
    );
    expect(analyzeButton).toBeDisabled();

    fireEvent.click(
      screen.getByTestId(`portfolio-select-${whatIfDecision.id}`)
    );
    expect(analyzeButton).not.toBeDisabled();
  });

  it("enforces a maximum of five selected decisions", async () => {
    const decisions = [101, 102, 103, 104, 105, 106].map(
      extraCompatibleDecision
    );
    mocks.getSavedDecisions.mockResolvedValue(decisions);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));

    for (const decision of decisions.slice(0, 5)) {
      fireEvent.click(
        screen.getByTestId(`portfolio-select-${decision.id}`)
      );
    }

    expect(screen.getByTestId("portfolio-selected-count")).toHaveTextContent(
      "Selected 5 of 5"
    );

    const sixthCheckbox = screen.getByTestId(`portfolio-select-${decisions[5].id}`);
    expect(sixthCheckbox).toBeDisabled();
  });

  it("sends the correct decision IDs to the API", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockResolvedValue(portfolioResultFixture);

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));

    await waitFor(() => {
      expect(mocks.evaluateDecisionPortfolio).toHaveBeenCalledWith(
        1,
        [
          { decision_id: purchaseDecision.id },
          { decision_id: whatIfDecision.id },
        ],
        expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/)
      );
    });
  });

  it("shows a loading state while analyzing", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);

    let resolvePromise: (value: DecisionPortfolioResult) => void = () => {};
    mocks.evaluateDecisionPortfolio.mockReturnValue(
      new Promise((resolve) => {
        resolvePromise = resolve;
      })
    );

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));

    expect(await screen.findByText("Analyzing…")).toBeInTheDocument();

    resolvePromise(portfolioResultFixture);

    await waitFor(() =>
      expect(
        screen.getByTestId("decision-portfolio-section")
      ).toBeInTheDocument()
    );
  });

  it("resets selection to 0 when re-entering portfolio mode after a prior selection", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    expect(screen.getByTestId("portfolio-selected-count")).toHaveTextContent(
      "Selected 2 of 5"
    );

    fireEvent.click(screen.getByTestId("cancel-portfolio-selection"));
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));

    expect(screen.getByTestId("portfolio-selected-count")).toHaveTextContent(
      "Selected 0 of 5"
    );
  });

  it("clears a previously chosen branch when re-entering portfolio mode", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      buyNowVsWaitDecision,
    ]);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));
    fireEvent.click(
      screen.getByTestId(`portfolio-select-${buyNowVsWaitDecision.id}`)
    );
    fireEvent.click(
      within(
        screen.getByTestId(`portfolio-variant-${buyNowVsWaitDecision.id}`)
      ).getByLabelText("Buy now")
    );

    fireEvent.click(screen.getByTestId("cancel-portfolio-selection"));
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));
    fireEvent.click(
      screen.getByTestId(`portfolio-select-${buyNowVsWaitDecision.id}`)
    );

    const radios = within(
      screen.getByTestId(`portfolio-variant-${buyNowVsWaitDecision.id}`)
    ).getAllByRole("radio");
    radios.forEach((radio) => expect(radio).not.toBeChecked());
  });

  it("does not show a prior session's result once a stale analyze response arrives after re-entry", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);

    let resolvePromise: (value: DecisionPortfolioResult) => void = () => {};
    mocks.evaluateDecisionPortfolio.mockReturnValue(
      new Promise((resolve) => {
        resolvePromise = resolve;
      })
    );

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));
    expect(await screen.findByText("Analyzing\u2026")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("cancel-portfolio-selection"));
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));

    resolvePromise(portfolioResultFixture);
    await new Promise((r) => setTimeout(r, 0));

    expect(
      screen.queryByTestId("decision-portfolio-section")
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("portfolio-selected-count")).toHaveTextContent(
      "Selected 0 of 5"
    );
  });

  it("does not show a prior session's error once a stale analyze rejection arrives after re-entry", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);

    let rejectPromise: (err: Error) => void = () => {};
    mocks.evaluateDecisionPortfolio.mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectPromise = reject;
      })
    );

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));
    expect(await screen.findByText("Analyzing\u2026")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("cancel-portfolio-selection"));
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));

    rejectPromise(new Error("validation error"));
    await new Promise((r) => setTimeout(r, 0));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByTestId("portfolio-selected-count")).toHaveTextContent(
      "Selected 0 of 5"
    );
  });

  it("shows an error when the backend rejects the portfolio request", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockRejectedValue(
      new Error("validation error")
    );

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't analyze these decisions together just now."
    );
  });

  it("shows an actionable message when a decision is outside the current analysis horizon", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockRejectedValue(
      new ApiError(
        "one or more selected decisions no longer fit the combined " +
          "evaluation horizon (422)",
        "event_date_out_of_horizon"
      )
    );

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "One selected decision is outside the current analysis horizon. " +
        "Run that decision again with a current date, then compare it."
    );
    // Never surface the raw backend message or an internal decision id.
    expect(alert).not.toHaveTextContent("evaluation horizon (422)");
  });

  it("keeps the generic fallback for an ApiError with an unrecognized reason", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockRejectedValue(
      new ApiError("stress amount unresolvable (422)", "stress_amount_unresolvable")
    );

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't analyze these decisions together just now."
    );
  });

  it("sends the browser's local calendar date, not the UTC date, as as_of_date", async () => {
    const originalTZ = process.env.TZ;
    // UTC-5 in August (CDT) -- picked so a late-evening local clock and
    // an already-rolled-over UTC clock land on different calendar dates.
    process.env.TZ = "America/Chicago";
    // Only fake Date -- setTimeout/etc. stay real so RTL's async
    // waitFor/findBy helpers (which rely on real timers) don't hang.
    vi.useFakeTimers({ toFake: ["Date"] });
    // 04:30 UTC on the 21st is still 23:30 local on the 20th.
    vi.setSystemTime(new Date("2026-08-21T04:30:00Z"));

    try {
      mocks.getSavedDecisions.mockResolvedValue([
        purchaseDecision,
        whatIfDecision,
      ]);
      mocks.evaluateDecisionPortfolio.mockResolvedValue(
        portfolioResultFixture
      );

      // Sanity check: the UTC date really has already rolled over, so
      // this test would catch a regression to toISOString().slice(0, 10).
      expect(new Date().toISOString().slice(0, 10)).toBe("2026-08-21");

      render(<DecisionHistoryPage />);
      await selectTwoCompatibleDecisions();
      fireEvent.click(screen.getByTestId("analyze-together"));

      await waitFor(() => {
        expect(mocks.evaluateDecisionPortfolio).toHaveBeenCalledWith(
          1,
          [
            { decision_id: purchaseDecision.id },
            { decision_id: whatIfDecision.id },
          ],
          "2026-08-20"
        );
      });
    } finally {
      vi.useRealTimers();
      process.env.TZ = originalTZ;
    }
  });

  it("renders the successful combined result with baseline, combined, and total change", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockResolvedValue(portfolioResultFixture);

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));

    const section = await screen.findByTestId("decision-portfolio-section");

    expect(within(section).getByText("$100,000.00")).toBeInTheDocument();
    expect(within(section).getByText("$66,600.00")).toBeInTheDocument();
    expect(within(section).getByText("-$33,400.00")).toBeInTheDocument();
    expect(within(section).getByText("Comfortable")).toBeInTheDocument();
  });

  it("renders the biggest-pressure ranking", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockResolvedValue(portfolioResultFixture);

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));

    const section = await screen.findByTestId("decision-portfolio-section");

    expect(
      within(section).getByText(/1\.\s*New Laptop/)
    ).toBeInTheDocument();
    expect(
      within(section).getByText(/2\.\s*Rent increase/)
    ).toBeInTheDocument();
    expect(within(section).getByText("-$2,200.00")).toBeInTheDocument();
    expect(within(section).getByText("-$1,200.00")).toBeInTheDocument();
  });

  it("renders goal impact when present", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockResolvedValue(portfolioResultFixture);

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));

    const section = await screen.findByTestId("decision-portfolio-section");
    const goalSection = within(section).getByTestId("portfolio-goal-effects");

    expect(goalSection).toHaveTextContent("House Down Payment");
    expect(goalSection).toHaveTextContent(
      "fall short of its target by $3,600.00"
    );
  });

  it("shows the ranked severity and conflict count for affected goals", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockResolvedValue(portfolioResultFixture);

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));

    const section = await screen.findByTestId("decision-portfolio-section");
    const goalSection = within(section).getByTestId("portfolio-goal-effects");

    expect(
      within(goalSection).getByText(/1\.\s*House Down Payment/)
    ).toBeInTheDocument();
    expect(within(goalSection).getByText("High")).toBeInTheDocument();
    expect(
      within(goalSection).getByTestId("portfolio-goal-conflict-count")
    ).toHaveTextContent("1 in conflict");

    // The underlying goal_impacts values remain exactly what the
    // deterministic engine produced -- this section only normalizes
    // presentation, it never recomputes them.
    expect(goalSection).toHaveTextContent("$3,600.00");
  });

  it("omits the goal effects section when there are no goal impacts", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockResolvedValue({
      ...portfolioResultFixture,
      goal_impacts: [],
      goal_conflict_intelligence: {
        supported: true,
        goals: [],
        most_affected_goal_id: null,
        conflict_count: 0,
        scenario_created_conflict_count: 0,
        scenario_worsened_conflict_count: 0,
        pre_existing_conflict_count: 0,
        scenario_improved_count: 0,
      },
    });

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));

    const section = await screen.findByTestId("decision-portfolio-section");
    expect(
      within(section).queryByTestId("portfolio-goal-effects")
    ).not.toBeInTheDocument();
  });

  it("renders warnings and conflict details", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockResolvedValue(portfolioResultFixture);

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));

    const section = await screen.findByTestId("decision-portfolio-section");
    const warningsSection = within(section).getByTestId(
      "portfolio-conflicts-warnings"
    );

    expect(warningsSection).toHaveTextContent(
      "No active recurring or budget obligations were found for the selected period."
    );
    expect(warningsSection).toHaveTextContent(
      portfolioResultFixture.conflicts.explanation
    );
  });

  it("Change selection returns to editing without losing the checked decisions", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockResolvedValue(portfolioResultFixture);

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));
    await screen.findByTestId("decision-portfolio-section");

    fireEvent.click(screen.getByText("Change selection"));

    expect(
      screen.queryByTestId("decision-portfolio-section")
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("portfolio-selection-toolbar")
    ).toBeInTheDocument();
    expect(screen.getByTestId("portfolio-selected-count")).toHaveTextContent(
      "Selected 2 of 5"
    );

    const checkbox = screen.getByTestId(`portfolio-select-${purchaseDecision.id}`);
    expect(checkbox).toBeChecked();
  });

  it("Clear analysis exits selection mode entirely", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockResolvedValue(portfolioResultFixture);

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));
    await screen.findByTestId("decision-portfolio-section");

    fireEvent.click(screen.getByText("Clear analysis"));

    expect(
      screen.queryByTestId("decision-portfolio-section")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("portfolio-selection-toolbar")
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("start-portfolio-selection")
    ).toBeInTheDocument();
  });

  it("leaves ordinary Decision History unchanged outside selection mode", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);

    render(<DecisionHistoryPage />);
    await screen.findByText("Laptop Purchase");

    expect(
      screen.queryByTestId("portfolio-selection-toolbar")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId(`portfolio-select-${purchaseDecision.id}`)
    ).not.toBeInTheDocument();
    expect(screen.getByText("I made this decision")).toBeInTheDocument();
  });

  it("exposes an accessible checkbox label naming the decision", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));

    expect(
      screen.getByRole("checkbox", {
        name: `Include ${purchaseDecision.title} in portfolio analysis`,
      })
    ).toBeInTheDocument();
  });

  it("applies a selected treatment to the card and removes it on deselect", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);

    render(<DecisionHistoryPage />);
    fireEvent.click(await screen.findByTestId("start-portfolio-selection"));

    const card = (
      await screen.findByTestId(`portfolio-select-${purchaseDecision.id}`)
    ).closest('[data-testid="decision-history-card"]') as HTMLElement;
    const checkbox = screen.getByTestId(
      `portfolio-select-${purchaseDecision.id}`
    );

    expect(card.className).not.toContain("border-[#6E4B63]/55");
    fireEvent.click(checkbox);
    expect(card.className).toContain("border-[#6E4B63]/55");
    fireEvent.click(checkbox);
    expect(card.className).not.toContain("border-[#6E4B63]/55");
  });

  it("hides normal per-decision actions during selection mode and restores them on cancel", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);

    render(<DecisionHistoryPage />);
    await screen.findByText("Laptop Purchase");
    expect(screen.getByText("I made this decision")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("start-portfolio-selection"));
    expect(
      screen.queryByText("I made this decision")
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Run again")).not.toBeInTheDocument();
    expect(screen.queryByText("View timeline")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("cancel-portfolio-selection"));
    expect(screen.getByText("I made this decision")).toBeInTheDocument();
    expect(screen.getByText("Run again")).toBeInTheDocument();
  });

  it("still renders the calibration section alongside the portfolio feature", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);
    mocks.getDecisionCalibration.mockResolvedValue(
      calibrationFixture({ tracked_decisions: 1 })
    );

    render(<DecisionHistoryPage />);

    expect(
      await screen.findByTestId("decision-calibration-section")
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("start-portfolio-selection")
    ).toBeInTheDocument();
  });

  it("never dumps raw JSON in the portfolio result", async () => {
    mocks.getSavedDecisions.mockResolvedValue([
      purchaseDecision,
      whatIfDecision,
    ]);
    mocks.evaluateDecisionPortfolio.mockResolvedValue(portfolioResultFixture);

    render(<DecisionHistoryPage />);
    await selectTwoCompatibleDecisions();
    fireEvent.click(screen.getByTestId("analyze-together"));

    const section = await screen.findByTestId("decision-portfolio-section");
    expect(section.textContent ?? "").not.toMatch(/[{}]/);
  });
});

describe("Decision review queue", () => {
  it("renders above calibration and decision history", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionCalibration.mockResolvedValue(
      calibrationFixture({ tracked_decisions: 1 })
    );
    mocks.getDecisionReviewQueue.mockResolvedValue({
      items: [savedUnresolvedItem],
      total_count: 1,
    });

    render(<DecisionHistoryPage />);

    const reviewSection = await screen.findByTestId(
      "decision-review-queue-section"
    );
    const calibrationSection = await screen.findByTestId(
      "decision-calibration-section"
    );
    const historyCard = await screen.findByTestId("decision-history-card");

    expect(
      reviewSection.compareDocumentPosition(calibrationSection) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      reviewSection.compareDocumentPosition(historyCard) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("renders the correct actions and reason text for a saved-unresolved item", async () => {
    mocks.getSavedDecisions.mockResolvedValue([]);
    mocks.getDecisionReviewQueue.mockResolvedValue({
      items: [savedUnresolvedItem],
      total_count: 1,
    });

    render(<DecisionHistoryPage />);

    const item = await screen.findByTestId("decision-review-queue-item");
    expect(
      within(item).getByRole("button", { name: /i made this decision/i })
    ).toBeInTheDocument();
    expect(
      within(item).getByRole("button", { name: /dismiss/i })
    ).toBeInTheDocument();
    expect(
      within(item).getByText(savedUnresolvedItem.review_reason_text)
    ).toBeInTheDocument();
  });

  it("renders Check outcome for a never-checked acted-on item", async () => {
    mocks.getSavedDecisions.mockResolvedValue([]);
    mocks.getDecisionReviewQueue.mockResolvedValue({
      items: [neverCheckedItem],
      total_count: 1,
    });

    render(<DecisionHistoryPage />);

    const item = await screen.findByTestId("decision-review-queue-item");
    expect(
      within(item).getByRole("button", { name: /check outcome/i })
    ).toBeInTheDocument();
    expect(
      within(item).queryByRole("button", { name: /review again/i })
    ).not.toBeInTheDocument();
  });

  it("renders Review again for a recheck-due item", async () => {
    mocks.getSavedDecisions.mockResolvedValue([]);
    mocks.getDecisionReviewQueue.mockResolvedValue({
      items: [recheckDueItem],
      total_count: 1,
    });

    render(<DecisionHistoryPage />);

    const item = await screen.findByTestId("decision-review-queue-item");
    expect(
      within(item).getByRole("button", { name: /review again/i })
    ).toBeInTheDocument();
  });

  it("only renders items included in the returned queue", async () => {
    mocks.getSavedDecisions.mockResolvedValue([]);
    mocks.getDecisionReviewQueue.mockResolvedValue({
      items: [savedUnresolvedItem],
      total_count: 1,
    });

    render(<DecisionHistoryPage />);

    await screen.findByTestId("decision-review-queue-item");
    expect(
      screen.getAllByTestId("decision-review-queue-item")
    ).toHaveLength(1);
    expect(screen.queryByText(neverCheckedItem.title)).not.toBeInTheDocument();
  });

  it("removes only the acted-on item from the queue after marking it acted on", async () => {
    mocks.getSavedDecisions.mockResolvedValue([]);
    mocks.getDecisionReviewQueue.mockResolvedValue({
      items: [savedUnresolvedItem, neverCheckedItem],
      total_count: 2,
    });
    mocks.updateDecisionStatus.mockResolvedValue({
      ...purchaseDecision,
      id: savedUnresolvedItem.decision_id,
      status: "acted_on",
    });

    render(<DecisionHistoryPage />);

    expect(
      await screen.findAllByTestId("decision-review-queue-item")
    ).toHaveLength(2);

    fireEvent.click(
      screen.getByRole("button", { name: /i made this decision/i })
    );

    await waitFor(() =>
      expect(mocks.updateDecisionStatus).toHaveBeenCalledWith(
        1,
        savedUnresolvedItem.decision_id,
        "acted_on"
      )
    );
    await waitFor(() =>
      expect(
        screen.getAllByTestId("decision-review-queue-item")
      ).toHaveLength(1)
    );
    expect(screen.queryByText(savedUnresolvedItem.title)).not.toBeInTheDocument();
    expect(screen.getByText(neverCheckedItem.title)).toBeInTheDocument();
  });

  it("removes only the checked item from the queue after checking its outcome", async () => {
    mocks.getSavedDecisions.mockResolvedValue([]);
    mocks.getDecisionReviewQueue.mockResolvedValue({
      items: [neverCheckedItem, recheckDueItem],
      total_count: 2,
    });
    mocks.evaluateDecisionOutcome.mockResolvedValue({
      id: 99,
      decision_id: neverCheckedItem.decision_id,
      evaluated_at: "2026-08-19T00:00:00Z",
      current_result_snapshot: {},
      comparison_snapshot: {
        changed: false,
        metrics: [],
        summary: { metrics_compared: 0, metrics_changed: 0 },
      },
    });

    render(<DecisionHistoryPage />);

    expect(
      await screen.findAllByTestId("decision-review-queue-item")
    ).toHaveLength(2);

    fireEvent.click(
      screen.getByRole("button", { name: /^check outcome$/i })
    );

    await waitFor(() =>
      expect(mocks.evaluateDecisionOutcome).toHaveBeenCalledWith(
        1,
        neverCheckedItem.decision_id
      )
    );
    await waitFor(() =>
      expect(
        screen.getAllByTestId("decision-review-queue-item")
      ).toHaveLength(1)
    );
    expect(screen.queryByText(neverCheckedItem.title)).not.toBeInTheDocument();
    expect(screen.getByText(recheckDueItem.title)).toBeInTheDocument();
  });

  it("refreshes decision calibration after a successful outcome check", async () => {
    mocks.getSavedDecisions.mockResolvedValue([]);
    mocks.getDecisionReviewQueue.mockResolvedValue({
      items: [neverCheckedItem],
      total_count: 1,
    });
    mocks.getDecisionCalibration.mockResolvedValueOnce(emptyCalibration);
    mocks.evaluateDecisionOutcome.mockResolvedValue({
      id: 99,
      decision_id: neverCheckedItem.decision_id,
      evaluated_at: "2026-08-19T00:00:00Z",
      current_result_snapshot: {},
      comparison_snapshot: {
        changed: false,
        metrics: [],
        summary: { metrics_compared: 0, metrics_changed: 0 },
      },
    });
    const refreshedCalibration = calibrationFixture({
      tracked_decisions: 1,
      outcome_checks: 1,
      calibration_label: "balanced",
    });
    mocks.getDecisionCalibration.mockResolvedValueOnce(refreshedCalibration);

    render(<DecisionHistoryPage />);

    await screen.findByTestId("decision-review-queue-item");

    fireEvent.click(
      screen.getByRole("button", { name: /^check outcome$/i })
    );

    await waitFor(() =>
      expect(mocks.evaluateDecisionOutcome).toHaveBeenCalled()
    );
    await waitFor(() =>
      expect(mocks.getDecisionCalibration).toHaveBeenCalledTimes(2)
    );
    await waitFor(() =>
      expect(screen.getByTestId("calibration-label")).toHaveTextContent(
        "Balanced"
      )
    );
  });

  it("keeps the outcome check successful even when the calibration refresh fails", async () => {
    mocks.getSavedDecisions.mockResolvedValue([]);
    mocks.getDecisionReviewQueue.mockResolvedValue({
      items: [neverCheckedItem],
      total_count: 1,
    });
    mocks.getDecisionCalibration.mockResolvedValueOnce(emptyCalibration);
    mocks.evaluateDecisionOutcome.mockResolvedValue({
      id: 99,
      decision_id: neverCheckedItem.decision_id,
      evaluated_at: "2026-08-19T00:00:00Z",
      current_result_snapshot: {},
      comparison_snapshot: {
        changed: false,
        metrics: [],
        summary: { metrics_compared: 0, metrics_changed: 0 },
      },
    });
    mocks.getDecisionCalibration.mockRejectedValueOnce(
      new Error("network error")
    );

    render(<DecisionHistoryPage />);

    await screen.findByTestId("decision-review-queue-item");

    fireEvent.click(
      screen.getByRole("button", { name: /^check outcome$/i })
    );

    await waitFor(() =>
      expect(mocks.evaluateDecisionOutcome).toHaveBeenCalled()
    );
    await waitFor(() =>
      expect(
        screen.queryByTestId("decision-review-queue-item")
      ).not.toBeInTheDocument()
    );
    expect(
      screen.queryByText("Couldn't check the outcome just now.")
    ).not.toBeInTheDocument();
  });

  it("does not break Decision History when the review queue request fails", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionReviewQueue.mockRejectedValue(
      new Error("network error")
    );

    render(<DecisionHistoryPage />);

    expect(await screen.findByText("Laptop Purchase")).toBeInTheDocument();
    expect(
      screen.queryByTestId("decision-review-queue-section")
    ).not.toBeInTheDocument();
  });

  it("does not render the section when there are no queue items", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionReviewQueue.mockResolvedValue({
      items: [],
      total_count: 0,
    });

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    expect(
      screen.queryByTestId("decision-review-queue-section")
    ).not.toBeInTheDocument();
  });

  it("leaves existing Decision History rendering unchanged when review queue items are present", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionReviewQueue.mockResolvedValue({
      items: [savedUnresolvedItem],
      total_count: 1,
    });

    render(<DecisionHistoryPage />);

    await screen.findByTestId("decision-review-queue-section");
    const historyCard = await screen.findByTestId("decision-history-card");
    expect(within(historyCard).getByText("Laptop Purchase")).toBeInTheDocument();
    expect(within(historyCard).getByText("$60,569.00")).toBeInTheDocument();
  });
});

describe("Decision timeline", () => {
  const timelineFixture: DecisionTimeline = {
    decision_id: purchaseDecision.id,
    decision_type: "major_purchase",
    title: "Laptop Purchase",
    current_status: "saved",
    events: [
      {
        event_type: "decision_saved",
        occurred_at: "2026-08-04T00:00:00Z",
        outcome_id: null,
        changed: null,
      },
      {
        event_type: "decision_acted_on",
        occurred_at: "2026-08-17T00:00:00Z",
        outcome_id: null,
        changed: null,
      },
      {
        event_type: "outcome_checked",
        occurred_at: "2026-09-20T00:00:00Z",
        outcome_id: 42,
        changed: true,
      },
    ],
  };

  it("does not fetch a timeline until the user opens it", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);

    render(<DecisionHistoryPage />);

    await screen.findByTestId("decision-history-card");
    expect(mocks.getDecisionTimeline).not.toHaveBeenCalled();
  });

  it("lazily fetches and renders the timeline when opened", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionTimeline.mockResolvedValue(timelineFixture);

    render(<DecisionHistoryPage />);

    await screen.findByTestId("decision-history-card");
    fireEvent.click(
      screen.getByRole("button", { name: /view timeline/i })
    );

    expect(mocks.getDecisionTimeline).toHaveBeenCalledWith(
      1,
      purchaseDecision.id
    );

    const panel = await screen.findByTestId("decision-timeline-panel");
    expect(within(panel).getByText("Analyzed & saved")).toBeInTheDocument();
    expect(within(panel).getByText("Acted on")).toBeInTheDocument();
    expect(
      within(panel).getByText("Outcome checked · change found")
    ).toBeInTheDocument();
  });

  it("caches the fetched timeline so reopening does not refetch", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionTimeline.mockResolvedValue(timelineFixture);

    render(<DecisionHistoryPage />);

    await screen.findByTestId("decision-history-card");
    const toggle = screen.getByRole("button", { name: /view timeline/i });

    fireEvent.click(toggle);
    await screen.findByTestId("decision-timeline-panel");

    fireEvent.click(screen.getByRole("button", { name: /hide timeline/i }));
    expect(
      screen.queryByTestId("decision-timeline-panel")
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /view timeline/i }));
    await screen.findByTestId("decision-timeline-panel");

    expect(mocks.getDecisionTimeline).toHaveBeenCalledTimes(1);
  });

  it("isolates a timeline failure from the rest of the page", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.getDecisionTimeline.mockRejectedValue(new Error("network error"));

    render(<DecisionHistoryPage />);

    await screen.findByTestId("decision-history-card");
    fireEvent.click(
      screen.getByRole("button", { name: /view timeline/i })
    );

    expect(
      await screen.findByTestId("decision-timeline-error")
    ).toBeInTheDocument();
    expect(screen.getByText("Laptop Purchase")).toBeInTheDocument();
  });
});

describe("Decision change explanation", () => {
  it("renders What changed metrics after a successful rerun", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.rerunSavedDecision.mockResolvedValue({
      decision_id: 1,
      decision_type: "major_purchase",
      evaluated_at: "2026-08-09",
      result_snapshot: {
        affordability_status: "affordable",
        purchase_amount_cents: 200_000,
        safe_to_spend_after_purchase_cents: 7_000_000,
        confidence_score: 90,
      },
      change_explanation: {
        changed_metrics: [
          {
            path: "safe_to_spend_after_purchase_cents",
            label: "safe to spend after purchase",
            before: 6_056_900,
            current: 7_000_000,
            delta: 943_100,
            change_type: "numeric",
            unit: "currency",
            direction: "higher_is_better",
          },
          {
            path: "affordability_status",
            label: "affordability status",
            before: "caution",
            current: "affordable",
            delta: null,
            change_type: "text",
            unit: null,
            direction: null,
          },
        ],
        total_changed_metric_count: 2,
        unchanged_metric_count: 1,
      },
    });

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    fireEvent.click(screen.getByRole("button", { name: /run again/i }));

    const section = await screen.findByTestId(
      "decision-change-explanation"
    );
    expect(within(section).getByText(/what changed/i)).toBeInTheDocument();
    expect(
      within(section).getByText("safe to spend after purchase")
    ).toBeInTheDocument();
    expect(within(section).getByText("$60,569.00")).toBeInTheDocument();
    expect(within(section).getByText("$70,000.00")).toBeInTheDocument();
    expect(within(section).getByText("+$9,431.00")).toBeInTheDocument();
    expect(within(section).getByText("caution")).toBeInTheDocument();
    expect(within(section).getByText("affordable")).toBeInTheDocument();
  });

  it("shows a no-change message when nothing changed", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.rerunSavedDecision.mockResolvedValue({
      decision_id: 1,
      decision_type: "major_purchase",
      evaluated_at: "2026-08-09",
      result_snapshot: {
        affordability_status: "affordable",
        purchase_amount_cents: 200_000,
      },
      change_explanation: {
        changed_metrics: [],
        total_changed_metric_count: 0,
        unchanged_metric_count: 2,
      },
    });

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    fireEvent.click(screen.getByRole("button", { name: /run again/i }));

    const section = await screen.findByTestId(
      "decision-change-explanation"
    );
    expect(
      within(section).getByText(/no meaningful change/i)
    ).toBeInTheDocument();
  });

  it("keeps the rerun result visible when change_explanation is unavailable", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.rerunSavedDecision.mockResolvedValue({
      decision_id: 1,
      decision_type: "major_purchase",
      evaluated_at: "2026-08-09",
      result_snapshot: {
        affordability_status: "affordable",
        purchase_amount_cents: 200_000,
      },
      change_explanation: null,
    });

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    fireEvent.click(screen.getByRole("button", { name: /run again/i }));

    await screen.findByTestId("decision-rerun-result");
    expect(
      screen.queryByTestId("decision-change-explanation")
    ).not.toBeInTheDocument();
  });

  it("does not create a decision outcome from Run Again", async () => {
    mocks.getSavedDecisions.mockResolvedValue([purchaseDecision]);
    mocks.rerunSavedDecision.mockResolvedValue({
      decision_id: 1,
      decision_type: "major_purchase",
      evaluated_at: "2026-08-09",
      result_snapshot: { affordability_status: "affordable" },
      change_explanation: null,
    });

    render(<DecisionHistoryPage />);

    await screen.findByText("Laptop Purchase");
    fireEvent.click(screen.getByRole("button", { name: /run again/i }));

    await screen.findByTestId("decision-rerun-result");
    expect(mocks.evaluateDecisionOutcome).not.toHaveBeenCalled();
  });
});
