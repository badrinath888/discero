"use client";

import {
  useCallback,
  useEffect,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import {
  CardSkeleton,
  EmptyState,
  PageError,
} from "../components/PageFeedback";
import {
  api,
  FinancialInsight,
  formatCents,
  MonthlyInsights,
  session,
} from "../lib/api";

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

export default function InsightsPage() {
  const router = useRouter();

  const [userId, setUserId] = useState<number | null>(null);
  const [month, setMonth] = useState(getCurrentMonth());
  const [insights, setInsights] =
    useState<MonthlyInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadInsights = useCallback(
    async (id: number, selectedMonth: string) => {
      setLoading(true);
      setError("");

      try {
        setInsights(
          await api.getMonthlyInsights(id, selectedMonth)
        );
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Unable to load financial insights"
        );
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    async function initialize() {
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
        await loadInsights(id, month);
      } catch {
        session.clear();
        router.replace("/");
      }
    }

    void initialize();
  }, [router, loadInsights, month]);

  return (
    <main className="min-h-screen bg-[#f5f1e8] text-[#14241e]">
      <AppSidebar />

      <div className="px-5 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-10">
        <div className="mx-auto max-w-7xl">
          <header className="grid gap-6 xl:grid-cols-[1fr_auto] xl:items-end">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
                Financial intelligence
              </p>

              <h1 className="mt-3 max-w-3xl text-4xl font-semibold leading-tight tracking-[-0.05em] sm:text-5xl">
                See the story behind
                <span className="block text-[#167c5a]">
                  your spending.
                </span>
              </h1>

              <p className="mt-4 max-w-2xl text-sm leading-6 text-[#66746e] sm:text-base">
                Understand what changed, where your money went, and
                which habits deserve your attention.
              </p>
            </div>

            <label className="rounded-[22px] border border-[#14241e]/10 bg-white p-4 text-sm font-medium">
              <span className="block text-xs uppercase tracking-[0.13em] text-[#7b8781]">
                Analysis month
              </span>

              <input
                type="month"
                value={month}
                max={getCurrentMonth()}
                onChange={(event) =>
                  setMonth(event.target.value)
                }
                className="mt-2 rounded-full border border-[#14241e]/10 bg-[#f7f4ed] px-4 py-2 text-sm outline-none focus:border-[#167c5a]"
              />
            </label>
          </header>

          {error && (
            <div className="mt-7">
              <PageError
                message={error}
                onRetry={
                  userId
                    ? () => void loadInsights(userId, month)
                    : undefined
                }
              />
            </div>
          )}

          {loading ? (
            <>
              <section className="mt-8">
                <CardSkeleton count={4} />
              </section>

              <div className="mt-6 h-80 animate-pulse rounded-[30px] border border-[#14241e]/10 bg-white" />
            </>
          ) : insights ? (
            <>
              <section className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <MetricCard
                  label="Income"
                  value={formatCents(insights.income_cents)}
                  tone="green"
                  description={formatMonth(insights.month)}
                />

                <MetricCard
                  label="Spending"
                  value={formatCents(-insights.spending_cents)}
                  tone="coral"
                  description={formatMonth(insights.month)}
                />

                <MetricCard
                  label="Net cash flow"
                  value={formatCents(insights.net_cents)}
                  tone={insights.net_cents >= 0 ? "yellow" : "coral"}
                  description="Income minus spending"
                />

                <MetricCard
                  label="Savings rate"
                  value={`${insights.savings_rate_percent}%`}
                  tone={
                    insights.savings_rate_percent >= 20
                      ? "green"
                      : insights.savings_rate_percent >= 10
                      ? "yellow"
                      : "coral"
                  }
                  description="Share of income retained"
                />
              </section>

              <section className="mt-6 grid gap-5 xl:grid-cols-[0.8fr_1.2fr]">
                <div
                  className={`rounded-[30px] p-7 ${
                    insights.spending_change_cents > 0
                      ? "bg-[#f8ddd5]"
                      : "bg-[#dff6c7]"
                  }`}
                >
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#52635b]">
                    Spending change
                  </p>

                  <p className="mt-4 text-5xl font-semibold tracking-[-0.06em]">
                    {insights.spending_change_percent === null
                      ? "—"
                      : `${
                          insights.spending_change_percent > 0
                            ? "+"
                            : ""
                        }${insights.spending_change_percent}%`}
                  </p>

                  <p className="mt-3 text-sm leading-6 text-[#66746e]">
                    {insights.spending_change_percent === null
                      ? "There is not enough previous-month data to compare spending yet."
                      : insights.spending_change_cents > 0
                      ? "Spending increased compared with the previous month."
                      : "Spending decreased compared with the previous month."}
                  </p>
                </div>

                <div className="rounded-[30px] bg-[#14241e] p-7 text-white">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#76dfbd]">
                    FinSight summary
                  </p>

                  <h2 className="mt-4 text-3xl font-semibold tracking-[-0.04em]">
                    {formatMonth(insights.month)}
                  </h2>

                  <p className="mt-3 max-w-2xl text-sm leading-6 text-white/65">
                    FinSight generated {insights.insights.length} personalized
                    observation{insights.insights.length === 1 ? "" : "s"} from
                    your imported and synchronized transaction history.
                  </p>
                </div>
              </section>

              <section className="mt-8">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
                      Personalized observations
                    </p>
                    <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
                      What deserves your attention
                    </h2>
                  </div>

                  <p className="text-sm text-[#7b8781]">
                    {insights.insights.length} insight
                    {insights.insights.length === 1 ? "" : "s"}
                  </p>
                </div>

                <div className="mt-5 grid gap-5 md:grid-cols-2">
                  {insights.insights.map((insight, index) => (
                    <InsightCard
                      key={`${insight.kind}-${insight.category ?? index}`}
                      insight={insight}
                      index={index}
                    />
                  ))}
                </div>
              </section>

              <p className="mt-6 text-xs leading-5 text-[#7b8781]">
                Insights are generated from imported and synchronized
                transaction history. Results improve as more data is added.
              </p>
            </>
          ) : (
            <div className="mt-8">
              <EmptyState
                title="No insights available"
                description="Add or synchronize transactions for this month to generate spending trends and financial observations."
                actionLabel="View transactions"
                onAction={() => router.push("/transactions")}
              />
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

function InsightCard({
  insight,
  index,
}: {
  insight: FinancialInsight;
  index: number;
}) {
  const tones = {
    positive: {
      background: "bg-[#eef6e9]",
      badge: "bg-[#dff6c7] text-[#167c5a]",
      symbol: "↑",
    },
    warning: {
      background: "bg-[#fbf0d1]",
      badge: "bg-[#f7e8b5] text-[#8b6518]",
      symbol: "!",
    },
    info: {
      background: "bg-[#e8f1ef]",
      badge: "bg-[#dceeea] text-[#476457]",
      symbol: "i",
    },
  };

  const style = tones[insight.severity];
  const fallback = ["bg-white", "bg-[#f7f4ed]"];
  const background =
    insight.severity === "info"
      ? style.background
      : `${style.background} ${fallback[index % fallback.length]}`;

  return (
    <article
      className={`rounded-[28px] border border-[#14241e]/10 p-6 shadow-sm shadow-[#14241e]/5 ${background}`}
    >
      <div className="flex items-start gap-4">
        <span
          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-sm font-bold ${style.badge}`}
        >
          {style.symbol}
        </span>

        <div className="min-w-0">
          <h3 className="text-lg font-semibold tracking-[-0.02em]">
            {insight.title}
          </h3>

          <p className="mt-2 text-sm leading-6 text-[#66746e]">
            {insight.description}
          </p>

          <div className="mt-4 flex flex-wrap gap-2">
            {insight.category && (
              <span className="rounded-full bg-white/70 px-3 py-1.5 text-xs font-medium text-[#52635b]">
                {insight.category}
              </span>
            )}

            {insight.amount_cents !== null && (
              <span className="rounded-full bg-white/70 px-3 py-1.5 text-xs font-medium text-[#52635b]">
                {formatCents(insight.amount_cents)}
              </span>
            )}

            {insight.percentage !== null && (
              <span className="rounded-full bg-white/70 px-3 py-1.5 text-xs font-medium text-[#52635b]">
                {insight.percentage > 0 ? "+" : ""}
                {insight.percentage}%
              </span>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}

function MetricCard({
  label,
  value,
  tone,
  description,
}: {
  label: string;
  value: string;
  tone: "green" | "coral" | "yellow";
  description: string;
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
      <p className="mt-2 text-xs text-[#66746e]">{description}</p>
    </article>
  );
}
