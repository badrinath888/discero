import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FinancialAccount, Transaction } from "../lib/api";
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
  sync_available: true,
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

  it("shows an account's recent transactions once expanded", async () => {
    const transaction: Transaction = {
      id: 1,
      posted_on: "2026-08-01",
      description: "Coffee shop",
      merchant_name: "Coffee Shop",
      amount_cents: -450,
      category: "Dining",
      source: "plaid",
      pending: false,
      financial_account_id: account.id,
      account_name: account.name,
      institution_name: account.institution_name,
    };

    mocks.getAccounts.mockResolvedValue([account]);
    mocks.getTransactions.mockResolvedValue([transaction]);
    render(<AccountsPage />);
    await screen.findByText("Everyday Checking");

    expect(screen.queryByText("Coffee Shop")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Everyday Checking"));

    expect(await screen.findByText("Coffee Shop")).toBeInTheDocument();
  });
});

describe("auth initialization race", () => {
  beforeEach(() => {
    mocks.getUserId.mockReturnValue(1);
    mocks.getToken.mockReturnValue("token");
    mocks.getAccounts.mockResolvedValue([account]);
    mocks.getTransactions.mockResolvedValue([]);
  });

  it("does not clear a still-valid session when the init getMe request is aborted", async () => {
    // Fast Dashboard -> Accounts navigation can abort the in-flight
    // /users/me. api.ts only clears the local session on a real 401, so
    // the token is still present here.
    mocks.getMe.mockRejectedValue(new Error("net::ERR_ABORTED"));

    render(<AccountsPage />);

    expect(await screen.findByText("net::ERR_ABORTED")).toBeInTheDocument();
    expect(mocks.clearSession).not.toHaveBeenCalled();
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it("still redirects when the failure was a genuine 401 (api.ts already cleared the session)", async () => {
    mocks.getMe.mockRejectedValue(new Error("Unauthorized"));
    // api.ts clears the session on a true 401 -> token is now gone.
    mocks.getToken.mockReturnValue(null);

    render(<AccountsPage />);

    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/"));
  });

  it("still clears and redirects on an explicit user-id mismatch", async () => {
    mocks.getMe.mockResolvedValue({ id: 999, email: "other@example.com" });

    render(<AccountsPage />);

    await waitFor(() => expect(mocks.clearSession).toHaveBeenCalled());
    expect(mocks.replace).toHaveBeenCalledWith("/");
  });
});
