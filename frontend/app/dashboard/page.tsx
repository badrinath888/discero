"use client";


import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import SafeToSpendCard from "../components/SafeToSpendCard";
import {
  api,
  Budget,
  CashFlowForecast,
  CategoryTotal,
  formatCents,
  Overview,
  SavingsGoal,
  session,
  Transaction,
} from "../lib/api";
import AppSidebar from "../components/AppSidebar";
import { AnimatedNumber, PageReveal } from "../components/PremiumMotion";
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
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [transactions, setTransactions] = useState<
    Transaction[]
  >([]);
  const [goals, setGoals] = useState<SavingsGoal[]>([]);
  const [cashFlow, setCashFlow] =
    useState<CashFlowForecast | null>(null);
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
          budgetData,
          transactionData,
          goalData,
          cashFlowData,
        ] = await Promise.all([
          api.overview(id),
          api.byCategory(id),
          api.getBudgets(id, budgetMonth),
          api.getTransactions(id),
          api.getSavingsGoals(id),
          api.getCashFlowForecast(id),
        ]);

        setOverview(overviewData);
        setCategories(categoryData);
        setBudgets(budgetData);
        setTransactions(transactionData);
        setGoals(goalData);
        setCashFlow(cashFlowData);
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

  const goalSummary = useMemo(
    () =>
      goals.reduce(
        (summary, goal) => ({
          target: summary.target + goal.target_cents,
          saved: summary.saved + goal.saved_cents,
          completed:
            summary.completed +
            (goal.status === "completed" ? 1 : 0),
        }),
        {
          target: 0,
          saved: 0,
          completed: 0,
        }
      ),
    [goals]
  );

  const goalProgress =
    goalSummary.target > 0
      ? Math.min(
          Math.round(
            (goalSummary.saved / goalSummary.target) * 100
          ),
          100
        )
      : 0;

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


  const currentMonthSpending = useMemo(
    () =>
      currentMonthCategories.reduce(
        (total, category) =>
          total + Math.abs(category.total_cents),
        0
      ),
    [currentMonthCategories]
  );

  const recentTransactions = useMemo(
    () => transactions.slice(0, 5),
    [transactions]
  );

  const budgetPreview = useMemo(
    () =>
      budgets.slice(0, 4).map((budget) => {
        const category = currentMonthCategories.find(
          (item) => item.category === budget.category
        );

        const spent = Math.abs(
          category?.total_cents ?? 0
        );

        const percentage =
          budget.limit_cents > 0
            ? Math.min(
                Math.round(
                  (spent / budget.limit_cents) * 100
                ),
                100
              )
            : 0;

        return {
          ...budget,
          spent,
          percentage,
        };
      }),
    [budgets, currentMonthCategories]
  );

  return (
    <main className="min-h-screen bg-[#f4efe5] text-[#173128]">
      <AppSidebar />

      <div className="px-5 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-8">
        <PageReveal className="mx-auto max-w-7xl">
          <header className="flex flex-col gap-6 border-b border-[#173128]/10 pb-8 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#187a59]">
                {formatMonth(budgetMonth)}
              </p>

              <h1 className="mt-3 max-w-3xl text-4xl font-semibold leading-tight tracking-[-0.055em] text-[#12261f] sm:text-6xl">
                Here’s how your money is doing.
              </h1>

              <p className="mt-4 max-w-2xl text-base leading-7 text-[#68766f]">
                Review your balance, spending patterns, upcoming
                cash flow, budgets, and goals in one place.
              </p>
            </div>

            <label className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-full bg-[#173128] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#26463b]">
              <UploadIcon />

              {uploading ? "Uploading..." : "Upload CSV"}

              <input
                type="file"
                accept=".csv"
                className="hidden"
                disabled={uploading}
                onChange={handleUpload}
              />
            </label>
          </header>

          {(message || error) && (
            <div
              className={`mt-6 rounded-2xl border px-4 py-3 text-sm ${
                error
                  ? "border-[#b65743]/20 bg-[#f0b8a8]/30 text-[#843d2f]"
                  : "border-[#187a59]/20 bg-[#dff6c7] text-[#285d42]"
              }`}
            >
              {error || message}
            </div>
          )}

          <SafeToSpendCard
  userId={userId}
  refreshKey={transactions.length}
/>

          <section className="mt-8 grid gap-5 lg:grid-cols-[1.25fr_0.75fr]">
            <article className="premium-hover relative overflow-hidden rounded-[30px] bg-[#173128] p-7 text-white shadow-[0_24px_60px_rgba(23,49,40,0.18)] sm:p-9">
              <div className="pointer-events-none absolute -right-14 -top-14 h-48 w-48 rounded-full bg-[#64d7aa]/20 blur-2xl" />

              <div className="relative">
                <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#83dcb9]">
                      Net financial position
                    </p>

                    {loading ? (
                      <div className="mt-5 h-14 w-56 animate-pulse rounded-xl bg-white/10" />
                    ) : (
                      <AnimatedNumber
                        value={overview?.net_cents ?? 0}
                        format={formatCents}
                        className="mt-4 block text-5xl font-semibold tracking-[-0.06em] sm:text-6xl"
                      />
                    )}

                    <p className="mt-3 text-sm text-white/55">
                      Income minus total recorded spending
                    </p>
                  </div>

                  <span
                    className={`inline-flex w-fit rounded-full px-3 py-1.5 text-xs font-semibold ${
                      (overview?.net_cents ?? 0) >= 0
                        ? "bg-[#dff6c7] text-[#315d31]"
                        : "bg-[#f0b8a8] text-[#7b3528]"
                    }`}
                  >
                    {(overview?.net_cents ?? 0) >= 0
                      ? "Positive balance"
                      : "Needs attention"}
                  </span>
                </div>

                <div className="mt-10 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-3">
                  <DarkMetric
                    label="Income"
                    value={formatCents(
                      overview?.total_income_cents ?? 0
                    )}
                    tone="positive"
                  />

                  <DarkMetric
                    label="Spending"
                    value={formatCents(
                      -(overview?.total_spending_cents ?? 0)
                    )}
                    tone="negative"
                  />

                  <DarkMetric
                    label="Transactions"
                    value={String(
                      overview?.transaction_count ?? 0
                    )}
                    tone="neutral"
                  />
                </div>
              </div>
            </article>

            <article className="premium-hover rounded-[30px] bg-[#dff6c7] p-7 sm:p-8">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#4c7e53]">
                    Month-end forecast
                  </p>

                  {loading ? (
                    <div className="mt-5 h-11 w-40 animate-pulse rounded-lg bg-[#173128]/10" />
                  ) : (
                    <AnimatedNumber
                      value={cashFlow?.projected_end_balance_cents ?? 0}
                      format={formatCents}
                      className="mt-4 block text-4xl font-semibold tracking-[-0.05em] text-[#173128]"
                    />
                  )}
                </div>

                <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#173128] text-[#dff6c7]">
                  <TrendIcon />
                </span>
              </div>

              <p className="mt-4 text-sm leading-6 text-[#56705d]">
                {cashFlow?.low_balance_risk
                  ? "Your projected balance may fall below a safe level."
                  : "Your current balance and expected activity remain on track."}
              </p>

              <div className="mt-8 space-y-4 border-t border-[#173128]/10 pt-6">
                <LightStat
                  label="Expected income"
                  value={formatCents(
                    cashFlow?.expected_income_cents ?? 0
                  )}
                />

                <LightStat
                  label="Upcoming bills"
                  value={formatCents(
                    -(cashFlow?.upcoming_bills_cents ?? 0)
                  )}
                />

                <LightStat
                  label="Days remaining"
                  value={String(
                    cashFlow?.days_remaining ?? 0
                  )}
                />
              </div>

              <button
                type="button"
                onClick={() => router.push("/forecast")}
                className="mt-7 text-sm font-semibold text-[#173128] transition hover:opacity-65"
              >
                View full forecast →
              </button>
            </article>
          </section>

          <section className="mt-8 grid gap-5 sm:grid-cols-3">
            <SoftMetric
              label="Income this month"
              value={formatCents(
                overview?.total_income_cents ?? 0
              )}
              description="Money received"
              background="bg-[#fffdf8]"
            />

            <SoftMetric
              label="Spending this month"
              value={formatCents(
                -(overview?.total_spending_cents ?? 0)
              )}
              description="Recorded expenses"
              background="bg-[#f0b8a8]"
            />

            <SoftMetric
              label="Goal progress"
              value={`${goalProgress}%`}
              description={
                goals.length > 0
                  ? `${goals.length} active goal${
                      goals.length === 1 ? "" : "s"
                    }`
                  : "No goals created yet"
              }
              background="bg-[#c9e7ff]"
            />
          </section>

          <section className="mt-12 grid gap-6 lg:grid-cols-[1.25fr_0.75fr]">
            <article className="premium-hover rounded-[30px] bg-white p-6 shadow-[0_18px_50px_rgba(23,49,40,0.08)] sm:p-8">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#187a59]">
                    Spending patterns
                  </p>

                  <h2 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">
                    Where your money went
                  </h2>

                  <p className="mt-2 text-sm text-[#758078]">
                    Top expense categories across imported activity
                  </p>
                </div>

                <p className="text-xs text-[#8b958f]">
                  {overview?.transaction_count ?? 0} transactions
                </p>
              </div>

              <div className="mt-7 h-[330px]">
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
                      data={spendingData.slice(0, 6)}
                      layout="vertical"
                      margin={{
                        top: 4,
                        right: 28,
                        bottom: 4,
                        left: 2,
                      }}
                    >
                      <CartesianGrid
                        strokeDasharray="3 5"
                        horizontal={false}
                        stroke="rgba(23,49,40,0.09)"
                      />

                      <XAxis
                        type="number"
                        tickFormatter={(value) =>
                          `$${Number(value).toLocaleString(
                            "en-US",
                            {
                              notation: "compact",
                            }
                          )}`
                        }
                        tick={{
                          fill: "#839088",
                          fontSize: 11,
                        }}
                        axisLine={false}
                        tickLine={false}
                      />

                      <YAxis
                        type="category"
                        dataKey="category"
                        width={105}
                        tick={{
                          fill: "#52645b",
                          fontSize: 12,
                        }}
                        axisLine={false}
                        tickLine={false}
                      />

                      <Tooltip
                        cursor={{
                          fill: "rgba(23,49,40,0.035)",
                        }}
                        content={<CustomTooltip />}
                      />

                      <Bar
                        dataKey="amount"
                        fill="#187a59"
                        radius={[0, 8, 8, 0]}
                        barSize={20}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </div>
            </article>

            <article className="rounded-[30px] bg-[#f5d66f] p-7 sm:p-8">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#735d15]">
                FinSight observation
              </p>

              <h2 className="mt-5 text-3xl font-semibold leading-tight tracking-[-0.045em] text-[#2f2912]">
                {highestCategory
                  ? `${highestCategory.category} is your largest category.`
                  : "Add transaction data to unlock spending insights."}
              </h2>

              <p className="mt-5 text-sm leading-7 text-[#695d2d]">
                {highestCategory
                  ? `${highestCategory.category} represents your highest recorded spending at ${highestCategory.amount.toLocaleString(
                      "en-US",
                      {
                        style: "currency",
                        currency: "USD",
                      }
                    )}. Review uncategorized items to improve the accuracy of your insights.`
                  : "Upload a CSV or synchronize a connected account to generate personalized observations."}
              </p>

              <div className="mt-8 border-t border-[#2f2912]/10 pt-6">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#735d15]">
                  Current-month spending
                </p>

                <p className="mt-2 text-3xl font-semibold tracking-[-0.04em] text-[#2f2912]">
                  {formatCents(-currentMonthSpending)}
                </p>
              </div>

              <button
                type="button"
                onClick={() => router.push("/insights")}
                className="mt-7 text-sm font-semibold text-[#2f2912] transition hover:opacity-65"
              >
                Explore insights →
              </button>
            </article>
          </section>

          <section className="mt-12 grid gap-6 lg:grid-cols-2">
            <DashboardSection
              eyebrow="Monthly plan"
              title="Budget progress"
              action="Manage budgets →"
              onAction={() => router.push("/budgets")}
            >
              {budgetPreview.length > 0 ? (
                <div className="space-y-5">
                  {budgetPreview.map((budget) => (
                    <div key={budget.id}>
                      <div className="flex items-center justify-between gap-4">
                        <div>
                          <p className="text-sm font-semibold text-[#173128]">
                            {budget.category}
                          </p>

                          <p className="mt-1 text-xs text-[#7b8781]">
                            {formatCents(budget.spent)} of{" "}
                            {formatCents(
                              budget.limit_cents
                            )}
                          </p>
                        </div>

                        <span className="text-sm font-semibold text-[#173128]">
                          {budget.percentage}%
                        </span>
                      </div>

                      <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#173128]/8">
                        <div
                          className={`h-full rounded-full ${
                            budget.percentage >= 100
                              ? "bg-[#b65743]"
                              : budget.percentage >= 75
                              ? "bg-[#d89e24]"
                              : "bg-[#187a59]"
                          }`}
                          style={{
                            width: `${budget.percentage}%`,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <CompactEmpty
                  title="No budgets configured"
                  description="Set monthly limits to start tracking category spending."
                  action="Create a budget"
                  onAction={() =>
                    router.push("/budgets")
                  }
                />
              )}
            </DashboardSection>

            <DashboardSection
              eyebrow="Your milestones"
              title="Savings goals"
              action="Manage goals →"
              onAction={() => router.push("/goals")}
            >
              {goals.length > 0 ? (
                <div>
                  <div className="grid grid-cols-3 gap-4">
                    <MiniStat
                      label="Saved"
                      value={formatCents(
                        goalSummary.saved
                      )}
                    />

                    <MiniStat
                      label="Target"
                      value={formatCents(
                        goalSummary.target
                      )}
                    />

                    <MiniStat
                      label="Complete"
                      value={`${goalSummary.completed}/${goals.length}`}
                    />
                  </div>

                  <div className="mt-7">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-[#7b8781]">
                        Overall progress
                      </span>

                      <span className="font-semibold text-[#187a59]">
                        {goalProgress}%
                      </span>
                    </div>

                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#173128]/8">
                      <div
                        className="h-full rounded-full bg-[#187a59]"
                        style={{
                          width: `${goalProgress}%`,
                        }}
                      />
                    </div>

                    <p className="mt-3 text-xs text-[#7b8781]">
                      {formatCents(
                        Math.max(
                          goalSummary.target -
                            goalSummary.saved,
                          0
                        )
                      )}{" "}
                      remaining
                    </p>
                  </div>
                </div>
              ) : (
                <CompactEmpty
                  title="No savings goals yet"
                  description="Create a goal for an emergency fund, trip, or major purchase."
                  action="Create a goal"
                  onAction={() =>
                    router.push("/goals")
                  }
                />
              )}
            </DashboardSection>
          </section>

          <section className="mt-12 rounded-[30px] bg-white p-6 shadow-[0_18px_50px_rgba(23,49,40,0.08)] sm:p-8">
            <div className="flex items-end justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#187a59]">
                  Recent activity
                </p>

                <h2 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">
                  Latest transactions
                </h2>
              </div>

              <button
                type="button"
                onClick={() =>
                  router.push("/transactions")
                }
                className="text-sm font-semibold text-[#187a59] transition hover:opacity-65"
              >
                View all →
              </button>
            </div>

            <div className="mt-6 divide-y divide-[#173128]/10">
              {recentTransactions.length > 0 ? (
                recentTransactions.map((transaction) => (
                  <div
                    key={transaction.id}
                    className="grid gap-3 py-4 sm:grid-cols-[120px_1fr_150px] sm:items-center"
                  >
                    <p className="text-sm text-[#7b8781]">
                      {new Date(
                        `${transaction.posted_on}T00:00:00`
                      ).toLocaleDateString("en-US", {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })}
                    </p>

                    <div>
                      <p className="text-sm font-semibold text-[#173128]">
                        {transaction.merchant_name ||
                          transaction.description}
                      </p>

                      <p className="mt-1 text-xs text-[#89938e]">
                        {transaction.category}
                      </p>
                    </div>

                    <p
                      className={`text-sm font-semibold sm:text-right ${
                        transaction.amount_cents >= 0
                          ? "text-[#187a59]"
                          : "text-[#a64c3b]"
                      }`}
                    >
                      {formatCents(
                        transaction.amount_cents
                      )}
                    </p>
                  </div>
                ))
              ) : (
                <div className="py-10 text-center text-sm text-[#7b8781]">
                  No recent transactions available.
                </div>
              )}
            </div>
          </section>
        </PageReveal>
      </div>
    </main>
  );
}

function DarkMetric({
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

function LightStat({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-sm text-[#607163]">
        {label}
      </span>

      <span className="text-sm font-semibold text-[#173128]">
        {value}
      </span>
    </div>
  );
}

function SoftMetric({
  label,
  value,
  description,
  background,
}: {
  label: string;
  value: string;
  description: string;
  background: string;
}) {
  return (
    <article className={`premium-hover rounded-[26px] p-6 ${background}`}>
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#52645b]">
        {label}
      </p>

      <p className="mt-4 text-3xl font-semibold tracking-[-0.045em] text-[#173128]">
        {value}
      </p>

      <p className="mt-2 text-sm text-[#65746d]">
        {description}
      </p>
    </article>
  );
}

function DashboardSection({
  eyebrow,
  title,
  action,
  onAction,
  children,
}: {
  eyebrow: string;
  title: string;
  action: string;
  onAction: () => void;
  children: React.ReactNode;
}) {
  return (
    <article className="premium-hover rounded-[30px] bg-white p-6 shadow-[0_18px_50px_rgba(23,49,40,0.08)] sm:p-8">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#187a59]">
            {eyebrow}
          </p>

          <h2 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">
            {title}
          </h2>
        </div>

        <button
          type="button"
          onClick={onAction}
          className="text-sm font-semibold text-[#187a59] transition hover:opacity-65"
        >
          {action}
        </button>
      </div>

      <div className="mt-7">{children}</div>
    </article>
  );
}

function MiniStat({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div>
      <p className="text-xs uppercase tracking-[0.12em] text-[#89938e]">
        {label}
      </p>

      <p className="mt-2 truncate text-lg font-semibold text-[#173128]">
        {value}
      </p>
    </div>
  );
}

function CompactEmpty({
  title,
  description,
  action,
  onAction,
}: {
  title: string;
  description: string;
  action: string;
  onAction: () => void;
}) {
  return (
    <div className="rounded-2xl border border-dashed border-[#173128]/15 bg-[#f8f5ee] px-5 py-9 text-center">
      <p className="text-sm font-semibold text-[#173128]">
        {title}
      </p>

      <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-[#7b8781]">
        {description}
      </p>

      <button
        type="button"
        onClick={onAction}
        className="mt-4 text-sm font-semibold text-[#187a59] transition hover:opacity-65"
      >
        {action} →
      </button>
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
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#187a59] border-t-transparent" />

      <p className="mt-3 text-sm text-[#7b8781]">
        {message}
      </p>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center rounded-2xl border border-dashed border-[#173128]/15 bg-[#f8f5ee] text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#dff6c7] text-xl text-[#187a59]">
        $
      </div>

      <p className="mt-4 font-medium text-[#173128]">
        No financial data yet
      </p>

      <p className="mt-2 max-w-xs text-sm text-[#7b8781]">
        Upload a transaction CSV to generate your
        spending analysis.
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

  const amount = Number(payload[0].value ?? 0);
  const count =
    payload[0].payload?.count ?? 0;

  return (
    <div className="rounded-xl border border-[#173128]/10 bg-white px-4 py-3 shadow-xl">
      <p className="text-sm font-semibold text-[#173128]">
        {label}
      </p>

      <p className="mt-1 text-sm font-semibold text-[#187a59]">
        {amount.toLocaleString("en-US", {
          style: "currency",
          currency: "USD",
        })}
      </p>

      <p className="mt-1 text-xs text-[#7b8781]">
        {count} transaction
        {count === 1 ? "" : "s"}
      </p>
    </div>
  );
}

function UploadIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4"
    >
      <path d="M12 16V4" />
      <path d="m7 9 5-5 5 5" />
      <path d="M5 20h14" />
    </svg>
  );
}

function TrendIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-5 w-5"
    >
      <path d="m4 17 6-6 4 4 6-8" />
      <path d="M15 7h5v5" />
    </svg>
  );
}
