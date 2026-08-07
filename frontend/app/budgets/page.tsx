"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Copy,
  Edit3,
  Gauge,
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
  EmptyState,
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
      <main className="flex min-h-screen items-center justify-center bg-[#f5f1e8] px-5">
        <div className="w-full max-w-xl">
          <PageLoading message="Checking your session..." />
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#f5f1e8] text-[#14241e]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[1500px]">
          <Reveal>
            <header className="flex flex-col gap-6 border-b border-[#14241e]/10 pb-7 xl:flex-row xl:items-end xl:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
                  Monthly spending plan
                </p>

                <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
                  Budgets
                </h1>

                <p className="mt-3 max-w-2xl text-sm leading-6 text-[#66746e]">
                  Plan category limits, monitor progress, and adjust your
                  monthly spending without managing a wall of forms.
                </p>
              </div>

              <div className="flex w-full flex-nowrap items-center gap-2 overflow-x-auto rounded-2xl border border-[#14241e]/10 bg-white p-2 shadow-sm xl:w-auto">
                <button
                  type="button"
                  onClick={() => changeMonth(-1)}
                  aria-label="Previous month"
                  className="flex h-10 w-10 items-center justify-center rounded-xl transition hover:bg-[#f7f4ed]"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>

                <label className="relative">
                  <CalendarDays
                    aria-hidden="true"
                    className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#728078]"
                  />
                  <input
                    type="month"
                    aria-label="Select month"
                    value={selectedMonth}
                    onChange={(event) =>
                      setSelectedMonth(event.target.value)
                    }
                    className="h-10 w-[170px] shrink-0 rounded-xl border border-[#14241e]/10 bg-[#f7f4ed] pl-9 pr-3 text-sm outline-none focus:border-[#167c5a]"
                  />
                </label>

                <button
                  type="button"
                  onClick={() => changeMonth(1)}
                  aria-label="Next month"
                  className="flex h-10 w-10 items-center justify-center rounded-xl transition hover:bg-[#f7f4ed]"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>

                <button
                  type="button"
                  onClick={copyPreviousMonth}
                  disabled={copying || loading}
                  className="inline-flex h-10 shrink-0 items-center gap-2 whitespace-nowrap rounded-xl border border-[#14241e]/10 bg-white px-4 text-sm font-semibold transition hover:bg-[#f7f4ed] disabled:cursor-not-allowed disabled:opacity-50"
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
                  className="h-10 shrink-0 whitespace-nowrap rounded-xl bg-[#14241e] px-4 text-sm font-semibold text-white transition hover:bg-[#20352d]"
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
            <section className="mt-6 grid gap-4 xl:grid-cols-[1.25fr_0.75fr]">
              <article className="premium-hover relative overflow-hidden rounded-[30px] bg-[#14241e] p-7 text-white shadow-[0_24px_70px_rgba(20,36,30,0.18)] sm:p-9">
                <div className="pointer-events-none absolute -right-14 -top-14 h-48 w-48 rounded-full bg-[#76dfbd]/15 blur-3xl" />

                <div className="relative">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#83dcb9]">
                    {formatMonth(selectedMonth)}
                  </p>

                  <AnimatedNumber
                    value={Math.abs(totalRemaining)}
                    format={formatCents}
                    className="mt-4 block text-5xl font-semibold tracking-[-0.06em] sm:text-6xl"
                  />

                  <p className="mt-3 text-sm text-white/55">
                    {totalRemaining < 0
                      ? "Over budget across configured categories"
                      : "Remaining across all configured categories"}
                  </p>

                  <div className="mt-10 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-3">
                    <PlanMetric
                      label="Budgeted"
                      value={formatCents(totalBudget)}
                      tone="positive"
                    />
                    <PlanMetric
                      label="Spent"
                      value={formatCents(-totalSpent)}
                      tone="negative"
                    />
                    <PlanMetric
                      label="Used"
                      value={`${overallPercent}%`}
                      tone="neutral"
                    />
                  </div>
                </div>
              </article>

              <article className="premium-hover rounded-[30px] bg-[#dff6c7] p-7 sm:p-8">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#4c7e53]">
                      Budget coverage
                    </p>
                    <AnimatedNumber
                      value={coverage}
                      format={(value) => `${value}%`}
                      className="mt-4 block text-5xl font-semibold tracking-[-0.05em]"
                    />
                  </div>

                  <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#14241e] text-[#dff6c7]">
                    <Gauge className="h-5 w-5" />
                  </span>
                </div>

                <p className="mt-3 text-sm leading-6 text-[#56705d]">
                  {budgets.length} of {CATEGORIES.length} categories have
                  active limits for this month.
                </p>

                <div className="mt-8 h-2 overflow-hidden rounded-full bg-[#14241e]/10">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${coverage}%` }}
                    transition={{
                      duration: 0.55,
                      ease: [0.22, 1, 0.36, 1],
                    }}
                    className="h-full rounded-full bg-[#167c5a]"
                  />
                </div>
              </article>
            </section>
          </Reveal>
          )}

          {loading ? (
            <div className="mt-6">
              <PageLoading message="Loading budgets..." />
            </div>
          ) : budgets.length === 0 && progress.length === 0 ? (
            error ? null : (
            <div className="mt-6">
              <EmptyState
                title="No budgets configured"
                description={`Set category limits for ${formatMonth(
                  selectedMonth
                )} to start tracking monthly spending progress.`}
                actionLabel="Create first budget"
                onAction={() => openEditor(CATEGORIES[0])}
              />
            </div>
            )
          ) : (
            <Reveal>
              <section className="mt-8 overflow-hidden rounded-[24px] border border-[#14241e]/10 bg-white">
                <header className="hidden gap-3 border-b border-[#14241e]/10 bg-[#faf8f3] px-5 py-4 text-xs font-semibold uppercase tracking-[0.12em] text-[#7a8780] md:grid md:grid-cols-[minmax(180px,1.3fr)_140px_minmax(200px,1fr)_140px_110px] md:items-center">
                  <span>Category</span>
                  <span>Limit</span>
                  <span>Progress</span>
                  <span>Status</span>
                  <span />
                </header>

                <div className="divide-y divide-[#14241e]/8">
                  {CATEGORIES.map((category) => {
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

function PlanMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "positive" | "negative" | "neutral";
}) {
  const toneClass = {
    positive: "text-[#83dcb9]",
    negative: "text-[#f4a594]",
    neutral: "text-white",
  };

  return (
    <div className="bg-white/[0.045] p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/35">
        {label}
      </p>
      <p className={`mt-2 text-lg font-semibold ${toneClass[tone]}`}>
        {value}
      </p>
    </div>
  );
}

function BudgetRow({
  category,
  budget,
  progress,
  onEdit,
}: {
  category: string;
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
      ? "bg-[#f1eee7] text-[#728078]"
      : progress?.overspent
        ? "bg-[#f8ddd5] text-[#a64b3d]"
        : percent >= 75
          ? "bg-[#f7e8b5] text-[#8b6518]"
          : "bg-[#edf5ee] text-[#167c5a]";

  return (
    <motion.article
      layout
      whileHover={
        reduceMotion
          ? undefined
          : { x: 3, backgroundColor: "#fbfaf6" }
      }
      transition={{ duration: reduceMotion ? 0 : 0.2 }}
      className="grid gap-4 px-5 py-4 md:grid-cols-[minmax(180px,1.3fr)_140px_minmax(200px,1fr)_140px_110px] md:items-center"
    >
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[#edf5ee] text-[#167c5a]">
          <PiggyBank className="h-4 w-4" />
        </span>

        <div>
          <p className="text-sm font-semibold">{category}</p>
          <p className="mt-1 text-xs text-[#87928d]">
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
        <div className="h-2 overflow-hidden rounded-full bg-[#14241e]/8">
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
                  : "bg-[#167c5a]"
            }`}
          />
        </div>

        <div className="mt-2 flex items-center justify-between gap-3 text-xs text-[#7b8781]">
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
        className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-[#14241e]/10 bg-white px-3 text-sm font-semibold transition hover:bg-[#f7f4ed]"
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
        className="absolute inset-0 bg-[#14241e]/35 backdrop-blur-[2px]"
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
        <header className="flex items-start justify-between border-b border-[#14241e]/10 px-6 py-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#167c5a]">
              Budget editor
            </p>
            <h2 id="budget-drawer-title" className="mt-2 text-xl font-semibold">
              {category}
            </h2>
            <p className="mt-1 text-sm text-[#728078]">
              {formatMonth(month)}
            </p>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close budget editor"
            className="flex h-10 w-10 items-center justify-center rounded-full border border-[#14241e]/10 bg-white"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        <div className="flex-1 px-6 py-6">
          <div className="rounded-2xl bg-[#edf5ee] p-5">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#167c5a] text-white">
                <Target className="h-4 w-4" />
              </span>

              <div>
                <p className="text-sm font-semibold">
                  {currentBudget ? "Update monthly limit" : "Set monthly limit"}
                </p>
                <p className="mt-1 text-sm leading-6 text-[#66746e]">
                  Choose the maximum amount you want to spend in this category.
                </p>
              </div>
            </div>
          </div>

          <label className="mt-7 block">
            <span className="text-xs font-semibold uppercase tracking-[0.12em] text-[#728078]">
              Monthly amount
            </span>

            <div className="relative mt-2">
              <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[#728078]">
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
                className="h-12 w-full rounded-xl border border-[#14241e]/10 bg-white pl-8 pr-4 text-lg font-semibold outline-none focus:border-[#167c5a]"
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
            <div className="mt-6 rounded-2xl border border-[#14241e]/10 bg-white p-4">
              <p className="text-xs uppercase tracking-[0.1em] text-[#87928d]">
                Current limit
              </p>
              <p className="mt-2 text-2xl font-semibold">
                {formatCents(currentBudget.limit_cents)}
              </p>
            </div>
          )}
        </div>

        <footer className="flex gap-3 border-t border-[#14241e]/10 p-6">
          {onDelete && (
            <button
              type="button"
              onClick={onDelete}
              disabled={saving}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-xl border border-[#a64b3d]/20 bg-white px-4 text-sm font-semibold text-[#a64b3d] transition hover:bg-[#f8eee9] disabled:opacity-50"
            >
              <Trash2 className="h-4 w-4" />
              Delete
            </button>
          )}
          <button
            type="button"
            onClick={onSave}
            disabled={saving}
            className="h-11 flex-1 rounded-xl bg-[#14241e] text-sm font-semibold text-white transition hover:bg-[#20352d] disabled:opacity-50"
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
