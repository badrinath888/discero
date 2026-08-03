import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Transaction, TransactionPage } from "../lib/api";
import TransactionsPage from "./page";


const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  getAccounts: vi.fn(),
  searchTransactions: vi.fn(),
  updateTransaction: vi.fn(),
  bulkUpdateTransactionCategory: vi.fn(),
  bulkUpdateTransactionCategories: vi.fn(),
  bulkDeleteTransactions: vi.fn(),
  syncPlaidTransactions: vi.fn(),
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
  const motionOnlyProps = new Set([
    "animate",
    "exit",
    "initial",
    "layout",
    "transition",
    "variants",
    "viewport",
    "whileHover",
    "whileInView",
  ]);
  const components = new Map<
    string,
    (props: Record<string, unknown>) => ReturnType<typeof createElement>
  >();
  const motion = new Proxy(
    {},
    {
      get: (_target, tag: string) => {
        if (!components.has(tag)) {
          components.set(tag, ({ children, ...props }) => {
          const domProps = Object.fromEntries(
            Object.entries(props).filter(
              ([name]) => !motionOnlyProps.has(name)
            )
          );

          return createElement(tag, domProps, children as ReactNode);
          });
        }

        return components.get(tag);
      },
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

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();

  return {
    ...actual,
    api: {
      ...actual.api,
      getMe: mocks.getMe,
      getAccounts: mocks.getAccounts,
      searchTransactions: mocks.searchTransactions,
      updateTransaction: mocks.updateTransaction,
      bulkUpdateTransactionCategory:
        mocks.bulkUpdateTransactionCategory,
      bulkUpdateTransactionCategories:
        mocks.bulkUpdateTransactionCategories,
      bulkDeleteTransactions: mocks.bulkDeleteTransactions,
      syncPlaidTransactions: mocks.syncPlaidTransactions,
    },
    session: {
      ...actual.session,
      getUserId: mocks.getUserId,
      getToken: mocks.getToken,
      clear: mocks.clearSession,
    },
  };
});

const transactions: Transaction[] = [
  {
    id: 1,
    posted_on: "2026-08-01",
    description: "Coffee",
    merchant_name: null,
    amount_cents: -550,
    category: "Dining",
    source: "csv",
    pending: false,
    financial_account_id: null,
    account_name: null,
    institution_name: null,
  },
  {
    id: 2,
    posted_on: "2026-08-01",
    description: "Rent",
    merchant_name: null,
    amount_cents: -120_000,
    category: "Housing",
    source: "plaid",
    pending: false,
    financial_account_id: 10,
    account_name: "Checking",
    institution_name: "Test Bank",
  },
  {
    id: 3,
    posted_on: "2026-07-31",
    description: "Payroll",
    merchant_name: null,
    amount_cents: 250_000,
    category: "Income",
    source: "plaid",
    pending: false,
    financial_account_id: 10,
    account_name: "Checking",
    institution_name: "Test Bank",
  },
];

function page(items: Transaction[]): TransactionPage {
  const income = items.reduce(
    (sum, item) => sum + Math.max(0, item.amount_cents),
    0
  );
  const spending = items.reduce(
    (sum, item) => sum + Math.max(0, -item.amount_cents),
    0
  );

  return {
    items,
    total: items.length,
    page: 1,
    page_size: 20,
    total_pages: items.length > 0 ? 1 : 0,
    total_income_cents: income,
    total_spending_cents: spending,
    net_cents: income - spending,
  };
}

function withCategory(
  items: Transaction[],
  ids: number[],
  category: string
): Transaction[] {
  return items
    .filter((item) => ids.includes(item.id))
    .map((item) => ({ ...item, category }));
}

async function renderPage(items = transactions.map((item) => ({ ...item }))) {
  mocks.searchTransactions.mockResolvedValue(page(items));
  render(<TransactionsPage />);
  await screen.findByLabelText("Select Coffee");
  return items;
}

function selectTransactions(...descriptions: string[]) {
  for (const description of descriptions) {
    fireEvent.click(screen.getByLabelText(`Select ${description}`));
  }
}

async function applyBulkCategory(category: string) {
  fireEvent.change(screen.getByLabelText("Bulk category"), {
    target: { value: category },
  });

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Apply category" }));
  });
}

