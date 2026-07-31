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
      <main className="flex min-h-screen items-center justify-center bg-[#050d18] px-5 text-white">
        <div className="w-full max-w-xl">
          <PageLoading message="Checking your session..." />
        </div>
      </main>
    );
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
        backgroundSize:
          "auto, auto, auto, 42px 42px, 42px 42px",
      }}
    >
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent via-[#050d18]/20 to-[#050d18]" />

      <AppSidebar />

      <div className="relative px-5 pb-10 pt-20 sm:px-8 lg:ml-72 lg:px-10 lg:pt-8">
        <div className="mx-auto max-w-6xl">
        <header className="flex flex-col gap-6 rounded-3xl border border-white/10 bg-white/[0.05] p-6 shadow-2xl shadow-black/30 backdrop-blur-xl sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-300">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              Spending plan
            </div>

            <h1 className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">
              Monthly budgets
            </h1>

            <p className="mt-2 text-sm text-slate-400">
              Set category limits independently for each month.
            </p>
          </div>

        </header>

        <section className="mt-6 rounded-3xl border border-white/10 bg-white/[0.06] p-5 shadow-2xl shadow-black/20 backdrop-blur-xl">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm text-slate-400">
                Budget month
              </p>

              <h2 className="mt-1 text-xl font-semibold text-slate-100">
                {formatMonth(selectedMonth)}
              </h2>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => changeMonth(-1)}
                className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm transition hover:bg-white/10"
              >
                Previous
              </button>

              <input
                type="month"
                value={selectedMonth}
                onChange={(event) =>
                  setSelectedMonth(event.target.value)
                }
                className="rounded-xl border border-white/10 bg-slate-950/70 px-4 py-2 text-sm outline-none transition focus:border-emerald-400"
              />

              <button
                onClick={() => changeMonth(1)}
                className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm transition hover:bg-white/10"
              >
                Next
              </button>

              <button
                onClick={() => setSelectedMonth(currentMonth())}
                className="rounded-xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-400/20"
              >
                Current month
              </button>
            </div>
          </div>
        </section>

        <section className="mt-6 grid gap-4 sm:grid-cols-3">
          <SummaryCard
            label="Total monthly budget"
            value={formatCents(totalBudget)}
          />

          <SummaryCard
            label="Categories configured"
            value={`${budgets.length} of ${CATEGORIES.length}`}
          />

          <SummaryCard
            label="Selected period"
            value={formatMonth(selectedMonth)}
          />
        </section>

        {error && (
          <div className="mt-5">
            <PageError message={error} />
          </div>
        )}

        {success && (
          <div className="mt-5">
            <PageSuccess message={success} />
          </div>
        )}

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
          <section className="mt-6 grid gap-4 md:grid-cols-2">
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
                <div
                  key={category}
                  className="rounded-3xl border border-white/10 bg-white/[0.06] p-5 shadow-xl shadow-black/20 backdrop-blur-xl transition hover:border-emerald-400/20 hover:bg-white/[0.075]"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h2 className="font-semibold text-slate-100">
                        {category}
                      </h2>

                      <p className="mt-1 text-xs text-slate-500">
                        {formatMonth(selectedMonth)}
                      </p>
                    </div>

                    <span
                      className={`rounded-xl px-3 py-1.5 text-sm font-medium ${
                        budget
                          ? "bg-emerald-400/10 text-emerald-300"
                          : "bg-white/5 text-slate-400"
                      }`}
                    >
                      {budget
                        ? formatCents(budget.limit_cents)
                        : "Not set"}
                    </span>
                  </div>

                  {categoryProgress && (
                    <div className="mt-5">
                      <div className="flex items-center justify-between gap-4 text-sm">
                        <span className="text-slate-400">
                          {formatCents(categoryProgress.spent_cents)} spent
                        </span>

                        <span
                          className={
                            categoryProgress.over_budget_cents > 0
                              ? "font-medium text-rose-300"
                              : "text-slate-400"
                          }
                        >
                          {categoryProgress.over_budget_cents > 0
                            ? `${formatCents(
                                categoryProgress.over_budget_cents
                              )} over`
                            : `${formatCents(
                                categoryProgress.remaining_cents
                              )} remaining`}
                        </span>
                      </div>

                      <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-white/10">
                        <div
                          className={`h-full rounded-full transition-all ${
                            categoryProgress.percent_used >= 100
                              ? "bg-rose-400"
                              : categoryProgress.percent_used >= 75
                              ? "bg-amber-400"
                              : "bg-emerald-400"
                          }`}
                          style={{
                            width: `${Math.min(
                              categoryProgress.percent_used,
                              100
                            )}%`,
                          }}
                        />
                      </div>

                      <p
                        className={`mt-2 text-xs ${
                          categoryProgress.percent_used >= 100
                            ? "text-rose-300"
                            : categoryProgress.percent_used >= 75
                            ? "text-amber-300"
                            : "text-slate-500"
                        }`}
                      >
                        {categoryProgress.percent_used}% used
                      </p>
                    </div>
                  )}

                  <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                    <div className="relative min-w-0 flex-1">
                      <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-sm text-slate-500">
                        $
                      </span>

                      <input
                        type="number"
                        min="0.01"
                        step="0.01"
                        value={values[category] ?? ""}
                        onChange={(event) =>
                          setValues((current) => ({
                            ...current,
                            [category]: event.target.value,
                          }))
                        }
                        placeholder="0.00"
                        className="w-full rounded-xl border border-white/10 bg-slate-950/70 py-3 pl-8 pr-4 outline-none transition placeholder:text-slate-600 focus:border-emerald-400"
                      />
                    </div>

                    <button
                      onClick={() => save(category)}
                      disabled={saving === category}
                      className="rounded-xl bg-emerald-400 px-5 py-3 font-semibold text-slate-950 transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {saving === category
                        ? "Saving..."
                        : budget
                        ? "Update"
                        : "Save"}
                    </button>
                  </div>
                </div>
              );
            })}
          </section>
        )}
        </div>
      </div>
    </main>
  );
}

function SummaryCard({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-3xl border border-white/10 bg-white/[0.06] p-5 shadow-xl shadow-black/20 backdrop-blur-xl">
      <p className="text-sm text-slate-400">{label}</p>

      <p className="mt-3 text-xl font-bold text-emerald-300">
        {value}
      </p>
    </div>
  );
}