"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import {
  EmptyState,
  PageError,
  PageLoading,
  PageSuccess,
} from "../components/PageFeedback";
import { api, formatCents, session, Transaction } from "../lib/api";

const CATEGORIES = [
  "All",
  "Dining",
  "Groceries",
  "Health",
  "Housing",
  "Income",
  "Shopping",
  "Subscriptions",
  "Transport",
  "Utilities",
  "Uncategorized",
];

const PAGE_SIZE = 10;

export default function TransactionsPage() {
  const router = useRouter();

  const [userId, setUserId] = useState<number | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");
  const [source, setSource] = useState("All");
  const [accountId, setAccountId] = useState("All");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [page, setPage] = useState(1);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadTransactions() {
      const id = session.getUserId();
      const token = session.getToken();

      if (!id || !token) {
        session.clear();
        router.replace("/");
        return;
      }

      try {
        const user = await api.getMe();

        if (user.id !== id) {
          session.clear();
          router.replace("/");
          return;
        }

        const data = await api.getTransactions(id);

        setUserId(id);
        setTransactions(data);
      } catch (err) {
        if (!session.getToken()) {
          router.replace("/");
          return;
        }

        setError(
          err instanceof Error
            ? err.message
            : "Unable to load transactions"
        );
      } finally {
        setLoading(false);
      }
    }

    void loadTransactions();
  }, [router]);

  const accountOptions = useMemo(() => {
    const accounts = new Map<number, string>();

    for (const transaction of transactions) {
      if (
        transaction.financial_account_id &&
        transaction.account_name
      ) {
        const label = transaction.institution_name
          ? `${transaction.institution_name} • ${transaction.account_name}`
          : transaction.account_name;

        accounts.set(transaction.financial_account_id, label);
      }
    }

    return [...accounts.entries()].sort((a, b) =>
      a[1].localeCompare(b[1])
    );
  }, [transactions]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();

    return transactions.filter((transaction) => {
      const matchesSearch =
        transaction.description.toLowerCase().includes(query) ||
        transaction.merchant_name?.toLowerCase().includes(query) ||
        transaction.category.toLowerCase().includes(query) ||
        transaction.account_name?.toLowerCase().includes(query) ||
        transaction.institution_name?.toLowerCase().includes(query);

      const matchesCategory =
        category === "All" || transaction.category === category;

      const matchesSource =
        source === "All" ||
        (source === "Pending"
          ? transaction.pending
          : transaction.source === source.toLowerCase());

      const matchesAccount =
        accountId === "All" ||
        transaction.financial_account_id === Number(accountId);

      const matchesFrom =
        !fromDate || transaction.posted_on >= fromDate;

      const matchesTo =
        !toDate || transaction.posted_on <= toDate;

      return (
        matchesSearch &&
        matchesCategory &&
        matchesSource &&
        matchesAccount &&
        matchesFrom &&
        matchesTo
      );
    });
  }, [
    transactions,
    search,
    category,
    source,
    accountId,
    fromDate,
    toDate,
  ]);

  const totalPages = Math.max(
    1,
    Math.ceil(filtered.length / PAGE_SIZE)
  );

  const visibleTransactions = filtered.slice(
    (page - 1) * PAGE_SIZE,
    page * PAGE_SIZE
  );

  const totalIncome = filtered
    .filter(({ amount_cents }) => amount_cents > 0)
    .reduce((total, item) => total + item.amount_cents, 0);

  const totalSpending = filtered
    .filter(({ amount_cents }) => amount_cents < 0)
    .reduce(
      (total, item) => total + Math.abs(item.amount_cents),
      0
    );

  const net = totalIncome - totalSpending;

  async function syncTransactions() {
    if (!userId) return;

    setSyncing(true);
    setError("");
    setMessage("");

    try {
      const result = await api.syncPlaidTransactions(userId);
      const refreshed = await api.getTransactions(userId);

      setTransactions(refreshed);
      setPage(1);
      setMessage(
        `Sync complete: ${result.added} added, ` +
          `${result.modified} updated, ` +
          `${result.removed} removed.`
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to synchronize transactions"
      );
    } finally {
      setSyncing(false);
    }
  }

  async function updateCategory(
    transactionId: number,
    nextCategory: string
  ) {
    if (!userId) return;

    setBusyId(transactionId);
    setError("");

    try {
      const updated = await api.updateTransaction(
        userId,
        transactionId,
        nextCategory
      );

      setTransactions((current) =>
        current.map((transaction) =>
          transaction.id === updated.id ? updated : transaction
        )
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to update category"
      );
    } finally {
      setBusyId(null);
    }
  }

  async function deleteTransaction(transaction: Transaction) {
    if (
      !userId ||
      !window.confirm(`Delete "${transaction.description}"?`)
    ) {
      return;
    }

    setBusyId(transaction.id);
    setError("");

    try {
      await api.deleteTransaction(userId, transaction.id);

      setTransactions((current) =>
        current.filter(({ id }) => id !== transaction.id)
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to delete transaction"
      );
    } finally {
      setBusyId(null);
    }
  }

  function clearFilters() {
    setSearch("");
    setCategory("All");
    setSource("All");
    setAccountId("All");
    setFromDate("");
    setToDate("");
    setPage(1);
  }

  return (
    <main className="min-h-screen bg-[#f5f1e8] text-[#14241e]">
      <AppSidebar />

      <div className="px-5 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-10">
        <div className="mx-auto max-w-7xl">
          <header className="grid gap-6 xl:grid-cols-[1fr_auto] xl:items-end">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
                Money activity
              </p>

              <h1 className="mt-3 max-w-3xl text-4xl font-semibold leading-tight tracking-[-0.05em] sm:text-5xl">
                Every transaction,
                <span className="block text-[#167c5a]">
                  clearly organized.
                </span>
              </h1>

              <p className="mt-4 max-w-2xl text-sm leading-6 text-[#66746e] sm:text-base">
                Search, filter, categorize, and review your financial
                activity without digging through a dense table.
              </p>
            </div>

            <button
              type="button"
              onClick={syncTransactions}
              disabled={!userId || syncing}
              className="rounded-full bg-[#14241e] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#20352d] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {syncing ? "Syncing..." : "Sync transactions"}
            </button>
          </header>

          <section className="mt-8 grid gap-4 md:grid-cols-3">
            <MetricCard
              label="Income in view"
              value={formatCents(totalIncome)}
              tone="green"
            />
            <MetricCard
              label="Spending in view"
              value={formatCents(-totalSpending)}
              tone="coral"
            />
            <MetricCard
              label="Net activity"
              value={formatCents(net)}
              tone={net >= 0 ? "yellow" : "coral"}
            />
          </section>

          {(message || error) && (
            <div className="mt-5">
              {message && <PageSuccess message={message} />}
              {error && <PageError message={error} />}
            </div>
          )}

          <section className="mt-6 rounded-[28px] border border-[#14241e]/10 bg-white p-5 shadow-sm shadow-[#14241e]/5 sm:p-6">
            <div className="flex flex-col gap-4 border-b border-[#14241e]/10 pb-5 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h2 className="text-lg font-semibold">
                  Find what matters
                </h2>
                <p className="mt-1 text-sm text-[#728078]">
                  {filtered.length} of {transactions.length} transactions
                </p>
              </div>

              <button
                type="button"
                onClick={clearFilters}
                className="text-left text-sm font-semibold text-[#167c5a]"
              >
                Clear all filters
              </button>
            </div>

            <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-7">
              <input
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setPage(1);
                }}
                placeholder="Search merchant, category, or account"
                className="rounded-2xl border border-[#14241e]/10 bg-[#f7f4ed] px-4 py-3 text-sm outline-none placeholder:text-[#9aa39e] focus:border-[#167c5a] xl:col-span-2"
              />

              <FilterSelect
                value={category}
                onChange={(value) => {
                  setCategory(value);
                  setPage(1);
                }}
                options={CATEGORIES.map((item) => ({
                  value: item,
                  label: item,
                }))}
              />

              <FilterSelect
                value={source}
                onChange={(value) => {
                  setSource(value);
                  setPage(1);
                }}
                options={[
                  { value: "All", label: "All sources" },
                  { value: "Plaid", label: "Plaid" },
                  { value: "CSV", label: "CSV" },
                  { value: "Pending", label: "Pending" },
                ]}
              />

              <FilterSelect
                value={accountId}
                onChange={(value) => {
                  setAccountId(value);
                  setPage(1);
                }}
                disabled={accountOptions.length === 0}
                options={[
                  { value: "All", label: "All accounts" },
                  ...accountOptions.map(([id, label]) => ({
                    value: String(id),
                    label,
                  })),
                ]}
              />

              <input
                type="date"
                value={fromDate}
                onChange={(event) => {
                  setFromDate(event.target.value);
                  setPage(1);
                }}
                className="rounded-2xl border border-[#14241e]/10 bg-[#f7f4ed] px-4 py-3 text-sm outline-none focus:border-[#167c5a]"
              />

              <input
                type="date"
                value={toDate}
                min={fromDate}
                onChange={(event) => {
                  setToDate(event.target.value);
                  setPage(1);
                }}
                className="rounded-2xl border border-[#14241e]/10 bg-[#f7f4ed] px-4 py-3 text-sm outline-none focus:border-[#167c5a]"
              />
            </div>
          </section>

          <section className="mt-6">
            {loading ? (
              <PageLoading message="Loading transactions..." />
            ) : visibleTransactions.length === 0 ? (
              <EmptyState
                title={
                  transactions.length === 0
                    ? "No transactions yet"
                    : "No transactions match your filters"
                }
                description={
                  transactions.length === 0
                    ? "Upload a CSV file or synchronize a connected account to add financial activity."
                    : "Adjust or clear your current filters to see more transactions."
                }
                actionLabel={
                  transactions.length === 0 ? undefined : "Clear filters"
                }
                onAction={
                  transactions.length === 0 ? undefined : clearFilters
                }
              />
            ) : (
              <div className="space-y-3">
                {visibleTransactions.map((transaction) => (
                  <TransactionRow
                    key={transaction.id}
                    transaction={transaction}
                    busy={busyId === transaction.id}
                    onCategoryChange={(nextCategory) =>
                      updateCategory(transaction.id, nextCategory)
                    }
                    onDelete={() => deleteTransaction(transaction)}
                  />
                ))}
              </div>
            )}
          </section>

          {!loading && filtered.length > PAGE_SIZE && (
            <div className="mt-6 flex flex-col gap-3 rounded-2xl border border-[#14241e]/10 bg-white px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-[#66746e]">
                Page {page} of {totalPages}
              </p>

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() =>
                    setPage((current) => Math.max(1, current - 1))
                  }
                  disabled={page === 1}
                  className="rounded-full border border-[#14241e]/10 px-4 py-2 text-sm font-medium transition hover:bg-[#f7f4ed] disabled:opacity-40"
                >
                  Previous
                </button>

                <button
                  type="button"
                  onClick={() =>
                    setPage((current) =>
                      Math.min(totalPages, current + 1)
                    )
                  }
                  disabled={page === totalPages}
                  className="rounded-full bg-[#14241e] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#20352d] disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

function MetricCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "green" | "coral" | "yellow";
}) {
  const styles = {
    green: "bg-[#dff6c7]",
    coral: "bg-[#f8ddd5]",
    yellow: "bg-[#f7e8b5]",
  };

  return (
    <article className={`rounded-[26px] p-5 ${styles[tone]}`}>
      <p className="text-sm text-[#52635b]">{label}</p>
      <p className="mt-3 text-3xl font-semibold tracking-[-0.04em]">
        {value}
      </p>
    </article>
  );
}

