"use client";

import {
  useCallback,
  useEffect,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
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

  const [month, setMonth] = useState(getCurrentMonth());
  const [insights, setInsights] =
    useState<MonthlyInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadInsights = useCallback(
    async (userId: number, selectedMonth: string) => {
      setLoading(true);
      setError("");

      try {
        setInsights(
          await api.getMonthlyInsights(
            userId,
            selectedMonth
          )
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
      const userId = session.getUserId();
      const token = session.getToken();

      if (!userId || !token) {
        session.clear();
        router.replace("/");
        return;
      }

      try {
        const user = await api.getMe();

        if (user.id !== userId) {
          session.clear();
          router.replace("/");
          return;
        }

        await loadInsights(userId, month);
      } catch {
        session.clear();
        router.replace("/");
      }
    }

    void initialize();
  }, [router, loadInsights, month]);

  return (
    <main
      className="relative min-h-screen overflow-hidden bg-[#07111f] text-white"
      style={{
        backgroundImage: `
          radial-gradient(circle at 15% 10%, rgba(14,165,233,0.14), transparent 30%),
          radial-gradient(circle at 85% 20%, rgba(16,185,129,0.10), transparent 28%),
          linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)
        `,
        backgroundSize:
          "auto, auto, 42px 42px, 42px 42px",
      }}
    >
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent via-[#07111f]/40 to-[#07111f]" />

      <AppSidebar />

      <div className="relative px-5 pb-10 pt-20 sm:px-8 lg:ml-72 lg:px-10 lg:pt-8">
        <div className="mx-auto max-w-7xl">
          <header className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs font-medium text-cyan-300">
                <span className="h-2 w-2 rounded-full bg-cyan-400" />
                Smart analysis
              </div>

              <h1 className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">
                Financial insights
              </h1>

              <p className="mt-2 max-w-2xl text-sm text-slate-400 sm:text-base">
                Understand spending changes, savings performance,
                and important category trends.
              </p>
            </div>

            <label className="text-sm text-slate-400">
              Analysis month

              <input
                type="month"
                value={month}
                max={getCurrentMonth()}
                onChange={(event) =>
                  setMonth(event.target.value)
                }
                className="mt-2 block rounded-xl border border-white/10 bg-slate-950/60 px-4 py-2.5 text-sm text-white outline-none transition focus:border-cyan-400/40"
              />
            </label>
          </header>

          {error && (
            <div className="mt-7 rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-300">
              {error}
            </div>
          )}

          {loading ? (
            <>
              <section className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
                {Array.from({ length: 4 }).map((_, index) => (
                  <div
                    key={index}
                    className="h-28 animate-pulse rounded-3xl bg-white/[0.05]"
                  />
                ))}
              </section>

              <div className="mt-6 h-72 animate-pulse rounded-3xl bg-white/[0.05]" />
            </>
          ) : insights ? (
            <>
              <section className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
                <MetricCard
                  label="Income"
                  value={formatCents(
                    insights.income_cents
                  )}
                  description={formatMonth(insights.month)}
                  accent="emerald"
                />

                <MetricCard
                  label="Spending"
                  value={formatCents(
                    -insights.spending_cents
                  )}
                  description={formatMonth(insights.month)}
                  accent="rose"
                />

                <MetricCard
                  label="Net cash flow"
                  value={formatCents(
                    insights.net_cents
                  )}
                  description="Income minus spending"
                  accent={
                    insights.net_cents < 0
                      ? "rose"
                      : "cyan"
                  }
                />

                <MetricCard
                  label="Savings rate"
                  value={`${insights.savings_rate_percent}%`}
                  description="Share of income retained"
                  accent={
                    insights.savings_rate_percent >= 20
                      ? "emerald"
                      : insights.savings_rate_percent >= 10
                      ? "amber"
                      : "rose"
                  }
                />
              </section>

              <section className="mt-6 rounded-3xl border border-white/10 bg-white/[0.06] p-5 shadow-xl shadow-black/20 backdrop-blur-xl sm:p-7">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h2 className="text-lg font-semibold">
                      Monthly analysis
                    </h2>

                    <p className="mt-1 text-sm text-slate-400">
                      Personalized observations for{" "}
                      {formatMonth(insights.month)}
                    </p>
                  </div>

                  <div
                    className={`rounded-xl border px-4 py-3 ${
                      insights.spending_change_cents > 0
                        ? "border-rose-400/20 bg-rose-400/10"
                        : "border-emerald-400/20 bg-emerald-400/10"
                    }`}
                  >
                    <p className="text-xs text-slate-400">
                      Spending change
                    </p>

                    <p
                      className={`mt-1 font-semibold ${
                        insights.spending_change_cents > 0
                          ? "text-rose-300"
                          : "text-emerald-300"
                      }`}
                    >
                      {insights.spending_change_percent === null
                        ? "No previous data"
                        : `${
                            insights.spending_change_percent > 0
                              ? "+"
                              : ""
                          }${insights.spending_change_percent}%`}
                    </p>
                  </div>
                </div>

                <div className="mt-6 grid gap-4 md:grid-cols-2">
                  {insights.insights.map(
                    (insight, index) => (
                      <InsightCard
                        key={`${insight.kind}-${
                          insight.category ?? index
                        }`}
                        insight={insight}
                      />
                    )
                  )}
                </div>
              </section>

              <p className="mt-5 text-xs leading-5 text-slate-500">
                Insights are generated from imported and synchronized
                transaction history. Results improve as more data is
                added.
              </p>
            </>
          ) : (
            <div className="mt-8 rounded-3xl border border-dashed border-white/10 px-5 py-16 text-center text-sm text-slate-500">
              Financial insights are unavailable.
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

function InsightCard({
  insight,
}: {
  insight: FinancialInsight;
}) {
  const styles = {
    positive: {
      border: "border-emerald-400/20",
      background: "bg-emerald-400/[0.07]",
      icon: "bg-emerald-400/15 text-emerald-300",
      symbol: "↑",
    },
    warning: {
      border: "border-amber-400/20",
      background: "bg-amber-400/[0.07]",
      icon: "bg-amber-400/15 text-amber-300",
      symbol: "!",
    },
    info: {
      border: "border-cyan-400/20",
      background: "bg-cyan-400/[0.07]",
      icon: "bg-cyan-400/15 text-cyan-300",
      symbol: "i",
    },
  };

  const style = styles[insight.severity];

  return (
    <article
      className={`rounded-2xl border p-5 ${style.border} ${style.background}`}
    >
      <div className="flex items-start gap-4">
        <span
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl font-bold ${style.icon}`}
        >
          {style.symbol}
        </span>

        <div>
          <h3 className="font-semibold text-slate-100">
            {insight.title}
          </h3>

          <p className="mt-2 text-sm leading-6 text-slate-400">
            {insight.description}
          </p>

          <div className="mt-3 flex flex-wrap gap-2">
            {insight.category && (
              <span className="rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-slate-300">
                {insight.category}
              </span>
            )}

            {insight.amount_cents !== null && (
              <span className="rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-slate-300">
                {formatCents(insight.amount_cents)}
              </span>
            )}

            {insight.percentage !== null && (
              <span className="rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-slate-300">
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
  description,
  accent,
}: {
  label: string;
  value: string;
  description: string;
  accent:
    | "cyan"
    | "emerald"
    | "rose"
    | "amber";
}) {
  const styles = {
    cyan: "text-cyan-300",
    emerald: "text-emerald-300",
    rose: "text-rose-300",
    amber: "text-amber-300",
  };

  return (
    <article className="rounded-3xl border border-white/10 bg-white/[0.06] p-5 shadow-xl shadow-black/20 backdrop-blur-xl">
      <p className="text-sm text-slate-400">
        {label}
      </p>

      <p
        className={`mt-3 text-2xl font-bold ${styles[accent]}`}
      >
        {value}
      </p>

      <p className="mt-2 text-xs text-slate-500">
        {description}
      </p>
    </article>
  );
}
