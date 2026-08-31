"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Copy,
  Edit3,
  PiggyBank,
  Target,
  Trash2,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import ConfirmationModal from "../components/ConfirmationModal";
import Toast from "../components/Toast";
import {
  CardSkeleton,
  PageError,
  PageLoading,
} from "../components/PageFeedback";
import {
  AnimatedNumber,
  PageReveal,
  Reveal,
} from "../components/PremiumMotion";
import {
  api,
  Budget,
  BudgetProgress,
  formatCents,
  session,
} from "../lib/api";

const CATEGORIES = [
  "Dining",
  "Groceries",
  "Health",
  "Housing",
  "Shopping",
  "Subscriptions",
  "Transport",
  "Utilities",
];

function currentMonth(): string {
  const today = new Date();

  return `${today.getFullYear()}-${String(
    today.getMonth() + 1
  ).padStart(2, "0")}`;
}

function previousMonth(month: string): string {
  const [year, monthNumber] = month.split("-").map(Number);
  const value = new Date(year, monthNumber - 2, 1);

  return `${value.getFullYear()}-${String(
    value.getMonth() + 1
  ).padStart(2, "0")}`;
}

function formatMonth(month: string): string {
  const [year, monthNumber] = month.split("-").map(Number);

  return new Date(year, monthNumber - 1, 1).toLocaleDateString(
    "en-US",
    {
      month: "long",
      year: "numeric",
    }
  );
}

