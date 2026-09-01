"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
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
    className: "bg-[#EFE6D2] text-[#8B6518]",
    barClassName: "bg-[#c9a13f]",
  },
  strong: {
    label: "Strong",
    className: "bg-[#E3EBE1] text-[#48634B]",
    barClassName: "bg-[#4d9a5a]",
  },
  very_strong: {
    label: "Very strong",
    className: "bg-[#E3EBE1] text-[#48634B]",
    barClassName: "bg-[#6E4B63]",
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
    className: "bg-[#E3EBE1] text-[#48634B]",
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
    className: "bg-[#E3EBE1] text-[#48634B]",
  },
  neutral: {
    label: "Neutral",
    className: "bg-[#f1eee7] text-[#706961]",
  },
  negative: {
    label: "Weak spot",
    className: "bg-[#f8ddd5] text-[#923f32]",
  },
};

export default function ForecastPage() {
  const router = useRouter();
  const reduceMotion = useReducedMotion();
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

  const trajectoryData = useMemo(() => {
    if (!forecast) return [];
    return [
      { label: "Current", balance: forecast.liquid_balance_cents / 100 },
      ...forecast.horizon_outlook.map((point) => ({
        label: `${point.horizon_days} days`,
        balance: point.projected_balance_cents / 100,
      })),
    ];
  }, [forecast]);

  return (
    <main className="min-h-screen bg-[#F5F1EA] text-[#181713]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-56 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[1500px]">
          <Reveal>
            <header className="flex flex-col gap-6 border-b border-[#181713]/10 pb-5 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
                  Forward view
                </p>

                <h1 className="mt-1 text-[32px] font-semibold tracking-[-0.03em]">
                  Forecast
                </h1>

                <p className="mt-1 text-sm text-[#706961]">
                  Where known cash movement takes you next.
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
                <section className="mt-6 border-y border-[#181713]/10 bg-[#FFFCF7] px-5 py-7 sm:px-8 sm:py-8">
                  <div className="grid gap-7 xl:grid-cols-[minmax(280px,0.9fr)_minmax(520px,1.35fr)] xl:items-end">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
                        Projected month-end balance
                      </p>
                      <AnimatedNumber
                        value={forecast.projected_end_balance_cents}
                        format={formatCents}
                        className="mt-4 block text-5xl font-semibold tracking-[-0.06em] text-[#2F2930] sm:text-6xl"
                      />
                      <span className={`mt-3 inline-flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${CONFIDENCE_LEVEL_CONTENT[forecast.confidence.level].className}`}>
                        <Gauge className="h-3.5 w-3.5" aria-hidden="true" />
                        {Math.round(forecast.confidence.score)}% · {CONFIDENCE_LEVEL_CONTENT[forecast.confidence.level].label}
                      </span>

                      {forecast.confidence.drivers.length > 0 && (
                        <ul className="mt-4 space-y-1.5">
                          {forecast.confidence.drivers.map((driver) => (
                            <li
                              key={driver.code}
                              className="flex items-start gap-2 text-xs leading-5 text-[#706961]"
                            >
                              <span
                                aria-hidden="true"
                                className={`mt-1 h-1.5 w-1.5 flex-none rounded-full ${
                                  driver.direction === "positive"
                                    ? "bg-[#58715A]"
                                    : "bg-[#C59A52]"
                                }`}
                              />
                              {driver.message}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <dl className="grid grid-cols-2 gap-y-5 sm:grid-cols-3 sm:divide-x sm:divide-[#181713]/10">
                      {[
                        ["Liquid balance", formatCents(forecast.liquid_balance_cents)],
                        ["Expected income", formatCents(forecast.expected_income_cents)],
                        ["Upcoming bills", formatCents(-forecast.upcoming_bills_cents)],
                      ].map(([label, value]) => (
                        <div key={label} className="sm:px-5 first:sm:pl-0 last:sm:pr-0">
                          <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#8A8178]">{label}</dt>
                          <dd className="mt-2 text-lg font-semibold tabular-nums text-[#2F2930] [overflow-wrap:anywhere]">{value}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>

                  <div className="mt-7 border-t border-[#181713]/10 pt-5">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[#706961]">
                      <span className="font-semibold text-[#2F2930]">Balance movement</span>
                      <span className={`inline-flex items-center gap-2 font-semibold ${forecast.low_balance_risk ? "text-[#A25543]" : "text-[#58715A]"}`}>
                        <span className={`h-2 w-2 rounded-full ${forecast.low_balance_risk ? "bg-[#A25543]" : "bg-[#58715A]"}`} />
                        {forecast.low_balance_risk ? "Low-balance risk" : "Positive outlook"}
                      </span>
                    </div>

                    <div className="mt-3 grid grid-cols-[minmax(0,auto)_minmax(60px,1fr)_minmax(0,auto)] items-center gap-3 text-sm font-semibold tabular-nums">
                      <span className="max-w-[38vw] [overflow-wrap:anywhere]">{formatCents(forecast.liquid_balance_cents)}</span>
                      <div className="relative h-2">
                        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-[#181713]/15" />
                        <motion.div
                          initial={reduceMotion ? false : { scaleX: 0 }}
                          animate={{ scaleX: 1 }}
                          transition={{ duration: reduceMotion ? 0 : 0.65, delay: reduceMotion ? 0 : 0.35, ease: [0.22, 1, 0.36, 1] }}
                          className={`absolute inset-x-0 top-1/2 h-0.5 origin-left -translate-y-1/2 ${forecast.low_balance_risk ? "bg-[#A25543]" : "bg-[#6E4B63]"}`}
                        />
                        <span className={`absolute right-0 top-1/2 h-2.5 w-2.5 -translate-y-1/2 rounded-full ${forecast.low_balance_risk ? "bg-[#A25543]" : "bg-[#6E4B63]"}`} />
                      </div>
                      <span className="max-w-[38vw] text-right [overflow-wrap:anywhere]">{formatCents(forecast.projected_end_balance_cents)}</span>
                    </div>

                    <p className="mt-2 text-xs text-[#8A8178]">
                      Through {formatDate(forecast.month_end)} · {forecast.days_remaining} days · {forecast.upcoming_cash_flows.length} predicted bill{forecast.upcoming_cash_flows.length === 1 ? "" : "s"}
                    </p>
                  </div>
                </section>
              </Reveal>

              {trajectoryData.length > 1 && (
                <Reveal delay={0.08}>
                  <section className="mt-6 border-y border-[#181713]/10 bg-[#FFFCF7] px-5 py-6 sm:px-8">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">Cash trajectory</p>
                        <h2 className="mt-2 text-2xl font-semibold tracking-[-0.035em]">Current balance to projected horizons</h2>
                      </div>
                      <p className="text-sm text-[#8A8178]">Based on existing forecast assumptions</p>
                    </div>
                    <div className="mt-6 h-[300px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={trajectoryData} margin={{ top: 10, right: 12, left: -8, bottom: 0 }}>
                          <defs>
                            <linearGradient id="forecastTrajectoryFill" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="0%" stopColor="#6E4B63" stopOpacity={0.2} />
                              <stop offset="100%" stopColor="#6E4B63" stopOpacity={0.01} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid vertical={false} stroke="rgba(24,23,19,0.08)" />
                          <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fill: "#8A8178", fontSize: 11 }} dy={10} />
                          <YAxis axisLine={false} tickLine={false} tick={{ fill: "#8A8178", fontSize: 11 }} tickFormatter={(value) => `$${Number(value).toLocaleString("en-US", { notation: "compact" })}`} />
                          <Tooltip formatter={(value) => Number(value).toLocaleString("en-US", { style: "currency", currency: "USD" })} contentStyle={{ border: "1px solid rgba(24,23,19,0.1)", background: "#FFFCF7", borderRadius: 12 }} />
                          <Area type="monotone" dataKey="balance" stroke="#6E4B63" strokeWidth={3} fill="url(#forecastTrajectoryFill)" dot={{ r: 4, fill: "#FFFCF7", stroke: "#6E4B63", strokeWidth: 2 }} isAnimationActive={!reduceMotion} animationDuration={900} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </section>
                </Reveal>
              )}

              {forecast.horizon_outlook.length > 0 && (
                <Reveal delay={0.08}>
                  <section className="mt-6">
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
                      30 / 60 / 90-day outlook
                    </p>
                    <p className="mt-1 max-w-2xl text-xs leading-5 text-[#8A8178]">
                      Expected income is a pace-based estimate from your
                      recent income spread evenly across each day -- not a
                      guaranteed forecast. It assumes your recent pace
                      continues and does not model irregular or seasonal
                      income; confidence falls when recent data is thin.
                    </p>
                    <div className="mt-4 grid gap-px overflow-hidden border-y border-[#181713]/10 bg-[#181713]/10 sm:grid-cols-3">
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
                <section className="mt-6 grid gap-px overflow-hidden border-y border-[#181713]/10 bg-[#181713]/10 md:grid-cols-3">
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
                  <article className="rounded-[30px] border border-[#181713]/10 bg-white p-6 shadow-[0_18px_50px_rgba(60,43,35,0.08)] sm:p-8">
                    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
                          Forecast confidence
                        </p>
                        <p className="mt-3 max-w-xl text-sm leading-6 text-[#706961]">
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
                        className="flex shrink-0 items-center gap-2 rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 py-2.5 text-sm font-semibold text-[#6E4B63] transition hover:bg-[#f1eee7]"
                      >
                        {confidenceExpanded
                          ? "Hide details ↑"
                          : "Why this confidence ↓"}
                      </button>
                    </div>

                    {confidenceExpanded && (
                      <div className="mt-6 border-t border-[#181713]/10 pt-6">
                        <div className="mb-5 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-[#8A8178]">
                          <span>
                            {forecast.confidence.data_quality.history_days} days
                            of history
                          </span>
                          <span>
                            {forecast.confidence.data_quality.transaction_count}{" "}
                            transaction
                            {forecast.confidence.data_quality
                              .transaction_count === 1
                              ? ""
                              : "s"}
                          </span>
                          <span>
                            {
                              forecast.confidence.data_quality
                                .recognized_recurring_items
                            }{" "}
                            recurring item
                            {forecast.confidence.data_quality
                              .recognized_recurring_items === 1
                              ? ""
                              : "s"}{" "}
                            recognized
                          </span>
                          <span>
                            {Math.round(
                              forecast.confidence.data_quality
                                .uncategorized_share * 100
                            )}
                            % of spending uncategorized
                          </span>
                        </div>

                        <div className="divide-y divide-[#181713]/8 overflow-hidden rounded-2xl border border-[#181713]/8">
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
                            <ul className="mt-3 space-y-2 text-sm leading-6 text-[#706961]">
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
                            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#6E4B63]">
                              Monthly confidence
                            </p>
                            <p className="mt-1 text-xs text-[#8A8178]">
                              Data quality for each recent month with
                              enough transaction history to measure.
                            </p>

                            <div className="mt-3 divide-y divide-[#181713]/8 rounded-2xl border border-[#181713]/8">
                              {forecast.confidence.monthly_confidence.map(
                                (entry) => (
                                  <div
                                    key={entry.month}
                                    className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-3"
                                  >
                                    <span className="text-sm font-medium text-[#181713]">
                                      {formatMonth(entry.month)}
                                    </span>
                                    <span className="text-xs text-[#8A8178]">
                                      {entry.transaction_count}{" "}
                                      transaction
                                      {entry.transaction_count === 1
                                        ? ""
                                        : "s"}
                                    </span>
                                    <span className="text-sm font-semibold text-[#181713]">
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
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
                        Upcoming timeline
                      </p>
                      <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
                        Predicted cash outflows
                      </h2>
                    </div>

                    <p className="text-sm text-[#8A8178]">
                      {forecast.upcoming_cash_flows.length} expected
                    </p>
                  </div>

                  {forecast.upcoming_cash_flows.length > 0 ? (
                    <div className="mt-5 overflow-hidden rounded-[24px] border border-[#181713]/10 bg-white">
                      <header className="hidden border-b border-[#181713]/10 bg-[#faf8f3] px-5 py-4 text-xs font-semibold uppercase tracking-[0.12em] text-[#7a8780] xl:grid xl:grid-cols-[minmax(220px,1.4fr)_160px_150px_150px_40px] xl:items-center">
                        <span>Merchant</span>
                        <span>Expected date</span>
                        <span>Amount</span>
                        <span>Confidence</span>
                        <span />
                      </header>

                      <div className="divide-y divide-[#181713]/8">
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
                    <div className="mt-5 rounded-[30px] border border-dashed border-[#181713]/15 bg-white px-6 py-14 text-center">
                      <p className="text-lg font-semibold">
                        No predicted bills
                      </p>
                      <p className="mt-2 text-sm text-[#777168]">
                        No recurring bills are currently expected before
                        month-end.
                      </p>
                    </div>
                  )}
                </section>
              </Reveal>

              <p className="mt-6 text-xs leading-5 text-[#8A8178]">
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
      className={`p-5 sm:p-6 ${
        warning ? "bg-[#f8ddd5]" : "bg-[#FFFCF7]"
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#8A8178]">
            {label}
          </p>
          <p className="mt-3 text-2xl font-semibold tracking-[-0.04em]">
            {value}
          </p>
        </div>

        <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[#edf5ee] text-[#6E4B63]">
          {icon === "up" ? (
            <TrendingUp className="h-4 w-4" />
          ) : icon === "down" ? (
            <TrendingDown className="h-4 w-4" />
          ) : (
            <Gauge className="h-4 w-4" />
          )}
        </span>
      </div>

      <p className="mt-3 text-sm text-[#706961]">{description}</p>
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
      className={`p-5 sm:p-6 ${
        shortfall
          ? "bg-[#fdf4f1]"
          : "bg-[#FFFCF7]"
      }`}
    >
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">{horizon.horizon_days} days</p>
        <span className="text-xs text-[#8A8178]">
          through {formatDate(horizon.through_date)}
        </span>
      </div>

      <p
        className={`mt-3 text-2xl font-semibold tracking-[-0.04em] ${
          shortfall ? "text-[#923f32]" : "text-[#181713]"
        }`}
      >
        {formatCents(horizon.projected_balance_cents)}
      </p>
      <p className={shortfall ? "mt-1 text-sm font-semibold text-[#923f32]" : "mt-1 text-xs text-[#8A8178]"}>
        {shortfall
          ? `${formatCents(horizon.shortfall_cents)} projected shortfall`
          : "Projected balance"}
      </p>

      <div className="mt-4 flex items-center justify-between text-xs text-[#706961]">
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
        <ShieldCheck className="h-5 w-5 text-[#6E4B63]" aria-hidden="true" />
        <h2 className="text-2xl font-semibold tracking-[-0.03em]">
          Financial resilience
        </h2>
      </div>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-[#706961]">
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
            <article className="rounded-[24px] border border-[#181713]/10 bg-white p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
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

            <article className="rounded-[24px] border border-[#181713]/10 bg-white p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
                What if essential spending changes?
              </p>
              <p className="mt-2 text-xs leading-5 text-[#706961]">
                Enter a monthly essential-spending amount to see how your
                runway would change.
              </p>

              <div className="mt-4 flex flex-wrap items-end gap-3">
                <label className="block">
                  <span className="text-xs font-semibold uppercase tracking-[0.1em] text-[#706961]">
                    Monthly essential spending
                  </span>
                  <div className="relative mt-2">
                    <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-sm font-semibold text-[#777168]">
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
                      className="h-11 w-40 rounded-xl border border-[#181713]/10 bg-[#FFFCF7] pl-8 pr-3 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
                    />
                  </div>
                </label>

                <button
                  type="button"
                  onClick={onSimulate}
                  disabled={simulating}
                  className="discero-button-primary h-11 rounded-xl px-4 text-sm font-semibold transition disabled:cursor-not-allowed"
                >
                  {simulating ? "Simulating..." : "Simulate"}
                </button>

                {overrideActive && (
                  <button
                    type="button"
                    onClick={onReset}
                    disabled={simulating}
                    className="h-11 rounded-xl border border-[#181713]/10 px-4 text-sm font-semibold text-[#706961] transition hover:bg-[#f1eee7] disabled:opacity-55"
                  >
                    Reset to estimated
                  </button>
                )}
              </div>

              {overrideActive && (
                <p className="mt-3 text-sm font-semibold text-[#6E4B63]">
                  Showing your scenario at{" "}
                  {formatCents(resilience.monthly_essential_cents)}/month.
                </p>
              )}
            </article>
          </div>

          <article className="rounded-[24px] border border-[#181713]/10 bg-[#F5F1EA] p-6">
            <div className="flex items-start gap-3">
              <Sparkles className="mt-0.5 h-5 w-5 shrink-0 text-[#6E4B63]" />
              <div>
                <p className="text-sm font-semibold">
                  {resilience.headline}
                </p>
                <p className="mt-2 text-sm leading-6 text-[#706961]">
                  {resilience.why}
                </p>
                <p className="mt-2 text-sm leading-6 text-[#706961]">
                  {resilience.what_this_means}
                </p>
                {resilience.suggested_actions.length > 0 && (
                  <ul className="mt-3 space-y-1.5 text-sm leading-6 text-[#706961]">
                    {resilience.suggested_actions.map((action) => (
                      <li key={action} className="flex gap-2">
                        <span aria-hidden="true">•</span>
                        <span>{action}</span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-3 text-xs font-medium text-[#8A8178]">
                  {resilience.essential_spending_source === "user_provided"
                    ? `${resilience.spending_basis_label}: your stated amount.`
                    : `${resilience.spending_basis_label}: estimated from your recent total spending (Discero doesn't yet classify essential vs. discretionary expenses).`}
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
    <article className="rounded-[24px] border border-[#181713]/10 bg-[#FFFCF7] p-7 sm:p-8">
      <div className="flex flex-col gap-8 lg:flex-row lg:items-start lg:justify-between">
        <div className="lg:max-w-[58%]">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
            {isExplicit ? "Emergency runway" : "Spending coverage"}
          </p>

          <p className="mt-3 text-4xl font-semibold tracking-[-0.05em] text-[#181713] sm:text-5xl">
            {resilience.runway_months === null
              ? "No measurable spending"
              : `${resilience.runway_months} months`}
          </p>

          <p className="mt-2 max-w-md text-sm leading-6 text-[#706961]">
            {resilience.runway_months === null
              ? isExplicit
                ? "of essential expenses covered"
                : "at your recent spending pace"
              : isExplicit
                ? "of essential expenses covered by liquid cash"
                : "covered by liquid cash at your recent spending pace"}
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-sm">
            <span
              className={`inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${status.className}`}
            >
              {resilience.resilience_status === "critical" ? (
                <ShieldAlert className="h-3.5 w-3.5" />
              ) : (
                <ShieldCheck className="h-3.5 w-3.5" />
              )}
              {status.label}
            </span>
            <span aria-hidden="true" className="text-[#8A8178]">
              ·
            </span>
            <span className="font-semibold tabular-nums text-[#181713]">
              {Math.round(resilience.confidence_score)}%
            </span>
            <span className="text-[#706961]">confidence</span>
          </div>

          <div className="mt-3 h-1.5 w-full max-w-xs overflow-hidden rounded-full bg-[#181713]/8">
            <div
              className={`h-full rounded-full ${status.barClassName}`}
              style={{ width: `${barPercent}%` }}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-x-6 gap-y-5 border-t border-[#181713]/8 pt-6 sm:grid-cols-2 lg:w-[38%] lg:shrink-0 lg:grid-cols-2 lg:border-l lg:border-t-0 lg:border-[#181713]/8 lg:pl-8 lg:pt-0">
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
    <div>
      <p className="whitespace-nowrap text-[10px] font-semibold uppercase tracking-[0.12em] text-[#8A8178]">
        {label}
      </p>
      <p className="mt-1 whitespace-nowrap text-base font-semibold tabular-nums text-[#181713]">
        {value}
      </p>
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
    <div className="rounded-2xl border border-[#181713]/8 bg-[#FFFCF7] p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">{horizon.horizon_days}-day coverage</p>
        <p
          className={`text-sm font-semibold ${
            shortfall ? "text-[#923f32]" : "text-[#6E4B63]"
          }`}
        >
          {horizon.coverage_percent}%
        </p>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#181713]/8">
        <div
          className={`h-full rounded-full ${
            shortfall ? "bg-[#c0604c]" : "bg-[#6E4B63]"
          }`}
          style={{ width: `${Math.min(horizon.coverage_percent, 100)}%` }}
        />
      </div>
      <p className={shortfall ? "mt-2 text-sm font-semibold text-[#923f32]" : "mt-2 text-sm font-medium text-[#706961]"}>
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
        <p className="text-sm font-semibold text-[#181713]">
          {factor.label}
        </p>
        <p className="mt-1 text-xs leading-5 text-[#8A8178]">
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
      className="grid w-full gap-4 px-5 py-4 text-left xl:grid-cols-[minmax(220px,1.4fr)_160px_150px_150px_40px] xl:items-center"
    >
      <div className="flex min-w-0 items-center gap-3">
        <MerchantAvatar merchant={item.merchant} />

        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">
            {item.merchant}
          </p>
          <p className="mt-1 text-xs text-[#8A8178]">
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
            ? "bg-[#edf5ee] text-[#6E4B63]"
            : item.confidence_score >= 75
              ? "bg-[#f7e8b5] text-[#8b6518]"
              : "bg-[#f8ddd5] text-[#923f32]"
        }`}
      >
        {item.confidence_score}% confidence
      </span>

      <ChevronRight className="h-4 w-4 text-[#8A8178]" />
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

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

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
        className="absolute inset-0 bg-[#181713]/35 backdrop-blur-[2px]"
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
        <header className="flex items-start justify-between border-b border-[#181713]/10 px-6 py-5">
          <div className="flex min-w-0 items-center gap-3 pr-4">
            <MerchantAvatar merchant={item.merchant} />

            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
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
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[#181713]/10 bg-white"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          <p className="text-sm text-[#777168]">
            Predicted amount
          </p>
          <p className="mt-2 text-4xl font-semibold tracking-[-0.05em] text-[#a64b3d]">
            {formatCents(-item.amount_cents)}
          </p>

          <dl className="mt-7 divide-y divide-[#181713]/10 border-y border-[#181713]/10">
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
              <Sparkles className="mt-0.5 h-5 w-5 shrink-0 text-[#6E4B63]" />
              <div>
                <p className="text-sm font-semibold">
                  Forecast explanation
                </p>
                <p className="mt-1 text-sm leading-6 text-[#706961]">
                  This charge is projected from recurring transaction
                  timing and historical amount consistency.
                </p>
              </div>
            </div>
          </div>

          <div className="mt-5 flex items-center gap-3 rounded-2xl border border-[#181713]/10 bg-white p-4">
            <CalendarClock className="h-5 w-5 text-[#777168]" />
            <p className="text-sm text-[#706961]">
              The actual charge date and amount may differ.
            </p>
          </div>

          <div className="mt-5 flex items-center gap-3 rounded-2xl border border-[#181713]/10 bg-white p-4">
            <CircleDollarSign className="h-5 w-5 text-[#777168]" />
            <p className="text-sm text-[#706961]">
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
      <dt className="text-xs font-semibold uppercase tracking-[0.1em] text-[#8A8178]">
        {label}
      </dt>
      <dd className="text-sm font-medium sm:text-right">{value}</dd>
    </div>
  );
}
