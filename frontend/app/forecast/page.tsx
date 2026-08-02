"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  AlertTriangle,
  CalendarClock,
  ChevronRight,
  CircleDollarSign,
  Gauge,
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
import {
  api,
  CashFlowForecast,
  formatCents,
  session,
} from "../lib/api";

type ForecastItem = CashFlowForecast["upcoming_cash_flows"][number];

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function confidenceLabel(score: number): string {
  if (score >= 90) return "High confidence";
  if (score >= 75) return "Moderate confidence";
  return "Low confidence";
}

export default function ForecastPage() {
  const router = useRouter();
  const [userId, setUserId] = useState<number | null>(null);
  const [forecast, setForecast] = useState<CashFlowForecast | null>(null);
  const [activeItem, setActiveItem] = useState<ForecastItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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
        await loadForecast(id);
      } catch {
        session.clear();
        router.replace("/");
      }
    }

    void initialize();
  }, [router, loadForecast]);

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
          ) : (
            <div className="mt-8">
              <EmptyState
                title="Forecast unavailable"
                description="Connect an account and add more transaction history to generate a cash-flow projection."
                actionLabel="View accounts"
                onAction={() => router.push("/accounts")}
              />
            </div>
          )}
        </PageReveal>
      </div>

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
              <h2 className="mt-1 truncate text-xl font-semibold">
                {item.merchant}
              </h2>
            </div>
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
