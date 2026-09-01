"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useReducedMotion } from "framer-motion";
import { useRouter } from "next/navigation";
import { ArrowRight, Upload } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import AppSidebar from "../components/AppSidebar";
import { PageError } from "../components/PageFeedback";
import { PageReveal } from "../components/PremiumMotion";
import SafeToSpendCard from "../components/SafeToSpendCard";
import {
  api,
  CalibrationLabel,
  CashFlowForecast,
  DashboardDecisionIntelligence,
  FinancialResilience,
  formatCents,
  Overview,
  Recommendation,
  RecommendationSeverity,
  SavingsGoal,
  session,
} from "../lib/api";

function getCurrentMonth(): string {
  const today = new Date();
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
}

function formatMonth(month: string): string {
  const [year, monthNumber] = month.split("-").map(Number);
  return new Date(year, monthNumber - 1, 1).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });
}

export default function Dashboard() {
  const router = useRouter();
  const reduceMotion = useReducedMotion();
  const budgetMonth = getCurrentMonth();
  const [userId, setUserId] = useState<number | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [goals, setGoals] = useState<SavingsGoal[]>([]);
  const [cashFlow, setCashFlow] = useState<CashFlowForecast | null>(null);
  const [resilience, setResilience] = useState<FinancialResilience | null>(null);
  const [decisionIntelligence, setDecisionIntelligence] =
    useState<DashboardDecisionIntelligence | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [recommendationsLoading, setRecommendationsLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const loadDashboard = useCallback(async (id: number) => {
    setLoading(true);
    setError("");

    try {
      const [
        overviewData,
        goalData,
        cashFlowData,
        resilienceResult,
        decisionIntelligenceResult,
      ] = await Promise.all([
        api.overview(id),
        api.getSavingsGoals(id),
        api.getCashFlowForecast(id),
        api.getFinancialResilience(id).catch(() => null),
        api.getDashboardDecisionIntelligence(id).catch(() => null),
      ]);
      setOverview(overviewData);
      setGoals(goalData);
      setCashFlow(cashFlowData);
      setResilience(resilienceResult);
      setDecisionIntelligence(decisionIntelligenceResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRecommendations = useCallback(async (id: number) => {
    setRecommendationsLoading(true);
    try {
      const result = await api.getRecommendations(id);
      setRecommendations(result.recommendations);
    } catch {
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
  }, [loadDashboard, loadRecommendations, router]);

  const goalSummary = useMemo(
    () =>
      goals.reduce(
        (summary, goal) => ({
          target: summary.target + goal.target_cents,
          saved: summary.saved + goal.saved_cents,
          completed: summary.completed + (goal.status === "completed" ? 1 : 0),
        }),
        { target: 0, saved: 0, completed: 0 }
      ),
    [goals]
  );

  const goalProgress =
    goalSummary.target > 0
      ? Math.min(Math.round((goalSummary.saved / goalSummary.target) * 100), 100)
      : 0;

  const chartData = useMemo(() => {
    if (!cashFlow) return [];
    const points = [
      { label: "Current", balance: cashFlow.liquid_balance_cents / 100 },
      ...cashFlow.horizon_outlook.map((point) => ({
        label: `${point.horizon_days} days`,
        balance: point.projected_balance_cents / 100,
      })),
    ];

    if (points.length === 1) {
      points.push({
        label: "Month end",
        balance: cashFlow.projected_end_balance_cents / 100,
      });
    }
    return points;
  }, [cashFlow]);

  async function handleUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || userId === null) return;

    setUploading(true);
    setMessage("");
    setError("");
    try {
      const result = await api.uploadTransactions(userId, file);
      const parts = [`${result.imported} imported`];
      if (result.duplicates > 0) parts.push(`${result.duplicates} duplicates skipped`);
      if (result.rejected > 0) parts.push(`${result.rejected} rejected`);
      setMessage(`${parts.join(", ")}.`);
      await loadDashboard(userId);
      void loadRecommendations(userId);
      setRefreshKey((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "CSV upload failed");
    } finally {
      setUploading(false);
      event.target.value = "";
    }
  }

  const showSkeleton = loading || (Boolean(error) && !overview);
  const attentionCount = recommendations.filter((item) =>
    ["critical", "warning", "opportunity"].includes(item.severity)
  ).length;

  return (
    <main className="min-h-screen bg-[#F5F1EA] text-[#181713]">
      <AppSidebar />
      <div className="px-5 pb-16 pt-20 sm:px-8 lg:ml-60 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto w-full max-w-[1500px]">
          <header className="flex items-end justify-between gap-5 border-b border-[#181713]/10 pb-5">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">Financial position</p>
              <h1 className="mt-1 text-[32px] font-semibold tracking-[-0.03em] text-[#181713]">Overview</h1>
              <p className="mt-1 text-sm text-[#706961]">Your money, distilled into what matters now.</p>
              <p className="mt-1 text-xs text-[#8A8178]">{formatMonth(budgetMonth)}</p>
            </div>
            <label className="focus-ring inline-flex cursor-pointer items-center gap-2 rounded-full px-3 py-2 text-sm font-medium text-[#706961] transition hover:bg-white hover:text-[#6E4B63]">
              <Upload className="h-4 w-4" />
              {uploading ? "Uploading…" : "Upload CSV"}
              <input type="file" accept=".csv" className="hidden" disabled={uploading} onChange={handleUpload} />
            </label>
          </header>

          {message && !error && (
            <div role="status" aria-live="polite" className="mt-5 rounded-xl bg-[#E8EEE7] px-4 py-3 text-sm text-[#58715A]">{message}</div>
          )}
          {error && (
            <div className="mt-5"><PageError message={error} onRetry={!overview && userId !== null ? () => loadDashboard(userId) : undefined} /></div>
          )}

          <SafeToSpendCard userId={userId} refreshKey={refreshKey} />

          <ExecutiveStrip
            cashFlow={cashFlow}
            resilience={resilience}
            attentionCount={attentionCount}
            loading={showSkeleton || recommendationsLoading}
          />

          <section className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(280px,0.65fr)]">
            <article className="rounded-[24px] bg-white p-6 shadow-[0_14px_40px_rgba(24,35,55,0.055)] ring-1 ring-[#181713]/[0.06] sm:p-8">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#6E4B63]">Cash trajectory</p>
                  <h2 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">Balance outlook</h2>
                </div>
                {!showSkeleton && cashFlow && (
                  <div className="sm:text-right">
                    <p className="text-xs text-[#8A8178]">Projected balance</p>
                    <p className={`mt-1 text-xl font-semibold ${cashFlow.low_balance_risk ? "text-[#b95547]" : "text-[#181713]"}`}>
                      {formatCents(cashFlow.projected_end_balance_cents)}
                    </p>
                  </div>
                )}
              </div>

              <div className="mt-7 h-[300px]">
                {showSkeleton ? (
                  <div className="h-full animate-pulse rounded-2xl bg-[#181713]/[0.035]" />
                ) : chartData.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -12, bottom: 0 }}>
                      <defs>
                        <linearGradient id="cashFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#6E4B63" stopOpacity={0.18} />
                          <stop offset="100%" stopColor="#6E4B63" stopOpacity={0.01} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid vertical={false} stroke="rgba(23,35,63,0.07)" />
                      <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fill: "#8A8178", fontSize: 11 }} dy={10} />
                      <YAxis axisLine={false} tickLine={false} tick={{ fill: "#8A8178", fontSize: 11 }} tickFormatter={(value) => `$${Number(value).toLocaleString("en-US", { notation: "compact" })}`} />
                      <Tooltip content={<TrajectoryTooltip />} />
                      <Area type="monotone" dataKey="balance" stroke="#6E4B63" strokeWidth={3} fill="url(#cashFill)" dot={{ r: 4, fill: "#fff", stroke: "#6E4B63", strokeWidth: 2 }} activeDot={{ r: 5 }} isAnimationActive={!reduceMotion} animationDuration={700} />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-full items-center justify-center text-sm text-[#8A8178]">Forecast data is not available yet.</div>
                )}
              </div>

              {!showSkeleton && cashFlow && (
                <div className="mt-5 flex flex-wrap gap-x-8 gap-y-3 border-t border-[#181713]/[0.07] pt-5 text-sm">
                  <span className="text-[#706961]">Current <strong className="ml-1 font-semibold text-[#181713]">{formatCents(cashFlow.liquid_balance_cents)}</strong></span>
                  <span className="text-[#706961]">Expected income <strong className="ml-1 font-semibold text-[#58715A]">{formatCents(cashFlow.expected_income_cents)}</strong></span>
                  <span className="text-[#706961]">Upcoming bills <strong className="ml-1 font-semibold text-[#b95547]">{formatCents(-cashFlow.upcoming_bills_cents)}</strong></span>
                </div>
              )}
            </article>

            <NeedsAttention recommendations={recommendations} loading={recommendationsLoading} onSelect={(path) => router.push(path ?? "/recommendations")} />
          </section>

          <GoalsSummary goals={goals} summary={goalSummary} progress={goalProgress} loading={showSkeleton} onOpen={() => router.push("/goals")} />

          <DecisionIntelligenceSummary
            data={decisionIntelligence}
            loading={loading}
            onReview={() => router.push("/decisions/history")}
          />

          <section className="mt-6 flex flex-col gap-5 border-y border-[#181713]/10 bg-[#EDE5DE]/45 px-6 py-6 sm:flex-row sm:items-center sm:justify-between sm:px-8">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">Thinking about a purchase?</p>
              <p className="mt-2 max-w-xl text-sm leading-6 text-[#706961]">See how it affects your cash, goals, and runway before committing.</p>
            </div>
            <button type="button" onClick={() => router.push("/decisions")} className="discero-button-primary inline-flex w-fit items-center gap-2 rounded-full px-5 py-3 text-sm font-semibold transition">
              Analyze a decision <ArrowRight className="h-4 w-4" />
            </button>
          </section>

          <footer className="mt-8 flex flex-col gap-3 border-t border-[#181713]/[0.07] py-6 text-sm text-[#8A8178] sm:flex-row sm:items-center sm:justify-between">
            <span>Need newer transaction data?</span>
            <label className="focus-ring inline-flex w-fit cursor-pointer items-center gap-2 font-semibold text-[#6E4B63] transition hover:text-[#6E4B63]">
              <Upload className="h-4 w-4" />
              {uploading ? "Uploading…" : "Upload a CSV"}
              <input type="file" accept=".csv" className="hidden" disabled={uploading} onChange={handleUpload} />
            </label>
          </footer>
        </PageReveal>
      </div>
    </main>
  );
}

