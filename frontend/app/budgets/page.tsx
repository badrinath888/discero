"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, Budget, formatCents, session } from "../lib/api";

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
        const data = await api.getBudgets(
          id,
          selectedMonth
        );

        setBudgets(data);
        setValues(
          Object.fromEntries(
            data.map((budget) => [
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
      <main className="flex min-h-screen items-center justify-center bg-[#050d18] text-white">
        <div className="text-center">
          <div className="mx-auto h-9 w-9 animate-spin rounded-full border-2 border-emerald-400 border-t-transparent" />

          <p className="mt-4 text-sm text-slate-400">
            Checking your session...
          </p>
        </div>
      </main>
    );
  }

  return (
    <main
      className="relative min-h-screen overflow-hidden bg-[#050d18] px-5 py-8 text-white"
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

      <div className="relative mx-auto max-w-6xl">
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

          <button
            onClick={() => router.push("/dashboard")}
            className="rounded-xl border border-white/10 bg-white/[0.06] px-5 py-2.5 text-sm font-medium text-slate-200 transition hover:bg-white/10"
          >
            Back to dashboard
          </button>
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
          <div className="mt-5 rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-300">
            {error}
          </div>
        )}

        {success && (
          <div className="mt-5 rounded-2xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-300">
            {success}
          </div>
        )}

        {loading ? (
          <div className="mt-6 flex min-h-72 items-center justify-center rounded-3xl border border-white/10 bg-white/[0.05] backdrop-blur-xl">
            <div className="text-center">
              <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-emerald-400 border-t-transparent" />

              <p className="mt-3 text-sm text-slate-400">
                Loading budgets...
              </p>
            </div>
          </div>
        ) : (
          <section className="mt-6 grid gap-4 md:grid-cols-2">
            {CATEGORIES.map((category) => {
              const budget = budgets.find(
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