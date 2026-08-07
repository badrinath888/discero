import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FinancialAccount } from "../lib/api";
import AccountsPage from "./page";


const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  getAccounts: vi.fn(),
  getTransactions: vi.fn(),
  syncPlaidTransactions: vi.fn(),
  disconnectPlaidItem: vi.fn(),
  getUserId: vi.fn(),
  getToken: vi.fn(),
  clearSession: vi.fn(),
}));
const routerMock = { replace: mocks.replace };

vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
}));

vi.mock("framer-motion", async () => {
  const { createElement } = await import("react");
  const ignored = new Set([
    "animate", "exit", "initial", "layout", "transition", "variants",
    "viewport", "whileHover", "whileInView",
  ]);
  const motion = new Proxy({}, {
    get: (_target, tag: string) =>
      ({ children, ...props }: Record<string, unknown>) =>
        createElement(
          tag,
          Object.fromEntries(
            Object.entries(props).filter(([name]) => !ignored.has(name))
          ),
          children as ReactNode
        ),
  });

  return {
    AnimatePresence: ({ children }: { children: ReactNode }) => children,
    motion,
    useReducedMotion: () => true,
  };
});

vi.mock("../components/AppSidebar", () => ({ default: () => null }));
vi.mock("../components/ConnectBankButton", () => ({
  default: () => <button type="button">Connect bank</button>,
}));
vi.mock("../components/PremiumMotion", () => ({
  PageReveal: ({ children }: { children: ReactNode }) => children,
  Reveal: ({ children }: { children: ReactNode }) => children,
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
      getMe: mocks.getMe,
      getAccounts: mocks.getAccounts,
      getTransactions: mocks.getTransactions,
      syncPlaidTransactions: mocks.syncPlaidTransactions,
      disconnectPlaidItem: mocks.disconnectPlaidItem,
    },
    session: {
      ...actual.session,
      getUserId: mocks.getUserId,
      getToken: mocks.getToken,
      clear: mocks.clearSession,
    },
  };
});

const account: FinancialAccount = {
  id: 10,
  plaid_item_id: 5,
  institution_name: "Test Bank",
  name: "Everyday Checking",
  official_name: null,
  account_type: "depository",
  account_subtype: "checking",
  mask: "1234",
  current_balance_cents: 125_000,
  available_balance_cents: 120_000,
  currency: "USD",
  connection_status: "active",
  sync_status: "succeeded",
  sync_error: null,
  last_sync_attempted_at: "2026-08-03T15:31:00Z",
  last_synced_at: "2026-08-03T15:30:00Z",
};

async function renderPage(item: FinancialAccount = account) {
  mocks.getAccounts.mockResolvedValue([item]);
  mocks.getTransactions.mockResolvedValue([]);
  render(<AccountsPage />);
  await screen.findByText("Everyday Checking");
}

describe("Accounts Plaid lifecycle", () => {
  beforeEach(() => {
    mocks.getUserId.mockReturnValue(1);
    mocks.getToken.mockReturnValue("token");
    mocks.getMe.mockResolvedValue({ id: 1, email: "user@example.com" });
    mocks.disconnectPlaidItem.mockResolvedValue(undefined);
  });

  it("syncs now and refreshes accounts and transactions", async () => {
    mocks.syncPlaidTransactions.mockResolvedValue({
      added: 2, modified: 1, removed: 1, items_synced: 1,
      synced_at: "2026-08-03T16:00:00Z",
    });
    await renderPage();
    const accountLoads = mocks.getAccounts.mock.calls.length;
    const transactionLoads = mocks.getTransactions.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));

    expect(await screen.findByText(/Sync complete: 2 added/)).toBeVisible();
    expect(mocks.syncPlaidTransactions).toHaveBeenCalledWith(1);
    expect(mocks.getAccounts).toHaveBeenCalledTimes(accountLoads + 1);
    expect(mocks.getTransactions).toHaveBeenCalledTimes(transactionLoads + 1);
  });

  it("shows sync loading state", async () => {
    let resolveSync!: (value: unknown) => void;
    mocks.syncPlaidTransactions.mockReturnValue(
      new Promise((resolve) => { resolveSync = resolve; })
    );
    await renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
    expect(screen.getByRole("button", { name: "Syncing..." })).toBeDisabled();

    resolveSync({ added: 0, modified: 0, removed: 0, items_synced: 1 });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Sync now" })).toBeEnabled()
    );
  });

  it("shows a sync failure and refreshes persisted status", async () => {
    mocks.syncPlaidTransactions.mockRejectedValue(new Error("Sync unavailable"));
    await renderPage({
      ...account,
      sync_status: "failed",
      sync_error: "Plaid synchronization failed",
    });
    const accountLoads = mocks.getAccounts.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "Sync now" }));

    expect(await screen.findByText("Sync unavailable")).toBeVisible();
    expect(screen.getByText("Plaid synchronization failed")).toBeVisible();
    expect(mocks.getAccounts).toHaveBeenCalledTimes(accountLoads + 1);
  });

  it("renders the last successful sync", async () => {
    await renderPage();
    expect(screen.getByText(/Last successful sync: Aug 3, 2026/)).toBeVisible();
  });

  it("requires confirmation before disconnecting", async () => {
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Everyday Checking/ }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Disconnect institution" })
    );

    expect(screen.getByRole("dialog")).toHaveTextContent("Disconnect Test Bank?");
    expect(mocks.disconnectPlaidItem).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("dialog").querySelector("button:last-child")!
    );
    await waitFor(() =>
      expect(mocks.disconnectPlaidItem).toHaveBeenCalledWith(1, 5)
    );
  });

  it("renders reconnect-required state", async () => {
    await renderPage({
      ...account,
      connection_status: "reconnect_required",
      sync_status: "failed",
      sync_error: "Reconnect required",
    });

    expect(screen.getByText(/Reconnect required/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect bank" })).toBeVisible();
  });

  it("does not flash zero-value portfolio numbers while still loading", async () => {
    let resolveAccounts!: (value: FinancialAccount[]) => void;
    mocks.getAccounts.mockReturnValue(
      new Promise((resolve) => {
        resolveAccounts = resolve;
      })
    );
    mocks.getTransactions.mockResolvedValue([]);

    render(<AccountsPage />);

    await screen.findByText("Connected network");
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
    expect(
      screen.queryByText("No bank accounts connected")
    ).not.toBeInTheDocument();

    resolveAccounts([account]);

    expect(await screen.findByText("Everyday Checking")).toBeInTheDocument();
  });

  it("shows a retryable error instead of a misleading empty state when the load fails", async () => {
    mocks.getAccounts.mockRejectedValueOnce(new Error("network down"));
    mocks.getTransactions.mockResolvedValue([]);

    render(<AccountsPage />);

    expect(await screen.findByText("network down")).toBeInTheDocument();
    expect(
      screen.queryByText("No bank accounts connected")
    ).not.toBeInTheDocument();
  });
});
