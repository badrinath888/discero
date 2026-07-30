"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import {
  api,
  Budget,
  CategoryTotal,
  formatCents,
  MonthTotal,
  Overview,
  RecurringPayment,
  session,
  Transaction,
} from "../lib/api";
import BudgetProgress from "../components/BudgetProgress";
import MonthlyTrend from "../components/MonthlyTrend";
import RecurringPayments from "../components/RecurringPayments";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

function getCurrentMonth(): string {
  const today = new Date();

  return `${today.getFullYear()}-${String(
    today.getMonth() + 1
  ).padStart(2, "0")}`;
}

function formatMonth(month: string): string {
  const [year, monthNumber] = month.split("-").map(Number);

  return new Date(
    year,
    monthNumber - 1,
    1
  ).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });
}

export default function Dashboard() {
  const router = useRouter();
  const budgetMonth = getCurrentMonth();

  const [userId, setUserId] = useState<number | null>(
    null
  );
  const [overview, setOverview] =
    useState<Overview | null>(null);
  const [categories, setCategories] = useState<
    CategoryTotal[]
  >([]);
  const [months, setMonths] = useState<MonthTotal[]>([]);
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [transactions, setTransactions] = useState<
    Transaction[]
  >([]);
  const [recurring, setRecurring] = useState<
    RecurringPayment[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const loadDashboard = useCallback(
    async (id: number) => {
      setLoading(true);
      setError("");

      try {
        const [
          overviewData,
          categoryData,
          monthData,
          budgetData,
          transactionData,
          recurringData,
        ] = await Promise.all([
          api.overview(id),
          api.byCategory(id),
          api.byMonth(id),
          api.getBudgets(id, budgetMonth),
          api.getTransactions(id),
          api.getRecurringPayments(id),
        ]);

        setOverview(overviewData);
        setCategories(categoryData);
        setMonths(monthData);
        setBudgets(budgetData);
        setTransactions(transactionData);
        setRecurring(recurringData);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Unable to load dashboard"
        );
      } finally {
        setLoading(false);
      }
    },
    [budgetMonth]
  );

  useEffect(() => {
    async function initializeDashboard() {
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

        setUserId(id);
        await loadDashboard(id);
      } catch {
        session.clear();
        router.replace("/");
      }
    }

    void initializeDashboard();
  }, [router, loadDashboard]);

  const currentMonthCategories = useMemo(() => {
    const totals = new Map<
      string,
      {
        total_cents: number;
        count: number;
      }
    >();

    for (const transaction of transactions) {
      if (
        !transaction.posted_on.startsWith(budgetMonth) ||
        transaction.amount_cents >= 0
      ) {
        continue;
      }

      const current = totals.get(
        transaction.category
      ) ?? {
        total_cents: 0,
        count: 0,
      };

      current.total_cents += transaction.amount_cents;
      current.count += 1;

      totals.set(transaction.category, current);
    }

    return Array.from(totals.entries())
      .map(([category, values]) => ({
        category,
        total_cents: values.total_cents,
        count: values.count,
      }))
      .sort(
        (a, b) =>
          Math.abs(b.total_cents) -
          Math.abs(a.total_cents)
      );
  }, [transactions, budgetMonth]);

  const spendingData = useMemo(
    () =>
      categories
        .filter(
          ({ total_cents }) => total_cents < 0
        )
        .map(
          ({
            category,
            total_cents,
            count,
          }) => ({
            category,
            amount: Math.abs(total_cents) / 100,
            count,
          })
        )
        .sort((a, b) => b.amount - a.amount),
    [categories]
  );

  const highestCategory = spendingData[0];

  async function handleUpload(
    event: React.ChangeEvent<HTMLInputElement>
  ) {
    const file = event.target.files?.[0];

    if (!file || userId === null) return;

    setUploading(true);
    setMessage("");
    setError("");

    try {
      const result =
        await api.uploadTransactions(userId, file);

      const parts = [
        `${result.imported} imported`,
      ];

      if (result.duplicates > 0) {
        parts.push(
          `${result.duplicates} duplicates skipped`
        );
      }

      if (result.rejected > 0) {
        parts.push(
          `${result.rejected} rejected`
        );
      }

      setMessage(`${parts.join(", ")}.`);

      await loadDashboard(userId);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "CSV upload failed"
      );
    } finally {
      setUploading(false);
      event.target.value = "";
    }
  }

  function signOut() {
    session.clear();
    router.replace("/");
  }

  return (
    <main
      className="relative min-h-screen overflow-hidden bg-[#07111f] text-white"
      style={{
        backgroundImage: `
          radial-gradient(circle at 15% 10%, rgba(16,185,129,0.16), transparent 30%),
          radial-gradient(circle at 85% 20%, rgba(14,165,233,0.10), transparent 28%),
          linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)
        `,
        backgroundSize:
          "auto, auto, 42px 42px, 42px 42px",
      }}
    >
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent via-[#07111f]/40 to-[#07111f]" />

      <div className="relative mx-auto max-w-7xl px-5 py-8 sm:px-8 lg:px-10">
        <header className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-300">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              Financial overview
            </div>

            <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
              Welcome to FinSight
            </h1>

            <p className="mt-2 max-w-xl text-sm text-slate-400 sm:text-base">
              Understand your income, spending
              patterns, and financial health in one
              place.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() =>
                router.push("/transactions")
              }
              className="rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-slate-300 transition hover:bg-white/10 hover:text-white"
            >
              Transactions
            </button>

            <button
              type="button"
              onClick={() =>
                router.push("/budgets")
              }
              className="rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-slate-300 transition hover:bg-white/10 hover:text-white"
            >
              Budgets
            </button>

            <button
             type="button"
              onClick={() =>
            router.push("/accounts")
            }
            className="rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-slate-300 transition hover:bg-white/10 hover:text-white"
     >
  Accounts
</button>

            <button
              type="button"
              onClick={signOut}
              className="rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-slate-300 transition hover:bg-white/10 hover:text-white"
            >
              Sign out
            </button>

            <label className="cursor-pointer rounded-xl bg-emerald-500 px-5 py-2.5 text-sm font-semibold text-slate-950 shadow-lg shadow-emerald-500/20 transition hover:bg-emerald-400">
              {uploading
                ? "Uploading..."
                : "Upload CSV"}

              <input
                type="file"
                accept=".csv"
                className="hidden"
                disabled={uploading}
                onChange={handleUpload}
              />
            </label>
          </div>
        </header>

        {(message || error) && (
          <div
            className={`mt-7 rounded-2xl border px-4 py-3 text-sm ${
              error
                ? "border-red-400/20 bg-red-400/10 text-red-300"
                : "border-emerald-400/20 bg-emerald-400/10 text-emerald-300"
            }`}
          >
            {error || message}
          </div>
        )}

        <section className="mt-8 grid gap-5 md:grid-cols-3">
          <SummaryCard
            label="Total income"
            value={
              overview
                ? formatCents(
                    overview.total_income_cents
                  )
                : "$0.00"
            }
            description="Money received"
            icon="↑"
            accent="emerald"
            loading={loading}
          />

          <SummaryCard
            label="Total spending"
            value={
              overview
                ? formatCents(
                    -overview.total_spending_cents
                  )
                : "$0.00"
            }
            description="Money spent"
            icon="↓"
            accent="rose"
            loading={loading}
          />

          <SummaryCard
            label="Net balance"
            value={
              overview
                ? formatCents(overview.net_cents)
                : "$0.00"
            }
            description="Income minus spending"
            icon="$"
            accent={
              overview && overview.net_cents < 0
                ? "rose"
                : "cyan"
            }
            loading={loading}
          />
        </section>

        <section className="mt-6 grid gap-6 lg:grid-cols-[1.7fr_0.8fr]">
          <div className="rounded-3xl border border-white/10 bg-white/[0.06] p-5 shadow-2xl shadow-black/20 backdrop-blur-xl sm:p-7">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-lg font-semibold">
                  Spending by category
                </p>

                <p className="mt-1 text-sm text-slate-400">
                  Your largest expense categories
                  across all imported transactions
                </p>
              </div>

              <div className="rounded-xl border border-white/10 bg-slate-900/60 px-3 py-2 text-xs text-slate-400">
                {overview?.transaction_count ?? 0}{" "}
                transactions
              </div>
            </div>

            <div className="mt-8 h-[390px]">
              {loading ? (
                <LoadingState message="Loading spending analysis..." />
              ) : spendingData.length === 0 ? (
                <EmptyState />
              ) : (
                <ResponsiveContainer
                  width="100%"
                  height="100%"
                >
                  <BarChart
                    data={spendingData}
                    layout="vertical"
                    margin={{
                      top: 0,
                      right: 20,
                      bottom: 0,
                      left: 15,
                    }}
                  >
                    <CartesianGrid
                      strokeDasharray="4 4"
                      horizontal={false}
                      stroke="rgba(255,255,255,0.08)"
                    />

                    <XAxis
                      type="number"
                      tickFormatter={(value) =>
                        `$${value}`
                      }
                      tick={{
                        fill: "#94a3b8",
                        fontSize: 12,
                      }}
                      axisLine={false}
                      tickLine={false}
                    />

                    <YAxis
                      type="category"
                      dataKey="category"
                      width={105}
                      tick={{
                        fill: "#cbd5e1",
                        fontSize: 12,
                      }}
                      axisLine={false}
                      tickLine={false}
                    />

                    <Tooltip
                      cursor={{
                        fill: "rgba(255,255,255,0.04)",
                      }}
                      content={<CustomTooltip />}
                    />

                    <Bar
                      dataKey="amount"
                      fill="#34d399"
                      radius={[0, 8, 8, 0]}
                      barSize={24}
                    />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          <aside className="space-y-6">
            <div className="rounded-3xl border border-white/10 bg-gradient-to-br from-emerald-500/20 to-cyan-500/10 p-6 backdrop-blur-xl">
              <p className="text-sm font-medium text-emerald-300">
                Spending insight
              </p>

              <h2 className="mt-3 text-2xl font-bold">
                {highestCategory
                  ? highestCategory.category
                  : "Upload data"}
              </h2>

              <p className="mt-2 text-sm leading-6 text-slate-300">
                {highestCategory
                  ? `${
                      highestCategory.category
                    } is currently your largest spending category at ${highestCategory.amount.toLocaleString(
                      "en-US",
                      {
                        style: "currency",
                        currency: "USD",
                      }
                    )}.`
                  : "Upload a CSV file to discover where most of your money is going."}
              </p>
            </div>

            <div className="rounded-3xl border border-white/10 bg-white/[0.06] p-6 backdrop-blur-xl">
              <p className="text-sm font-semibold">
                Category breakdown
              </p>

              <div className="mt-5 space-y-4">
                {spendingData
                  .slice(0, 5)
                  .map((item) => {
                    const totalSpending =
                      overview?.total_spending_cents ??
                      0;

                    const percentage =
                      totalSpending > 0
                        ? Math.round(
                            ((item.amount * 100) /
                              totalSpending) *
                              100
                          )
                        : 0;

                    return (
                      <div key={item.category}>
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-slate-300">
                            {item.category}
                          </span>

                          <span className="font-medium">
                            {item.amount.toLocaleString(
                              "en-US",
                              {
                                style:
                                  "currency",
                                currency: "USD",
                              }
                            )}
                          </span>
                        </div>

                        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
                          <div
                            className="h-full rounded-full bg-emerald-400"
                            style={{
                              width: `${Math.min(
                                percentage,
                                100
                              )}%`,
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}

                {!loading &&
                  spendingData.length === 0 && (
                    <p className="text-sm text-slate-500">
                      No spending data available
                      yet.
                    </p>
                  )}
              </div>
            </div>
          </aside>
        </section>

        <div className="mt-6">
          <MonthlyTrend data={months} />
        </div>

        <section className="mt-6">
          <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-lg font-semibold">
                Monthly budget progress
              </p>

              <p className="mt-1 text-sm text-slate-400">
                Comparing spending and limits for{" "}
                {formatMonth(budgetMonth)}
              </p>
            </div>

            <button
              type="button"
              onClick={() =>
                router.push("/budgets")
              }
              className="rounded-xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-400/20"
            >
              Manage budgets
            </button>
          </div>

          <BudgetProgress
            budgets={budgets}
            categories={currentMonthCategories}
          />
        </section>

        <div className="mt-6">
          <RecurringPayments
            payments={recurring}
          />
        </div>
      </div>
    </main>
  );
}

function SummaryCard({
  label,
  value,
  description,
  icon,
  accent,
  loading,
}: {
  label: string;
  value: string;
  description: string;
  icon: string;
  accent: "emerald" | "rose" | "cyan";
  loading: boolean;
}) {
  const styles = {
    emerald: {
      icon: "bg-emerald-400/15 text-emerald-300",
      value: "text-emerald-300",
    },
    rose: {
      icon: "bg-rose-400/15 text-rose-300",
      value: "text-rose-300",
    },
    cyan: {
      icon: "bg-cyan-400/15 text-cyan-300",
      value: "text-cyan-300",
    },
  };

  return (
    <div className="rounded-3xl border border-white/10 bg-white/[0.06] p-6 shadow-xl shadow-black/10 backdrop-blur-xl transition hover:-translate-y-1 hover:bg-white/[0.08]">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-slate-400">
            {label}
          </p>

          {loading ? (
            <div className="mt-4 h-9 w-32 animate-pulse rounded-lg bg-white/10" />
          ) : (
            <p
              className={`mt-3 text-3xl font-bold tracking-tight ${styles[accent].value}`}
            >
              {value}
            </p>
          )}

          <p className="mt-2 text-xs text-slate-500">
            {description}
          </p>
        </div>

        <div
          className={`flex h-11 w-11 items-center justify-center rounded-2xl text-lg font-bold ${styles[accent].icon}`}
        >
          {icon}
        </div>
      </div>
    </div>
  );
}

function LoadingState({
  message,
}: {
  message: string;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-emerald-400 border-t-transparent" />

      <p className="mt-3 text-sm text-slate-400">
        {message}
      </p>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 bg-white/[0.02] text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-400/10 text-2xl">
        $
      </div>

      <p className="mt-4 font-medium">
        No financial data yet
      </p>

      <p className="mt-2 max-w-xs text-sm text-slate-500">
        Upload a transaction CSV to generate your
        dashboard and spending analysis.
      </p>
    </div>
  );
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{
    value?: number;
    payload?: {
      count?: number;
    };
  }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;

  const amount = Number(
    payload[0].value ?? 0
  );
  const count =
    payload[0].payload?.count ?? 0;

  return (
    <div className="rounded-xl border border-white/10 bg-slate-900/95 px-4 py-3 shadow-xl">
      <p className="text-sm font-semibold">
        {label}
      </p>

      <p className="mt-1 text-sm text-emerald-300">
        {amount.toLocaleString("en-US", {
          style: "currency",
          currency: "USD",
        })}
      </p>

      <p className="mt-1 text-xs text-slate-500">
        {count} transaction
        {count === 1 ? "" : "s"}
      </p>
    </div>
  );
}
