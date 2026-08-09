"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  AlertTriangle,
  CalendarClock,
  ChevronRight,
  CircleDollarSign,
  Gauge,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import MerchantAvatar from "../components/MerchantAvatar";
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
import Toast from "../components/Toast";
import {
  api,
  CashFlowForecast,
  FinancialResilience,
  ForecastConfidence,
  ForecastConfidenceFactor,
  formatCents,
  session,
} from "../lib/api";

type ForecastItem = CashFlowForecast["upcoming_cash_flows"][number];

const RESILIENCE_STATUS_CONTENT: Record<
  FinancialResilience["resilience_status"],
  { label: string; className: string; barClassName: string }
> = {
  critical: {
    label: "Critical",
    className: "bg-[#f8ddd5] text-[#923f32]",
    barClassName: "bg-[#c0604c]",
  },
  weak: {
    label: "Weak",
    className: "bg-[#f5d66f] text-[#66500f]",
    barClassName: "bg-[#d9a53a]",
  },
  fair: {
    label: "Fair",
    className: "bg-[#f7e8b5] text-[#8b6518]",
    barClassName: "bg-[#c9a13f]",
  },
  strong: {
    label: "Strong",
    className: "bg-[#dff6c7] text-[#315d31]",
    barClassName: "bg-[#4d9a5a]",
  },
  very_strong: {
    label: "Very strong",
    className: "bg-[#dff6c7] text-[#315d31]",
    barClassName: "bg-[#167c5a]",
  },
};

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatMonth(value: string): string {
  return new Date(`${value}-01T00:00:00`).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });
}

function confidenceLabel(score: number): string {
  if (score >= 90) return "High confidence";
  if (score >= 75) return "Moderate confidence";
  return "Low confidence";
}

const CONFIDENCE_LEVEL_CONTENT: Record<
  ForecastConfidence["level"],
  { label: string; className: string }
> = {
  high: {
    label: "High confidence",
    className: "bg-[#dff6c7] text-[#315d31]",
  },
  medium: {
    label: "Medium confidence",
    className: "bg-[#f5d66f] text-[#66500f]",
  },
  low: {
    label: "Low confidence",
    className: "bg-[#f8ddd5] text-[#923f32]",
  },
};

const FACTOR_IMPACT_CONTENT: Record<
  ForecastConfidenceFactor["impact"],
  { label: string; className: string }
> = {
  positive: {
    label: "Strength",
    className: "bg-[#dff6c7] text-[#315d31]",
  },
  neutral: {
    label: "Neutral",
    className: "bg-[#f1eee7] text-[#66746e]",
  },
  negative: {
    label: "Weak spot",
    className: "bg-[#f8ddd5] text-[#923f32]",
  },
};

