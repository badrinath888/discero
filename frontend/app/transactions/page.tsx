"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import AppSidebar from "../components/AppSidebar";
import ConfirmationModal from "../components/ConfirmationModal";
import {
  EmptyState,
  PageError,
  PageLoading,
  PageSuccess,
} from "../components/PageFeedback";
import {
  api,
  FinancialAccount,
  formatCents,
  session,
  Transaction,
} from "../lib/api";
import { PageReveal, Reveal } from "../components/PremiumMotion";

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

const EDITABLE_CATEGORIES = CATEGORIES.filter(
  (category) => category !== "All"
);

const PAGE_SIZE = 20;

type Density = "compact" | "comfortable";

export default function TransactionsPage() {
  const router = useRouter();

  const [userId, setUserId] = useState<number | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [accounts, setAccounts] = useState<FinancialAccount[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [totalIncome, setTotalIncome] = useState(0);
  const [totalSpending, setTotalSpending] = useState(0);
  const [net, setNet] = useState(0);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");
  const [source, setSource] = useState("All");
  const [accountId, setAccountId] = useState("All");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [page, setPage] = useState(1);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkCategory, setBulkCategory] = useState("");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [menuId, setMenuId] = useState<number | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [density, setDensity] = useState<Density>("compact");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<
    | { type: "single"; transaction: Transaction }
    | { type: "bulk"; transactionIds: number[] }
    | null
  >(null);

  useEffect(() => {
    async function initializePage() {
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

        const accountData = await api.getAccounts(id);

        setUserId(id);
        setAccounts(accountData);
      } catch (err) {
        if (!session.getToken()) {
          router.replace("/");
          return;
        }

        setError(
          err instanceof Error
            ? err.message
            : "Unable to initialize transactions"
        );
        setLoading(false);
      }
    }

    void initializePage();
  }, [router]);

  useEffect(() => {
    if (!userId) return;

    const controller = new AbortController();
    const delay = search.trim() ? 300 : 0;

    const timeout = window.setTimeout(async () => {
      setLoading(true);
      setError("");

      try {
        const data = await api.searchTransactions(userId, {
          search: search.trim() || undefined,
          category: category === "All" ? undefined : category,
          source:
            source === "All" || source === "Pending"
              ? undefined
              : source.toLowerCase(),
          pending: source === "Pending" ? true : undefined,
          account_id:
            accountId === "All" ? undefined : Number(accountId),
          start_date: fromDate || undefined,
          end_date: toDate || undefined,
          page,
          page_size: PAGE_SIZE,
        });

        if (controller.signal.aborted) return;

        setTransactions(data.items);
        setTotal(data.total);
        setTotalPages(data.total_pages);
        setTotalIncome(data.total_income_cents);
        setTotalSpending(data.total_spending_cents);
        setNet(data.net_cents);
        setSelectedIds([]);
        setExpandedId(null);
      } catch (err) {
        if (controller.signal.aborted) return;

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
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }, delay);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [
    userId,
    search,
    category,
    source,
    accountId,
    fromDate,
    toDate,
    page,
    router,
  ]);

  const accountOptions = useMemo(
    () =>
      accounts
        .map((account) => {
          const label = account.institution_name
            ? `${account.institution_name} • ${account.name}`
            : account.name;

          return [account.id, label] as const;
        })
        .sort((a, b) => a[1].localeCompare(b[1])),
    [accounts]
  );

  const visibleTransactions = transactions;

  const groupedTransactions = useMemo(() => {
    const groups = new Map<string, Transaction[]>();

    for (const transaction of visibleTransactions) {
      const existing = groups.get(transaction.posted_on) ?? [];
      existing.push(transaction);
      groups.set(transaction.posted_on, existing);
    }

    return [...groups.entries()];
  }, [visibleTransactions]);

  const activeTransaction =
    transactions.find(({ id }) => id === expandedId) ?? null;

  const activeFilterCount = [
    category !== "All",
    source !== "All",
    accountId !== "All",
    Boolean(fromDate),
    Boolean(toDate),
  ].filter(Boolean).length;

  const visibleIds = visibleTransactions.map(({ id }) => id);
  const allVisibleSelected =
    visibleIds.length > 0 &&
    visibleIds.every((id) => selectedIds.includes(id));

  async function syncTransactions() {
    if (!userId) return;

    setSyncing(true);
    setError("");
    setMessage("");

    try {
      const result = await api.syncPlaidTransactions(userId);

      setSelectedIds([]);
      setExpandedId(null);
      setPage(1);

      const refreshed = await api.searchTransactions(userId, {
        search: search.trim() || undefined,
        category: category === "All" ? undefined : category,
        source:
          source === "All" || source === "Pending"
            ? undefined
            : source.toLowerCase(),
        pending: source === "Pending" ? true : undefined,
        account_id:
          accountId === "All" ? undefined : Number(accountId),
        start_date: fromDate || undefined,
        end_date: toDate || undefined,
        page: 1,
        page_size: PAGE_SIZE,
      });

      setTransactions(refreshed.items);
      setTotal(refreshed.total);
      setTotalPages(refreshed.total_pages);
      setTotalIncome(refreshed.total_income_cents);
      setTotalSpending(refreshed.total_spending_cents);
      setNet(refreshed.net_cents);
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
    setMessage("");

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

      setMessage("Transaction category updated.");
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

  function deleteTransaction(transaction: Transaction) {
    if (!userId || busyId !== null || bulkBusy) return;

    setMenuId(null);
    setPendingDelete({
      type: "single",
      transaction,
    });
  }

  async function confirmSingleDelete(transaction: Transaction) {
    if (!userId) return;

    setBusyId(transaction.id);
    setError("");
    setMessage("");
    setMenuId(null);

    try {
      await api.deleteTransaction(userId, transaction.id);

      setTransactions((current) =>
        current.filter(({ id }) => id !== transaction.id)
      );
      setSelectedIds((current) =>
        current.filter((id) => id !== transaction.id)
      );

      if (expandedId === transaction.id) {
        setExpandedId(null);
      }

      setPendingDelete(null);
      setMessage("Transaction deleted.");
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

  async function updateSelectedCategory() {
    if (!userId || !bulkCategory || selectedIds.length === 0) return;

    setBulkBusy(true);
    setError("");
    setMessage("");

    try {
      const updatedTransactions = await Promise.all(
        selectedIds.map((transactionId) =>
          api.updateTransaction(
            userId,
            transactionId,
            bulkCategory
          )
        )
      );

      const updatedById = new Map(
        updatedTransactions.map((transaction) => [
          transaction.id,
          transaction,
        ])
      );

      setTransactions((current) =>
        current.map(
          (transaction) =>
            updatedById.get(transaction.id) ?? transaction
        )
      );

      setSelectedIds([]);
      setBulkCategory("");
      setMessage(
        `${updatedTransactions.length} transactions updated.`
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to update selected transactions"
      );
    } finally {
      setBulkBusy(false);
    }
  }

  function deleteSelectedTransactions() {
    if (!userId || selectedIds.length === 0 || bulkBusy) return;

    setPendingDelete({
      type: "bulk",
      transactionIds: [...selectedIds],
    });
  }

  async function confirmBulkDelete(transactionIds: number[]) {
    if (!userId || transactionIds.length === 0) return;

    setBulkBusy(true);
    setError("");
    setMessage("");

    try {
      await Promise.all(
        transactionIds.map((transactionId) =>
          api.deleteTransaction(userId, transactionId)
        )
      );

      const deletedIds = new Set(transactionIds);

      setTransactions((current) =>
        current.filter(
          (transaction) => !deletedIds.has(transaction.id)
        )
      );

      if (expandedId && deletedIds.has(expandedId)) {
        setExpandedId(null);
      }

      setPendingDelete(null);
      setMessage(`${transactionIds.length} transactions deleted.`);
      setSelectedIds([]);
      setBulkCategory("");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to delete selected transactions"
      );
    } finally {
      setBulkBusy(false);
    }
  }

  function toggleSelection(transactionId: number) {
    setSelectedIds((current) =>
      current.includes(transactionId)
        ? current.filter((id) => id !== transactionId)
        : [...current, transactionId]
    );
  }

  function toggleVisibleSelection() {
    setSelectedIds((current) => {
      if (allVisibleSelected) {
        return current.filter((id) => !visibleIds.includes(id));
      }

      return [...new Set([...current, ...visibleIds])];
    });
  }

  function openDetails(transactionId: number) {
    setExpandedId(transactionId);
    setMenuId(null);
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

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[1500px]">
          <Reveal>
          <header className="flex flex-col gap-5 border-b border-[#14241e]/10 pb-6 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
                Money activity
              </p>

              <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
                Transactions
              </h1>

              <p className="mt-3 max-w-2xl text-sm leading-6 text-[#66746e]">
                Review, organize, and manage every financial event
                from one focused workspace.
              </p>
            </div>

            <button
              type="button"
              onClick={syncTransactions}
              disabled={!userId || syncing}
              className="inline-flex min-h-11 items-center justify-center rounded-full bg-[#14241e] px-5 text-sm font-semibold text-white transition hover:bg-[#20352d] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {syncing ? "Syncing transactions..." : "Sync transactions"}
            </button>
          </header>
          </Reveal>

          <Reveal delay={0.06}>
          <section className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <SummaryItem
              label="Transactions"
              value={total.toLocaleString()}
            />
            <SummaryItem
              label="Income"
              value={formatCents(totalIncome)}
              valueClassName="text-[#167c5a]"
            />
            <SummaryItem
              label="Spending"
              value={formatCents(-totalSpending)}
              valueClassName="text-[#a64b3d]"
            />
            <SummaryItem
              label="Net activity"
              value={formatCents(net)}
              valueClassName={
                net >= 0 ? "text-[#167c5a]" : "text-[#a64b3d]"
              }
            />
          </section>
          </Reveal>

          {(message || error) && (
            <div className="mt-4 space-y-3">
              {message && <PageSuccess message={message} />}
              {error && <PageError message={error} />}
            </div>
          )}

          <section className="sticky top-0 z-30 mt-5 border-y border-[#14241e]/10 bg-[#f5f1e8]/95 py-3 backdrop-blur lg:top-0">
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                <div className="relative min-w-0 flex-1">
                  <span className="pointer-events-none absolute inset-y-0 left-4 flex items-center text-[#7a8780]">
                    <SearchIcon />
                  </span>

                  <input
                    value={search}
                    onChange={(event) => {
                      setSearch(event.target.value);
                      setPage(1);
                    }}
                    placeholder="Search merchant, description, category, or account"
                    className="h-11 w-full rounded-xl border border-[#14241e]/10 bg-white pl-11 pr-4 text-sm outline-none transition placeholder:text-[#98a19d] focus:border-[#167c5a]"
                  />
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setShowFilters((current) => !current)}
                    className={`inline-flex h-11 items-center gap-2 rounded-xl border px-4 text-sm font-semibold transition ${
                      showFilters || activeFilterCount > 0
                        ? "border-[#167c5a] bg-[#e7f3eb] text-[#126a4d]"
                        : "border-[#14241e]/10 bg-white hover:bg-[#f9f7f1]"
                    }`}
                  >
                    <FilterIcon />
                    Filters
                    {activeFilterCount > 0 && (
                      <span className="rounded-full bg-[#167c5a] px-2 py-0.5 text-xs text-white">
                        {activeFilterCount}
                      </span>
                    )}
                  </button>

                  <div className="flex h-11 items-center rounded-xl border border-[#14241e]/10 bg-white p-1">
                    <button
                      type="button"
                      onClick={() => setDensity("compact")}
                      className={`h-full rounded-lg px-3 text-xs font-semibold transition ${
                        density === "compact"
                          ? "bg-[#14241e] text-white"
                          : "text-[#66746e]"
                      }`}
                    >
                      Compact
                    </button>

                    <button
                      type="button"
                      onClick={() => setDensity("comfortable")}
                      className={`h-full rounded-lg px-3 text-xs font-semibold transition ${
                        density === "comfortable"
                          ? "bg-[#14241e] text-white"
                          : "text-[#66746e]"
                      }`}
                    >
                      Comfortable
                    </button>
                  </div>
                </div>
              </div>

              <AnimatePresence initial={false}>
              {showFilters && (
                <motion.div
                  initial={{ opacity: 0, height: 0, y: -8 }}
                  animate={{ opacity: 1, height: "auto", y: 0 }}
                  exit={{ opacity: 0, height: 0, y: -8 }}
                  transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
                  className="grid overflow-hidden gap-2 rounded-2xl border border-[#14241e]/10 bg-white p-3 sm:grid-cols-2 xl:grid-cols-[1fr_1fr_1.4fr_1fr_1fr_auto]"
                >
                  <FilterSelect
                    value={category}
                    onChange={(value) => {
                      setCategory(value);
                      setPage(1);
                    }}
                    options={CATEGORIES.map((item) => ({
                      value: item,
                      label:
                        item === "All"
                          ? "All categories"
                          : item,
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
                    aria-label="From date"
                    onChange={(event) => {
                      setFromDate(event.target.value);
                      setPage(1);
                    }}
                    className="h-10 rounded-xl border border-[#14241e]/10 bg-[#f7f4ed] px-3 text-sm outline-none focus:border-[#167c5a]"
                  />

                  <input
                    type="date"
                    value={toDate}
                    min={fromDate}
                    aria-label="To date"
                    onChange={(event) => {
                      setToDate(event.target.value);
                      setPage(1);
                    }}
                    className="h-10 rounded-xl border border-[#14241e]/10 bg-[#f7f4ed] px-3 text-sm outline-none focus:border-[#167c5a]"
                  />

                  <button
                    type="button"
                    onClick={clearFilters}
                    className="h-10 rounded-xl px-4 text-sm font-semibold text-[#167c5a] transition hover:bg-[#edf5ee]"
                  >
                    Clear
                  </button>
                </motion.div>
              )}
              </AnimatePresence>
            </div>
          </section>

          <AnimatePresence initial={false}>
          {selectedIds.length > 0 && (
            <motion.section
              initial={{ opacity: 0, y: -10, scale: 0.99 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -10, scale: 0.99 }}
              transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
              className="mt-4 flex flex-col gap-3 rounded-2xl border border-[#167c5a]/20 bg-[#e7f3eb] p-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <p className="text-sm font-semibold text-[#126a4d]">
                {selectedIds.length} selected
              </p>

              <div className="flex flex-col gap-2 sm:flex-row">
                <select
                  value={bulkCategory}
                  disabled={bulkBusy}
                  onChange={(event) =>
                    setBulkCategory(event.target.value)
                  }
                  className="h-10 rounded-xl border border-[#167c5a]/20 bg-white px-3 text-sm outline-none disabled:opacity-50"
                >
                  <option value="">Choose category</option>
                  {EDITABLE_CATEGORIES.map((item) => (
                    <option key={item}>{item}</option>
                  ))}
                </select>

                <button
                  type="button"
                  onClick={updateSelectedCategory}
                  disabled={!bulkCategory || bulkBusy}
                  className="h-10 rounded-xl bg-[#167c5a] px-4 text-sm font-semibold text-white disabled:opacity-40"
                >
                  Apply category
                </button>

                <button
                  type="button"
                  onClick={deleteSelectedTransactions}
                  disabled={bulkBusy}
                  className="h-10 rounded-xl border border-[#a64b3d]/20 bg-white px-4 text-sm font-semibold text-[#a64b3d] disabled:opacity-40"
                >
                  Delete selected
                </button>

                <button
                  type="button"
                  onClick={() => setSelectedIds([])}
                  disabled={bulkBusy}
                  className="h-10 rounded-xl px-3 text-sm font-semibold text-[#66746e]"
                >
                  Cancel
                </button>
              </div>
            </motion.section>
          )}
          </AnimatePresence>

          <section className="mt-4 overflow-hidden rounded-2xl border border-[#14241e]/10 bg-white">
            <div className="hidden grid-cols-[44px_minmax(240px,1.8fr)_minmax(160px,1fr)_150px_130px_48px] items-center gap-4 border-b border-[#14241e]/10 bg-[#f9f7f1] px-4 py-3 text-xs font-semibold uppercase tracking-[0.12em] text-[#7a8780] lg:grid">
              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleVisibleSelection}
                  aria-label="Select visible transactions"
                  className="h-4 w-4 accent-[#167c5a]"
                />
              </label>

              <span>Transaction</span>
              <span>Account</span>
              <span>Category</span>
              <span className="text-right">Amount</span>
              <span />
            </div>

            {loading ? (
              <div className="p-5">
                <PageLoading message="Loading transactions..." />
              </div>
            ) : visibleTransactions.length === 0 ? (
              <div className="p-5">
                <EmptyState
                  title={
                    total === 0 && activeFilterCount === 0 && !search.trim()
                      ? "No transactions yet"
                      : "No transactions match your filters"
                  }
                  description={
                    total === 0 && activeFilterCount === 0 && !search.trim()
                      ? "Upload a CSV file or synchronize a connected account to add financial activity."
                      : "Adjust or clear your current filters to see more transactions."
                  }
                  actionLabel={
                    total === 0 && activeFilterCount === 0 && !search.trim()
                      ? undefined
                      : "Clear filters"
                  }
                  onAction={
                    total === 0 && activeFilterCount === 0 && !search.trim()
                      ? undefined
                      : clearFilters
                  }
                />
              </div>
            ) : (
              groupedTransactions.map(([date, items]) => (
                <TransactionGroup
                  key={date}
                  date={date}
                  transactions={items}
                  density={density}
                  busyId={busyId}
                  selectedIds={selectedIds}
                  menuId={menuId}
                  onSelect={toggleSelection}
                  onOpen={openDetails}
                  onMenuChange={setMenuId}
                  onCategoryChange={updateCategory}
                  onDelete={deleteTransaction}
                />
              ))
            )}
          </section>

          {!loading && totalPages > 1 && (
            <div className="mt-5 flex flex-col gap-3 rounded-2xl border border-[#14241e]/10 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-[#66746e]">
                Showing {(page - 1) * PAGE_SIZE + 1}–
                {Math.min(page * PAGE_SIZE, total)} of{" "}
                {total}
              </p>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() =>
                    setPage((current) => Math.max(1, current - 1))
                  }
                  disabled={page === 1}
                  className="h-10 rounded-xl border border-[#14241e]/10 px-4 text-sm font-semibold transition hover:bg-[#f7f4ed] disabled:opacity-40"
                >
                  Previous
                </button>

                <span className="px-2 text-sm font-medium text-[#66746e]">
                  {page} / {totalPages}
                </span>

                <button
                  type="button"
                  onClick={() =>
                    setPage((current) =>
                      Math.min(totalPages, current + 1)
                    )
                  }
                  disabled={page === totalPages}
                  className="h-10 rounded-xl bg-[#14241e] px-4 text-sm font-semibold text-white transition hover:bg-[#20352d] disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </PageReveal>
      </div>

      <AnimatePresence>
        {activeTransaction && (
          <TransactionDrawer
            transaction={activeTransaction}
            busy={busyId === activeTransaction.id}
            onClose={() => setExpandedId(null)}
            onCategoryChange={(nextCategory) =>
              updateCategory(activeTransaction.id, nextCategory)
            }
            onDelete={() => deleteTransaction(activeTransaction)}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {pendingDelete && (
          <ConfirmationModal
            eyebrow="Confirm deletion"
            title={
              pendingDelete.type === "single"
                ? `Delete "${pendingDelete.transaction.description}"?`
                : `Delete ${pendingDelete.transactionIds.length} transactions?`
            }
            description={
              pendingDelete.type === "single"
                ? "This transaction will be permanently removed from FinSight."
                : "All selected transactions will be permanently removed from FinSight."
            }
            cancelLabel={
              pendingDelete.type === "single"
                ? "Keep transaction"
                : "Keep transactions"
            }
            confirmLabel="Delete permanently"
            busyLabel="Deleting..."
            busy={
              pendingDelete.type === "single"
                ? busyId === pendingDelete.transaction.id
                : bulkBusy
            }
            icon={
              <span className="text-xl font-semibold leading-none">
                ×
              </span>
            }
            onCancel={() => {
              if (busyId === null && !bulkBusy) {
                setPendingDelete(null);
              }
            }}
            onConfirm={() => {
              if (pendingDelete.type === "single") {
                void confirmSingleDelete(pendingDelete.transaction);
              } else {
                void confirmBulkDelete(
                  pendingDelete.transactionIds
                );
              }
            }}
          />
        )}
      </AnimatePresence>
    </main>
  );
}

function SummaryItem({
  label,
  value,
  valueClassName = "",
}: {
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <motion.article
      whileHover={{ y: -2 }}
      transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
      className="border-l-2 border-[#14241e]/10 bg-white px-4 py-3"
    >
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#849089]">
        {label}
      </p>
      <p
        className={`mt-1 text-xl font-semibold tracking-[-0.03em] ${valueClassName}`}
      >
        {value}
      </p>
    </motion.article>
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
      className="h-10 min-w-0 rounded-xl border border-[#14241e]/10 bg-[#f7f4ed] px-3 text-sm outline-none focus:border-[#167c5a] disabled:cursor-not-allowed disabled:opacity-50"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

function TransactionGroup({
  date,
  transactions,
  density,
  busyId,
  selectedIds,
  menuId,
  onSelect,
  onOpen,
  onMenuChange,
  onCategoryChange,
  onDelete,
}: {
  date: string;
  transactions: Transaction[];
  density: Density;
  busyId: number | null;
  selectedIds: number[];
  menuId: number | null;
  onSelect: (transactionId: number) => void;
  onOpen: (transactionId: number) => void;
  onMenuChange: (transactionId: number | null) => void;
  onCategoryChange: (
    transactionId: number,
    category: string
  ) => void;
  onDelete: (transaction: Transaction) => void;
}) {
  const dailyTotal = transactions.reduce(
    (total, transaction) => total + transaction.amount_cents,
    0
  );

  const reduceMotion = useReducedMotion();

  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduceMotion ? 0 : 0.32 }}
      className="border-b border-[#14241e]/10 last:border-b-0"
    >
      <div className="flex items-center justify-between bg-[#faf8f3] px-4 py-2.5">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#68756f]">
          {formatDateHeading(date)}
        </p>

        <p
          className={`text-xs font-semibold ${
            dailyTotal >= 0 ? "text-[#167c5a]" : "text-[#a64b3d]"
          }`}
        >
          {formatCents(dailyTotal)}
        </p>
      </div>

      {transactions.map((transaction) => (
        <TransactionListRow
          key={transaction.id}
          transaction={transaction}
          density={density}
          busy={busyId === transaction.id}
          selected={selectedIds.includes(transaction.id)}
          menuOpen={menuId === transaction.id}
          onSelect={() => onSelect(transaction.id)}
          onOpen={() => onOpen(transaction.id)}
          onMenuChange={(open) =>
            onMenuChange(open ? transaction.id : null)
          }
          onCategoryChange={(nextCategory) =>
            onCategoryChange(transaction.id, nextCategory)
          }
          onDelete={() => onDelete(transaction)}
        />
      ))}
    </motion.div>
  );
}

function TransactionListRow({
  transaction,
  density,
  busy,
  selected,
  menuOpen,
  onSelect,
  onOpen,
  onMenuChange,
  onCategoryChange,
  onDelete,
}: {
  transaction: Transaction;
  density: Density;
  busy: boolean;
  selected: boolean;
  menuOpen: boolean;
  onSelect: () => void;
  onOpen: () => void;
  onMenuChange: (open: boolean) => void;
  onCategoryChange: (category: string) => void;
  onDelete: () => void;
}) {
  const positive = transaction.amount_cents >= 0;
  const padding = density === "compact" ? "py-3" : "py-5";
  const reduceMotion = useReducedMotion();

  return (
    <motion.article
      layout
      initial={reduceMotion ? false : { opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 14, height: 0 }}
      whileHover={reduceMotion ? undefined : { x: 3 }}
      transition={{ duration: reduceMotion ? 0 : 0.22 }}
      className={`relative grid gap-3 border-t border-[#14241e]/5 px-4 transition first:border-t-0 hover:bg-[#fbfaf6] lg:grid-cols-[44px_minmax(240px,1.8fr)_minmax(160px,1fr)_150px_130px_48px] lg:items-center ${padding}`}
    >
      <label className="absolute left-4 top-4 flex lg:static">
        <input
          type="checkbox"
          checked={selected}
          onChange={onSelect}
          aria-label={`Select ${transaction.description}`}
          className="h-4 w-4 accent-[#167c5a]"
        />
      </label>

      <button
        type="button"
        onClick={onOpen}
        className="min-w-0 pl-8 text-left lg:pl-0"
      >
        <div className="flex min-w-0 items-center gap-2">
          <p className="truncate text-sm font-semibold">
            {transaction.merchant_name || transaction.description}
          </p>

          {transaction.pending && (
            <span className="shrink-0 rounded-full bg-[#f7e8b5] px-2 py-0.5 text-[10px] font-semibold text-[#8b6518]">
              Pending
            </span>
          )}
        </div>

        <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          {transaction.merchant_name &&
            transaction.merchant_name !== transaction.description && (
              <span className="max-w-full truncate text-xs text-[#7b8781]">
                {transaction.description}
              </span>
            )}

          <span className="rounded-full bg-[#edf5ee] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#476457]">
            {transaction.source === "plaid" ? "Plaid" : "CSV"}
          </span>
        </div>
      </button>

      <button
        type="button"
        onClick={onOpen}
        className="min-w-0 text-left"
      >
        <p className="truncate text-sm font-medium text-[#405149]">
          {transaction.account_name || "Manual transaction"}
        </p>
        <p className="mt-0.5 truncate text-xs text-[#8a958f]">
          {transaction.institution_name ||
            (transaction.source === "plaid"
              ? "Connected account"
              : "CSV import")}
        </p>
      </button>

      <select
        value={transaction.category}
        disabled={busy}
        onChange={(event) => onCategoryChange(event.target.value)}
        onClick={(event) => event.stopPropagation()}
        className="h-9 rounded-xl border border-[#14241e]/10 bg-[#f7f4ed] px-3 text-xs font-medium outline-none focus:border-[#167c5a] disabled:opacity-50"
      >
        {EDITABLE_CATEGORIES.map((item) => (
          <option key={item}>{item}</option>
        ))}
      </select>

      <button
        type="button"
        onClick={onOpen}
        className={`text-left text-base font-semibold lg:text-right ${
          positive ? "text-[#167c5a]" : "text-[#a64b3d]"
        }`}
      >
        {formatCents(transaction.amount_cents)}
      </button>

      <div className="relative flex justify-end">
        <button
          type="button"
          onClick={() => onMenuChange(!menuOpen)}
          disabled={busy}
          aria-label="Transaction actions"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-[#66746e] transition hover:bg-[#f0eee7] disabled:opacity-50"
        >
          <MoreIcon />
        </button>

        <AnimatePresence>
        {menuOpen && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.96 }}
            transition={{ duration: 0.16 }}
            className="absolute right-0 top-10 z-20 w-40 overflow-hidden rounded-xl border border-[#14241e]/10 bg-white py-1 shadow-xl shadow-[#14241e]/10"
          >
            <button
              type="button"
              onClick={() => {
                onOpen();
                onMenuChange(false);
              }}
              className="w-full px-4 py-2.5 text-left text-sm font-medium hover:bg-[#f7f4ed]"
            >
              View details
            </button>

            <button
              type="button"
              onClick={onDelete}
              className="w-full px-4 py-2.5 text-left text-sm font-medium text-[#a64b3d] hover:bg-[#fdf1ed]"
            >
              Delete
            </button>
          </motion.div>
        )}
        </AnimatePresence>
      </div>
    </motion.article>
  );
}

function TransactionDrawer({
  transaction,
  busy,
  onClose,
  onCategoryChange,
  onDelete,
}: {
  transaction: Transaction;
  busy: boolean;
  onClose: () => void;
  onCategoryChange: (category: string) => void;
  onDelete: () => void;
}) {
  const positive = transaction.amount_cents >= 0;

  const reduceMotion = useReducedMotion();

  return (
    <motion.div
      className="fixed inset-0 z-50"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduceMotion ? 0 : 0.2 }}
    >
      <motion.button
        type="button"
        aria-label="Close transaction details"
        onClick={onClose}
        className="absolute inset-0 bg-[#14241e]/35 backdrop-blur-[2px]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      />

      <motion.aside
        initial={reduceMotion ? false : { x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ duration: reduceMotion ? 0 : 0.32, ease: [0.22, 1, 0.36, 1] }}
        className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col bg-[#fdfcf8] shadow-2xl"
      >
        <header className="flex items-start justify-between border-b border-[#14241e]/10 px-6 py-5">
          <div className="min-w-0 pr-4">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#167c5a]">
              Transaction details
            </p>

            <h2 className="mt-2 truncate text-xl font-semibold">
              {transaction.merchant_name || transaction.description}
            </h2>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[#14241e]/10 bg-white text-xl"
          >
            ×
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="border-b border-[#14241e]/10 pb-6">
            <p
              className={`text-4xl font-semibold tracking-[-0.05em] ${
                positive ? "text-[#167c5a]" : "text-[#a64b3d]"
              }`}
            >
              {formatCents(transaction.amount_cents)}
            </p>

            <div className="mt-3 flex flex-wrap gap-2">
              <StatusBadge>
                {transaction.source === "plaid" ? "Plaid" : "CSV"}
              </StatusBadge>

              {transaction.pending && (
                <StatusBadge tone="warning">Pending</StatusBadge>
              )}
            </div>
          </div>

          <dl className="divide-y divide-[#14241e]/10">
            <DetailRow
              label="Date"
              value={new Date(
                `${transaction.posted_on}T00:00:00`
              ).toLocaleDateString("en-US", {
                weekday: "long",
                month: "long",
                day: "numeric",
                year: "numeric",
              })}
            />

            <DetailRow
              label="Description"
              value={transaction.description}
            />

            <DetailRow
              label="Merchant"
              value={transaction.merchant_name || "Not available"}
            />

            <DetailRow
              label="Account"
              value={transaction.account_name || "Manual transaction"}
            />

            <DetailRow
              label="Institution"
              value={
                transaction.institution_name || "Not available"
              }
            />

            <DetailRow
              label="Source"
              value={
                transaction.source === "plaid"
                  ? "Plaid synchronization"
                  : "CSV import"
              }
            />
          </dl>

          <div className="mt-6">
            <label className="text-xs font-semibold uppercase tracking-[0.12em] text-[#7a8780]">
              Category
            </label>

            <select
              value={transaction.category}
              disabled={busy}
              onChange={(event) =>
                onCategoryChange(event.target.value)
              }
              className="mt-2 h-11 w-full rounded-xl border border-[#14241e]/10 bg-white px-3 text-sm outline-none focus:border-[#167c5a] disabled:opacity-50"
            >
              {EDITABLE_CATEGORIES.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </div>
        </div>

        <footer className="border-t border-[#14241e]/10 p-6">
          <button
            type="button"
            onClick={onDelete}
            disabled={busy}
            className="h-11 w-full rounded-xl border border-[#a64b3d]/20 bg-white text-sm font-semibold text-[#a64b3d] transition hover:bg-[#fdf1ed] disabled:opacity-50"
          >
            {busy ? "Working..." : "Delete transaction"}
          </button>
        </footer>
      </motion.aside>
    </motion.div>
  );
}

function DetailRow({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="grid gap-1 py-4 sm:grid-cols-[110px_1fr]">
      <dt className="text-xs font-semibold uppercase tracking-[0.1em] text-[#859089]">
        {label}
      </dt>
      <dd className="break-words text-sm font-medium text-[#31423a]">
        {value}
      </dd>
    </div>
  );
}

function StatusBadge({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: "default" | "warning";
}) {
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
        tone === "warning"
          ? "bg-[#f7e8b5] text-[#8b6518]"
          : "bg-[#edf5ee] text-[#476457]"
      }`}
    >
      {children}
    </span>
  );
}

function formatDateHeading(date: string) {
  const value = new Date(`${date}T00:00:00`);
  const today = new Date();
  const yesterday = new Date();

  today.setHours(0, 0, 0, 0);
  yesterday.setDate(today.getDate() - 1);
  yesterday.setHours(0, 0, 0, 0);

  if (value.getTime() === today.getTime()) {
    return "Today";
  }

  if (value.getTime() === yesterday.getTime()) {
    return "Yesterday";
  }

  return value.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year:
      value.getFullYear() === today.getFullYear()
        ? undefined
        : "numeric",
  });
}

function SearchIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}

function FilterIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <path d="M4 6h16M7 12h10M10 18h4" />
    </svg>
  );
}

function MoreIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className="h-5 w-5"
      fill="currentColor"
    >
      <circle cx="5" cy="12" r="1.5" />
      <circle cx="12" cy="12" r="1.5" />
      <circle cx="19" cy="12" r="1.5" />
    </svg>
  );
}
