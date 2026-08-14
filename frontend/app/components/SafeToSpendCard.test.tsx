import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SafeToSpendResult } from "../lib/api";
import SafeToSpendCard from "./SafeToSpendCard";

const mocks = vi.hoisted(() => ({ getSafeToSpend: vi.fn() }));

vi.mock("framer-motion", async () => {
  const { createElement } = await import("react");
  const ignored = new Set(["initial", "animate", "exit", "transition"]);
  return {
    AnimatePresence: ({ children }: { children: ReactNode }) => children,
    useReducedMotion: () => true,
    motion: new Proxy({}, {
      get: (_target, tag: string) => ({ children, ...props }: Record<string, unknown>) =>
        createElement(tag, Object.fromEntries(Object.entries(props).filter(([key]) => !ignored.has(key))), children as ReactNode),
    }),
  };
});

vi.mock("./PremiumMotion", () => ({
  AnimatedNumber: ({ value, format }: { value: number; format: (value: number) => string }) => <span>{format(value)}</span>,
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return { ...actual, api: { ...actual.api, getSafeToSpend: mocks.getSafeToSpend } };
});

const result: SafeToSpendResult = {
  as_of: "2026-08-11",
  through_date: "2026-09-10",
  horizon_days: 30,
  safe_to_spend_cents: 2_740_666,
  shortfall_cents: 0,
  status: "safe",
  confidence_score: 94,
  confidence_level: "high",
  confidence_drivers: [
    { code: "LIQUID_BALANCE_FOUND", direction: "positive", message: "A liquid balance was found across your active accounts." },
  ],
  breakdown: {
    liquid_balance_cents: 3_000_000,
    projected_income_cents: 0,
    upcoming_obligations_cents: 259_334,
    essential_spending_cents: 0,
    goal_reserve_cents: 0,
    safety_reserve_cents: 0,
  },
  obligations: [],
  explanation: [],
  warnings: [],
};

const shortfallResult: SafeToSpendResult = {
  ...result,
  safe_to_spend_cents: 0,
  shortfall_cents: 34_000,
  status: "negative",
  confidence_level: "low",
  breakdown: {
    ...result.breakdown,
    upcoming_obligations_cents: 3_034_000,
  },
};

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mocks.getSafeToSpend.mockReset();
  mocks.getSafeToSpend.mockResolvedValue(result);
});

describe("SafeToSpendCard", () => {
  it("shows the primary signal and keeps assumptions collapsed by default", async () => {
    render(<SafeToSpendCard userId={1} />);

    expect(await screen.findByText("$27,406.66")).toBeInTheDocument();
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("Through Sep 10 · High confidence (94%)")).toBeInTheDocument();
    expect(screen.queryByLabelText("Safety reserve")).not.toBeInTheDocument();
    expect(screen.queryByText("Liquid balance")).not.toBeInTheDocument();
  });

  it("reveals assumptions and recalculates with entered values", async () => {
    render(<SafeToSpendCard userId={1} />);
    await screen.findByText("$27,406.66");
    fireEvent.click(screen.getByRole("button", { name: "Adjust assumptions" }));

    fireEvent.change(screen.getByLabelText("Safety reserve"), { target: { value: "250" } });
    fireEvent.change(screen.getByLabelText("Essential spending"), { target: { value: "75" } });
    fireEvent.change(screen.getByLabelText(/Horizon/), { target: { value: "45" } });
    fireEvent.click(screen.getByRole("button", { name: "Update" }));

    await waitFor(() => expect(mocks.getSafeToSpend).toHaveBeenLastCalledWith(1, {
      safety_reserve_cents: 25_000,
      essential_spending_cents: 7_500,
      horizon_days: 45,
      include_projected_income: true,
      include_goal_reserve: true,
    }));
  });

  it("debounces automatic recalculation while editing assumptions", async () => {
    render(<SafeToSpendCard userId={1} />);
    await screen.findByText("$27,406.66");
    fireEvent.click(screen.getByRole("button", { name: "Adjust assumptions" }));
    const initialCalls = mocks.getSafeToSpend.mock.calls.length;

    fireEvent.change(screen.getByLabelText("Safety reserve"), { target: { value: "123" } });
    expect(mocks.getSafeToSpend).toHaveBeenCalledTimes(initialCalls);
    await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    expect(mocks.getSafeToSpend).toHaveBeenCalledTimes(initialCalls + 1);
  });

  it("reveals the calculation breakdown and confidence drivers", async () => {
    render(<SafeToSpendCard userId={1} />);
    await screen.findByText("$27,406.66");
    fireEvent.click(screen.getByRole("button", { name: "Why this amount?" }));

    expect(screen.getByText("Liquid balance")).toBeInTheDocument();
    expect(screen.getByText("$30,000.00")).toBeInTheDocument();
    expect(screen.getByText("Upcoming obligations")).toBeInTheDocument();
    expect(screen.getByText("− $2,593.34")).toBeInTheDocument();
    expect(screen.getByText("Confidence drivers")).toBeInTheDocument();
    expect(screen.getByText("A liquid balance was found across your active accounts.")).toBeInTheDocument();
    expect(screen.queryByText("Goal commitments")).not.toBeInTheDocument();
  });

  it("shows the shortfall state with restrained risk styling", async () => {
    mocks.getSafeToSpend.mockResolvedValue(shortfallResult);
    render(<SafeToSpendCard userId={1} />);

    expect(await screen.findByText("$0.00")).toBeInTheDocument();
    expect(screen.getByText("At risk")).toBeInTheDocument();
    expect(
      screen.getByText("You are projected to be short by $340.00 this period, so nothing is available to spend right now.")
    ).toBeInTheDocument();
  });
});