export default function ForecastPage() {
  const router = useRouter();
  const [userId, setUserId] = useState<number | null>(null);
  const [forecast, setForecast] = useState<CashFlowForecast | null>(null);
  const [activeItem, setActiveItem] = useState<ForecastItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [confidenceExpanded, setConfidenceExpanded] = useState(false);
  const [resilience, setResilience] = useState<FinancialResilience | null>(
    null
  );
  const [resilienceLoading, setResilienceLoading] = useState(true);
  const [resilienceError, setResilienceError] = useState("");
  const [essentialOverride, setEssentialOverride] = useState("");
  const [overrideActive, setOverrideActive] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [toast, setToast] = useState("");
  const [toastType, setToastType] = useState<"success" | "error">(
    "success"
  );

  const loadForecast = useCallback(async (id: number) => {
    setLoading(true);
    setError("");

    try {
      setForecast(await api.getCashFlowForecast(id));
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to load forecast"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const loadResilience = useCallback(
    async (id: number, essentialSpendingCents?: number) => {
      setResilienceLoading(true);
      setResilienceError("");

      try {
        setResilience(
          await api.getFinancialResilience(id, essentialSpendingCents)
        );
      } catch (err) {
        setResilienceError(
          err instanceof Error
            ? err.message
            : "Unable to load financial resilience"
        );
      } finally {
        setResilienceLoading(false);
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
        await Promise.all([loadForecast(id), loadResilience(id)]);
      } catch {
        session.clear();
        router.replace("/");
      }
    }

    void initialize();
  }, [router, loadForecast, loadResilience]);

  async function handleSimulateEssentialSpending() {
    if (!userId) return;

    const amount = Number(essentialOverride);

    if (!essentialOverride.trim() || !Number.isFinite(amount) || amount < 0) {
      setToastType("error");
      setToast("Enter a valid monthly essential-spending amount.");
      return;
    }

    setSimulating(true);

    try {
      await loadResilience(userId, Math.round(amount * 100));
      setOverrideActive(true);
      setToastType("success");
      setToast("Resilience recalculated with your scenario.");
    } finally {
      setSimulating(false);
    }
  }

  async function handleResetToEstimated() {
    if (!userId) return;

    setEssentialOverride("");
    setOverrideActive(false);
    setSimulating(true);

    try {
      await loadResilience(userId);
    } finally {
      setSimulating(false);
    }
  }

  const bestCaseBalance = useMemo(() => {
    if (!forecast) return 0;
    return (
      forecast.liquid_balance_cents +
      forecast.expected_income_cents
    );
  }, [forecast]);

  const riskMargin = useMemo(() => {
    if (!forecast) return 0;
    return forecast.projected_end_balance_cents;
  }, [forecast]);

  return (
    <main className="min-h-screen bg-[#f5f1e8] text-[#14241e]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[1500px]">
          <Reveal>
            <header className="flex flex-col gap-6 border-b border-[#14241e]/10 pb-7 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
                  Forward projection
                </p>

                <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
                  Forecast
                </h1>

                <p className="mt-3 max-w-2xl text-sm leading-6 text-[#66746e]">
                  Project month-end cash, review expected outflows, and spot
                  low-balance risk before it becomes urgent.
                </p>
              </div>
            </header>
          </Reveal>

          {error && (
            <div className="mt-5">
              <PageError
                message={error}
                onRetry={
                  userId
                    ? () => void loadForecast(userId)
                    : undefined
                }
              />
            </div>
          )}

          {loading ? (
            <div className="mt-8">
              <CardSkeleton count={4} />
            </div>
          ) : forecast ? (
            <>
              <Reveal delay={0.06}>
                <section className="mt-6 grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
                  <article className="premium-hover relative overflow-hidden rounded-[30px] bg-[#14241e] p-7 text-white shadow-[0_24px_70px_rgba(20,36,30,0.18)] sm:p-9">
                    <div className="pointer-events-none absolute -right-16 -top-16 h-52 w-52 rounded-full bg-[#76dfbd]/15 blur-3xl" />

                    <div className="relative">
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#83dcb9]">
                        Projected month-end balance
                      </p>

                      <AnimatedNumber
                        value={forecast.projected_end_balance_cents}
                        format={formatCents}
                        className="mt-4 block text-5xl font-semibold tracking-[-0.06em] sm:text-6xl"
                      />

                      <p className="mt-3 text-sm text-white/55">
                        Estimated through {formatDate(forecast.month_end)}.
                      </p>

                      <span
                        className={`mt-4 inline-flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${
                          CONFIDENCE_LEVEL_CONTENT[
                            forecast.confidence.level
                          ].className
                        }`}
                      >
                        <Gauge className="h-3.5 w-3.5" aria-hidden="true" />
                        {Math.round(forecast.confidence.score)}% ·{" "}
                        {
                          CONFIDENCE_LEVEL_CONTENT[
                            forecast.confidence.level
                          ].label
                        }
                      </span>

                      <div className="mt-10 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-3">
                        <ForecastMetric
                          label="Liquid balance"
                          value={formatCents(
                            forecast.liquid_balance_cents
                          )}
                          tone="neutral"
                        />
                        <ForecastMetric
                          label="Expected income"
                          value={formatCents(
                            forecast.expected_income_cents
                          )}
                          tone="positive"
                        />
                        <ForecastMetric
                          label="Upcoming bills"
                          value={formatCents(
                            -forecast.upcoming_bills_cents
                          )}
                          tone="negative"
                        />
                      </div>
                    </div>
                  </article>

                  <article
                    className={`premium-hover rounded-[30px] p-7 sm:p-8 ${
                      forecast.low_balance_risk
                        ? "bg-[#f8ddd5]"
                        : "bg-[#dff6c7]"
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#52635b]">
                          Forecast outlook
                        </p>
                        <h2 className="mt-4 text-3xl font-semibold tracking-[-0.04em]">
                          {forecast.low_balance_risk
                            ? "Low-balance risk"
                            : "Positive outlook"}
                        </h2>
                      </div>

                      <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#14241e] text-white">
                        {forecast.low_balance_risk ? (
                          <AlertTriangle className="h-5 w-5" />
                        ) : (
                          <TrendingUp className="h-5 w-5" />
                        )}
                      </span>
                    </div>

                    <p className="mt-4 text-sm leading-6 text-[#66746e]">
                      {forecast.low_balance_risk
                        ? "Expected bills may exceed available cash and incoming funds."
                        : "Available cash and expected income currently cover predicted bills."}
                    </p>

                    <div className="mt-8 grid grid-cols-2 gap-3">
                      <OutlookStat
                        label="Days remaining"
                        value={String(forecast.days_remaining)}
                      />
                      <OutlookStat
                        label="Predicted bills"
                        value={String(
                          forecast.upcoming_cash_flows.length
                        )}
                      />
                    </div>
                  </article>
                </section>
              </Reveal>

              {forecast.horizon_outlook.length > 0 && (
                <Reveal delay={0.08}>
                  <section className="mt-6">
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
                      30 / 60 / 90-day outlook
                    </p>
                    <p className="mt-1 max-w-2xl text-xs leading-5 text-[#87928d]">
                      Expected income is a pace-based estimate from your
                      recent income spread evenly across each day -- not a
                      guaranteed forecast. It assumes your recent pace
                      continues and does not model irregular or seasonal
                      income; confidence falls when recent data is thin.
                    </p>
                    <div className="mt-3 grid gap-4 sm:grid-cols-3">
                      {forecast.horizon_outlook.map((horizon) => (
                        <HorizonOutlookCard
                          key={horizon.horizon_days}
                          horizon={horizon}
                        />
                      ))}
                    </div>
                  </section>
                </Reveal>
              )}

              <Reveal>
                <section className="mt-6 grid gap-4 md:grid-cols-3">
                  <ScenarioCard
                    label="Best case"
                    value={formatCents(bestCaseBalance)}
                    description="No additional predicted bills"
                    icon="up"
                  />
                  <ScenarioCard
                    label="Expected case"
                    value={formatCents(
                      forecast.projected_end_balance_cents
                    )}
                    description="Current forecast assumptions"
                    icon="steady"
                  />
                  <ScenarioCard
                    label="Risk margin"
                    value={formatCents(riskMargin)}
                    description={
                      forecast.low_balance_risk
                        ? "Potential shortfall"
                        : "Projected buffer"
                    }
                    icon="down"
                    warning={forecast.low_balance_risk}
                  />
                </section>
              </Reveal>

              <Reveal>
                <section className="mt-6">
                  <article className="rounded-[30px] border border-[#14241e]/10 bg-white p-6 shadow-[0_18px_50px_rgba(20,36,30,0.08)] sm:p-8">
                    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
                          Forecast confidence
                        </p>
                        <p className="mt-3 max-w-xl text-sm leading-6 text-[#66746e]">
                          How reliable this forecast is, based on your
                          connected accounts and transaction history.
                        </p>
                      </div>

                      <button
                        type="button"
                        onClick={() =>
                          setConfidenceExpanded((value) => !value)
                        }
                        aria-expanded={confidenceExpanded}
                        className="flex shrink-0 items-center gap-2 rounded-xl border border-[#14241e]/10 bg-[#fbfaf7] px-4 py-2.5 text-sm font-semibold text-[#167c5a] transition hover:bg-[#f1eee7]"
                      >
                        {confidenceExpanded
                          ? "Hide details ↑"
                          : "Why this confidence ↓"}
                      </button>
                    </div>

                    {confidenceExpanded && (
                      <div className="mt-6 border-t border-[#14241e]/10 pt-6">
                        <div className="divide-y divide-[#14241e]/8 overflow-hidden rounded-2xl border border-[#14241e]/8">
                          {forecast.confidence.factors.map((factor) => (
                            <ConfidenceFactorRow
                              key={factor.key}
                              factor={factor}
                            />
                          ))}
                        </div>

                        {forecast.confidence.recommendations.length >
                          0 && (
                          <div className="mt-6 rounded-2xl border border-[#f5d66f]/30 bg-[#fbf6df] p-5">
                            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#8b6518]">
                              Recommendations
                            </p>
                            <ul className="mt-3 space-y-2 text-sm leading-6 text-[#66746e]">
                              {forecast.confidence.recommendations.map(
                                (recommendation) => (
                                  <li
                                    key={recommendation}
                                    className="flex gap-2"
                                  >
                                    <span aria-hidden="true">•</span>
                                    <span>{recommendation}</span>
                                  </li>
                                )
                              )}
                            </ul>
                          </div>
                        )}

                        {forecast.confidence.monthly_confidence.length >
                          0 && (
                          <div className="mt-6">
                            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#167c5a]">
                              Monthly confidence
                            </p>
                            <p className="mt-1 text-xs text-[#7b8781]">
                              Data quality for each recent month with
                              enough transaction history to measure.
                            </p>

                            <div className="mt-3 divide-y divide-[#14241e]/8 rounded-2xl border border-[#14241e]/8">
                              {forecast.confidence.monthly_confidence.map(
                                (entry) => (
                                  <div
                                    key={entry.month}
                                    className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-3"
                                  >
                                    <span className="text-sm font-medium text-[#14241e]">
                                      {formatMonth(entry.month)}
                                    </span>
                                    <span className="text-xs text-[#7b8781]">
                                      {entry.transaction_count}{" "}
                                      transaction
                                      {entry.transaction_count === 1
                                        ? ""
                                        : "s"}
                                    </span>
                                    <span className="text-sm font-semibold text-[#14241e]">
                                      {Math.round(entry.score)}%
                                    </span>
                                  </div>
                                )
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </article>
                </section>
              </Reveal>

              <Reveal>
                <section className="mt-8">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
                        Upcoming timeline
                      </p>
                      <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
                        Predicted cash outflows
                      </h2>
                    </div>

                    <p className="text-sm text-[#7b8781]">
                      {forecast.upcoming_cash_flows.length} expected
                    </p>
                  </div>

                  {forecast.upcoming_cash_flows.length > 0 ? (
                    <div className="mt-5 overflow-hidden rounded-[24px] border border-[#14241e]/10 bg-white">
                      <header className="hidden border-b border-[#14241e]/10 bg-[#faf8f3] px-5 py-4 text-xs font-semibold uppercase tracking-[0.12em] text-[#7a8780] md:grid md:grid-cols-[minmax(220px,1.4fr)_160px_150px_150px_40px] md:items-center">
                        <span>Merchant</span>
                        <span>Expected date</span>
                        <span>Amount</span>
                        <span>Confidence</span>
                        <span />
                      </header>

                      <div className="divide-y divide-[#14241e]/8">
                        {forecast.upcoming_cash_flows.map((item) => (
                          <ForecastRow
                            key={`${item.merchant}-${item.expected_date}`}
                            item={item}
                            onOpen={() => setActiveItem(item)}
                          />
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="mt-5 rounded-[30px] border border-dashed border-[#14241e]/15 bg-white px-6 py-14 text-center">
                      <p className="text-lg font-semibold">
                        No predicted bills
                      </p>
                      <p className="mt-2 text-sm text-[#728078]">
                        No recurring bills are currently expected before
                        month-end.
                      </p>
                    </div>
                  )}
                </section>
              </Reveal>

              <p className="mt-6 text-xs leading-5 text-[#7b8781]">
                Forecasts are estimates based on connected balances,
                expected income, and recurring-payment patterns.
              </p>
            </>
          ) : error ? null : (
            <div className="mt-8">
              <EmptyState
                title="Forecast unavailable"
                description="Connect an account and add more transaction history to generate a cash-flow projection."
                actionLabel="View accounts"
                onAction={() => router.push("/accounts")}
              />
            </div>
          )}

          <Reveal>
            <ResilienceSection
              resilience={resilience}
              loading={resilienceLoading}
              error={resilienceError}
              simulating={simulating}
              essentialOverride={essentialOverride}
              overrideActive={overrideActive}
              onEssentialOverrideChange={setEssentialOverride}
              onSimulate={() => void handleSimulateEssentialSpending()}
              onReset={() => void handleResetToEstimated()}
              onRetry={
                userId ? () => void loadResilience(userId) : undefined
              }
            />
          </Reveal>
        </PageReveal>
      </div>

      <Toast
        message={toast}
        type={toastType}
        onClose={() => setToast("")}
      />

      <AnimatePresence>
        {activeItem && (
          <ForecastDrawer
            item={activeItem}
            monthEnd={forecast?.month_end ?? ""}
            onClose={() => setActiveItem(null)}
          />
        )}
      </AnimatePresence>
    </main>
  );
}

function ForecastMetric({
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

function OutlookStat({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl bg-white/45 p-4">
      <p className="text-[10px] uppercase tracking-[0.1em] text-[#66746e]">
        {label}
      </p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
    </div>
  );
}

function ScenarioCard({
  label,
  value,
  description,
  icon,
  warning = false,
}: {
  label: string;
  value: string;
  description: string;
  icon: "up" | "steady" | "down";
  warning?: boolean;
}) {
  return (
    <article
      className={`premium-hover rounded-[24px] border border-[#14241e]/10 p-5 ${
        warning ? "bg-[#f8ddd5]" : "bg-white"
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#7b8781]">
            {label}
          </p>
          <p className="mt-3 text-2xl font-semibold tracking-[-0.04em]">
            {value}
          </p>
        </div>

        <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[#edf5ee] text-[#167c5a]">
          {icon === "up" ? (
            <TrendingUp className="h-4 w-4" />
          ) : icon === "down" ? (
            <TrendingDown className="h-4 w-4" />
          ) : (
            <Gauge className="h-4 w-4" />
          )}
        </span>
      </div>

      <p className="mt-3 text-sm text-[#66746e]">{description}</p>
    </article>
  );
}

function HorizonOutlookCard({
  horizon,
}: {
  horizon: CashFlowForecast["horizon_outlook"][number];
}) {
  const shortfall = horizon.shortfall_cents > 0;

  return (
    <article
      className={`rounded-[24px] border p-5 ${
        shortfall
          ? "border-[#923f32]/20 bg-[#fdf4f1]"
          : "border-[#14241e]/10 bg-white"
      }`}
    >
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">{horizon.horizon_days} days</p>
        <span className="text-xs text-[#87928d]">
          through {formatDate(horizon.through_date)}
        </span>
      </div>

      <p
        className={`mt-3 text-2xl font-semibold tracking-[-0.04em] ${
          shortfall ? "text-[#923f32]" : "text-[#14241e]"
        }`}
      >
        {formatCents(horizon.projected_balance_cents)}
      </p>
      <p className="mt-1 text-xs text-[#87928d]">
        {shortfall
          ? `${formatCents(horizon.shortfall_cents)} projected shortfall`
          : "Projected balance"}
      </p>

      <div className="mt-4 flex items-center justify-between text-xs text-[#66746e]">
        <span>
          Known bills{" "}
          {formatCents(-horizon.known_obligations_cents)}
        </span>
        <span>{Math.round(horizon.confidence_score)}% confidence</span>
      </div>
    </article>
  );
}

function ResilienceSection({
  resilience,
  loading,
  error,
  simulating,
  essentialOverride,
  overrideActive,
  onEssentialOverrideChange,
  onSimulate,
  onReset,
  onRetry,
}: {
  resilience: FinancialResilience | null;
  loading: boolean;
  error: string;
  simulating: boolean;
  essentialOverride: string;
  overrideActive: boolean;
  onEssentialOverrideChange: (value: string) => void;
  onSimulate: () => void;
  onReset: () => void;
  onRetry?: () => void;
}) {
  return (
    <section className="mt-10">
      <div className="flex items-center gap-3">
        <ShieldCheck className="h-5 w-5 text-[#167c5a]" aria-hidden="true" />
        <h2 className="text-2xl font-semibold tracking-[-0.03em]">
          Financial resilience
        </h2>
      </div>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-[#66746e]">
        How long your liquid cash would last if income stopped today, at
        your recent spending pace or a specific essential-spending amount
        you provide.
      </p>

      {error ? (
        <div className="mt-5">
          <PageError message={error} onRetry={onRetry} />
        </div>
      ) : loading ? (
        <div className="mt-5">
          <CardSkeleton count={2} />
        </div>
      ) : !resilience ? null : (
        <div className="mt-5 space-y-4">
          <ResilienceHero resilience={resilience} />

          <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
            <article className="rounded-[24px] border border-[#14241e]/10 bg-white p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#167c5a]">
                30 / 60 / 90-day{" "}
                {resilience.essential_spending_source === "user_provided"
                  ? "essential-expense"
                  : "spending-pace"}{" "}
                coverage
              </p>
              <div className="mt-4 space-y-3">
                {resilience.horizons.map((horizon) => (
                  <CoverageHorizonRow
                    key={horizon.horizon_days}
                    horizon={horizon}
                    isExplicit={
                      resilience.essential_spending_source ===
                      "user_provided"
                    }
                  />
                ))}
              </div>
            </article>

            <article className="rounded-[24px] border border-[#14241e]/10 bg-white p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#167c5a]">
                What if essential spending changes?
              </p>
              <p className="mt-2 text-xs leading-5 text-[#66746e]">
                Enter a monthly essential-spending amount to see how your
                runway would change.
              </p>

              <div className="mt-4 flex flex-wrap items-end gap-3">
                <label className="block">
                  <span className="text-xs font-semibold uppercase tracking-[0.1em] text-[#66746e]">
                    Monthly essential spending
                  </span>
                  <div className="relative mt-2">
                    <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-sm font-semibold text-[#728078]">
                      $
                    </span>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={essentialOverride}
                      onChange={(event) =>
                        onEssentialOverrideChange(event.target.value)
                      }
                      placeholder="4000.00"
                      className="h-11 w-40 rounded-xl border border-[#14241e]/10 bg-[#fbfaf7] pl-8 pr-3 text-sm outline-none transition focus:border-[#167c5a] focus:bg-white"
                    />
                  </div>
                </label>

                <button
                  type="button"
                  onClick={onSimulate}
                  disabled={simulating}
                  className="h-11 rounded-xl bg-[#14241e] px-4 text-sm font-semibold text-white transition hover:bg-[#25443a] disabled:cursor-not-allowed disabled:opacity-55"
                >
                  {simulating ? "Simulating..." : "Simulate"}
                </button>

                {overrideActive && (
                  <button
                    type="button"
                    onClick={onReset}
                    disabled={simulating}
                    className="h-11 rounded-xl border border-[#14241e]/10 px-4 text-sm font-semibold text-[#66746e] transition hover:bg-[#f1eee7] disabled:opacity-55"
                  >
                    Reset to estimated
                  </button>
                )}
              </div>

              {overrideActive && (
                <p className="mt-3 text-xs font-medium text-[#167c5a]">
                  Showing your scenario at{" "}
                  {formatCents(resilience.monthly_essential_cents)}/month.
                </p>
              )}
            </article>
          </div>

          <article className="rounded-[24px] border border-[#14241e]/10 bg-[#f5f1e8] p-6">
            <div className="flex items-start gap-3">
              <Sparkles className="mt-0.5 h-5 w-5 shrink-0 text-[#167c5a]" />
              <div>
                <p className="text-sm font-semibold">
                  {resilience.headline}
                </p>
                <p className="mt-2 text-sm leading-6 text-[#66746e]">
                  {resilience.why}
                </p>
                <p className="mt-2 text-sm leading-6 text-[#66746e]">
                  {resilience.what_this_means}
                </p>
                {resilience.suggested_actions.length > 0 && (
                  <ul className="mt-3 space-y-1.5 text-sm leading-6 text-[#66746e]">
                    {resilience.suggested_actions.map((action) => (
                      <li key={action} className="flex gap-2">
                        <span aria-hidden="true">•</span>
                        <span>{action}</span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-3 text-xs font-medium text-[#87928d]">
                  {resilience.essential_spending_source === "user_provided"
                    ? `${resilience.spending_basis_label}: your stated amount.`
                    : `${resilience.spending_basis_label}: estimated from your recent total spending (FinSight doesn't yet classify essential vs. discretionary expenses).`}
                  {resilience.data_quality_note
                    ? ` ${resilience.data_quality_note}`
                    : ""}
                </p>
              </div>
            </div>
          </article>
        </div>
      )}
    </section>
  );
}

function ResilienceHero({
  resilience,
}: {
  resilience: FinancialResilience;
}) {
  const status = RESILIENCE_STATUS_CONTENT[resilience.resilience_status];
  const barPercent =
    resilience.runway_months === null
      ? 100
      : Math.min((resilience.runway_months / 12) * 100, 100);
  const isExplicit = resilience.essential_spending_source === "user_provided";

  return (
    <article className="relative overflow-hidden rounded-[30px] bg-[#14241e] p-7 text-white shadow-[0_24px_70px_rgba(20,36,30,0.18)] sm:p-9">
      <div className="pointer-events-none absolute -right-16 -top-16 h-52 w-52 rounded-full bg-[#76dfbd]/15 blur-3xl" />

      <div className="relative flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#83dcb9]">
            {isExplicit ? "Emergency runway" : "Spending coverage"}
          </p>
          <p className="mt-3 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
            {resilience.runway_months === null
              ? "No measurable spending"
              : `${resilience.runway_months} months`}
          </p>
          <p className="mt-2 text-sm text-white/55">
            {resilience.runway_months === null
              ? isExplicit
                ? "of essential expenses covered"
                : "at your recent spending pace"
              : isExplicit
                ? "of essential expenses covered by liquid cash"
                : "covered by liquid cash at your recent spending pace"}
          </p>

          <span
            className={`mt-4 inline-flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${status.className}`}
          >
            {resilience.resilience_status === "critical" ? (
              <ShieldAlert className="h-3.5 w-3.5" />
            ) : (
              <ShieldCheck className="h-3.5 w-3.5" />
            )}
            {status.label}
          </span>

          <div className="mt-5 h-2 w-full max-w-xs overflow-hidden rounded-full bg-white/10">
            <div
              className={`h-full rounded-full ${status.barClassName}`}
              style={{ width: `${barPercent}%` }}
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-4 lg:w-[420px]">
          <ResilienceMetric
            label="Liquid cash"
            value={formatCents(resilience.liquid_balance_cents)}
          />
          <ResilienceMetric
            label={resilience.spending_basis_label}
            value={`${formatCents(resilience.monthly_essential_cents)}/mo`}
          />
          <ResilienceMetric
            label="Accounts"
            value={String(resilience.liquid_account_count)}
          />
          <ResilienceMetric
            label="Confidence"
            value={`${Math.round(resilience.confidence_score)}%`}
          />
        </div>
      </div>
    </article>
  );
}

function ResilienceMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="bg-white/[0.045] p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/35">
        {label}
      </p>
      <p className="mt-2 text-lg font-semibold">{value}</p>
    </div>
  );
}

function CoverageHorizonRow({
  horizon,
  isExplicit,
}: {
  horizon: FinancialResilience["horizons"][number];
  isExplicit: boolean;
}) {
  const shortfall = horizon.shortfall_cents > 0;
  const spendingPhrase = isExplicit
    ? "essential spending"
    : "your recent spending pace";

  return (
    <div className="rounded-2xl border border-[#14241e]/8 bg-[#fbfaf7] p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">{horizon.horizon_days}-day coverage</p>
        <p
          className={`text-sm font-semibold ${
            shortfall ? "text-[#923f32]" : "text-[#167c5a]"
          }`}
        >
          {horizon.coverage_percent}%
        </p>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#14241e]/8">
        <div
          className={`h-full rounded-full ${
            shortfall ? "bg-[#c0604c]" : "bg-[#167c5a]"
          }`}
          style={{ width: `${Math.min(horizon.coverage_percent, 100)}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-[#87928d]">
        {shortfall
          ? `${formatCents(horizon.shortfall_cents)} shortfall against ${spendingPhrase}`
          : `${formatCents(horizon.remaining_liquid_cents)} remaining after ${spendingPhrase}`}
      </p>
    </div>
  );
}

function ConfidenceFactorRow({
  factor,
}: {
  factor: ForecastConfidenceFactor;
}) {
  const impact = FACTOR_IMPACT_CONTENT[factor.impact];

  return (
    <div className="grid gap-2 px-4 py-4 sm:grid-cols-[1fr_auto] sm:items-center sm:gap-4">
      <div>
        <p className="text-sm font-semibold text-[#14241e]">
          {factor.label}
        </p>
        <p className="mt-1 text-xs leading-5 text-[#7b8781]">
          {factor.detail}
        </p>
      </div>

      <span
        className={`w-fit rounded-full px-3 py-1 text-xs font-semibold sm:justify-self-end ${impact.className}`}
      >
        {impact.label}
      </span>
    </div>
  );
}

function ForecastRow({
  item,
  onOpen,
}: {
  item: ForecastItem;
  onOpen: () => void;
}) {
  const reduceMotion = useReducedMotion();

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
      className="grid w-full gap-4 px-5 py-4 text-left md:grid-cols-[minmax(220px,1.4fr)_160px_150px_150px_40px] md:items-center"
    >
      <div className="flex min-w-0 items-center gap-3">
        <MerchantAvatar merchant={item.merchant} />

        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">
            {item.merchant}
          </p>
          <p className="mt-1 text-xs text-[#87928d]">
            Predicted recurring charge
          </p>
        </div>
      </div>

      <p className="text-sm font-medium">
        {formatDate(item.expected_date)}
      </p>

      <p className="text-sm font-semibold text-[#a64b3d]">
        {formatCents(-item.amount_cents)}
      </p>

      <span
        className={`w-fit rounded-full px-3 py-1.5 text-xs font-semibold ${
          item.confidence_score >= 90
            ? "bg-[#edf5ee] text-[#167c5a]"
            : item.confidence_score >= 75
              ? "bg-[#f7e8b5] text-[#8b6518]"
              : "bg-[#f8ddd5] text-[#923f32]"
        }`}
      >
        {item.confidence_score}% confidence
      </span>

      <ChevronRight className="h-4 w-4 text-[#87928d]" />
    </motion.button>
  );
}

function ForecastDrawer({
  item,
  monthEnd,
  onClose,
}: {
  item: ForecastItem;
  monthEnd: string;
  onClose: () => void;
}) {
  const reduceMotion = useReducedMotion();

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
        aria-label="Close forecast details"
        onClick={onClose}
        className="absolute inset-0 bg-[#14241e]/35 backdrop-blur-[2px]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      />

      <motion.aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="forecast-drawer-title"
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
          <div className="flex min-w-0 items-center gap-3 pr-4">
            <MerchantAvatar merchant={item.merchant} />

            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#167c5a]">
                Forecast detail
              </p>
              <h2
                id="forecast-drawer-title"
                className="mt-1 truncate text-xl font-semibold"
              >
                {item.merchant}
              </h2>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close forecast details"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[#14241e]/10 bg-white"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          <p className="text-sm text-[#728078]">
            Predicted amount
          </p>
          <p className="mt-2 text-4xl font-semibold tracking-[-0.05em] text-[#a64b3d]">
            {formatCents(-item.amount_cents)}
          </p>

          <dl className="mt-7 divide-y divide-[#14241e]/10 border-y border-[#14241e]/10">
            <DrawerDetail
              label="Expected date"
              value={formatDate(item.expected_date)}
            />
            <DrawerDetail
              label="Confidence"
              value={`${item.confidence_score}%`}
            />
            <DrawerDetail
              label="Confidence level"
              value={confidenceLabel(item.confidence_score)}
            />
            <DrawerDetail
              label="Forecast period"
              value={monthEnd ? `Through ${formatDate(monthEnd)}` : "Current period"}
            />
          </dl>

          <div className="mt-7 rounded-2xl bg-[#edf5ee] p-5">
            <div className="flex gap-3">
              <Sparkles className="mt-0.5 h-5 w-5 shrink-0 text-[#167c5a]" />
              <div>
                <p className="text-sm font-semibold">
                  Forecast explanation
                </p>
                <p className="mt-1 text-sm leading-6 text-[#66746e]">
                  This charge is projected from recurring transaction
                  timing and historical amount consistency.
                </p>
              </div>
            </div>
          </div>

          <div className="mt-5 flex items-center gap-3 rounded-2xl border border-[#14241e]/10 bg-white p-4">
            <CalendarClock className="h-5 w-5 text-[#728078]" />
            <p className="text-sm text-[#66746e]">
              The actual charge date and amount may differ.
            </p>
          </div>

          <div className="mt-5 flex items-center gap-3 rounded-2xl border border-[#14241e]/10 bg-white p-4">
            <CircleDollarSign className="h-5 w-5 text-[#728078]" />
            <p className="text-sm text-[#66746e]">
              Include this predicted outflow when planning your remaining
              monthly cash.
            </p>
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
    <div className="grid gap-1 py-4 sm:grid-cols-[130px_1fr]">
      <dt className="text-xs font-semibold uppercase tracking-[0.1em] text-[#87928d]">
        {label}
      </dt>
      <dd className="text-sm font-medium sm:text-right">{value}</dd>
    </div>
  );
}
