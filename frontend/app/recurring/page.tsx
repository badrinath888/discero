"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  AlertTriangle,
  CalendarClock,
  ChevronRight,
  Clock3,
  Search,
  Sparkles,
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
  formatCents,
  RecurringPayment,
  session,
} from "../lib/api";

type Filter = "all" | "upcoming" | "alerts";

function monthlyEquivalent(payment: RecurringPayment): number {
  const multipliers: Record<string, number> = {
    Weekly: 52 / 12,
    Biweekly: 26 / 12,
    Monthly: 1,
  };

  return Math.round(
    payment.amount_cents * (multipliers[payment.frequency] ?? 1)
  );
}

function dueLabel(days: number): string {
  if (days === 0) return "Due today";
  if (days > 0) return `Due in ${days} days`;
  return "Past due";
}

export default function RecurringPage() {
  const router = useRouter();
  const [userId, setUserId] = useState<number | null>(null);
  const [payments, setPayments] = useState<RecurringPayment[]>([]);
  const [activePayment, setActivePayment] =
    useState<RecurringPayment | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadPayments = useCallback(async (id: number) => {
    setLoading(true);
    setError("");

    try {
      setPayments(await api.getRecurringPayments(id));
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to load recurring payments"
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
        await loadPayments(id);
      } catch {
        session.clear();
        router.replace("/");
      }
    }

    void initialize();
  }, [router, loadPayments]);

  const summary = useMemo(
    () =>
      payments.reduce(
        (result, payment) => ({
          monthly: result.monthly + monthlyEquivalent(payment),
          upcoming:
            result.upcoming +
            (payment.days_until_due >= 0 &&
            payment.days_until_due <= 30
              ? payment.amount_cents
              : 0),
          warnings:
            result.warnings +
            (payment.price_change_warning ? 1 : 0),
        }),
        { monthly: 0, upcoming: 0, warnings: 0 }
      ),
    [payments]
  );

  const filteredPayments = useMemo(() => {
    const query = search.trim().toLowerCase();

    return payments.filter((payment) => {
      const matchesSearch =
        payment.merchant.toLowerCase().includes(query) ||
        payment.frequency.toLowerCase().includes(query);

      const matchesFilter =
        filter === "all" ||
        (filter === "upcoming" &&
          payment.days_until_due >= 0 &&
          payment.days_until_due <= 30) ||
        (filter === "alerts" && payment.price_change_warning);

      return matchesSearch && matchesFilter;
    });
  }, [payments, search, filter]);

  const upcomingPayments = useMemo(
    () =>
      payments
        .filter((payment) => payment.days_until_due >= 0)
        .sort((a, b) => a.days_until_due - b.days_until_due)
        .slice(0, 4),
    [payments]
  );

  return (
    <main className="min-h-screen bg-[#f5f1e8] text-[#14241e]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[1500px]">
          <Reveal>
            <header className="flex flex-col gap-6 border-b border-[#14241e]/10 pb-7 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
                  Subscription intelligence
                </p>

                <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
                  Recurring
                </h1>

                <p className="mt-3 max-w-2xl text-sm leading-6 text-[#66746e]">
                  Understand what repeats, what is due next, and where
                  recurring costs may be changing.
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
                    ? () => void loadPayments(userId)
                    : undefined
                }
              />
            </div>
          )}

          {loading ? (
            <section className="mt-8">
              <CardSkeleton count={3} />
            </section>
          ) : payments.length === 0 ? (
            <div className="mt-8">
              <EmptyState
                title="No recurring bills detected"
                description="Add more transaction history or synchronize your bank account so FinSight can identify repeating payments."
                actionLabel="View transactions"
                onAction={() => router.push("/transactions")}
              />
            </div>
          ) : (
            <>
              <Reveal delay={0.06}>
                <section className="mt-6 grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
                  <article className="premium-hover relative overflow-hidden rounded-[30px] bg-[#14241e] p-7 text-white shadow-[0_24px_70px_rgba(20,36,30,0.18)] sm:p-9">
                    <div className="pointer-events-none absolute -right-16 -top-16 h-52 w-52 rounded-full bg-[#76dfbd]/15 blur-3xl" />

                    <div className="relative">
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#83dcb9]">
                        Monthly recurring load
                      </p>

                      <AnimatedNumber
                        value={summary.monthly}
                        format={(value) => formatCents(-value)}
                        className="mt-4 block text-5xl font-semibold tracking-[-0.06em] sm:text-6xl"
                      />

                      <p className="mt-3 text-sm text-white/55">
                        Estimated monthly cost based on detected billing
                        frequencies.
                      </p>

                      <div className="mt-10 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-3">
                        <RecurringMetric
                          label="Detected"
                          value={String(payments.length)}
                          tone="neutral"
                        />
                        <RecurringMetric
                          label="Due in 30 days"
                          value={formatCents(-summary.upcoming)}
                          tone="warning"
                        />
                        <RecurringMetric
                          label="Price alerts"
                          value={String(summary.warnings)}
                          tone={
                            summary.warnings > 0
                              ? "warning"
                              : "positive"
                          }
                        />
                      </div>
                    </div>
                  </article>

                  <article className="premium-hover rounded-[30px] bg-[#f7e8b5] p-7 sm:p-8">
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#8b6518]">
                          Next charges
                        </p>
                        <p className="mt-4 text-3xl font-semibold tracking-[-0.04em]">
                          Upcoming timeline
                        </p>
                      </div>

                      <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#14241e] text-[#f7e8b5]">
                        <CalendarClock className="h-5 w-5" />
                      </span>
                    </div>

                    <div className="mt-6 space-y-4">
                      {upcomingPayments.map((payment) => (
                        <div
                          key={`${payment.merchant}-${payment.last_payment}`}
                          className="flex items-center justify-between gap-4 border-b border-[#14241e]/10 pb-4 last:border-b-0 last:pb-0"
                        >
                          <div className="min-w-0">
                            <p className="truncate text-sm font-semibold">
                              {payment.merchant}
                            </p>
                            <p className="mt-1 text-xs text-[#6b5d39]">
                              {dueLabel(payment.days_until_due)}
                            </p>
                          </div>

                          <p className="shrink-0 text-sm font-semibold text-[#a64b3d]">
                            {formatCents(-payment.amount_cents)}
                          </p>
                        </div>
                      ))}
                    </div>
                  </article>
                </section>
              </Reveal>

              <Reveal>
                <section className="mt-8">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
                        Detected patterns
                      </p>
                      <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
                        Recurring payments
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
                          placeholder="Search merchant or frequency"
                          className="h-11 w-full rounded-xl border border-[#14241e]/10 bg-white pl-10 pr-4 text-sm outline-none focus:border-[#167c5a]"
                        />
                      </label>

                      <div className="flex h-11 items-center rounded-xl border border-[#14241e]/10 bg-white p-1">
                        {(
                          [
                            ["all", "All"],
                            ["upcoming", "Upcoming"],
                            ["alerts", "Alerts"],
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
                    <header className="hidden border-b border-[#14241e]/10 bg-[#faf8f3] px-5 py-4 text-xs font-semibold uppercase tracking-[0.12em] text-[#7a8780] md:grid md:grid-cols-[minmax(220px,1.4fr)_130px_150px_150px_130px_40px] md:items-center">
                      <span>Merchant</span>
                      <span>Frequency</span>
                      <span>Typical payment</span>
                      <span>Next charge</span>
                      <span>Health</span>
                      <span />
                    </header>

                    <div className="divide-y divide-[#14241e]/8">
                      {filteredPayments.map((payment) => (
                        <RecurringRow
                          key={`${payment.merchant}-${payment.last_payment}`}
                          payment={payment}
                          onOpen={() => setActivePayment(payment)}
                        />
                      ))}
                    </div>

                    {filteredPayments.length === 0 && (
                      <div className="px-6 py-12 text-center">
                        <p className="text-sm font-semibold">
                          No recurring payments match
                        </p>
                        <p className="mt-2 text-sm text-[#7b8781]">
                          Adjust the search or filter to see more results.
                        </p>
                      </div>
                    )}
                  </div>
                </section>
              </Reveal>

              <p className="mt-6 text-xs leading-5 text-[#7b8781]">
                Recurring payments are inferred from transaction timing
                and amount consistency. Predictions may not match future
                charges exactly.
              </p>
            </>
          )}
        </PageReveal>
      </div>

      <AnimatePresence>
        {activePayment && (
          <RecurringDrawer
            payment={activePayment}
            onClose={() => setActivePayment(null)}
          />
        )}
      </AnimatePresence>
    </main>
  );
}

function RecurringMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "positive" | "warning" | "neutral";
}) {
  const className = {
    positive: "text-[#83dcb9]",
    warning: "text-[#f4c978]",
    neutral: "text-white",
  };

  return (
    <div className="bg-white/[0.045] p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/35">
        {label}
      </p>
      <p className={`mt-2 text-lg font-semibold ${className[tone]}`}>
        {value}
      </p>
    </div>
  );
}

