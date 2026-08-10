"use client";


import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import SafeToSpendCard from "../components/SafeToSpendCard";
import { PageError } from "../components/PageFeedback";
import {
  api,
  Budget,
  CashFlowForecast,
  CategoryTotal,
  formatCents,
  Overview,
  Recommendation,
  RecommendationSeverity,
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

  const [recommendations, setRecommendations] = useState<
    Recommendation[]
  >([]);
  const [recommendationsLoading, setRecommendationsLoading] =
    useState(true);

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

  const loadRecommendations = useCallback(async (id: number) => {
    setRecommendationsLoading(true);

    try {
      const result = await api.getRecommendations(id);
      setRecommendations(result.recommendations);
    } catch {
      // Compact, secondary section -- a failure here should never
      // block or clutter the rest of the dashboard with another error
      // banner, it just quietly shows nothing.
      setRecommendations([]);
    } finally {
      setRecommendationsLoading(false);
    }
  }, []);

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
        void loadRecommendations(id);
      } catch {
        session.clear();
        router.replace("/");
      }
    }

    void initializeDashboard();
  }, [router, loadDashboard, loadRecommendations]);

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

  // True while there is no successfully loaded data to show yet,
  // whether that's because the initial load is still in flight or
  // because it failed before ever succeeding once. Prevents showing
  // misleading zero/empty values in place of real data.
  const showSkeleton = loading || (Boolean(error) && !overview);

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

              <h1 className="mt-3 text-[clamp(1.45rem,4.8vw,3.75rem)] font-semibold leading-tight tracking-[-0.055em] text-[#12261f]">
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

          {message && !error && (
            <div
              role="status"
              aria-live="polite"
              className="mt-6 rounded-2xl border border-[#187a59]/20 bg-[#dff6c7] px-4 py-3 text-sm text-[#285d42]"
            >
              {message}
            </div>
          )}

          {error && (
            <div className="mt-6">
              <PageError
                message={error}
                onRetry={
                  !overview && userId !== null
                    ? () => loadDashboard(userId)
                    : undefined
                }
              />
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

                    {showSkeleton ? (
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

                  {!showSkeleton && (
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
                  )}
                </div>

                <div className="mt-10 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-3">
                  <DarkMetric
                    label="Income"
                    loading={showSkeleton}
                    value={formatCents(
                      overview?.total_income_cents ?? 0
                    )}
                    tone="positive"
                  />

                  <DarkMetric
                    label="Spending"
                    loading={showSkeleton}
                    value={formatCents(
                      -(overview?.total_spending_cents ?? 0)
                    )}
                    tone="negative"
                  />

                  <DarkMetric
                    label="Transactions"
                    loading={showSkeleton}
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

                  {showSkeleton ? (
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
                {showSkeleton
                  ? "Calculating your forecast..."
                  : cashFlow?.low_balance_risk
                  ? "Your projected balance may fall below a safe level."
                  : "Your current balance and expected activity remain on track."}
              </p>

              <div className="mt-8 space-y-4 border-t border-[#173128]/10 pt-6">
                <LightStat
                  label="Expected income"
                  loading={showSkeleton}
                  value={formatCents(
                    cashFlow?.expected_income_cents ?? 0
                  )}
                />

                <LightStat
                  label="Upcoming bills"
                  loading={showSkeleton}
                  value={formatCents(
                    -(cashFlow?.upcoming_bills_cents ?? 0)
                  )}
                />

                <LightStat
                  label="Days remaining"
                  loading={showSkeleton}
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

          <NeedsAttentionSection
            recommendations={recommendations}
            loading={recommendationsLoading}
            onSelect={(deepLink) => router.push(deepLink ?? "/recommendations")}
          />

          <section className="mt-8 grid gap-5 sm:grid-cols-3">
            <SoftMetric
              label="Income this month"
              loading={showSkeleton}
              value={formatCents(
                overview?.total_income_cents ?? 0
              )}
              description="Money received"
              background="bg-[#fffdf8]"
            />

            <SoftMetric
              label="Spending this month"
              loading={showSkeleton}
              value={formatCents(
                -(overview?.total_spending_cents ?? 0)
              )}
              description="Recorded expenses"
              background="bg-[#f0b8a8]"
            />

            <SoftMetric
              label="Goal progress"
              loading={showSkeleton}
              value={`${goalProgress}%`}
              description={
                showSkeleton
                  ? "Loading..."
                  : goals.length > 0
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
                  {showSkeleton
                    ? ""
                    : `${overview?.transaction_count ?? 0} transactions`}
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

              {showSkeleton ? (
                <div className="mt-5 space-y-3">
                  <div className="h-8 w-full animate-pulse rounded-lg bg-[#2f2912]/[0.08]" />
                  <div className="h-5 w-2/3 animate-pulse rounded-lg bg-[#2f2912]/[0.08]" />
                </div>
              ) : (
                <>
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
                </>
              )}

              <div className="mt-8 border-t border-[#2f2912]/10 pt-6">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#735d15]">
                  Current-month spending
                </p>

                {showSkeleton ? (
                  <div className="mt-2 h-9 w-32 animate-pulse rounded-lg bg-[#2f2912]/[0.08]" />
                ) : (
                  <p className="mt-2 text-3xl font-semibold tracking-[-0.04em] text-[#2f2912]">
                    {formatCents(-currentMonthSpending)}
                  </p>
                )}
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
              {showSkeleton ? (
                <PreviewSkeleton />
              ) : budgetPreview.length > 0 ? (
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
              {showSkeleton ? (
                <PreviewSkeleton />
              ) : goals.length > 0 ? (
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
              {showSkeleton ? (
                <PreviewSkeleton />
              ) : recentTransactions.length > 0 ? (
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
  loading = false,
}: {
  label: string;
  value: string;
  tone: "positive" | "negative" | "neutral";
  loading?: boolean;
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

      {loading ? (
        <div className="mt-2 h-[22px] w-16 animate-pulse rounded bg-white/10" />
      ) : (
        <p className={`mt-2 text-lg font-semibold ${toneClass[tone]}`}>
          {value}
        </p>
      )}
    </div>
  );
}

function LightStat({
  label,
  value,
  loading = false,
}: {
  label: string;
  value: string;
  loading?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-sm text-[#607163]">
        {label}
      </span>

      {loading ? (
        <span className="h-[18px] w-14 animate-pulse rounded bg-[#173128]/10" />
      ) : (
        <span className="text-sm font-semibold text-[#173128]">
          {value}
        </span>
      )}
    </div>
  );
}

function SoftMetric({
  label,
  value,
  description,
  background,
  loading = false,
}: {
  label: string;
  value: string;
  description: string;
  background: string;
  loading?: boolean;
}) {
  return (
    <article className={`premium-hover rounded-[26px] p-6 ${background}`}>
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#52645b]">
        {label}
      </p>

      {loading ? (
        <div className="mt-4 h-8 w-20 animate-pulse rounded bg-[#173128]/10" />
      ) : (
        <p className="mt-4 text-3xl font-semibold tracking-[-0.045em] text-[#173128]">
          {value}
        </p>
      )}

      <p className="mt-2 text-sm text-[#65746d]">
        {description}
      </p>
    </article>
  );
}

function PreviewSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading"
      className="space-y-3"
    >
      <div className="h-5 w-full animate-pulse rounded-lg bg-[#173128]/[0.06]" />
      <div className="h-5 w-3/4 animate-pulse rounded-lg bg-[#173128]/[0.06]" />
      <div className="h-5 w-5/6 animate-pulse rounded-lg bg-[#173128]/[0.06]" />
    </div>
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

const NEEDS_ATTENTION_STYLES: Record<
  RecommendationSeverity,
  { dot: string; label: string }
> = {
  critical: { dot: "bg-[#c9503f]", label: "Critical" },
  warning: { dot: "bg-[#d9a022]", label: "Warning" },
  opportunity: { dot: "bg-[#1c78ac]", label: "Opportunity" },
  positive: { dot: "bg-[#3f8f52]", label: "Positive" },
  informational: { dot: "bg-[#7b8781]", label: "Info" },
};

function NeedsAttentionSection({
  recommendations,
  loading,
  onSelect,
}: {
  recommendations: Recommendation[];
  loading: boolean;
  onSelect: (deepLink: string | null) => void;
}) {
  if (loading) {
    return (
      <section className="mt-8">
        <div className="grid gap-3 sm:grid-cols-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <div
              key={index}
              className="h-20 animate-pulse rounded-2xl border border-[#173128]/8 bg-white"
            />
          ))}
        </div>
      </section>
    );
  }

  // A compact, opportunistic section -- nothing to show simply means
  // nothing needs attention, so it stays out of the way entirely
  // rather than adding an empty-state box to an already busy page.
  if (recommendations.length === 0) return null;

  const topSignals = recommendations.slice(0, 3);

  return (
    <section className="mt-8">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#7b8781]">
          Needs attention
        </p>
        <button
          type="button"
          onClick={() => onSelect("/recommendations")}
          className="text-xs font-semibold text-[#187a59] transition hover:opacity-65"
        >
          See all →
        </button>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        {topSignals.map((recommendation) => {
          const style = NEEDS_ATTENTION_STYLES[recommendation.severity];

          return (
            <button
              key={recommendation.id}
              type="button"
              onClick={() => onSelect(recommendation.deep_link)}
              className="premium-hover flex items-start gap-3 rounded-2xl border border-[#173128]/8 bg-white p-4 text-left transition hover:border-[#173128]/20"
            >
              <span
                className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${style.dot}`}
                aria-hidden="true"
              />
              <span className="min-w-0">
                <span className="block text-[10px] font-semibold uppercase tracking-[0.1em] text-[#89938e]">
                  {style.label}
                </span>
                <span className="mt-1 block truncate text-sm font-semibold text-[#173128]">
                  {recommendation.title}
                </span>
                <span className="mt-1 flex items-center gap-1 text-xs text-[#7b8781]">
                  {recommendation.impact ?? "View details"}
                  <ArrowRight className="h-3 w-3" />
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
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