function FilterSelect({
  value,
  onChange,
  options,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
      className="rounded-2xl border border-[#14241e]/10 bg-[#f7f4ed] px-4 py-3 text-sm outline-none focus:border-[#167c5a] disabled:cursor-not-allowed disabled:opacity-50"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

function TransactionRow({
  transaction,
  busy,
  onCategoryChange,
  onDelete,
}: {
  transaction: Transaction;
  busy: boolean;
  onCategoryChange: (category: string) => void;
  onDelete: () => void;
}) {
  const positive = transaction.amount_cents >= 0;

  return (
    <article className="grid gap-4 rounded-[24px] border border-[#14241e]/10 bg-white p-5 transition hover:-translate-y-0.5 hover:shadow-md hover:shadow-[#14241e]/5 lg:grid-cols-[140px_minmax(0,1fr)_190px_140px_90px] lg:items-center">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#8a958f]">
          Date
        </p>
        <p className="mt-2 text-sm font-medium">
          {new Date(
            `${transaction.posted_on}T00:00:00`
          ).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            year: "numeric",
          })}
        </p>
      </div>

      <div className="min-w-0">
        <p className="truncate text-base font-semibold">
          {transaction.merchant_name || transaction.description}
        </p>

        {transaction.merchant_name &&
          transaction.merchant_name !== transaction.description && (
            <p className="mt-1 truncate text-sm text-[#7b8781]">
              {transaction.description}
            </p>
          )}

        <div className="mt-2 flex flex-wrap gap-2">
          <span className="rounded-full bg-[#edf5ee] px-2.5 py-1 text-[11px] font-semibold text-[#476457]">
            {transaction.source === "plaid" ? "Plaid" : "CSV"}
          </span>

          {transaction.pending && (
            <span className="rounded-full bg-[#f7e8b5] px-2.5 py-1 text-[11px] font-semibold text-[#8b6518]">
              Pending
            </span>
          )}

          {transaction.account_name && (
            <span className="text-xs text-[#8a958f]">
              {transaction.institution_name
                ? `${transaction.institution_name} • `
                : ""}
              {transaction.account_name}
            </span>
          )}
        </div>
      </div>

      <select
        value={transaction.category}
        disabled={busy}
        onChange={(event) => onCategoryChange(event.target.value)}
        className="rounded-2xl border border-[#14241e]/10 bg-[#f7f4ed] px-3 py-2.5 text-sm outline-none focus:border-[#167c5a] disabled:opacity-50"
      >
        {CATEGORIES.filter((item) => item !== "All").map((item) => (
          <option key={item}>{item}</option>
        ))}
      </select>

      <p
        className={`text-lg font-semibold lg:text-right ${
          positive ? "text-[#167c5a]" : "text-[#a64b3d]"
        }`}
      >
        {formatCents(transaction.amount_cents)}
      </p>

      <button
        type="button"
        onClick={onDelete}
        disabled={busy}
        className="text-left text-sm font-semibold text-[#a64b3d] transition hover:text-[#843a30] disabled:opacity-50 lg:text-right"
      >
        {busy ? "Working..." : "Delete"}
      </button>
    </article>
  );
}