function RecurringRow({
  payment,
  onOpen,
}: {
  payment: RecurringPayment;
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
      className="grid w-full gap-4 px-5 py-4 text-left md:grid-cols-[minmax(220px,1.4fr)_130px_150px_150px_130px_40px] md:items-center"
    >
      <div className="flex min-w-0 items-center gap-3">
        <MerchantAvatar merchant={payment.merchant} />

        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">
            {payment.merchant}
          </p>
          <p className="mt-1 text-xs text-[#87928d]">
            {payment.occurrences} detected payments
          </p>
        </div>
      </div>

      <p className="text-sm font-medium">{payment.frequency}</p>

      <p className="text-sm font-semibold text-[#a64b3d]">
        {formatCents(-payment.amount_cents)}
      </p>

      <div>
        <p className="text-sm font-medium">
          {dueLabel(payment.days_until_due)}
        </p>
        <p className="mt-1 text-xs text-[#87928d]">
          {payment.days_until_due >= 0
            ? "Estimated"
            : "Review timing"}
        </p>
      </div>

      <span
        className={`w-fit rounded-full px-3 py-1.5 text-xs font-semibold ${
          payment.price_change_warning
            ? "bg-[#f8ddd5] text-[#923f32]"
            : "bg-[#edf5ee] text-[#167c5a]"
        }`}
      >
        {payment.price_change_warning
          ? "Price changed"
          : `${payment.confidence_score}% confidence`}
      </span>

      <ChevronRight className="h-4 w-4 text-[#87928d]" />
    </motion.button>
  );
}

