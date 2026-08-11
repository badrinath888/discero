import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  RecurringIntelligence,
  RecurringItem,
  RecurringPayment,
  SpendingAnomalies,
} from "../lib/api";
import RecurringPage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  getRecurringPayments: vi.fn(),
  getRecurringItems: vi.fn(),
  createRecurringItem: vi.fn(),
  getRecurringIntelligence: vi.fn(),
  getSpendingAnomalies: vi.fn(),
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
      getRecurringPayments: mocks.getRecurringPayments,
      getRecurringItems: mocks.getRecurringItems,
      createRecurringItem: mocks.createRecurringItem,
      getRecurringIntelligence: mocks.getRecurringIntelligence,
      getSpendingAnomalies: mocks.getSpendingAnomalies,
    },
    session: {
      ...actual.session,
      getUserId: mocks.getUserId,
      getToken: mocks.getToken,
      clear: mocks.clearSession,
    },
  };
});

const detectedPayment: RecurringPayment = {
  merchant: "Streamflix",
  amount_cents: 1_599,
  frequency: "Monthly",
  last_payment: "2026-07-01",
  next_payment: "2026-08-01",
  days_until_due: 5,
  occurrences: 3,
  confidence_score: 90,
  price_change_percent: 0,
  price_change_warning: false,
};

const createdItem: RecurringItem = {
  id: 1,
  merchant: "Streamflix",
  normalized_merchant: "STREAMFLIX",
  category: "Subscriptions",
  amount_cents: 1_599,
  frequency: "Monthly",
  last_payment: "2026-07-01",
  next_payment: "2026-08-01",
  status: "active",
  confidence_score: 90,
  price_change_percent: 0,
  price_change_warning: false,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const emptyIntelligence: RecurringIntelligence = {
  as_of: "2026-08-09",
  burden: {
    monthly_recurring_cents: 0,
    active_recurring_count: 0,
    percent_of_income: null,
    percent_of_spending: null,
    next_30_days_cents: 0,
    next_60_days_cents: 0,
    next_90_days_cents: 0,
  },
  upcoming: [],
  amount_changes: [],
  new_recurring: [],
  possibly_missing: [],
  possible_duplicates: [],
  data_quality_note: "No active recurring items were found.",
};

const emptyAnomalies: SpendingAnomalies = {
  as_of: "2026-08-09",
  lookback_months: 6,
  anomalies: [],
  data_quality_note: null,
};

beforeEach(() => {
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({
    id: 1,
    email: "user@example.com",
    email_verified: true,
  });
  mocks.getRecurringPayments.mockResolvedValue([detectedPayment]);
  mocks.getRecurringItems.mockResolvedValue([]);
  mocks.createRecurringItem.mockResolvedValue(createdItem);
  mocks.getRecurringIntelligence.mockResolvedValue(emptyIntelligence);
  mocks.getSpendingAnomalies.mockResolvedValue(emptyAnomalies);
});

describe("recurring confirm-detected performance", () => {
  it("adds the confirmed item locally instead of reloading both lists", async () => {
    render(<RecurringPage />);

    await screen.findByText("Streamflix");
    expect(mocks.getRecurringPayments).toHaveBeenCalledTimes(1);
    expect(mocks.getRecurringItems).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() =>
      expect(mocks.createRecurringItem).toHaveBeenCalledOnce()
    );

    // The detected suggestion should disappear once it's confirmed
    // as a managed item, without a fresh reload of either list.
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Confirm" })
      ).not.toBeInTheDocument()
    );
    expect(mocks.getRecurringPayments).toHaveBeenCalledTimes(1);
    expect(mocks.getRecurringItems).toHaveBeenCalledTimes(1);
  });
});

const populatedIntelligence: RecurringIntelligence = {
  as_of: "2026-08-09",
  burden: {
    monthly_recurring_cents: 18_00,
    active_recurring_count: 1,
    percent_of_income: 10,
    percent_of_spending: null,
    next_30_days_cents: 18_00,
    next_60_days_cents: 36_00,
    next_90_days_cents: 54_00,
  },
  upcoming: [
    {
      recurring_item_id: 1,
      merchant: "Netflix",
      category: "Subscriptions",
      amount_cents: 18_00,
      frequency: "Monthly",
      next_payment: "2026-08-15",
      days_until_due: 6,
    },
  ],
  amount_changes: [
    {
      recurring_item_id: 1,
      merchant: "Netflix",
      category: "Subscriptions",
      status: "increased",
      current_amount_cents: 18_00,
      baseline_amount_cents: 15_00,
      change_cents: 300,
      change_percent: 20,
      occurrences_considered: 4,
      last_payment: "2026-07-15",
    },
  ],
  new_recurring: [
    {
      recurring_item_id: 2,
      merchant: "Widget Co",
      category: "Bills",
      amount_cents: 20_00,
      frequency: "Monthly",
      occurrences_seen: 1,
      last_payment: "2026-07-20",
    },
  ],
  possibly_missing: [
    {
      recurring_item_id: 3,
      merchant: "Gym",
      category: "Bills",
      amount_cents: 40_00,
      frequency: "Monthly",
      expected_date: "2026-07-15",
      days_overdue: 20,
      message:
        "FinSight has not seen the expected Gym payment yet -- it was due 2026-07-15.",
    },
  ],
  possible_duplicates: [
    {
      recurring_item_id_a: 4,
      recurring_item_id_b: 5,
      merchant_a: "Netflix",
      merchant_b: "Netflix.com",
      amount_a_cents: 18_00,
      amount_b_cents: 18_50,
      frequency: "Monthly",
      reason:
        "Netflix and Netflix.com have very similar names, similar amounts, and the same monthly cadence -- this may be the same subscription tracked twice.",
    },
  ],
  data_quality_note: null,
};

