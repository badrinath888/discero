"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  ArrowUpRight,
  CalendarDays,
  ChevronRight,
  CircleAlert,
  Lightbulb,
  Search,
  Sparkles,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import {
  CardSkeleton,
  EmptyState,
  PageError,
} from "../components/PageFeedback";
import {
  AnimatedNumber,
  PageReveal,
  Reveal,
} from "../components/PremiumMotion";
import {
  api,
  FinancialInsight,
  formatCents,
  MonthlyInsights,
  session,
} from "../lib/api";

type InsightFilter = "all" | "warning" | "positive" | "info";

function getCurrentMonth(): string {
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

function actionForInsight(insight: FinancialInsight): string {
  if (insight.severity === "warning") {
    return insight.category
      ? `Review recent ${insight.category.toLowerCase()} transactions and decide whether the pattern should continue.`
      : "Review the related transactions and identify one immediate adjustment.";
  }

  if (insight.severity === "positive") {
    return "Keep the behavior consistent and consider directing the improvement toward a savings goal.";
  }

  return insight.category
    ? `Open ${insight.category.toLowerCase()} activity to understand the underlying pattern.`
    : "Review the supporting activity before making a financial decision.";
}

export default function InsightsPage() {
  const router = useRouter();

  const [userId, setUserId] = useState<number | null>(null);
  const [month, setMonth] = useState(getCurrentMonth());
  const [insights, setInsights] =
    useState<MonthlyInsights | null>(null);
  const [activeInsight, setActiveInsight] =
    useState<FinancialInsight | null>(null);
  const [filter, setFilter] = useState<InsightFilter>("all");
  const [search, setSearch] = useState("");
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

  const filteredInsights = useMemo(() => {
    const query = search.trim().toLowerCase();

    return (insights?.insights ?? []).filter((insight) => {
      const matchesFilter =
        filter === "all" || insight.severity === filter;

      const matchesSearch =
        insight.title.toLowerCase().includes(query) ||
        insight.description.toLowerCase().includes(query) ||
        insight.category?.toLowerCase().includes(query);

      return matchesFilter && matchesSearch;
    });
  }, [insights, filter, search]);

  const severityCounts = useMemo(
    () =>
      (insights?.insights ?? []).reduce(
        (counts, insight) => ({
          ...counts,
          [insight.severity]: counts[insight.severity] + 1,
        }),
        { positive: 0, warning: 0, info: 0 }
      ),
    [insights]
  );

  const hasCurrentMonthActivity = Boolean(
    insights &&
      (insights.income_cents !== 0 || insights.spending_cents !== 0)
  );

  return (
    <main className="min-h-screen bg-[#f5f1e8] text-[#14241e]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[1500px]">
          <Reveal>
            <header className="flex flex-col gap-6 border-b border-[#14241e]/10 pb-7 xl:flex-row xl:items-end xl:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
                  Financial intelligence
                </p>

                <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
                  Insights
                </h1>

                <p className="mt-3 max-w-2xl text-sm leading-6 text-[#66746e]">
                  Understand what changed, what deserves attention, and
                  which financial patterns are moving in the right direction.
                </p>
              </div>

              <label className="relative w-full max-w-xs">
                <CalendarDays className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[#728078]" />
                <input
                  type="month"
                  value={month}
                  max={getCurrentMonth()}
                  onChange={(event) => setMonth(event.target.value)}
                  className="h-11 w-full rounded-xl border border-[#14241e]/10 bg-white pl-11 pr-4 text-sm outline-none focus:border-[#167c5a]"
                />
              </label>
            </header>
          </Reveal>

          {error && (
            <div className="mt-5">
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
              <Reveal delay={0.06}>
                <section className="mt-6 grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
                  <article className="premium-hover relative overflow-hidden rounded-[30px] bg-[#14241e] p-7 text-white shadow-[0_24px_70px_rgba(20,36,30,0.18)] sm:p-9">
                    <div className="pointer-events-none absolute -right-16 -top-16 h-52 w-52 rounded-full bg-[#76dfbd]/15 blur-3xl" />

                    <div className="relative">
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#83dcb9]">
                        Net cash flow · {formatMonth(insights.month)}
                      </p>

                      <AnimatedNumber
                        value={insights.net_cents}
                        format={formatCents}
                        className="mt-4 block text-5xl font-semibold tracking-[-0.06em] sm:text-6xl"
                      />

                      <p className="mt-3 text-sm text-white/55">
                        Income after spending for the selected month.
                      </p>

                      <div className="mt-10 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-3">
                        <InsightMetric
                          label="Income"
                          value={formatCents(insights.income_cents)}
                          tone="positive"
                        />
                        <InsightMetric
                          label="Spending"
                          value={formatCents(-insights.spending_cents)}
                          tone="negative"
                        />
                        <InsightMetric
                          label="Savings rate"
                          value={`${insights.savings_rate_percent}%`}
                          tone="neutral"
                        />
                      </div>
                    </div>
                  </article>

                  <article
                    className={`premium-hover rounded-[30px] p-7 sm:p-8 ${
                      insights.spending_change_cents > 0
                        ? "bg-[#f8ddd5]"
                        : "bg-[#dff6c7]"
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#52635b]">
                          Month-over-month
                        </p>
                        <p className="mt-4 text-5xl font-semibold tracking-[-0.05em]">
                          {!hasCurrentMonthActivity
                            ? "No activity"
                            : insights.spending_change_percent === null
                              ? "—"
                              : `${
                                  insights.spending_change_percent > 0
                                    ? "+"
                                    : ""
                                }${insights.spending_change_percent}%`}
                        </p>
                      </div>

                      <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#14241e] text-white">
                        {insights.spending_change_cents > 0 ? (
                          <TrendingUp className="h-5 w-5" />
                        ) : (
                          <TrendingDown className="h-5 w-5" />
                        )}
                      </span>
                    </div>

                    <p className="mt-4 text-sm leading-6 text-[#66746e]">
                      {!hasCurrentMonthActivity
                        ? `Add or synchronize ${formatMonth(
                            insights.month
                          )} transactions to compare spending.`
                        : insights.spending_change_percent === null
                          ? "There is not enough previous-month data for a reliable comparison."
                          : insights.spending_change_cents > 0
                            ? "Spending increased compared with the previous month."
                            : "Spending decreased compared with the previous month."}
                    </p>

                    <div className="mt-8 grid grid-cols-3 gap-2">
                      <SeverityCount
                        label="Positive"
                        value={severityCounts.positive}
                      />
                      <SeverityCount
                        label="Warnings"
                        value={severityCounts.warning}
                      />
                      <SeverityCount
                        label="Informational"
                        value={severityCounts.info}
                      />
                    </div>
                  </article>
                </section>
              </Reveal>

              <Reveal>
                <section className="mt-8">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
                        Ranked observations
                      </p>
                      <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
                        What deserves your attention
                      </h2>
                    </div>

                    <div className="flex flex-col gap-2 sm:flex-row">
                      <label className="relative min-w-0 sm:w-72">
                        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#87928d]" />
                        <input
                          value={search}
                          onChange={(event) =>
                            setSearch(event.target.value)
                          }
                          placeholder="Search insights"
                          className="h-11 w-full rounded-xl border border-[#14241e]/10 bg-white pl-10 pr-4 text-sm outline-none focus:border-[#167c5a]"
                        />
                      </label>

                      <div className="flex h-11 items-center rounded-xl border border-[#14241e]/10 bg-white p-1">
                        {(
                          [
                            ["all", "All"],
                            ["warning", "Warnings"],
                            ["positive", "Positive"],
                            ["info", "Info"],
                          ] as const
                        ).map(([value, label]) => (
                          <button
                            key={value}
                            type="button"
                            onClick={() => setFilter(value)}
                            className={`h-full rounded-lg px-3 text-xs font-semibold transition ${
                              filter === value
                                ? "bg-[#14241e] text-white"
                                : "text-[#66746e]"
                            }`}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="mt-5 overflow-hidden rounded-[24px] border border-[#14241e]/10 bg-white">
                    <header className="hidden border-b border-[#14241e]/10 bg-[#faf8f3] px-5 py-4 text-xs font-semibold uppercase tracking-[0.12em] text-[#7a8780] md:grid md:grid-cols-[54px_minmax(260px,1.5fr)_150px_150px_40px] md:items-center">
                      <span>Rank</span>
                      <span>Observation</span>
                      <span>Category</span>
                      <span>Signal</span>
                      <span />
                    </header>

                    <div className="divide-y divide-[#14241e]/8">
                      {filteredInsights.map((insight, index) => (
                        <InsightRow
                          key={`${insight.kind}-${insight.category ?? index}`}
                          insight={insight}
                          rank={index + 1}
                          onOpen={() => setActiveInsight(insight)}
                        />
                      ))}
                    </div>

                    {filteredInsights.length === 0 && (
                      <div className="px-6 py-12 text-center">
                        <p className="text-sm font-semibold">
                          No insights match
                        </p>
                        <p className="mt-2 text-sm text-[#7b8781]">
                          Adjust the search or severity filter.
                        </p>
                      </div>
                    )}
                  </div>
                </section>
              </Reveal>

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
        </PageReveal>
      </div>

      <AnimatePresence>
        {activeInsight && (
          <InsightDrawer
            insight={activeInsight}
            month={month}
            onClose={() => setActiveInsight(null)}
          />
        )}
      </AnimatePresence>
    </main>
  );
}

function InsightMetric({
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

function SeverityCount({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  return (
    <div className="rounded-2xl bg-white/45 p-3">
      <p className="text-[10px] uppercase tracking-[0.1em] text-[#66746e]">
        {label}
      </p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}

function InsightRow({
  insight,
  rank,
  onOpen,
}: {
  insight: FinancialInsight;
  rank: number;
  onOpen: () => void;
}) {
  const reduceMotion = useReducedMotion();

  const severity = {
    positive: {
      badge: "bg-[#edf5ee] text-[#167c5a]",
      label: "Positive",
      icon: ArrowUpRight,
    },
    warning: {
      badge: "bg-[#f8ddd5] text-[#923f32]",
      label: "Warning",
      icon: CircleAlert,
    },
    info: {
      badge: "bg-[#dceeea] text-[#476457]",
      label: "Information",
      icon: Lightbulb,
    },
  }[insight.severity];

  const SeverityIcon = severity.icon;

  return (
    <motion.button
      type="button"
      onClick={onOpen}
      whileHover={
        reduceMotion
          ? undefined
          : { x: 3, backgroundColor: "#fbfaf6" }
      }
      transition={{ duration: reduceMotion ? 0 : 0.2 }}
      className="grid w-full gap-4 px-5 py-4 text-left md:grid-cols-[54px_minmax(260px,1.5fr)_150px_150px_40px] md:items-center"
    >
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#f1eee7] text-xs font-bold text-[#66746e]">
        {String(rank).padStart(2, "0")}
      </span>

      <div className="min-w-0">
        <p className="truncate text-sm font-semibold">{insight.title}</p>
        <p className="mt-1 line-clamp-2 text-xs leading-5 text-[#87928d]">
          {insight.description}
        </p>
      </div>

      <p className="text-sm font-medium text-[#52635b]">
        {insight.category || "General"}
      </p>

      <span
        className={`inline-flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${severity.badge}`}
      >
        <SeverityIcon className="h-3.5 w-3.5" />
        {severity.label}
      </span>

      <ChevronRight className="h-4 w-4 text-[#87928d]" />
    </motion.button>
  );
}

function InsightDrawer({
  insight,
  month,
  onClose,
}: {
  insight: FinancialInsight;
  month: string;
  onClose: () => void;
}) {
  const reduceMotion = useReducedMotion();

  const severityLabel = {
    positive: "Positive signal",
    warning: "Needs attention",
    info: "Informational",
  }[insight.severity];

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
        aria-label="Close insight details"
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
        className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col bg-[#fdfcf8] shadow-2xl"
      >
        <header className="flex items-start justify-between border-b border-[#14241e]/10 px-6 py-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#167c5a]">
              Insight details
            </p>
            <h2 className="mt-2 text-xl font-semibold">
              {insight.title}
            </h2>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[#14241e]/10 bg-white"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          <span
            className={`inline-flex rounded-full px-3 py-1.5 text-xs font-semibold ${
              insight.severity === "warning"
                ? "bg-[#f8ddd5] text-[#923f32]"
                : insight.severity === "positive"
                  ? "bg-[#edf5ee] text-[#167c5a]"
                  : "bg-[#dceeea] text-[#476457]"
            }`}
          >
            {severityLabel}
          </span>

          <p className="mt-5 text-sm leading-7 text-[#52635b]">
            {insight.description}
          </p>

          <dl className="mt-7 divide-y divide-[#14241e]/10 border-y border-[#14241e]/10">
            <DrawerDetail
              label="Period"
              value={formatMonth(month)}
            />
            <DrawerDetail
              label="Category"
              value={insight.category || "General"}
            />
            {insight.amount_cents !== null && (
              <DrawerDetail
                label="Amount"
                value={formatCents(insight.amount_cents)}
              />
            )}
            {insight.percentage !== null && (
              <DrawerDetail
                label="Change"
                value={`${insight.percentage > 0 ? "+" : ""}${insight.percentage}%`}
              />
            )}
          </dl>

          <div className="mt-7 rounded-2xl bg-[#edf5ee] p-5">
            <div className="flex gap-3">
              <Sparkles className="mt-0.5 h-5 w-5 shrink-0 text-[#167c5a]" />
              <div>
                <p className="text-sm font-semibold">
                  Recommended next action
                </p>
                <p className="mt-1 text-sm leading-6 text-[#66746e]">
                  {actionForInsight(insight)}
                </p>
              </div>
            </div>
          </div>
        </div>
      </motion.aside>
    </motion.div>
  );
}

function DrawerDetail({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="grid gap-1 py-4 sm:grid-cols-[120px_1fr]">
      <dt className="text-xs font-semibold uppercase tracking-[0.1em] text-[#87928d]">
        {label}
      </dt>
      <dd className="text-sm font-medium sm:text-right">{value}</dd>
    </div>
  );
}