function RecurringDrawer({
  payment,
  onClose,
}: {
  payment: RecurringPayment;
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
        aria-label="Close recurring payment details"
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
            <MerchantAvatar merchant={payment.merchant} />

            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#167c5a]">
                Recurring payment
              </p>
              <h2 className="mt-1 truncate text-xl font-semibold">
                {payment.merchant}
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
            Typical payment
          </p>
          <p className="mt-2 text-4xl font-semibold tracking-[-0.05em] text-[#a64b3d]">
            {formatCents(-payment.amount_cents)}
          </p>

          {payment.price_change_warning && (
            <div className="mt-5 flex gap-3 rounded-2xl border border-[#c56755]/20 bg-[#f8ddd5] p-4">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-[#923f32]" />
              <div>
                <p className="text-sm font-semibold text-[#923f32]">
                  Price change detected
                </p>
                <p className="mt-1 text-sm leading-6 text-[#7b4d45]">
                  Recent charges differ meaningfully from the earlier
                  payment pattern.
                </p>
              </div>
            </div>
          )}

          <dl className="mt-7 divide-y divide-[#14241e]/10 border-y border-[#14241e]/10">
            <DrawerDetail
              label="Frequency"
              value={payment.frequency}
            />
            <DrawerDetail
              label="Next charge"
              value={dueLabel(payment.days_until_due)}
            />
            <DrawerDetail
              label="Monthly equivalent"
              value={formatCents(-monthlyEquivalent(payment))}
            />
            <DrawerDetail
              label="Occurrences"
              value={String(payment.occurrences)}
            />
            <DrawerDetail
              label="Confidence"
              value={`${payment.confidence_score}%`}
            />
            <DrawerDetail
              label="Last paid"
              value={new Date(
                `${payment.last_payment}T00:00:00`
              ).toLocaleDateString("en-US", {
                month: "long",
                day: "numeric",
                year: "numeric",
              })}
            />
          </dl>

          <div className="mt-7 rounded-2xl bg-[#edf5ee] p-5">
            <div className="flex gap-3">
              <Sparkles className="mt-0.5 h-5 w-5 shrink-0 text-[#167c5a]" />
              <div>
                <p className="text-sm font-semibold">
                  Detection insight
                </p>
                <p className="mt-1 text-sm leading-6 text-[#66746e]">
                  FinSight identified this pattern from repeated timing
                  and similar transaction amounts.
                </p>
              </div>
            </div>
          </div>

          <div className="mt-5 flex items-center gap-3 rounded-2xl border border-[#14241e]/10 bg-white p-4">
            <Clock3 className="h-5 w-5 text-[#728078]" />
            <p className="text-sm text-[#66746e]">
              Future timing and amounts remain estimates.
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
