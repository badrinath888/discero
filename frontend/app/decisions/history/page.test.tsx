import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DecisionCalibration, SavedDecision } from "../../lib/api";
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
  getDecisionCalibration: vi.fn(),
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
      getDecisionCalibration: mocks.getDecisionCalibration,
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
  mocks.getDecisionCalibration.mockReset();
  mocks.getDecisionCalibration.mockResolvedValue(emptyCalibration);
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
    expect(
      screen.getByText(
        "Assumes stable income and no other large purchases."
      )
    ).toBeInTheDocument();
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