const populatedAnomalies: SpendingAnomalies = {
  as_of: "2026-08-09",
  lookback_months: 6,
  anomalies: [
    {
      id: "merchant_unusual_spend:1",
      type: "merchant_unusual_spend",
      severity: "high",
      title: "Unusual charge at Whole Foods",
      merchant: "Whole Foods",
      category: "Groceries",
      transaction_id: 1,
      date: "2026-08-05",
      current_amount_cents: 400_00,
      baseline_amount_cents: 50_00,
      difference_cents: 350_00,
      percent_difference: 700,
      reason:
        "$400.00 is well above the typical $50.00 charge from this merchant, based on 5 prior charges.",
      confidence: "high",
    },
  ],
  data_quality_note: null,
};

describe("recurring intelligence and spending anomalies", () => {
  it("renders the recurring intelligence summary from real data", async () => {
    mocks.getRecurringIntelligence.mockResolvedValue(populatedIntelligence);

    render(<RecurringPage />);

    await screen.findByText("What's changed");
    expect(await screen.findAllByText("-$18.00")).not.toHaveLength(0);
    expect(screen.getByText("10% of average income")).toBeInTheDocument();
  });

  it("renders signal cards for increased, new, missing, and duplicate items", async () => {
    mocks.getRecurringIntelligence.mockResolvedValue(populatedIntelligence);

    render(<RecurringPage />);

    await screen.findByText("What's changed");

    expect(screen.getAllByText("Netflix").length).toBeGreaterThan(0);
    expect(screen.getByText(/up 20% from/)).toBeInTheDocument();
    expect(screen.getByText("Widget Co")).toBeInTheDocument();
    expect(screen.getByText("Gym")).toBeInTheDocument();
    expect(screen.getByText("20 days past expected")).toBeInTheDocument();
    expect(
      screen.getByText("Netflix & Netflix.com")
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Discero has not seen these expected payments yet -- this does not necessarily mean a subscription was cancelled."
      )
    ).toBeInTheDocument();
  });

  it("renders the spending anomaly list with severity and reason", async () => {
    mocks.getSpendingAnomalies.mockResolvedValue(populatedAnomalies);

    render(<RecurringPage />);

    await screen.findByText("Unusual charge at Whole Foods");
    expect(screen.getByText("High")).toBeInTheDocument();
    expect(screen.getByText("Unusual merchant charge")).toBeInTheDocument();
    expect(
      screen.getByText(
        "$400.00 is well above the typical $50.00 charge from this merchant, based on 5 prior charges."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("-$400.00")).toBeInTheDocument();
  });

  it("shows the occurrence count for grouped repeated charges", async () => {
    mocks.getSpendingAnomalies.mockResolvedValue({
      as_of: "2026-08-09",
      lookback_months: 6,
      anomalies: [
        {
          id: "repeated_charge:10:11:12:13",
          type: "repeated_charge",
          severity: "high",
          title: "Possible duplicate charge at Fun",
          merchant: "Fun",
          category: "Entertainment",
          transaction_id: 13,
          transaction_ids: [10, 11, 12, 13],
          occurrence_count: 4,
          date: "2026-08-07",
          current_amount_cents: 8_940,
          baseline_amount_cents: 8_940,
          difference_cents: 0,
          percent_difference: 0,
          reason:
            "4 similar charges from Fun were posted within 0 days, ranging from $89.40 to $89.40 between 2026-08-07 and 2026-08-07.",
          confidence: "high",
        },
      ],
      data_quality_note: null,
    });

    render(<RecurringPage />);

    expect(
      await screen.findByText("Possible duplicate charge at Fun")
    ).toBeInTheDocument();

    expect(screen.getByText("-$89.40 × 4")).toBeInTheDocument();

    expect(
      screen.queryByText("vs -$89.40 usual")
    ).not.toBeInTheDocument();
  });

  it("shows a positive, non-alarming empty state when nothing unusual is found", async () => {
    render(<RecurringPage />);

    const emptyState = await screen.findByText(
      "No unusual spending patterns detected from the available data."
    );
    expect(emptyState).toBeInTheDocument();

    const anomalySection = emptyState.closest("section");
    expect(anomalySection?.textContent?.toLowerCase()).not.toContain(
      "danger"
    );
    expect(anomalySection?.textContent?.toLowerCase()).not.toContain(
      "critical"
    );
  });

  it("shows a neutral message when no recurring items are active yet", async () => {
    render(<RecurringPage />);

    expect(
      await screen.findByText("No active recurring items were found.")
    ).toBeInTheDocument();
  });

  it("recovers from an insights load failure via retry", async () => {
    mocks.getRecurringIntelligence.mockRejectedValueOnce(
      new Error("network down")
    );
    mocks.getSpendingAnomalies.mockRejectedValueOnce(
      new Error("network down")
    );

    render(<RecurringPage />);

    await screen.findAllByText("Something went wrong");

    mocks.getRecurringIntelligence.mockResolvedValue(emptyIntelligence);
    mocks.getSpendingAnomalies.mockResolvedValue(emptyAnomalies);

    const [retryButton] = screen.getAllByRole("button", {
      name: "Try again",
    });
    fireEvent.click(retryButton);

    await screen.findByText(
      "No unusual spending patterns detected from the available data."
    );
  });
});
