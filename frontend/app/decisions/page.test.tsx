import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ScenarioComparisonResult } from "../lib/api";
import DecisionsPage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  simulateMajorPurchase: vi.fn(),
  compareMajorPurchaseScenarios: vi.fn(),
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
      confidence_score: 85,
      explanation: "New laptop is within the recommended purchase range.",
      alternatives: [],
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
      confidence_score: 85,
      explanation: "Used laptop is technically affordable.",
      alternatives: [],
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