async function confirmBulkDeletion() {
  fireEvent.click(screen.getByRole("button", { name: "Delete selected" }));
  await act(async () => {
    fireEvent.click(
      screen.getByRole("button", { name: "Delete permanently" })
    );
  });
}

beforeEach(() => {
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({ id: 1, email: "user@example.com" });
  mocks.getAccounts.mockResolvedValue([]);
  mocks.bulkDeleteTransactions.mockResolvedValue({ deleted: 2 });
  mocks.syncPlaidTransactions.mockResolvedValue({
    added: 0,
    modified: 0,
    removed: 0,
    items_synced: 0,
    synced_at: "2026-08-03T00:00:00Z",
  });
});

describe("TransactionsPage bulk workflows", () => {
  it("applies one bulk category request and offers Undo", async () => {
    const items = await renderPage();
    mocks.bulkUpdateTransactionCategory.mockResolvedValue(
      withCategory(items, [1, 2], "Groceries")
    );

    selectTransactions("Coffee", "Rent");
    await applyBulkCategory("Groceries");

    expect(mocks.bulkUpdateTransactionCategory).toHaveBeenCalledOnce();
    expect(mocks.bulkUpdateTransactionCategory).toHaveBeenCalledWith(
      1,
      [1, 2],
      "Groceries"
    );
    await waitFor(() => {
      expect(screen.getByLabelText("Category for Coffee")).toHaveValue(
        "Groceries"
      );
      expect(screen.getByLabelText("Category for Rent")).toHaveValue(
        "Groceries"
      );
    });
    expect(screen.getByLabelText("Select Coffee")).not.toBeChecked();
    expect(screen.getByLabelText("Select Rent")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Undo" })).toBeVisible();
  });

  it("aborts stale selections, reloads, and asks for reselection", async () => {
    const loadedItems = await renderPage();
    selectTransactions("Coffee", "Rent");

    loadedItems.splice(
      loadedItems.findIndex((item) => item.id === 2),
      1
    );
    mocks.searchTransactions.mockResolvedValue(page([...loadedItems]));

    await applyBulkCategory("Groceries");

    await waitFor(() => {
      expect(mocks.bulkUpdateTransactionCategory).not.toHaveBeenCalled();
      expect(mocks.searchTransactions).toHaveBeenCalledTimes(2);
      expect(screen.queryByText("2 selected")).not.toBeInTheDocument();
      expect(screen.getByLabelText("Select Coffee")).not.toBeChecked();
      expect(
        screen.getByText(
          "Your selection was out of date. The transaction page was refreshed; please select the transactions again."
        )
      ).toBeVisible();
    });
  });

  it("restores different original categories with one Undo request", async () => {
    const items = await renderPage();
    mocks.bulkUpdateTransactionCategory.mockResolvedValue(
      withCategory(items, [1, 2], "Shopping")
    );
    mocks.bulkUpdateTransactionCategories.mockResolvedValue([
      { ...items[0], category: "Dining" },
      { ...items[1], category: "Housing" },
    ]);

    selectTransactions("Coffee", "Rent");
    await applyBulkCategory("Shopping");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    });

    expect(mocks.bulkUpdateTransactionCategories).toHaveBeenCalledOnce();
    expect(mocks.bulkUpdateTransactionCategories).toHaveBeenCalledWith(1, [
      { transaction_id: 1, category: "Dining" },
      { transaction_id: 2, category: "Housing" },
    ]);
    expect(screen.getByLabelText("Category for Coffee")).toHaveValue(
      "Dining"
    );
    expect(screen.getByLabelText("Category for Rent")).toHaveValue("Housing");
    expect(screen.getByText("Category change undone.")).toBeVisible();
  });

  it("expires category Undo without sending a restore request", async () => {
    const items = await renderPage();
    mocks.bulkUpdateTransactionCategory.mockResolvedValue(
      withCategory(items, [1, 2], "Shopping")
    );
    vi.useFakeTimers();

    selectTransactions("Coffee", "Rent");
    await applyBulkCategory("Shopping");
    expect(screen.getByRole("button", { name: "Undo" })).toBeVisible();

    await act(async () => vi.advanceTimersByTime(6_001));

    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    expect(mocks.bulkUpdateTransactionCategories).not.toHaveBeenCalled();
  });

  it("replaces an older category Undo without stale timer interference", async () => {
    const items = await renderPage();
    mocks.updateTransaction.mockImplementation(
      (_userId: number, transactionId: number, category: string) =>
        Promise.resolve({
          ...items.find((item) => item.id === transactionId)!,
          category,
        })
    );
    mocks.bulkUpdateTransactionCategories.mockResolvedValue([
      { ...items[1], category: "Housing" },
    ]);
    vi.useFakeTimers();

    await act(async () => {
      fireEvent.change(screen.getByLabelText("Category for Coffee"), {
        target: { value: "Shopping" },
      });
    });
    act(() => vi.advanceTimersByTime(3_000));
    await act(async () => {
      fireEvent.change(screen.getByLabelText("Category for Rent"), {
        target: { value: "Utilities" },
      });
    });

    act(() => vi.advanceTimersByTime(3_001));
    expect(screen.getByRole("button", { name: "Undo" })).toBeVisible();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    });
    expect(mocks.bulkUpdateTransactionCategories).toHaveBeenCalledWith(1, [
      { transaction_id: 2, category: "Housing" },
    ]);
  });

  it("restores optimistic bulk deletion when Undo is clicked", async () => {
    await renderPage();
    vi.useFakeTimers();

    selectTransactions("Coffee", "Rent");
    await confirmBulkDeletion();
    expect(screen.queryByLabelText("Select Coffee")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Select Rent")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));

    expect(screen.getByLabelText("Select Coffee")).toBeVisible();
    expect(screen.getByLabelText("Select Rent")).toBeVisible();
    expect(mocks.bulkDeleteTransactions).not.toHaveBeenCalled();
  });

  it("sends one atomic bulk delete after the Undo window", async () => {
    await renderPage();
    vi.useFakeTimers();

    selectTransactions("Coffee", "Rent");
    await confirmBulkDeletion();
    await act(async () => {
      vi.advanceTimersByTime(6_000);
    });

    expect(mocks.bulkDeleteTransactions).toHaveBeenCalledOnce();
    expect(mocks.bulkDeleteTransactions).toHaveBeenCalledWith(1, [1, 2]);
  });

  it("restores all rows and shows backend detail when deletion fails", async () => {
    await renderPage();
    mocks.bulkDeleteTransactions.mockRejectedValue(
      new Error("one or more transactions were not found (404 Not Found)")
    );
    vi.useFakeTimers();

    selectTransactions("Coffee", "Rent");
    await confirmBulkDeletion();
    await act(async () => {
      vi.advanceTimersByTime(6_000);
    });

    vi.useRealTimers();

    await waitFor(() => {
      expect(screen.getByLabelText("Select Coffee")).toBeVisible();
      expect(screen.getByLabelText("Select Rent")).toBeVisible();
      expect(
        screen.getByText(
          "one or more transactions were not found (404 Not Found)"
        )
      ).toBeVisible();
    });
  });

  it("renders backend category error detail instead of a generic message", async () => {
    await renderPage();
    mocks.bulkUpdateTransactionCategory.mockRejectedValue(
      new Error("one or more transactions were not found (404 Not Found)")
    );

    selectTransactions("Coffee");
    await applyBulkCategory("Groceries");

    await waitFor(() =>
      expect(
        screen.getByText(
          "one or more transactions were not found (404 Not Found)"
        )
      ).toBeVisible()
    );
  });

  it("keeps bulk actions compatible with Potential duplicates", async () => {
    const items = await renderPage();
    fireEvent.click(
      screen.getByRole("switch", { name: "Potential duplicates" })
    );

    await waitFor(() =>
      expect(mocks.searchTransactions).toHaveBeenLastCalledWith(
        1,
        expect.objectContaining({ duplicates_only: true })
      )
    );
    mocks.bulkUpdateTransactionCategory.mockResolvedValue(
      withCategory(items, [1, 2], "Groceries")
    );

    selectTransactions("Coffee", "Rent");
    await applyBulkCategory("Groceries");

    expect(mocks.bulkUpdateTransactionCategory).toHaveBeenCalledWith(
      1,
      [1, 2],
      "Groceries"
    );
  });
});