function ExecutiveStrip({
  cashFlow,
  resilience,
  attentionCount,
  loading,
}: {
  cashFlow: CashFlowForecast | null;
  resilience: FinancialResilience | null;
  attentionCount: number;
  loading: boolean;
}) {
  const indicators = [
    { label: "Liquid cash", value: cashFlow ? formatCents(cashFlow.liquid_balance_cents) : "—", detail: "Available balance", tone: "text-[#181713]" },
    { label: "Cash outlook", value: cashFlow ? formatCents(cashFlow.projected_end_balance_cents) : "—", detail: cashFlow?.low_balance_risk ? "Below safe level" : "Projected month end", tone: cashFlow?.low_balance_risk ? "text-[#b95547]" : "text-[#181713]" },
    { label: "Runway", value: resilience?.runway_months != null ? `${resilience.runway_months} months` : "—", detail: resilience?.headline ?? "Limited data", tone: resilience?.resilience_status === "critical" || resilience?.resilience_status === "weak" ? "text-[#b95547]" : "text-[#181713]" },
    { label: "Needs attention", value: String(attentionCount), detail: attentionCount === 1 ? "Actionable item" : "Actionable items", tone: attentionCount > 0 ? "text-[#a66b10]" : "text-[#58715A]" },
  ];

  return (
    <section aria-label="Executive financial summary" className="mt-6 grid overflow-hidden rounded-[20px] bg-white shadow-[0_10px_32px_rgba(24,35,55,0.045)] ring-1 ring-[#181713]/[0.06] sm:grid-cols-2 lg:grid-cols-4">
      {indicators.map((indicator, index) => (
        <div key={indicator.label} className={`px-5 py-5 sm:px-6 ${index > 0 ? "border-t border-[#181713]/[0.07] sm:border-l" : ""} ${index === 2 ? "sm:border-l-0 lg:border-l" : ""} ${index > 1 ? "lg:border-t-0" : ""}`}>
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#8A8178]">{indicator.label}</p>
          {loading ? <div className="mt-3 h-7 w-24 animate-pulse rounded bg-[#181713]/[0.05]" /> : <p className={`mt-2 text-xl font-semibold tracking-[-0.03em] ${indicator.tone}`}>{indicator.value}</p>}
          <p className="mt-1 text-xs text-[#8A8178]">{indicator.detail}</p>
        </div>
      ))}
    </section>
  );
}

