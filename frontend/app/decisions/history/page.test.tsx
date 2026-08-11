import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SavedDecision } from "../../lib/api";
import DecisionHistoryPage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  getSavedDecisions: vi.fn(),
  deleteSavedDecision: vi.fn(),
  rerunSavedDecision: vi.fn(),
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
  created_at: "2026-08-08T00:00:00Z",
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
  created_at: "2026-08-08T00:00:00Z",
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
  created_at: "2026-08-08T00:00:00Z",
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
  created_at: "2026-08-08T00:00:00Z",
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
  created_at: "2026-08-08T00:00:00Z",
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
});
