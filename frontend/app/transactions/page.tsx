"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import AppSidebar from "../components/AppSidebar";
import ConfirmationModal from "../components/ConfirmationModal";
import Toast from "../components/Toast";
import {
  CardSkeleton,
  EmptyState,
  PageError,
  PageLoading,
} from "../components/PageFeedback";
import {
  api,
  FinancialAccount,
  formatCents,
  session,
  Transaction,
} from "../lib/api";
import { downloadCsv, transactionsToCsv } from "../lib/csv";
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

function sourceLabel(source: string): string {
  if (source === "plaid") return "Plaid";
  if (source === "manual") return "Manual";
  return "CSV";
}

type Density = "compact" | "comfortable";

type CategoryUndoItem = {
  transactionId: number;
  previousCategory: string;
  newCategory: string;
};

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
  const [duplicatesOnly, setDuplicatesOnly] = useState(false);
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
  const [undoTransactions, setUndoTransactions] = useState<Transaction[]>([]);
  const [categoryUndo, setCategoryUndo] = useState<CategoryUndoItem[]>([]);
  const deleteTimerRef = useRef<number | null>(null);
  const categoryUndoTimerRef = useRef<number | null>(null);
  const categoryUndoGenerationRef = useRef(0);
  const pendingDeleteBatchRef = useRef<Transaction[]>([]);
  const [pendingDelete, setPendingDelete] = useState<
    | { type: "single"; transaction: Transaction }
    | { type: "bulk"; transactionIds: number[] }
    | null
  >(null);
  const [formOpen, setFormOpen] = useState<"create" | "edit" | null>(
    null
  );
  const [formTransactionId, setFormTransactionId] = useState<
    number | null
  >(null);
  const [formDate, setFormDate] = useState("");
  const [formDescription, setFormDescription] = useState("");
  const [formMerchant, setFormMerchant] = useState("");
  const [formCategory, setFormCategory] = useState(
    EDITABLE_CATEGORIES[0]
  );
  const [formType, setFormType] = useState<"expense" | "income">(
    "expense"
  );
  const [formAmount, setFormAmount] = useState("");
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    return () => {
      if (deleteTimerRef.current !== null) {
        window.clearTimeout(deleteTimerRef.current);
      }

      if (categoryUndoTimerRef.current !== null) {
        window.clearTimeout(categoryUndoTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!message) return;

    const timeout = window.setTimeout(() => {
      setMessage("");
    }, 5_000);

    return () => window.clearTimeout(timeout);
  }, [message]);

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
          duplicates_only: duplicatesOnly || undefined,
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
    duplicatesOnly,
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
    duplicatesOnly,
  ].filter(Boolean).length;

  const visibleIds = visibleTransactions.map(({ id }) => id);
  const allVisibleSelected =
    visibleIds.length > 0 &&
    visibleIds.every((id) => selectedIds.includes(id));

  function clearCategoryUndo() {
    categoryUndoGenerationRef.current += 1;

    if (categoryUndoTimerRef.current !== null) {
      window.clearTimeout(categoryUndoTimerRef.current);
      categoryUndoTimerRef.current = null;
    }

    setCategoryUndo([]);
  }

  function showCategoryUndo(updates: CategoryUndoItem[]) {
    clearCategoryUndo();
    setUndoTransactions([]);
    setCategoryUndo(updates);

    const generation = categoryUndoGenerationRef.current;
    categoryUndoTimerRef.current = window.setTimeout(() => {
      if (categoryUndoGenerationRef.current !== generation) return;

      categoryUndoTimerRef.current = null;
      setCategoryUndo([]);
    }, 6_000);
  }

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
        duplicates_only: duplicatesOnly || undefined,
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

    const previousTransaction = transactions.find(
      (transaction) => transaction.id === transactionId
    );

    if (!previousTransaction) return;

    clearCategoryUndo();
    setUndoTransactions([]);
    setBusyId(transactionId);
    setError("");
    setMessage("");

    try {
      const updated = await api.updateTransaction(
        userId,
        transactionId,
        { category: nextCategory }
      );

      setTransactions((current) =>
        current.map((transaction) =>
          transaction.id === updated.id ? updated : transaction
        )
      );

      showCategoryUndo([
        {
          transactionId,
          previousCategory: previousTransaction.category,
          newCategory: updated.category,
        },
      ]);
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

  function confirmSingleDelete(transaction: Transaction) {
    if (!userId) return;

    scheduleDeletion([transaction]);
    setPendingDelete(null);
    setMenuId(null);
  }

  async function updateSelectedCategory() {
    if (!userId || !bulkCategory || selectedIds.length === 0) return;

    setBulkBusy(true);
    setError("");
    setMessage("");
    clearCategoryUndo();
    setUndoTransactions([]);

    try {
      const loadedIds = new Set(
        transactions.map((transaction) => transaction.id)
      );
      const hasStaleSelection = selectedIds.some(
        (transactionId) => !loadedIds.has(transactionId)
      );

      if (hasStaleSelection) {
        setSelectedIds([]);

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
          duplicates_only: duplicatesOnly || undefined,
          page,
          page_size: PAGE_SIZE,
        });

        setTransactions(refreshed.items);
        setTotal(refreshed.total);
        setTotalPages(refreshed.total_pages);
        setTotalIncome(refreshed.total_income_cents);
        setTotalSpending(refreshed.total_spending_cents);
        setNet(refreshed.net_cents);
        setExpandedId(null);
        setError(
          "Your selection was out of date. The transaction page was " +
            "refreshed; please select the transactions again."
        );
        return;
      }

      const previousCategories = selectedIds.map((transactionId) => {
        const transaction = transactions.find(
          (item) => item.id === transactionId
        );

        return {
          transactionId,
          previousCategory: transaction!.category,
        };
      });

      const updatedTransactions =
        await api.bulkUpdateTransactionCategory(
          userId,
          selectedIds,
          bulkCategory
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
      const updatedByIdForUndo = new Map(
        updatedTransactions.map((transaction) => [
          transaction.id,
          transaction.category,
        ])
      );
      showCategoryUndo(
        previousCategories.map((update) => ({
          ...update,
          newCategory:
            updatedByIdForUndo.get(update.transactionId) ?? bulkCategory,
        }))
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

  function confirmBulkDelete(transactionIds: number[]) {
    if (!userId || transactionIds.length === 0) return;

    const selectedTransactions = transactions.filter((transaction) =>
      transactionIds.includes(transaction.id)
    );

    scheduleDeletion(selectedTransactions);
    setPendingDelete(null);
    setSelectedIds([]);
    setBulkCategory("");
  }

  function scheduleDeletion(
    deletedTransactions: Transaction[]
  ) {
    if (!userId || deletedTransactions.length === 0) return;

    clearCategoryUndo();

    if (deleteTimerRef.current !== null) {
      window.clearTimeout(deleteTimerRef.current);
      deleteTimerRef.current = null;
    }

    const deletedIds = new Set(
      deletedTransactions.map((transaction) => transaction.id)
    );

    const mergedBatch = [
      ...pendingDeleteBatchRef.current.filter(
        (transaction) => !deletedIds.has(transaction.id)
      ),
      ...deletedTransactions,
    ];
    pendingDeleteBatchRef.current = mergedBatch;

    setError("");
    setUndoTransactions(mergedBatch);
    setTransactions((current) =>
      current.filter((transaction) => !deletedIds.has(transaction.id))
    );
    setSelectedIds((current) =>
      current.filter((id) => !deletedIds.has(id))
    );

    if (expandedId && deletedIds.has(expandedId)) {
      setExpandedId(null);
    }

    const removedIncome = deletedTransactions.reduce(
      (sum, transaction) =>
        sum +
        (transaction.amount_cents > 0
          ? transaction.amount_cents
          : 0),
      0
    );
    const removedSpending = deletedTransactions.reduce(
      (sum, transaction) =>
        sum +
        (transaction.amount_cents < 0
          ? Math.abs(transaction.amount_cents)
          : 0),
      0
    );
    const removedNet = deletedTransactions.reduce(
      (sum, transaction) => sum + transaction.amount_cents,
      0
    );

    setTotal((current) =>
      Math.max(0, current - deletedTransactions.length)
    );
    setTotalIncome((current) => current - removedIncome);
    setTotalSpending((current) => current - removedSpending);
    setNet((current) => current - removedNet);
    setMessage("");

    deleteTimerRef.current = window.setTimeout(async () => {
      const batchToDelete = pendingDeleteBatchRef.current;
      pendingDeleteBatchRef.current = [];
      setUndoTransactions([]);
      setMessage("");
      deleteTimerRef.current = null;
      setBulkBusy(true);

      try {
        await api.bulkDeleteTransactions(
          userId,
          batchToDelete.map((transaction) => transaction.id)
        );
      } catch (err) {
        restoreDeletedTransactions(batchToDelete);
        setError(
          err instanceof Error
            ? err.message
            : "Unable to delete transactions"
        );
      } finally {
        setBulkBusy(false);
      }
    }, 6_000);
  }

  function restoreDeletedTransactions(
    deletedTransactions = undoTransactions
  ) {
    if (deletedTransactions.length === 0) return;

    if (deleteTimerRef.current !== null) {
      window.clearTimeout(deleteTimerRef.current);
      deleteTimerRef.current = null;
    }

    pendingDeleteBatchRef.current = [];

    setTransactions((current) => {
      const currentIds = new Set(
        current.map((transaction) => transaction.id)
      );

      return [...current, ...deletedTransactions]
        .filter((transaction) => {
          if (currentIds.has(transaction.id)) {
            return false;
          }

          currentIds.add(transaction.id);
          return true;
        })
        .sort((a, b) => {
          const dateComparison = b.posted_on.localeCompare(a.posted_on);
          return dateComparison || b.id - a.id;
        });
    });

    const restoredIncome = deletedTransactions.reduce(
      (sum, transaction) =>
        sum +
        (transaction.amount_cents > 0
          ? transaction.amount_cents
          : 0),
      0
    );
    const restoredSpending = deletedTransactions.reduce(
      (sum, transaction) =>
        sum +
        (transaction.amount_cents < 0
          ? Math.abs(transaction.amount_cents)
          : 0),
      0
    );
    const restoredNet = deletedTransactions.reduce(
      (sum, transaction) => sum + transaction.amount_cents,
      0
    );

    setTotal((current) => current + deletedTransactions.length);
    setTotalIncome((current) => current + restoredIncome);
    setTotalSpending((current) => current + restoredSpending);
    setNet((current) => current + restoredNet);
    setUndoTransactions([]);
    setMessage("Deletion undone.");
  }

  async function restorePreviousCategories() {
    if (!userId || categoryUndo.length === 0) return;

    const undoItems = categoryUndo;
    clearCategoryUndo();
    setBulkBusy(true);
    setError("");
    setMessage("");

    try {
      const restoredTransactions =
        await api.bulkUpdateTransactionCategories(
          userId,
          undoItems.map((item) => ({
            transaction_id: item.transactionId,
            category: item.previousCategory,
          }))
        );
      const restoredById = new Map(
        restoredTransactions.map((transaction) => [
          transaction.id,
          transaction,
        ])
      );

      setTransactions((current) =>
        current.map(
          (transaction) =>
            restoredById.get(transaction.id) ?? transaction
        )
      );
      setMessage("Category change undone.");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to undo category change"
      );
    } finally {
      setBulkBusy(false);
    }
  }

  async function refreshCurrentSearch(targetPage: number) {
    if (!userId) return;

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
      duplicates_only: duplicatesOnly || undefined,
      page: targetPage,
      page_size: PAGE_SIZE,
    });

    setTransactions(refreshed.items);
    setTotal(refreshed.total);
    setTotalPages(refreshed.total_pages);
    setTotalIncome(refreshed.total_income_cents);
    setTotalSpending(refreshed.total_spending_cents);
    setNet(refreshed.net_cents);
    setPage(targetPage);
  }

  function openCreateForm() {
    setFormOpen("create");
    setFormTransactionId(null);
    setFormDate(new Date().toISOString().split("T")[0]);
    setFormDescription("");
    setFormMerchant("");
    setFormCategory(EDITABLE_CATEGORIES[0]);
    setFormType("expense");
    setFormAmount("");
    setFormError("");
  }

  function openEditForm(transaction: Transaction) {
    setMenuId(null);
    setFormOpen("edit");
    setFormTransactionId(transaction.id);
    setFormDate(transaction.posted_on);
    setFormDescription(transaction.description);
    setFormMerchant(transaction.merchant_name || "");
    setFormCategory(transaction.category);
    setFormType(
      transaction.amount_cents >= 0 ? "income" : "expense"
    );
    setFormAmount(
      (Math.abs(transaction.amount_cents) / 100).toFixed(2)
    );
    setFormError("");
  }

  function closeForm() {
    if (formBusy) return;

    setFormOpen(null);
    setFormTransactionId(null);
  }

  async function submitTransactionForm() {
    if (!userId || formBusy || !formOpen) return;

    const description = formDescription.trim();
    const magnitude = Math.round(Number(formAmount) * 100);

    if (!formDate) {
      setFormError("Choose a transaction date.");
      return;
    }

    if (!description) {
      setFormError("Enter a description.");
      return;
    }

    if (!Number.isFinite(magnitude) || magnitude <= 0) {
      setFormError("Enter an amount greater than $0.");
      return;
    }

    const amountCents =
      formType === "expense" ? -magnitude : magnitude;

    setFormBusy(true);
    setFormError("");

    try {
      if (formOpen === "create") {
        await api.createTransaction(userId, {
          posted_on: formDate,
          description,
          merchant_name: formMerchant.trim() || null,
          amount_cents: amountCents,
          category: formCategory,
        });
        setMessage("Transaction added.");
      } else if (formTransactionId !== null) {
        await api.updateTransaction(userId, formTransactionId, {
          posted_on: formDate,
          description,
          merchant_name: formMerchant.trim() || null,
          amount_cents: amountCents,
          category: formCategory,
        });
        setMessage("Transaction updated.");
      }

      const nextPage = formOpen === "create" ? 1 : page;
      setFormOpen(null);
      setFormTransactionId(null);
      setExpandedId(null);
      await refreshCurrentSearch(nextPage);
    } catch (err) {
      setFormError(
        err instanceof Error
          ? err.message
          : "Unable to save transaction"
      );
    } finally {
      setFormBusy(false);
    }
  }

  async function exportFilteredTransactions() {
    if (!userId || exporting) return;

    setExporting(true);
    setError("");
    setMessage("");

    try {
      const baseParams = {
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
        duplicates_only: duplicatesOnly || undefined,
      };

      const first = await api.searchTransactions(userId, {
        ...baseParams,
        page: 1,
        page_size: 100,
      });

      const items = [...first.items];

      for (
        let nextPage = 2;
        nextPage <= first.total_pages;
        nextPage += 1
      ) {
        const chunk = await api.searchTransactions(userId, {
          ...baseParams,
          page: nextPage,
          page_size: 100,
        });
        items.push(...chunk.items);
      }

      const csv = transactionsToCsv(items);

      downloadCsv(
        `discero-transactions-${
          new Date().toISOString().split("T")[0]
        }.csv`,
        csv
      );

      setMessage(
        items.length
          ? `Exported ${items.length.toLocaleString()} transactions matching the current filters.`
          : "No transactions matched the current filters."
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to export transactions"
      );
    } finally {
      setExporting(false);
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
    setDuplicatesOnly(false);
    setPage(1);
  }

  return (
    <main className="min-h-screen bg-[#F5F1EA] text-[#181713]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-56 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[1500px]">
          <Reveal>
          <header className="flex flex-col gap-5 border-b border-[#181713]/10 pb-5 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
                Money movement
              </p>

              <h1 className="mt-1 text-[32px] font-semibold tracking-[-0.03em]">
                Transactions
              </h1>

              <p className="mt-1 text-sm text-[#706961]">
                Every movement, in context.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={openCreateForm}
                disabled={!userId}
                className="discero-button-secondary inline-flex min-h-11 items-center justify-center rounded-xl border px-4 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50"
              >
                Add transaction
              </button>

              <button
                type="button"
                onClick={exportFilteredTransactions}
                disabled={!userId || exporting}
                className="inline-flex min-h-11 items-center justify-center rounded-xl px-3 text-sm font-semibold text-[#706961] transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                {exporting ? "Preparing export..." : "Export CSV"}
              </button>

              <button
                type="button"
                onClick={syncTransactions}
                disabled={!userId || syncing}
                aria-busy={syncing}
                className="discero-button-primary inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold transition disabled:cursor-not-allowed"
              >
                {syncing && (
                  <span
                    aria-hidden="true"
                    className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent motion-reduce:animate-none"
                  />
                )}
                {syncing ? "Syncing…" : "Sync transactions"}
              </button>
            </div>
          </header>
          </Reveal>

          <Reveal delay={0.06}>
          {loading ? (
            <section className="mt-5">
              <CardSkeleton count={4} />
            </section>
          ) : (
          <section className="mt-5 grid overflow-hidden border-y border-[#181713]/10 bg-[#FFFCF7] sm:grid-cols-2 xl:grid-cols-4 xl:divide-x xl:divide-[#181713]/10">
            <SummaryItem
              label="Transactions"
              value={total}
              format={(value) => Math.round(value).toLocaleString()}
            />
            <SummaryItem
              label="Income"
              value={totalIncome}
              format={formatCents}
              valueClassName="text-[#58715A]"
            />
            <SummaryItem
              label="Spending"
              value={totalSpending}
              format={(value) => formatCents(-value)}
              valueClassName="text-[#A25543]"
            />
            <SummaryItem
              label="Net activity"
              value={net}
              format={formatCents}
              valueClassName={
                net >= 0 ? "text-[#58715A]" : "text-[#A25543]"
              }
            />
          </section>
          )}
          </Reveal>

          {error && (
            <div className="mt-4">
              <PageError
                message={error}
                onRetry={
                  userId ? () => void refreshCurrentSearch(page) : undefined
                }
              />
            </div>
          )}

          <section className="sticky top-0 z-30 mt-5 border-y border-[#181713]/10 bg-[#F5F1EA]/95 py-3 backdrop-blur lg:top-0">
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
                    aria-label="Search transactions"
                    placeholder="Search merchant, description, category, or account"
                    className="h-11 w-full rounded-xl border border-[#181713]/10 bg-white pl-11 pr-4 text-sm outline-none transition placeholder:text-[#8A8178] focus:border-[#6E4B63]"
                  />
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setShowFilters((current) => !current)}
                    aria-expanded={showFilters}
                    className={`inline-flex h-11 items-center gap-2 rounded-xl border px-4 text-sm font-semibold transition ${
                      showFilters || activeFilterCount > 0
                        ? "border-[#6E4B63] bg-[#EDE5DE] text-[#6E4B63]"
                        : "border-[#181713]/10 bg-white hover:bg-[#F8F4EE]"
                    }`}
                  >
                    <FilterIcon />
                    Filters
                    {activeFilterCount > 0 && (
                      <span className="rounded-full bg-[#6E4B63] px-2 py-0.5 text-xs text-white">
                        {activeFilterCount}
                      </span>
                    )}
                  </button>

                  <button
                    type="button"
                    role="switch"
                    aria-checked={duplicatesOnly}
                    onClick={() => {
                      setDuplicatesOnly((current) => !current);
                      setPage(1);
                    }}
                    className={`inline-flex h-11 items-center gap-2 rounded-xl border px-4 text-sm font-semibold transition ${
                      duplicatesOnly
                        ? "border-[#6E4B63] bg-[#EDE5DE] text-[#6E4B63]"
                        : "border-[#181713]/10 bg-white hover:bg-[#F8F4EE]"
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className={`relative h-5 w-9 rounded-full transition ${
                        duplicatesOnly ? "bg-[#6E4B63]" : "bg-[#c9cfcc]"
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition ${
                          duplicatesOnly ? "left-[18px]" : "left-0.5"
                        }`}
                      />
                    </span>
                    Potential duplicates
                  </button>

                  <div className="flex h-11 items-center rounded-xl border border-[#14241e]/10 bg-white p-1">
                    <button
                      type="button"
                      onClick={() => setDensity("compact")}
                      aria-pressed={density === "compact"}
                      className={`h-full rounded-lg px-3 text-xs font-semibold transition ${
                        density === "compact"
                          ? "discero-segment-selected"
                          : "text-[#706961]"
                      }`}
                    >
                      Compact
                    </button>

                    <button
                      type="button"
                      onClick={() => setDensity("comfortable")}
                      aria-pressed={density === "comfortable"}
                      className={`h-full rounded-lg px-3 text-xs font-semibold transition ${
                        density === "comfortable"
                          ? "discero-segment-selected"
                          : "text-[#706961]"
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
                  className="grid overflow-hidden gap-2 bg-[#FFFCF7] py-3 sm:grid-cols-2 xl:grid-cols-[1fr_1fr_1.4fr_1fr_1fr_auto]"
                >
                  <FilterSelect
                    value={category}
                    onChange={(value) => {
                      setCategory(value);
                      setPage(1);
                    }}
                    ariaLabel="Filter by category"
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
                    ariaLabel="Filter by source"
                    options={[
                      { value: "All", label: "All sources" },
                      { value: "Plaid", label: "Plaid" },
                      { value: "CSV", label: "CSV" },
                      { value: "Manual", label: "Manual" },
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
                    ariaLabel="Filter by account"
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
                    className="h-10 rounded-xl border border-[#181713]/10 bg-[#F8F4EE] px-3 text-sm outline-none focus:border-[#6E4B63]"
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
                    className="h-10 rounded-xl border border-[#181713]/10 bg-[#F8F4EE] px-3 text-sm outline-none focus:border-[#6E4B63]"
                  />

                  <button
                    type="button"
                    onClick={clearFilters}
                    className="h-10 rounded-xl px-4 text-sm font-semibold text-[#6E4B63] transition hover:bg-[#EDE7E1]"
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
              className="mt-4 flex flex-col gap-3 rounded-2xl border border-[#6E4B63]/20 bg-[#EDE5DE] p-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <p className="text-sm font-semibold text-[#126a4d]">
                {selectedIds.length} selected
              </p>

              <div className="flex flex-col gap-2 sm:flex-row">
                <select
                  aria-label="Bulk category"
                  value={bulkCategory}
                  disabled={bulkBusy}
                  onChange={(event) =>
                    setBulkCategory(event.target.value)
                  }
                  className="h-10 rounded-xl border border-[#6E4B63]/20 bg-white px-3 text-sm outline-none disabled:opacity-50"
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
                  className="discero-button-primary h-10 rounded-xl px-4 text-sm font-semibold"
                >
                  Apply category
                </button>

                <button
                  type="button"
                  onClick={deleteSelectedTransactions}
                  disabled={bulkBusy}
                  className="discero-button-destructive h-10 rounded-xl border px-4 text-sm font-semibold disabled:opacity-40"
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

          <section className="mt-4 overflow-hidden border-y border-[#181713]/10 bg-[#FFFCF7]">
            <div className="hidden grid-cols-[44px_minmax(240px,1.8fr)_minmax(160px,1fr)_150px_130px_48px] items-center gap-4 border-b border-[#181713]/10 bg-[#F8F4EE] px-4 py-3 text-xs font-semibold uppercase tracking-[0.12em] text-[#7a8780] xl:grid">
              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleVisibleSelection}
                  aria-label="Select visible transactions"
                  className="h-4 w-4 accent-[#6E4B63]"
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
              error ? null : (
              <div className="p-5">
                <EmptyState
                  title={
                    duplicatesOnly
                      ? "No potential duplicates found"
                      : total === 0 && activeFilterCount === 0 && !search.trim()
                      ? "No transactions yet"
                      : "No transactions match your filters"
                  }
                  description={
                    duplicatesOnly
                      ? "No transactions match another transaction by date, amount, and merchant or description."
                      : total === 0 && activeFilterCount === 0 && !search.trim()
                      ? "Upload a CSV file, synchronize a connected account, or add a transaction manually."
                      : "Adjust or clear your current filters to see more transactions."
                  }
                  actionLabel={
                    duplicatesOnly
                      ? undefined
                      : total === 0 &&
                        activeFilterCount === 0 &&
                        !search.trim()
                      ? "Add transaction"
                      : "Clear filters"
                  }
                  onAction={
                    duplicatesOnly
                      ? undefined
                      : total === 0 &&
                        activeFilterCount === 0 &&
                        !search.trim()
                      ? openCreateForm
                      : clearFilters
                  }
                />
              </div>
              )
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
                  onEdit={openEditForm}
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
                  className="discero-button-secondary h-10 rounded-xl border px-4 text-sm font-semibold transition disabled:opacity-40"
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
                  className="discero-button-secondary h-10 rounded-xl border px-4 text-sm font-semibold transition disabled:opacity-40"
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
            onEdit={() => openEditForm(activeTransaction)}
            onDelete={() => deleteTransaction(activeTransaction)}
          />
        )}
      </AnimatePresence>

      <Toast
        message={
          categoryUndo.length > 0 || undoTransactions.length > 0
            ? ""
            : message
        }
        type="success"
        onClose={() => setMessage("")}
      />

      <Toast
        message={
          categoryUndo.length > 0
            ? categoryUndo.length === 1
              ? "Category updated."
              : `${categoryUndo.length} transactions updated.`
            : undoTransactions.length === 0
              ? ""
              : undoTransactions.length === 1
                ? "Transaction deleted."
                : `${undoTransactions.length} transactions deleted.`
        }
        type="success"
        actionLabel={
          categoryUndo.length > 0 || undoTransactions.length > 0
            ? "Undo"
            : undefined
        }
        onAction={
          categoryUndo.length > 0
            ? () => void restorePreviousCategories()
            : undoTransactions.length > 0
            ? () => restoreDeletedTransactions()
            : undefined
        }
        onClose={() => {
          if (categoryUndo.length > 0) {
            clearCategoryUndo();
          } else {
            setUndoTransactions([]);
          }
        }}
      />

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
                ? "This transaction will be permanently removed from Discero."
                : "All selected transactions will be permanently removed from Discero."
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

      <AnimatePresence>
        {formOpen && (
          <TransactionFormModal
            mode={formOpen}
            date={formDate}
            description={formDescription}
            merchant={formMerchant}
            category={formCategory}
            type={formType}
            amount={formAmount}
            busy={formBusy}
            error={formError}
            onDateChange={setFormDate}
            onDescriptionChange={setFormDescription}
            onMerchantChange={setFormMerchant}
            onCategoryChange={setFormCategory}
            onTypeChange={setFormType}
            onAmountChange={setFormAmount}
            onCancel={closeForm}
            onSubmit={() => void submitTransactionForm()}
          />
        )}
      </AnimatePresence>
    </main>
  );
}

function SummaryItem({
  label,
  value,
  format,
  valueClassName = "",
}: {
  label: string;
  value: number;
  format: (value: number) => string;
  valueClassName?: string;
}) {
  return (
    <article className="border-b border-[#181713]/10 px-5 py-4 last:border-b-0 sm:[&:nth-child(3)]:border-b-0 sm:[&:nth-child(4)]:border-b-0 xl:border-b-0">
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#8A8178]">
        {label}
      </p>
      <p className={`mt-1 text-xl font-semibold tracking-[-0.03em] tabular-nums ${valueClassName}`}>
        {format(value)}
      </p>
    </article>
  );
}

function FilterSelect({
  value,
  onChange,
  options,
  disabled = false,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
  disabled?: boolean;
  ariaLabel: string;
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
      aria-label={ariaLabel}
      className="h-10 min-w-0 rounded-xl border border-[#181713]/10 bg-[#F8F4EE] px-3 text-sm outline-none focus:border-[#6E4B63] disabled:cursor-not-allowed disabled:opacity-50"
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
  onEdit,
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
  onEdit: (transaction: Transaction) => void;
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
      className="border-b border-[#181713]/10 last:border-b-0"
    >
      <div className="flex items-center justify-between bg-[#F8F4EE] px-4 py-2.5">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#706961]">
          {formatDateHeading(date)}
        </p>

        <p
          className={`text-sm font-semibold tabular-nums ${
            dailyTotal >= 0 ? "text-[#58715A]" : "text-[#A25543]"
          }`}
        >
          {formatCents(dailyTotal)}
        </p>
      </div>

      {transactions.map((transaction, index) => (
        <TransactionListRow
          key={transaction.id}
          transaction={transaction}
          density={density}
          busy={busyId === transaction.id}
          selected={selectedIds.includes(transaction.id)}
          menuOpen={menuId === transaction.id}
          index={index}
          onSelect={() => onSelect(transaction.id)}
          onOpen={() => onOpen(transaction.id)}
          onMenuChange={(open) =>
            onMenuChange(open ? transaction.id : null)
          }
          onCategoryChange={(nextCategory) =>
            onCategoryChange(transaction.id, nextCategory)
          }
          onEdit={() => onEdit(transaction)}
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
  index,
  onSelect,
  onOpen,
  onMenuChange,
  onCategoryChange,
  onEdit,
  onDelete,
}: {
  transaction: Transaction;
  density: Density;
  busy: boolean;
  selected: boolean;
  menuOpen: boolean;
  index: number;
  onSelect: () => void;
  onOpen: () => void;
  onMenuChange: (open: boolean) => void;
  onCategoryChange: (category: string) => void;
  onEdit: () => void;
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
      transition={{ duration: reduceMotion ? 0 : 0.28, delay: reduceMotion ? 0 : index * 0.04 }}
      className={`relative grid gap-3 border-t border-[#181713]/5 px-4 transition first:border-t-0 hover:bg-[#FBF8F3] xl:grid-cols-[44px_minmax(240px,1.8fr)_minmax(160px,1fr)_150px_130px_48px] xl:items-center ${padding}`}
    >
      <label className="absolute left-4 top-4 flex xl:static">
        <input
          type="checkbox"
          checked={selected}
          onChange={onSelect}
          aria-label={`Select ${transaction.description}`}
          className="h-4 w-4 accent-[#6E4B63]"
        />
      </label>

      <button
        type="button"
        onClick={onOpen}
        className="min-w-0 pl-8 text-left xl:pl-0"
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

          <span className="rounded-full bg-[#EDE7E1] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#6E4B63]">
            {sourceLabel(transaction.source)}
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
              : transaction.source === "manual"
              ? "Manually added"
              : "CSV import")}
        </p>
      </button>

      <select
        aria-label={`Category for ${transaction.description}`}
        value={transaction.category}
        disabled={busy}
        onChange={(event) => onCategoryChange(event.target.value)}
        onClick={(event) => event.stopPropagation()}
        className="h-9 rounded-xl border border-[#181713]/10 bg-[#F8F4EE] px-3 text-xs font-medium outline-none focus:border-[#6E4B63] disabled:opacity-50"
      >
        {EDITABLE_CATEGORIES.map((item) => (
          <option key={item}>{item}</option>
        ))}
      </select>

      <button
        type="button"
        onClick={onOpen}
        aria-label={`Amount ${formatCents(transaction.amount_cents)} for ${
          transaction.merchant_name || transaction.description
        }`}
        className={`text-left text-base font-semibold xl:text-right ${
          positive ? "text-[#58715A]" : "text-[#A25543]"
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
          aria-haspopup="menu"
          aria-expanded={menuOpen}
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
              onClick={() => {
                onEdit();
                onMenuChange(false);
              }}
              className="w-full px-4 py-2.5 text-left text-sm font-medium hover:bg-[#f7f4ed]"
            >
              Edit
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
  onEdit,
  onDelete,
}: {
  transaction: Transaction;
  busy: boolean;
  onClose: () => void;
  onCategoryChange: (category: string) => void;
  onEdit: () => void;
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
        role="dialog"
        aria-modal="true"
        aria-labelledby="transaction-drawer-title"
        initial={reduceMotion ? false : { x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ duration: reduceMotion ? 0 : 0.32, ease: [0.22, 1, 0.36, 1] }}
        className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col bg-[#fdfcf8] shadow-2xl"
      >
        <header className="flex items-start justify-between border-b border-[#14241e]/10 px-6 py-5">
          <div className="min-w-0 pr-4">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#6E4B63]">
              Transaction details
            </p>

            <h2
              id="transaction-drawer-title"
              className="mt-2 truncate text-xl font-semibold"
            >
              {transaction.merchant_name || transaction.description}
            </h2>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close transaction details"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[#14241e]/10 bg-white text-xl"
          >
            <span aria-hidden="true">×</span>
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="border-b border-[#14241e]/10 pb-6">
            <p
              className={`text-4xl font-semibold tracking-[-0.05em] ${
                positive ? "text-[#58715A]" : "text-[#A25543]"
              }`}
            >
              {formatCents(transaction.amount_cents)}
            </p>

            <div className="mt-3 flex flex-wrap gap-2">
              <StatusBadge>
                {sourceLabel(transaction.source)}
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
                  : transaction.source === "manual"
                  ? "Manually added"
                  : "CSV import"
              }
            />
          </dl>

          <div className="mt-6">
            <label className="block text-xs font-semibold uppercase tracking-[0.12em] text-[#7a8780]">
              Category
              <select
                value={transaction.category}
                disabled={busy}
                onChange={(event) =>
                  onCategoryChange(event.target.value)
                }
                className="mt-2 h-11 w-full rounded-xl border border-[#181713]/10 bg-white px-3 text-sm font-normal normal-case tracking-normal outline-none focus:border-[#6E4B63] disabled:opacity-50"
              >
                {EDITABLE_CATEGORIES.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <footer className="flex flex-col gap-3 border-t border-[#14241e]/10 p-6">
          <button
            type="button"
            onClick={onEdit}
            disabled={busy}
            className="discero-button-secondary h-11 w-full rounded-xl border text-sm font-semibold transition disabled:opacity-50"
          >
            Edit transaction
          </button>

          <button
            type="button"
            onClick={onDelete}
            disabled={busy}
            className="discero-button-destructive h-11 w-full rounded-xl border text-sm font-semibold transition disabled:opacity-50"
          >
            {busy ? "Working..." : "Delete transaction"}
          </button>
        </footer>
      </motion.aside>
    </motion.div>
  );
}

function TransactionFormModal({
  mode,
  date,
  description,
  merchant,
  category,
  type,
  amount,
  busy,
  error,
  onDateChange,
  onDescriptionChange,
  onMerchantChange,
  onCategoryChange,
  onTypeChange,
  onAmountChange,
  onCancel,
  onSubmit,
}: {
  mode: "create" | "edit";
  date: string;
  description: string;
  merchant: string;
  category: string;
  type: "expense" | "income";
  amount: string;
  busy: boolean;
  error: string;
  onDateChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onMerchantChange: (value: string) => void;
  onCategoryChange: (value: string) => void;
  onTypeChange: (value: "expense" | "income") => void;
  onAmountChange: (value: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const reduceMotion = useReducedMotion();

  return (
    <motion.div
      className="fixed inset-0 z-[60] flex items-center justify-center px-4 py-8"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduceMotion ? 0 : 0.18 }}
    >
      <button
        type="button"
        aria-label="Close transaction form"
        onClick={onCancel}
        disabled={busy}
        className="absolute inset-0 bg-[#14241e]/45 backdrop-blur-[3px]"
      />

      <motion.form
        role="dialog"
        aria-modal="true"
        aria-label={
          mode === "create" ? "Add transaction" : "Edit transaction"
        }
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
        initial={
          reduceMotion ? false : { opacity: 0, scale: 0.96, y: 16 }
        }
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 16 }}
        transition={{
          duration: reduceMotion ? 0 : 0.22,
          ease: [0.22, 1, 0.36, 1],
        }}
        className="relative max-h-[90vh] w-full max-w-md overflow-y-auto rounded-[28px] border border-[#14241e]/10 bg-[#fdfcf8] p-6 shadow-[0_30px_90px_rgba(20,36,30,0.28)] sm:p-7"
      >
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
          {mode === "create" ? "New transaction" : "Edit transaction"}
        </p>

        <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em]">
          {mode === "create"
            ? "Add a transaction"
            : "Update transaction"}
        </h2>

        <div className="mt-6 grid gap-4">
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => onTypeChange("expense")}
              aria-pressed={type === "expense"}
              disabled={busy}
              className={`h-10 rounded-xl border text-sm font-semibold transition disabled:opacity-50 ${
                type === "expense"
                  ? "border-[#a64b3d] bg-[#fdf1ed] text-[#a64b3d]"
                  : "border-[#14241e]/10 bg-white text-[#66746e]"
              }`}
            >
              Expense
            </button>

            <button
              type="button"
              onClick={() => onTypeChange("income")}
              aria-pressed={type === "income"}
              disabled={busy}
              className={`h-10 rounded-xl border text-sm font-semibold transition disabled:opacity-50 ${
                type === "income"
                  ? "border-[#6E4B63] bg-[#EDE5DE] text-[#6E4B63]"
                  : "border-[#14241e]/10 bg-white text-[#66746e]"
              }`}
            >
              Income
            </button>
          </div>

          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-[0.1em] text-[#7a8780]">
              Amount
            </span>
            <input
              type="number"
              inputMode="decimal"
              min="0.01"
              step="0.01"
              value={amount}
              onChange={(event) => onAmountChange(event.target.value)}
              disabled={busy}
              className="mt-1 h-11 w-full rounded-xl border border-[#181713]/10 bg-white px-3 text-sm outline-none focus:border-[#6E4B63] disabled:opacity-50"
            />
          </label>

          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-[0.1em] text-[#7a8780]">
              Date
            </span>
            <input
              type="date"
              value={date}
              onChange={(event) => onDateChange(event.target.value)}
              disabled={busy}
              className="mt-1 h-11 w-full rounded-xl border border-[#181713]/10 bg-white px-3 text-sm outline-none focus:border-[#6E4B63] disabled:opacity-50"
            />
          </label>

          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-[0.1em] text-[#7a8780]">
              Description
            </span>
            <input
              type="text"
              value={description}
              onChange={(event) =>
                onDescriptionChange(event.target.value)
              }
              disabled={busy}
              maxLength={512}
              className="mt-1 h-11 w-full rounded-xl border border-[#181713]/10 bg-white px-3 text-sm outline-none focus:border-[#6E4B63] disabled:opacity-50"
            />
          </label>

          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-[0.1em] text-[#7a8780]">
              Merchant (optional)
            </span>
            <input
              type="text"
              value={merchant}
              onChange={(event) => onMerchantChange(event.target.value)}
              disabled={busy}
              maxLength={255}
              className="mt-1 h-11 w-full rounded-xl border border-[#181713]/10 bg-white px-3 text-sm outline-none focus:border-[#6E4B63] disabled:opacity-50"
            />
          </label>

          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-[0.1em] text-[#7a8780]">
              Category
            </span>
            <select
              value={category}
              onChange={(event) => onCategoryChange(event.target.value)}
              disabled={busy}
              className="mt-1 h-11 w-full rounded-xl border border-[#181713]/10 bg-white px-3 text-sm outline-none focus:border-[#6E4B63] disabled:opacity-50"
            >
              {EDITABLE_CATEGORIES.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
        </div>

        {error && (
          <p
            role="alert"
            className="mt-4 text-sm font-medium text-[#a64b3d]"
          >
            {error}
          </p>
        )}

        <div className="mt-7 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="discero-button-secondary min-h-11 rounded-full border px-5 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50"
          >
            Cancel
          </button>

          <button
            type="submit"
            disabled={busy}
            className="discero-button-primary inline-flex min-h-11 items-center justify-center rounded-full px-5 text-sm font-semibold transition disabled:cursor-not-allowed"
          >
            {busy
              ? "Saving..."
              : mode === "create"
              ? "Add transaction"
              : "Save changes"}
          </button>
        </div>
      </motion.form>
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
