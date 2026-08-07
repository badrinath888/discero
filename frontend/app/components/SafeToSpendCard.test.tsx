import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SafeToSpendResult } from "../lib/api";
import SafeToSpendCard from "./SafeToSpendCard";

const mocks = vi.hoisted(() => ({
  getSafeToSpend: vi.fn(),
}));

vi.mock("./PremiumMotion", () => ({
  AnimatedNumber: ({
    value,
    format,
  }: {
    value: number;
    format: (value: number) => string;
  }) => <span>{format(value)}</span>,
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();

  return {
    ...actual,
    api: {
      ...actual.api,
      getSafeToSpend: mocks.getSafeToSpend,
    },
  };
});

const baseResult: SafeToSpendResult = {
  as_of: "2026-08-04",
  through_date: "2026-09-03",
  horizon_days: 30,
  safe_to_spend_cents: 200_000,
  shortfall_cents: 0,
  status: "safe",
  confidence_score: 82,
  breakdown: {
    liquid_balance_cents: 500_000,
    upcoming_obligations_cents: 190_000,
    essential_spending_cents: 50_000,
    safety_reserve_cents: 100_000,
  },
  obligations: [
    {
      name: "Rent",
      amount_cents: 150_000,
      expected_date: "2026-08-09",
      category: "Housing",
      confidence_score: 90,
      source: "recurring",
    },
    {
      name: "Groceries budget",
      amount_cents: 40_000,
      expected_date: "2026-08-31",
      category: "Groceries",
      confidence_score: 75,
      source: "budget",
    },
  ],
  warnings: [],
};

async function renderCard() {
  render(<SafeToSpendCard userId={1} />);
  await screen.findByRole("button", { name: /view details/i });
  fireEvent.click(
    screen.getByRole("button", { name: /view details/i })
  );
  await screen.findByText("Rent");
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mocks.getSafeToSpend.mockReset();
  mocks.getSafeToSpend.mockResolvedValue(baseResult);
});

describe("SafeToSpendCard obligations", () => {
  it("renders recurring and budget obligations in separate labeled sections", async () => {
    await renderCard();

    const recurringSection = screen.getByTestId(
      "obligation-section-recurring"
    );
    const budgetSection = screen.getByTestId(
      "obligation-section-budget"
    );

    expect(
      within(recurringSection).getByText("Rent")
    ).toBeInTheDocument();
    expect(
      within(recurringSection).queryByText("Groceries budget")
    ).not.toBeInTheDocument();

    expect(
      within(budgetSection).getByText("Groceries budget")
    ).toBeInTheDocument();
    expect(
      within(budgetSection).queryByText("Rent")
    ).not.toBeInTheDocument();

    expect(
      within(recurringSection).getByText("Recurring obligations")
    ).toBeInTheDocument();
    expect(
      within(budgetSection).getByText("Budget obligations")
    ).toBeInTheDocument();
  });

  it("shows category, expected date, and confidence score for each obligation", async () => {
    await renderCard();

    const recurringSection = screen.getByTestId(
      "obligation-section-recurring"
    );

    expect(
      within(recurringSection).getByText("Housing")
    ).toBeInTheDocument();
    expect(
      within(recurringSection).getByText("Aug 9")
    ).toBeInTheDocument();
    expect(
      within(recurringSection).getByText(/90% confidence/)
    ).toBeInTheDocument();
  });

  it("labels budget obligations as remaining amounts, not full monthly limits", async () => {
    await renderCard();

    const budgetSection = screen.getByTestId(
      "obligation-section-budget"
    );

    expect(
      within(budgetSection).getByText(
        /remaining amount left in each budget/i
      )
    ).toBeInTheDocument();
    expect(
      within(budgetSection).getByText(/not the full monthly limit/i)
    ).toBeInTheDocument();
  });

  it("splits calculation totals correctly by source", async () => {
    await renderCard();

    expect(screen.getByText("Recurring total")).toBeInTheDocument();
    expect(
      screen.getByText("Budget total (remaining)")
    ).toBeInTheDocument();

    const recurringTile = screen
      .getByText("Recurring total")
      .closest("div") as HTMLElement;
    const budgetTile = screen
      .getByText("Budget total (remaining)")
      .closest("div") as HTMLElement;

    expect(
      within(recurringTile).getByText("-$1,500.00")
    ).toBeInTheDocument();
    expect(
      within(budgetTile).getByText("-$400.00")
    ).toBeInTheDocument();
  });

  it("shows an empty state message when a section has no obligations", async () => {
    mocks.getSafeToSpend.mockResolvedValue({
      ...baseResult,
      obligations: [baseResult.obligations[0]],
    });

    await renderCard();

    const budgetSection = screen.getByTestId(
      "obligation-section-budget"
    );

    expect(
      within(budgetSection).getByText(
        "No remaining budget obligations for this period."
      )
    ).toBeInTheDocument();

    const recurringSection = screen.getByTestId(
      "obligation-section-recurring"
    );

    expect(
      within(recurringSection).getByText("Rent")
    ).toBeInTheDocument();
  });

  it("still renders status and warnings", async () => {
    mocks.getSafeToSpend.mockResolvedValue({
      ...baseResult,
      status: "limited",
      warnings: ["No active liquid accounts were found."],
    });

    await renderCard();

    expect(screen.getByText("Limited")).toBeInTheDocument();
    expect(
      screen.getByText("No active liquid accounts were found.", {
        exact: false,
      })
    ).toBeInTheDocument();
  });

  it("recalculates with the currently entered inputs when the button is clicked", async () => {
    render(<SafeToSpendCard userId={1} />);
    await screen.findByRole("button", { name: /view details/i });

    fireEvent.change(screen.getByLabelText(/safety reserve/i), {
      target: { value: "250" },
    });
    fireEvent.change(screen.getByLabelText(/essential spending/i), {
      target: { value: "75" },
    });
    fireEvent.change(screen.getByLabelText(/horizon days/i), {
      target: { value: "45" },
    });

    fireEvent.click(
      screen.getByRole("button", { name: /recalculate/i })
    );

    await waitFor(() =>
      expect(mocks.getSafeToSpend).toHaveBeenLastCalledWith(1, {
        safety_reserve_cents: 25_000,
        essential_spending_cents: 7_500,
        horizon_days: 45,
      })
    );
  });

  it("debounces automatic recalculation while typing instead of firing a request per keystroke", async () => {
    render(<SafeToSpendCard userId={1} />);
    await screen.findByRole("button", { name: /view details/i });

    const initialCalls = mocks.getSafeToSpend.mock.calls.length;
    const reserveInput = screen.getByLabelText(/safety reserve/i);

    fireEvent.change(reserveInput, { target: { value: "1" } });
    fireEvent.change(reserveInput, { target: { value: "12" } });
    fireEvent.change(reserveInput, { target: { value: "123" } });

    // No new request should have fired yet from the keystrokes alone.
    expect(mocks.getSafeToSpend.mock.calls.length).toBe(initialCalls);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(mocks.getSafeToSpend.mock.calls.length).toBe(
      initialCalls + 1
    );
    expect(mocks.getSafeToSpend).toHaveBeenLastCalledWith(1, {
      safety_reserve_cents: 12_300,
      essential_spending_cents: 0,
      horizon_days: 30,
    });
  });
});