const ATTENTION_STYLES: Record<RecommendationSeverity, string> = {
  critical: "bg-[#B75C50]",
  warning: "bg-[#C59A52]",
  opportunity: "bg-[#6E4B63]",
  positive: "bg-[#58715A]",
  informational: "bg-[#8A8178]",
};

function NeedsAttention({ recommendations, loading, onSelect }: { recommendations: Recommendation[]; loading: boolean; onSelect: (path: string | null) => void }) {
  const items = recommendations.filter((item) => ["critical", "warning", "opportunity"].includes(item.severity)).slice(0, 3);

  return (
    <aside className="rounded-[24px] bg-[#FFFCF7] p-6 ring-1 ring-[#181713]/[0.06] sm:p-7">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-lg font-semibold tracking-[-0.025em]">Needs attention</h2>
        <button type="button" onClick={() => onSelect("/recommendations")} className="text-xs font-semibold text-[#6E4B63]">View all</button>
      </div>
      <div className="mt-5 divide-y divide-[#181713]/[0.07]">
        {loading ? (
          <div className="space-y-3"><div className="h-16 animate-pulse rounded-xl bg-[#181713]/[0.04]" /><div className="h-16 animate-pulse rounded-xl bg-[#181713]/[0.04]" /></div>
        ) : items.length ? (
          items.map((item) => (
            <button key={item.id} type="button" onClick={() => onSelect(item.deep_link)} className="group flex w-full items-start gap-3 py-4 text-left first:pt-0 last:pb-0">
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${ATTENTION_STYLES[item.severity]}`} />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold leading-5 text-[#2F2930]">{item.title}</span>
                <span className="mt-1 block text-xs leading-5 text-[#8A8178]">{item.impact ?? item.recommended_action}</span>
              </span>
              <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-[#AAA198] transition group-hover:translate-x-0.5 group-hover:text-[#6E4B63]" />
            </button>
          ))
        ) : (
          <p className="py-8 text-sm text-[#8A8178]">No actionable items right now.</p>
        )}
      </div>
    </aside>
  );
}

function GoalsSummary({ goals, summary, progress, loading, onOpen }: { goals: SavingsGoal[]; summary: { target: number; saved: number; completed: number }; progress: number; loading: boolean; onOpen: () => void }) {
  return (
    <section className="mt-6 rounded-[24px] bg-white px-6 py-6 shadow-[0_10px_32px_rgba(24,35,55,0.045)] ring-1 ring-[#181713]/[0.06] sm:px-8">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-center">
        <div className="lg:w-48">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">Goals</p>
          <h2 className="mt-2 text-xl font-semibold tracking-[-0.03em]">Savings progress</h2>
        </div>
        {loading ? (
          <div className="h-14 flex-1 animate-pulse rounded-xl bg-[#181713]/[0.04]" />
        ) : goals.length ? (
          <>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between text-sm">
                <span className="font-semibold text-[#2F2930]">{formatCents(summary.saved)} <span className="font-normal text-[#8A8178]">of {formatCents(summary.target)}</span></span>
                <span className="font-semibold text-[#6E4B63]">{progress}%</span>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#EDE7E1]"><div className="h-full rounded-full bg-[#6E4B63] transition-[width] duration-700 motion-reduce:transition-none" style={{ width: `${progress}%` }} /></div>
              <p className="mt-2 text-xs text-[#8A8178]">{summary.completed} of {goals.length} complete · {formatCents(Math.max(summary.target - summary.saved, 0))} remaining</p>
            </div>
            <span className={`w-fit rounded-full px-3 py-1.5 text-xs font-semibold ${goals.some((goal) => goal.status === "overdue") ? "bg-[#fbe9e5] text-[#ad4b3d]" : "bg-[#E8EEE7] text-[#58715A]"}`}>
              {goals.some((goal) => goal.status === "overdue") ? "Review timing" : "On track"}
            </span>
          </>
        ) : (
          <p className="flex-1 text-sm text-[#8A8178]">No savings goals yet.</p>
        )}
        <button type="button" onClick={onOpen} className="w-fit text-sm font-semibold text-[#6E4B63]">Manage goals →</button>
      </div>
    </section>
  );
}

const DASHBOARD_CALIBRATION_LABEL: Record<CalibrationLabel, string> = {
  mostly_conservative: "Mostly conservative",
  mostly_optimistic: "Mostly optimistic",
  balanced: "Balanced",
  insufficient_data: "Insufficient data",
};

function DecisionIntelligenceSummary({
  data,
  loading,
  onReview,
}: {
  data: DashboardDecisionIntelligence | null;
  loading: boolean;
  onReview: () => void;
}) {
  if (loading) {
    return (
      <section className="mt-6 rounded-[24px] bg-white px-6 py-6 shadow-[0_10px_32px_rgba(24,35,55,0.045)] ring-1 ring-[#181713]/[0.06] sm:px-8">
        <div className="h-20 animate-pulse rounded-xl bg-[#181713]/[0.04]" />
      </section>
    );
  }

  // Failure-isolated: a null result (fetch failure or still loading)
  // simply omits the section -- the rest of the dashboard is
  // unaffected either way.
  if (data === null) return null;

  const reviewCount = data.review_queue.count;

  return (
    <section
      data-testid="dashboard-decision-intelligence"
      className="mt-6 rounded-[24px] bg-white px-6 py-6 shadow-[0_10px_32px_rgba(24,35,55,0.045)] ring-1 ring-[#181713]/[0.06] sm:px-8"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
            Decision intelligence
          </p>
          <h2 className="mt-2 text-xl font-semibold tracking-[-0.03em]">
            {reviewCount > 0
              ? `${reviewCount} decision${reviewCount === 1 ? "" : "s"} need review`
              : "You're all caught up"}
          </h2>
          <p className="mt-1 text-xs text-[#8A8178]">
            Calibration: {DASHBOARD_CALIBRATION_LABEL[data.calibration.label]}
          </p>
        </div>
        <button
          type="button"
          onClick={onReview}
          className="discero-button-secondary w-fit shrink-0 rounded-full border px-4 py-2 text-sm font-semibold transition"
        >
          Review decisions
        </button>
      </div>

      {data.review_queue.highest_priority && (
        <div className="mt-4 border-t border-[#181713]/[0.07] pt-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[#8A8178]">
            Highest priority
          </p>
          <p className="mt-1 text-sm font-semibold text-[#2F2930]">
            {data.review_queue.highest_priority.title}
          </p>
          <p className="mt-0.5 text-xs text-[#8A8178]">
            {data.review_queue.highest_priority.review_reason_text}
          </p>
        </div>
      )}
    </section>
  );
}

function TrajectoryTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ value?: number }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl bg-[#181713] px-3 py-2 text-white shadow-xl">
      <p className="text-[11px] text-white/60">{label}</p>
      <p className="mt-1 text-sm font-semibold">{Number(payload[0].value ?? 0).toLocaleString("en-US", { style: "currency", currency: "USD" })}</p>
    </div>
  );
}
