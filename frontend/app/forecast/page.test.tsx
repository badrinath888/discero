import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CashFlowForecast } from "../lib/api";
import ForecastPage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  getCashFlowForecast: vi.fn(),
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
  },
};

async function renderPage() {
  render(<ForecastPage />);
  await screen.findByText("Projected month-end balance");
}

beforeEach(() => {
  mocks.replace.mockReset();
  mocks.getMe.mockReset();
  mocks.getCashFlowForecast.mockReset();
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({
    id: 1,
    email: "user@example.com",
    email_verified: true,
  });
  mocks.getCashFlowForecast.mockResolvedValue(forecastResult);
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
      screen.getByText(
        "180 days of transaction history (180+ days is treated as a mature baseline)."
      )
    ).toBeInTheDocument();
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
    expect(screen.getByText("$5,000.00")).toBeInTheDocument();
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