export default function BudgetsPage() {
  const router = useRouter();

  const [userId, setUserId] = useState<number | null>(null);
  const [selectedMonth, setSelectedMonth] = useState(currentMonth);
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [progress, setProgress] = useState<BudgetProgress[]>([]);
  const [editingCategory, setEditingCategory] = useState<string | null>(
    null
  );
  const [draftAmount, setDraftAmount] = useState("");
  const [saving, setSaving] = useState(false);
  const [budgetToDelete, setBudgetToDelete] = useState<Budget | null>(
    null
  );
  const [deleting, setDeleting] = useState(false);
  const [copying, setCopying] = useState(false);
  const [loading, setLoading] = useState(true);
  const [checkingSession, setCheckingSession] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    const id = session.getUserId();
    const token = session.getToken();

    if (!id || !token) {
      session.clear();
      router.replace("/");
      return;
    }

    api
      .getMe()
      .then((user) => {
        if (user.id !== id) {
          session.clear();
          router.replace("/");
          return;
        }

        setUserId(id);
        setCheckingSession(false);
      })
      .catch(() => {
        session.clear();
        router.replace("/");
      });
  }, [router]);

  const loadBudgets = useCallback(async () => {
    if (!userId) return;

    setLoading(true);
    setError("");
    setSuccess("");

    try {
      const [budgetData, progressData] = await Promise.all([
        api.getBudgets(userId, selectedMonth),
        api.getBudgetProgress(userId, selectedMonth),
      ]);

      setBudgets(budgetData);
      setProgress(progressData);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to load budgets"
      );
    } finally {
      setLoading(false);
    }
  }, [userId, selectedMonth]);

  useEffect(() => {
    void Promise.resolve().then(loadBudgets);
  }, [loadBudgets]);

  const totalBudget = useMemo(
    () =>
      budgets.reduce(
        (total, budget) => total + budget.limit_cents,
        0
      ),
    [budgets]
  );

  const totalSpent = useMemo(
    () =>
      progress.reduce(
        (total, item) => total + item.spent_cents,
        0
      ),
    [progress]
  );

  const totalRemaining = totalBudget - totalSpent;
  const coverage = Math.round(
    (budgets.length / CATEGORIES.length) * 100
  );
  const overallPercent =
    totalBudget > 0
      ? Math.round((totalSpent / totalBudget) * 100)
      : 0;
  const overBudgetCount = progress.filter((item) => item.overspent).length;
  const orderedCategories = useMemo(
    () =>
      [...CATEGORIES].sort((left, right) => {
        const leftProgress = progress.find((item) => item.category === left);
        const rightProgress = progress.find((item) => item.category === right);
        return (rightProgress?.percent_used ?? -1) - (leftProgress?.percent_used ?? -1);
      }),
    [progress]
  );

  const activeBudget = editingCategory
    ? budgets.find(
        (budget) =>
          budget.category === editingCategory &&
          budget.month === selectedMonth
      )
    : undefined;

  function openEditor(category: string) {
    const budget = budgets.find(
      (item) =>
        item.category === category &&
        item.month === selectedMonth
    );

    setEditingCategory(category);
    setDraftAmount(
      budget ? String(budget.limit_cents / 100) : ""
    );
    setError("");
    setSuccess("");
  }

  async function saveBudget() {
    const amount = Number(draftAmount);

    if (
      !userId ||
      !editingCategory ||
      !Number.isFinite(amount) ||
      amount <= 0
    ) {
      setError("Enter a valid budget amount greater than $0.");
      setSuccess("");
      return;
    }

    setSaving(true);
    setError("");
    setSuccess("");

    try {
      const saved = await api.saveBudget(
        userId,
        editingCategory,
        selectedMonth,
        Math.round(amount * 100)
      );

      setBudgets((current) => [
        ...current.filter(
          (budget) =>
            !(
              budget.category === saved.category &&
              budget.month === saved.month
            )
        ),
        saved,
      ]);

      setProgress(
        await api.getBudgetProgress(userId, selectedMonth)
      );

      setSuccess(
        `${editingCategory} budget saved for ${formatMonth(
          selectedMonth
        )}.`
      );
      setEditingCategory(null);
      setDraftAmount("");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to save budget"
      );
    } finally {
      setSaving(false);
    }
  }

  async function copyPreviousMonth() {
    if (!userId) return;

    setCopying(true);
    setError("");
    setSuccess("");

    try {
      const result = await api.copyBudgets(
        userId,
        previousMonth(selectedMonth),
        selectedMonth
      );

      setBudgets(result.budgets);
      setProgress(
        await api.getBudgetProgress(userId, selectedMonth)
      );

      const changes = [
        result.copied > 0 ? `${result.copied} copied` : "",
        result.updated > 0 ? `${result.updated} updated` : "",
        result.skipped > 0 ? `${result.skipped} kept` : "",
      ]
        .filter(Boolean)
        .join(", ");

      setSuccess(
        `Budget plan copied from ${formatMonth(
          result.source_month
        )} to ${formatMonth(result.target_month)}${
          changes ? ` — ${changes}.` : "."
        }`
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to copy the previous month"
      );
    } finally {
      setCopying(false);
    }
  }

  async function deleteBudget() {
    if (!userId || !budgetToDelete) return;

    setDeleting(true);
    setError("");
    setSuccess("");

    try {
      await api.deleteBudget(
        userId,
        budgetToDelete.category,
        budgetToDelete.month
      );

      setBudgets((current) =>
        current.filter((budget) => budget.id !== budgetToDelete.id)
      );
      setProgress((current) =>
        current.filter(
          (item) =>
            item.category !== budgetToDelete.category ||
            item.month !== budgetToDelete.month
        )
      );
      setSuccess(
        `${budgetToDelete.category} budget deleted for ${formatMonth(
          budgetToDelete.month
        )}.`
      );
      setBudgetToDelete(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to delete budget"
      );
    } finally {
      setDeleting(false);
    }
  }

  function changeMonth(offset: number) {
    const [year, month] = selectedMonth.split("-").map(Number);
    const next = new Date(year, month - 1 + offset, 1);

    setSelectedMonth(
      `${next.getFullYear()}-${String(
        next.getMonth() + 1
      ).padStart(2, "0")}`
    );
    setEditingCategory(null);
  }

  if (checkingSession) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#F5F1EA] px-5">
        <div className="w-full max-w-xl">
          <PageLoading message="Checking your session..." />
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#F5F1EA] text-[#181713]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-56 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[1500px]">
          <Reveal>
            <header className="flex flex-col gap-6 border-b border-[#181713]/10 pb-5 xl:flex-row xl:items-end xl:justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
                  Spending plan
                </p>

                <h1 className="mt-1 text-[32px] font-semibold tracking-[-0.03em]">
                  Budgets
                </h1>

                <p className="mt-1 text-sm text-[#706961]">
                  Guardrails for the money you intend to use.
                </p>
              </div>

              <div className="flex w-full flex-nowrap items-center gap-2 overflow-x-auto rounded-2xl border border-[#181713]/10 bg-white p-2 shadow-sm xl:w-auto">
                <button
                  type="button"
                  onClick={() => changeMonth(-1)}
                  aria-label="Previous month"
                  className="flex h-10 w-10 items-center justify-center rounded-xl transition hover:bg-[#F8F4EE]"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>

                <label className="relative">
                  <CalendarDays
                    aria-hidden="true"
                    className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#777168]"
                  />
                  <input
                    type="month"
                    aria-label="Select month"
                    value={selectedMonth}
                    onChange={(event) =>
                      setSelectedMonth(event.target.value)
                    }
                    className="h-10 w-[170px] shrink-0 rounded-xl border border-[#181713]/10 bg-[#F8F4EE] pl-9 pr-3 text-sm outline-none focus:border-[#6E4B63]"
                  />
                </label>

                <button
                  type="button"
                  onClick={() => changeMonth(1)}
                  aria-label="Next month"
                  className="flex h-10 w-10 items-center justify-center rounded-xl transition hover:bg-[#F8F4EE]"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>

                <button
                  type="button"
                  onClick={copyPreviousMonth}
                  disabled={copying || loading}
                  className="inline-flex h-10 shrink-0 items-center gap-2 whitespace-nowrap rounded-xl border border-[#181713]/10 bg-white px-4 text-sm font-semibold transition hover:bg-[#F8F4EE] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Copy className="h-4 w-4" />
                  {copying
                    ? "Copying..."
                    : `Copy ${formatMonth(
                        previousMonth(selectedMonth)
                      )}`}
                </button>

                <button
                  type="button"
                  onClick={() => setSelectedMonth(currentMonth())}
                  className="discero-button-primary h-10 shrink-0 whitespace-nowrap rounded-xl px-4 text-sm font-semibold transition"
                >
                  Current month
                </button>
              </div>
            </header>
          </Reveal>

          {error && !editingCategory && (
            <div className="mt-5">
              <PageError message={error} onRetry={() => void loadBudgets()} />
            </div>
          )}

          {loading ? (
            <div className="mt-6">
              <CardSkeleton count={2} />
            </div>
          ) : (
            <Reveal delay={0.06}>
              <section className="mt-6 border-y border-[#181713]/10 bg-[#FFFCF7] px-5 py-7 sm:px-8 sm:py-8">
                <div className="grid gap-8 xl:grid-cols-[minmax(260px,0.9fr)_minmax(520px,1.4fr)] xl:items-end">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
                      {formatMonth(selectedMonth)}
                    </p>
                    <p className="mt-4 text-sm font-medium text-[#706961]">
                      {totalRemaining < 0 ? "Over plan" : "Remaining"}
                    </p>
                    <AnimatedNumber
                      value={Math.abs(totalRemaining)}
                      format={formatCents}
                      className={`mt-1 block text-5xl font-semibold tracking-[-0.06em] sm:text-6xl ${
                        totalRemaining < 0
                          ? "text-[#A25543]"
                          : "text-[#2F2930]"
                      }`}
                    />
                  </div>

                  <dl className="grid grid-cols-2 gap-y-6 sm:grid-cols-4 sm:divide-x sm:divide-[#181713]/10">
                    {[
                      ["Budgeted", formatCents(totalBudget)],
                      ["Spent", formatCents(-totalSpent)],
                      ["Used", `${overallPercent}%`],
                      ["Categories over plan", String(overBudgetCount)],
                    ].map(([label, value]) => (
                      <div key={label} className="sm:px-5 first:sm:pl-0 last:sm:pr-0">
                        <dt className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#8A8178]">
                          {label}
                        </dt>
                        <dd className="mt-2 text-lg font-semibold tabular-nums text-[#2F2930]">
                          {value}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>

                <div className="mt-8 border-t border-[#181713]/10 pt-5">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[#706961]">
                    <span className="font-semibold text-[#2F2930]">Total budget allocation</span>
                    <span>{budgets.length} of {CATEGORIES.length} categories · {coverage}% coverage</span>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#EDE7E1]">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.min(overallPercent, 100)}%` }}
                      transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
                      className={`h-full rounded-full ${
                        overallPercent > 100 ? "bg-[#A25543]" : "bg-[#6E4B63]"
                      }`}
                    />
                  </div>
                </div>
              </section>
            </Reveal>
          )}

          {loading ? (
            <div className="mt-6">
              <PageLoading message="Loading budgets..." />
            </div>
          ) : budgets.length === 0 && progress.length === 0 ? (
            error ? null : (
              <Reveal>
                <section className="mt-6 border-y border-[#181713]/10 bg-[#FFFCF7] px-5 py-7 sm:flex sm:items-center sm:justify-between sm:gap-8 sm:px-8">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
                      {formatMonth(selectedMonth)} plan
                    </p>
                    <h2 className="mt-2 text-xl font-semibold tracking-[-0.02em]">
                      No budgets configured
                    </h2>
                    <p className="mt-2 max-w-xl text-sm leading-6 text-[#706961]">
                      Set category limits to start tracking monthly spending progress.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => openEditor(CATEGORIES[0])}
                    className="discero-button-primary mt-5 h-10 shrink-0 rounded-xl px-4 text-sm font-semibold transition sm:mt-0"
                  >
                    Create first budget
                  </button>
                </section>
              </Reveal>
            )
          ) : (
            <Reveal>
              <section className="mt-8 overflow-hidden border-y border-[#181713]/10 bg-[#FFFCF7]">
                <header className="hidden gap-3 border-b border-[#181713]/10 bg-[#F8F4EE] px-5 py-4 text-xs font-semibold uppercase tracking-[0.12em] text-[#7a8780] xl:grid xl:grid-cols-[minmax(180px,1.3fr)_140px_minmax(200px,1fr)_140px_110px] xl:items-center">
                  <span>Category</span>
                  <span>Limit</span>
                  <span>Progress</span>
                  <span>Status</span>
                  <span />
                </header>

                <div className="divide-y divide-[#181713]/8">
                  {orderedCategories.map((category, index) => {
                    const budget = budgets.find(
                      (item) =>
                        item.category === category &&
                        item.month === selectedMonth
                    );

                    const categoryProgress = progress.find(
                      (item) =>
                        item.category === category &&
                        item.month === selectedMonth
                    );

                    return (
                      <BudgetRow
                        key={category}
                        category={category}
                        index={index}
                        budget={budget}
                        progress={categoryProgress}
                        onEdit={() => openEditor(category)}
                      />
                    );
                  })}
                </div>
              </section>
            </Reveal>
          )}
        </PageReveal>
      </div>

      <AnimatePresence>
        {editingCategory && (
          <BudgetDrawer
            category={editingCategory}
            month={selectedMonth}
            currentBudget={activeBudget}
            value={draftAmount}
            saving={saving}
            error={error}
            onChange={setDraftAmount}
            onClose={() => setEditingCategory(null)}
            onSave={saveBudget}
            onDelete={
              activeBudget
                ? () => {
                    setEditingCategory(null);
                    setBudgetToDelete(activeBudget);
                  }
                : undefined
            }
          />
        )}
        {budgetToDelete && (
          <ConfirmationModal
            eyebrow="Delete monthly budget"
            title={`Delete ${budgetToDelete.category}?`}
            description={`This removes only the ${formatMonth(
              budgetToDelete.month
            )} budget. Other months are unchanged.`}
            cancelLabel="Keep budget"
            confirmLabel="Delete budget"
            busyLabel="Deleting..."
            busy={deleting}
            icon={<Trash2 className="h-5 w-5" />}
            onCancel={() => setBudgetToDelete(null)}
            onConfirm={() => void deleteBudget()}
          />
        )}
      </AnimatePresence>
      <Toast
        message={success}
        type="success"
        onClose={() => setSuccess("")}
      />
    </main>
  );
}

function BudgetRow({
  category,
  index,
  budget,
  progress,
  onEdit,
}: {
  category: string;
  index: number;
  budget?: Budget;
  progress?: BudgetProgress;
  onEdit: () => void;
}) {
  const percent = progress?.percent_used ?? 0;
  const reduceMotion = useReducedMotion();

  const status = !budget
    ? "Not configured"
    : progress?.overspent
      ? "Over budget"
      : percent >= 100
        ? "At limit"
        : percent >= 75
          ? "Near limit"
          : "On track";

  const statusClass =
    !budget
      ? "bg-[#f1eee7] text-[#777168]"
      : progress?.overspent
        ? "bg-[#f8ddd5] text-[#a64b3d]"
        : percent >= 75
          ? "bg-[#f7e8b5] text-[#8b6518]"
          : "bg-[#E3EBE1] text-[#48634B]";

  return (
    <motion.article
      layout
      initial={reduceMotion ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={
        reduceMotion
          ? undefined
          : { x: 3, backgroundColor: "#fbfaf6" }
      }
      transition={{ duration: reduceMotion ? 0 : 0.32, delay: reduceMotion ? 0 : index * 0.06 }}
      className="grid gap-4 px-5 py-4 xl:grid-cols-[minmax(180px,1.3fr)_140px_minmax(200px,1fr)_140px_110px] xl:items-center"
    >
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[#EDE5DE] text-[#6E4B63]">
          <PiggyBank className="h-4 w-4" />
        </span>

        <div>
          <p className="text-sm font-semibold">{category}</p>
          <p className="mt-1 text-xs text-[#8A8178]">
            {progress
              ? `${formatCents(progress.spent_cents)} spent`
              : "No tracked spending"}
          </p>
        </div>
      </div>

      <p className="text-sm font-semibold">
        {budget ? formatCents(budget.limit_cents) : "Not set"}
      </p>

      <div>
        <div className="h-2 overflow-hidden rounded-full bg-[#181713]/8">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(percent, 100)}%` }}
            transition={{
              duration: reduceMotion ? 0 : 0.5,
              ease: [0.22, 1, 0.36, 1],
            }}
            className={`h-full rounded-full ${
              progress?.overspent
                ? "bg-[#c56755]"
                : percent >= 75
                  ? "bg-[#d5a737]"
                  : "bg-[#6E4B63]"
            }`}
          />
        </div>

        <div className="mt-2 flex items-center justify-between gap-3 text-xs text-[#8A8178]">
          <span>{Math.round(percent)}% used</span>
          <span>
            {progress
              ? progress.over_budget_cents > 0
                ? `${formatCents(progress.over_budget_cents)} over`
                : `${formatCents(progress.remaining_cents)} left`
              : "Set a limit"}
          </span>
        </div>
      </div>

      <span
        className={`w-fit rounded-full px-3 py-1.5 text-xs font-semibold ${statusClass}`}
      >
        {status}
      </span>

      <button
        type="button"
        onClick={onEdit}
        className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-[#181713]/10 bg-white px-3 text-sm font-semibold transition hover:bg-[#F8F4EE]"
      >
        <Edit3 className="h-4 w-4" />
        {budget ? "Edit" : "Set"}
      </button>
    </motion.article>
  );
}

function BudgetDrawer({
  category,
  month,
  currentBudget,
  value,
  saving,
  error,
  onChange,
  onClose,
  onSave,
  onDelete,
}: {
  category: string;
  month: string;
  currentBudget?: Budget;
  value: string;
  saving: boolean;
  error?: string;
  onChange: (value: string) => void;
  onClose: () => void;
  onSave: () => void;
  onDelete?: () => void;
}) {
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
        aria-label="Close budget editor"
        onClick={onClose}
        className="absolute inset-0 bg-[#181713]/35 backdrop-blur-[2px]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      />

      <motion.aside
        initial={reduceMotion ? false : { x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{
          duration: reduceMotion ? 0 : 0.32,
          ease: [0.22, 1, 0.36, 1],
        }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="budget-drawer-title"
        className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col bg-[#fdfcf8] shadow-2xl"
      >
        <header className="flex items-start justify-between border-b border-[#181713]/10 px-6 py-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
              Budget editor
            </p>
            <h2 id="budget-drawer-title" className="mt-2 text-xl font-semibold">
              {category}
            </h2>
            <p className="mt-1 text-sm text-[#777168]">
              {formatMonth(month)}
            </p>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close budget editor"
            className="flex h-10 w-10 items-center justify-center rounded-full border border-[#181713]/10 bg-white"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        <div className="flex-1 px-6 py-6">
          <div className="rounded-2xl bg-[#E8EEE7] p-5">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#6E4B63] text-white">
                <Target className="h-4 w-4" />
              </span>

              <div>
                <p className="text-sm font-semibold">
                  {currentBudget ? "Update monthly limit" : "Set monthly limit"}
                </p>
                <p className="mt-1 text-sm leading-6 text-[#706961]">
                  Choose the maximum amount you want to spend in this category.
                </p>
              </div>
            </div>
          </div>

          <label className="mt-7 block">
            <span className="text-xs font-semibold uppercase tracking-[0.12em] text-[#777168]">
              Monthly amount
            </span>

            <div className="relative mt-2">
              <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[#777168]">
                $
              </span>
              <input
                type="number"
                min="0.01"
                step="0.01"
                aria-required="true"
                aria-invalid={Boolean(error)}
                aria-describedby={error ? "budget-amount-error" : undefined}
                value={value}
                onChange={(event) => onChange(event.target.value)}
                placeholder="0.00"
                autoFocus
                className="h-12 w-full rounded-xl border border-[#181713]/10 bg-white pl-8 pr-4 text-lg font-semibold outline-none focus:border-[#6E4B63]"
              />
            </div>

            {error && (
              <p
                id="budget-amount-error"
                role="alert"
                className="mt-2 text-sm font-medium text-[#a64b3d]"
              >
                {error}
              </p>
            )}
          </label>

          {currentBudget && (
            <div className="mt-6 rounded-2xl border border-[#181713]/10 bg-white p-4">
              <p className="text-xs uppercase tracking-[0.1em] text-[#8A8178]">
                Current limit
              </p>
              <p className="mt-2 text-2xl font-semibold">
                {formatCents(currentBudget.limit_cents)}
              </p>
            </div>
          )}
        </div>

        <footer className="flex gap-3 border-t border-[#181713]/10 p-6">
          {onDelete && (
            <button
              type="button"
              onClick={onDelete}
              disabled={saving}
              className="discero-button-destructive inline-flex h-11 items-center justify-center gap-2 rounded-xl border px-4 text-sm font-semibold transition disabled:opacity-50"
            >
              <Trash2 className="h-4 w-4" />
              Delete
            </button>
          )}
          <button
            type="button"
            onClick={onSave}
            disabled={saving}
            className="discero-button-primary h-11 flex-1 rounded-xl text-sm font-semibold transition"
          >
            {saving
              ? "Saving..."
              : currentBudget
                ? "Update budget"
                : "Create budget"}
          </button>
        </footer>
      </motion.aside>
    </motion.div>
  );
}
