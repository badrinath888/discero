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
    .reduce((total, item) => total + Math.abs(item.amount_cents), 0);

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
    <main
      className="relative min-h-screen overflow-hidden bg-[#050d18] text-white"
      style={{
        backgroundImage: `
          radial-gradient(circle at 10% 5%, rgba(16,185,129,0.20), transparent 28%),
          radial-gradient(circle at 88% 15%, rgba(14,165,233,0.14), transparent 25%),
          radial-gradient(circle at 50% 100%, rgba(6,182,212,0.08), transparent 35%),
          linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)
        `,
        backgroundSize: "auto, auto, auto, 42px 42px, 42px 42px",
      }}
    >
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent via-[#050d18]/20 to-[#050d18]" />

      <AppSidebar />

      <div className="relative px-5 pb-10 pt-20 sm:px-8 lg:ml-72 lg:px-10 lg:pt-8">
        <div className="mx-auto max-w-7xl">
        <header className="flex flex-col gap-6 rounded-3xl border border-white/10 bg-white/[0.05] p-6 shadow-2xl shadow-black/30 backdrop-blur-xl sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-300">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              Financial activity
            </div>

            <h1 className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">
              Transactions
            </h1>

            <p className="mt-2 max-w-xl text-sm text-slate-400">
              Review, filter, categorize, and manage your financial activity.
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={syncTransactions}
              disabled={!userId || syncing}
              className="rounded-xl border border-emerald-400/20 bg-emerald-400/10 px-5 py-2.5 text-sm font-medium text-emerald-300 transition hover:bg-emerald-400/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {syncing ? "Syncing..." : "Sync transactions"}
            </button>

          </div>
        </header>

        <section className="mt-6 grid gap-4 sm:grid-cols-3">
          <SummaryCard
            label="Filtered transactions"
            value={String(filtered.length)}
            accent="cyan"
          />

          <SummaryCard
            label="Filtered income"
            value={formatCents(totalIncome)}
            accent="emerald"
          />

          <SummaryCard
            label="Filtered spending"
            value={formatCents(-totalSpending)}
            accent="rose"
          />
        </section>

        <section className="mt-6 rounded-3xl border border-white/10 bg-white/[0.06] p-5 shadow-2xl shadow-black/20 backdrop-blur-xl">
          <div className="grid gap-3 md:grid-cols-7">
            <input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
              placeholder="Search merchant or category"
              className="rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none transition placeholder:text-slate-500 focus:border-emerald-400 md:col-span-2"
            />

            <select
              value={category}
              onChange={(event) => {
                setCategory(event.target.value);
                setPage(1);
              }}
              className="rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none transition focus:border-emerald-400"
            >
              {CATEGORIES.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>

            <select
              value={source}
              onChange={(event) => {
                setSource(event.target.value);
                setPage(1);
              }}
              className="rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none transition focus:border-emerald-400"
            >
              <option>All</option>
              <option>Plaid</option>
              <option>CSV</option>
              <option>Pending</option>
            </select>

            <select
              value={accountId}
              onChange={(event) => {
                setAccountId(event.target.value);
                setPage(1);
              }}
              disabled={accountOptions.length === 0}
              className="rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none transition focus:border-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <option value="All">All accounts</option>

              {accountOptions.map(([id, label]) => (
                <option key={id} value={String(id)}>
                  {label}
                </option>
              ))}
            </select>

            <input
              type="date"
              value={fromDate}
              onChange={(event) => {
                setFromDate(event.target.value);
                setPage(1);
              }}
              className="rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none transition focus:border-emerald-400"
            />

            <input
              type="date"
              value={toDate}
              min={fromDate}
              onChange={(event) => {
                setToDate(event.target.value);
                setPage(1);
              }}
              className="rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none transition focus:border-emerald-400"
            />
          </div>

          <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-slate-400">
              Showing {filtered.length} of {transactions.length} transactions
            </p>

            <button
              onClick={clearFilters}
              className="text-left text-sm font-medium text-emerald-300 transition hover:text-emerald-200"
            >
              Clear filters
            </button>
          </div>
        </section>

        {message && (
          <div className="mt-5">
            <PageSuccess message={message} />
          </div>
        )}

        {error && (
          <div className="mt-5">
            <PageError message={error} />
          </div>
        )}

        <section className="mt-6 overflow-hidden rounded-3xl border border-white/10 bg-white/[0.05] shadow-2xl shadow-black/25 backdrop-blur-xl">
          {loading ? (
            <div className="p-5">
              <PageLoading message="Loading transactions..." />
            </div>
          ) : visibleTransactions.length === 0 ? (
            <div className="p-5">
              <EmptyState
                title={
                  transactions.length === 0
                    ? "No transactions yet"
                    : "No transactions match your filters"
                }
                description={
                  transactions.length === 0
                    ? "Upload a CSV file or synchronize a connected bank account to add financial activity."
                    : "Adjust or clear the current filters to view more transactions."
                }
                actionLabel={
                  transactions.length === 0
                    ? undefined
                    : "Clear filters"
                }
                onAction={
                  transactions.length === 0
                    ? undefined
                    : clearFilters
                }
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[850px] text-left text-sm">
                <thead className="border-b border-white/10 bg-emerald-400/[0.06] text-slate-300">
                  <tr>
                    <th className="px-6 py-4 font-medium">Date</th>
                    <th className="px-6 py-4 font-medium">Description</th>
                    <th className="px-6 py-4 font-medium">Category</th>
                    <th className="px-6 py-4 text-right font-medium">
                      Amount
                    </th>
                    <th className="px-6 py-4 text-right font-medium">
                      Action
                    </th>
                  </tr>
                </thead>

                <tbody className="divide-y divide-white/[0.07]">
                  {visibleTransactions.map((transaction) => (
                    <tr
                      key={transaction.id}
                      className="transition hover:bg-emerald-400/[0.035]"
                    >
                      <td className="whitespace-nowrap px-6 py-4 text-slate-400">
                        {new Date(
                          `${transaction.posted_on}T00:00:00`
                        ).toLocaleDateString("en-US")}
                      </td>

                      <td className="px-6 py-4">
                        <p className="font-medium text-slate-100">
                          {transaction.merchant_name ||
                            transaction.description}
                        </p>

                        {transaction.merchant_name &&
                          transaction.merchant_name !==
                            transaction.description && (
                            <p className="mt-1 text-xs text-slate-500">
                              {transaction.description}
                            </p>
                          )}

                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <span
                            className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
                              transaction.source === "plaid"
                                ? "bg-cyan-400/10 text-cyan-300"
                                : "bg-slate-400/10 text-slate-300"
                            }`}
                          >
                            {transaction.source === "plaid"
                              ? "Plaid"
                              : "CSV"}
                          </span>

                          {transaction.pending && (
                            <span className="rounded-full bg-amber-400/10 px-2.5 py-1 text-[11px] font-medium text-amber-300">
                              Pending
                            </span>
                          )}

                          {transaction.source === "plaid" &&
                            transaction.account_name && (
                              <span className="text-xs text-slate-500">
                                {transaction.institution_name
                                  ? `${transaction.institution_name} • `
                                  : ""}
                                {transaction.account_name}
                              </span>
                            )}
                        </div>
                      </td>

                      <td className="px-6 py-4">
                        <select
                          value={transaction.category}
                          disabled={busyId === transaction.id}
                          onChange={(event) =>
                            updateCategory(
                              transaction.id,
                              event.target.value
                            )
                          }
                          className="rounded-xl border border-white/10 bg-slate-950/70 px-3 py-2 text-sm text-slate-200 outline-none transition focus:border-emerald-400 disabled:opacity-50"
                        >
                          {CATEGORIES.filter(
                            (item) => item !== "All"
                          ).map((item) => (
                            <option key={item}>{item}</option>
                          ))}
                        </select>
                      </td>

                      <td
                        className={`whitespace-nowrap px-6 py-4 text-right font-semibold ${
                          transaction.amount_cents >= 0
                            ? "text-emerald-300"
                            : "text-rose-300"
                        }`}
                      >
                        {formatCents(transaction.amount_cents)}
                      </td>

                      <td className="px-6 py-4 text-right">
                        <button
                          onClick={() =>
                            deleteTransaction(transaction)
                          }
                          disabled={busyId === transaction.id}
                          className="rounded-xl border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs font-medium text-rose-300 transition hover:bg-rose-400/20 disabled:opacity-50"
                        >
                          {busyId === transaction.id
                            ? "Working..."
                            : "Delete"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {!loading && !error && filtered.length === 0 && (
            <div className="px-5 py-16 text-center">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-400/10 text-2xl text-emerald-300">
                $
              </div>

              <p className="mt-4 font-medium text-slate-200">
                No matching transactions
              </p>

              <p className="mt-2 text-sm text-slate-500">
                Adjust or clear the selected filters.
              </p>
            </div>
          )}
        </section>

        {!loading && filtered.length > PAGE_SIZE && (
          <div className="mt-5 flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/[0.04] px-5 py-4 backdrop-blur-xl sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-slate-400">
              Page {page} of {totalPages}
            </p>

            <div className="flex gap-2">
              <button
                onClick={() =>
                  setPage((current) => Math.max(1, current - 1))
                }
                disabled={page === 1}
                className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Previous
              </button>

              <button
                onClick={() =>
                  setPage((current) =>
                    Math.min(totalPages, current + 1)
                  )
                }
                disabled={page === totalPages}
                className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40"
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

function SummaryCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent: "emerald" | "rose" | "cyan";
}) {
  const styles = {
    emerald: "text-emerald-300 bg-emerald-400/10",
    rose: "text-rose-300 bg-rose-400/10",
    cyan: "text-cyan-300 bg-cyan-400/10",
  };

  return (
    <div className="rounded-3xl border border-white/10 bg-white/[0.06] p-5 shadow-xl shadow-black/20 backdrop-blur-xl">
      <p className="text-sm text-slate-400">{label}</p>

      <div
        className={`mt-3 inline-flex rounded-xl px-3 py-2 text-2xl font-bold ${styles[accent]}`}
      >
        {value}
      </div>
    </div>
  );
}