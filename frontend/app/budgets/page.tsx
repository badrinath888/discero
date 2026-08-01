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
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState("");
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

  useEffect(() => {
    if (!userId) return;

    const id = userId;

    void Promise.resolve().then(async () => {
      setLoading(true);
      setError("");
      setSuccess("");

      try {
        const [budgetData, progressData] = await Promise.all([
          api.getBudgets(id, selectedMonth),
          api.getBudgetProgress(id, selectedMonth),
        ]);

        setBudgets(budgetData);
        setProgress(progressData);
        setValues(
          Object.fromEntries(
            budgetData.map((budget) => [
              budget.category,
              String(budget.limit_cents / 100),
            ])
          )
        );
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Unable to load budgets"
        );
      } finally {
        setLoading(false);
      }
    });
  }, [userId, selectedMonth]);

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

  const totalRemaining = Math.max(totalBudget - totalSpent, 0);

  async function save(category: string) {
    const amount = Number(values[category]);

    if (!userId || !Number.isFinite(amount) || amount <= 0) {
      setError("Enter a valid budget amount greater than $0.");
      setSuccess("");
      return;
    }

    setSaving(category);
    setError("");
    setSuccess("");

    try {
      const saved = await api.saveBudget(
        userId,
        category,
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
        `${category} budget saved for ${formatMonth(
          selectedMonth
        )}.`
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to save budget"
      );
    } finally {
      setSaving("");
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

      <div className="px-5 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-10">
        <div className="mx-auto max-w-7xl">
          <header className="grid gap-6 xl:grid-cols-[1fr_auto] xl:items-end">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
                Monthly spending plan
              </p>

              <h1 className="mt-3 max-w-3xl text-4xl font-semibold leading-tight tracking-[-0.05em] sm:text-5xl">
                Give every category
                <span className="block text-[#167c5a]">
                  a clear limit.
                </span>
              </h1>

              <p className="mt-4 max-w-2xl text-sm leading-6 text-[#66746e] sm:text-base">
                Set monthly targets, compare actual spending, and adjust
                category limits as your plans change.
              </p>
            </div>

            <div className="rounded-[24px] border border-[#14241e]/10 bg-white p-3 shadow-sm shadow-[#14241e]/5">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => changeMonth(-1)}
                  className="rounded-full border border-[#14241e]/10 px-4 py-2 text-sm font-medium transition hover:bg-[#f7f4ed]"
                >
                  Previous
                </button>

                <input
                  type="month"
                  value={selectedMonth}
                  onChange={(event) =>
                    setSelectedMonth(event.target.value)
                  }
                  className="rounded-full border border-[#14241e]/10 bg-[#f7f4ed] px-4 py-2 text-sm outline-none focus:border-[#167c5a]"
                />

                <button
                  type="button"
                  onClick={() => changeMonth(1)}
                  className="rounded-full border border-[#14241e]/10 px-4 py-2 text-sm font-medium transition hover:bg-[#f7f4ed]"
                >
                  Next
                </button>

                <button
                  type="button"
                  onClick={() => setSelectedMonth(currentMonth())}
                  className="rounded-full bg-[#14241e] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#20352d]"
                >
                  Current
                </button>
              </div>
            </div>
          </header>

          <section className="mt-8 grid gap-4 md:grid-cols-3">
            <MetricCard
              label="Monthly budget"
              value={formatCents(totalBudget)}
              tone="green"
            />
            <MetricCard
              label="Spent so far"
              value={formatCents(totalSpent)}
              tone="coral"
            />
            <MetricCard
              label="Still available"
              value={formatCents(totalRemaining)}
              tone="yellow"
            />
          </section>

          {(error || success) && (
            <div className="mt-6 space-y-3">
              {error && <PageError message={error} />}
              {success && <PageSuccess message={success} />}
            </div>
          )}

          <section className="mt-6 rounded-[28px] bg-[#14241e] p-6 text-white sm:p-8">
            <div className="grid gap-6 lg:grid-cols-[1fr_auto] lg:items-end">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#76dfbd]">
                  Selected period
                </p>
                <h2 className="mt-3 text-3xl font-semibold tracking-[-0.04em]">
                  {formatMonth(selectedMonth)}
                </h2>
                <p className="mt-2 max-w-xl text-sm leading-6 text-white/65">
                  {budgets.length} of {CATEGORIES.length} categories
                  currently have a limit.
                </p>
              </div>

              <div className="rounded-2xl bg-white/10 px-5 py-4">
                <p className="text-xs text-white/55">
                  Budget coverage
                </p>
                <p className="mt-2 text-2xl font-semibold">
                  {Math.round(
                    (budgets.length / CATEGORIES.length) * 100
                  )}
                  %
                </p>
              </div>
            </div>
          </section>

          {loading ? (
            <div className="mt-6">
              <PageLoading message="Loading budgets..." />
            </div>
          ) : budgets.length === 0 && progress.length === 0 ? (
            <div className="mt-6">
              <EmptyState
                title="No budgets configured"
                description={`Set category limits for ${formatMonth(
                  selectedMonth
                )} to start tracking monthly spending progress.`}
              />
            </div>
          ) : (
            <section className="mt-6 grid gap-5 md:grid-cols-2">
              {CATEGORIES.map((category, index) => {
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
                  <BudgetCard
                    key={category}
                    category={category}
                    index={index}
                    month={selectedMonth}
                    budget={budget}
                    progress={categoryProgress}
                    value={values[category] ?? ""}
                    saving={saving === category}
                    onValueChange={(value) =>
                      setValues((current) => ({
                        ...current,
                        [category]: value,
                      }))
                    }
                    onSave={() => save(category)}
                  />
                );
              })}
            </section>
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

function BudgetCard({
  category,
  index,
  month,
  budget,
  progress,
  value,
  saving,
  onValueChange,
  onSave,
}: {
  category: string;
  index: number;
  month: string;
  budget?: Budget;
  progress?: BudgetProgress;
  value: string;
  saving: boolean;
  onValueChange: (value: string) => void;
  onSave: () => void;
}) {
  const tones = [
    "bg-white",
    "bg-[#eef6e9]",
    "bg-[#fbf0d1]",
    "bg-[#f5e4de]",
  ];

  const percent = progress?.percent_used ?? 0;
  const status =
    percent >= 100
      ? "Over budget"
      : percent >= 75
      ? "Watch closely"
      : "On track";

  return (
    <article
      className={`rounded-[28px] border border-[#14241e]/10 p-6 shadow-sm shadow-[#14241e]/5 ${
        tones[index % tones.length]
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#7b8781]">
            {formatMonth(month)}
          </p>
          <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
            {category}
          </h2>
        </div>

        <span
          className={`rounded-full px-3 py-1.5 text-xs font-semibold ${
            budget
              ? "bg-[#dff6c7] text-[#167c5a]"
              : "bg-white/60 text-[#7b8781]"
          }`}
        >
          {budget ? formatCents(budget.limit_cents) : "Not set"}
        </span>
      </div>

      {progress ? (
        <div className="mt-6">
          <div className="flex items-end justify-between gap-4">
            <div>
              <p className="text-sm text-[#66746e]">Spent</p>
              <p className="mt-1 text-2xl font-semibold">
                {formatCents(progress.spent_cents)}
              </p>
            </div>

            <div className="text-right">
              <p className="text-sm text-[#66746e]">{status}</p>
              <p
                className={`mt-1 text-sm font-semibold ${
                  progress.over_budget_cents > 0
                    ? "text-[#a64b3d]"
                    : "text-[#167c5a]"
                }`}
              >
                {progress.over_budget_cents > 0
                  ? `${formatCents(progress.over_budget_cents)} over`
                  : `${formatCents(progress.remaining_cents)} left`}
              </p>
            </div>
          </div>

          <div className="mt-4 h-3 overflow-hidden rounded-full bg-[#14241e]/10">
            <div
              className={`h-full rounded-full transition-all ${
                percent >= 100
                  ? "bg-[#c56755]"
                  : percent >= 75
                  ? "bg-[#d5a737]"
                  : "bg-[#167c5a]"
              }`}
              style={{
                width: `${Math.min(percent, 100)}%`,
              }}
            />
          </div>

          <p className="mt-2 text-xs text-[#7b8781]">
            {percent}% used
          </p>
        </div>
      ) : (
        <p className="mt-6 text-sm leading-6 text-[#7b8781]">
          Add a limit to begin tracking this category.
        </p>
      )}

      <div className="mt-6 flex flex-col gap-3 sm:flex-row">
        <div className="relative min-w-0 flex-1">
          <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-sm text-[#7b8781]">
            $
          </span>

          <input
            type="number"
            min="0.01"
            step="0.01"
            value={value}
            onChange={(event) => onValueChange(event.target.value)}
            placeholder="0.00"
            className="w-full rounded-2xl border border-[#14241e]/10 bg-white/70 py-3 pl-8 pr-4 text-sm outline-none placeholder:text-[#9aa39e] focus:border-[#167c5a]"
          />
        </div>

        <button
          type="button"
          onClick={onSave}
          disabled={saving}
          className="rounded-full bg-[#14241e] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#20352d] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? "Saving..." : budget ? "Update" : "Set budget"}
        </button>
      </div>
    </article>
  );
}
