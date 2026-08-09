import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Recommendation } from "../lib/api";
import RecommendationsPage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  push: vi.fn(),
  getMe: vi.fn(),
  getRecommendations: vi.fn(),
  getUserId: vi.fn(),
  getToken: vi.fn(),
  clearSession: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace, push: mocks.push }),
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

vi.mock("../components/AppSidebar", () => ({
  default: () => null,
}));

vi.mock("../components/PremiumMotion", () => ({
  PageReveal: ({ children }: { children: ReactNode }) => children,
  Reveal: ({ children }: { children: ReactNode }) => children,
  Stagger: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();

  return {
    ...actual,
    api: {
      ...actual.api,
      getMe: mocks.getMe,
      getRecommendations: mocks.getRecommendations,
    },
    session: {
      ...actual.session,
      getUserId: mocks.getUserId,
      getToken: mocks.getToken,
      clear: mocks.clearSession,
    },
  };
});

const goalRecommendation: Recommendation = {
  id: "goal-conflict",
  category: "goals",
  severity: "critical",
  priority: 1,
  title: "Close your $50.00/month goal gap",
  summary: "Your goal requires more than your current capacity supports.",
  why: "Your goals require $150.00/month but your current capacity is $100.00/month.",
  recommended_action: "Increase monthly savings by $50.00.",
  impact: "$50.00/month shortfall",
  confidence: 90,
  source_signals: [
    { label: "Monthly capacity", value_display: "$100.00" },
    { label: "Required monthly", value_display: "$150.00" },
  ],
  deep_link: "/goals",
  evaluated_at: "2026-08-08",
};

const positiveRecommendation: Recommendation = {
  id: "spending-trend-down",
  category: "spending",
  severity: "positive",
  priority: 2,
  title: "Your spending decreased this month",
  summary: "Spending is down 12% versus last month.",
  why: "You spent $120.00 less than last month.",
  recommended_action: "Keep up the trend.",
  impact: "$120.00 less spent",
  confidence: null,
  source_signals: [],
  deep_link: "/insights",
  evaluated_at: "2026-08-08",
};

beforeEach(() => {
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({
    id: 1,
    email: "user@example.com",
    email_verified: true,
  });
  mocks.getRecommendations.mockReset();
  mocks.push.mockReset();
});

describe("Recommendations page", () => {
  it("renders ranked recommendation cards with why, impact, and confidence", async () => {
    mocks.getRecommendations.mockResolvedValue({
      as_of: "2026-08-08",
      recommendations: [goalRecommendation, positiveRecommendation],
    });

    render(<RecommendationsPage />);

    expect(
      await screen.findByText("Close your $50.00/month goal gap")
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Your goals require $150.00/month but your current capacity is $100.00/month."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("$50.00/month shortfall")).toBeInTheDocument();
    expect(screen.getByText("90% confidence")).toBeInTheDocument();
    expect(screen.getByText("$100.00")).toBeInTheDocument();

    expect(
      screen.getByText("Your spending decreased this month")
    ).toBeInTheDocument();

    const cards = screen.getAllByTestId("recommendation-card");
    expect(cards).toHaveLength(2);
  });

  it("shows a positive empty state when there are no recommendations", async () => {
    mocks.getRecommendations.mockResolvedValue({
      as_of: "2026-08-08",
      recommendations: [],
    });

    render(<RecommendationsPage />);

    expect(
      await screen.findByTestId("recommendations-empty")
    ).toBeInTheDocument();
    expect(screen.getByText("You’re all caught up")).toBeInTheDocument();
  });

  it("shows an error state when the request fails", async () => {
    mocks.getRecommendations.mockRejectedValue(new Error("network error"));

    render(<RecommendationsPage />);

    expect(
      await screen.findByText(
        "Couldn't load your recommendations just now. Please try again."
      )
    ).toBeInTheDocument();
  });

  it("navigates to the deep link when Review is clicked", async () => {
    mocks.getRecommendations.mockResolvedValue({
      as_of: "2026-08-08",
      recommendations: [goalRecommendation],
    });

    render(<RecommendationsPage />);

    const reviewButton = await screen.findByRole("button", {
      name: /review/i,
    });
    reviewButton.click();

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/goals"));
  });

  it("redirects to login when there is no session", async () => {
    mocks.getUserId.mockReturnValue(null);
    mocks.getToken.mockReturnValue(null);

    render(<RecommendationsPage />);

    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/"));
    expect(mocks.getRecommendations).not.toHaveBeenCalled();
  });
});
