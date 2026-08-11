"use client";

import {
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  AlertTriangle,
  CalendarClock,
  Check,
  ChevronRight,
  Clock3,
  Copy,
  HelpCircle,
  Pause,
  Play,
  Search,
  Sparkles,
  Trash2,
  TrendingUp,
  X,
  XCircle,
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
  RecurringIntelligence,
  RecurringItem,
  RecurringItemStatus,
  RecurringPayment,
  SpendingAnomaly,
  SpendingAnomalies,
  session,
} from "../lib/api";

type Filter = "all" | "upcoming" | "alerts";
type DrawerSelection =
  | { kind: "detected"; payment: RecurringPayment }
  | { kind: "saved"; item: RecurringItem };

const FREQUENCY_MULTIPLIERS: Record<string, number> = {
  Weekly: 52 / 12,
  Biweekly: 26 / 12,
  Monthly: 1,
};

function monthlyEquivalent(
  payment: Pick<RecurringPayment, "amount_cents" | "frequency">
): number {
  return Math.round(
    payment.amount_cents *
      (FREQUENCY_MULTIPLIERS[payment.frequency] ?? 1)
  );
}

function daysUntil(dateValue: string): number {
  const today = new Date();
  const target = new Date(`${dateValue}T00:00:00`);
  const start = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate()
  );

  return Math.round(
    (target.getTime() - start.getTime()) / 86_400_000
  );
}

function dueLabel(days: number): string {
  if (days === 0) return "Due today";
  if (days > 0) return `Due in ${days} days`;
  return "Past due";
}

function normalizeMerchant(value: string): string {
  return value
    .toUpperCase()
    .replace(/\d+/g, "")
    .replace(/[^A-Z ]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function statusLabel(status: RecurringItemStatus): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export default function RecurringPage() {
  const router = useRouter();
  const [userId, setUserId] = useState<number | null>(null);
  const [payments, setPayments] = useState<RecurringPayment[]>([]);
  const [items, setItems] = useState<RecurringItem[]>([]);
  const [selection, setSelection] =
    useState<DrawerSelection | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  const [intelligence, setIntelligence] =
    useState<RecurringIntelligence | null>(null);
  const [anomalies, setAnomalies] = useState<SpendingAnomalies | null>(
    null
  );
  const [insightsLoading, setInsightsLoading] = useState(true);
  const [insightsError, setInsightsError] = useState("");

  const loadData = useCallback(async (id: number) => {
    setLoading(true);
    setError("");

    try {
      const [detected, saved] = await Promise.all([
        api.getRecurringPayments(id),
        api.getRecurringItems(id),
      ]);

      setPayments(detected);
      setItems(saved);
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

  const loadInsights = useCallback(async (id: number) => {
    setInsightsLoading(true);
    setInsightsError("");

    try {
      const [recurringIntelligence, spendingAnomalies] = await Promise.all([
        api.getRecurringIntelligence(id),
        api.getSpendingAnomalies(id),
      ]);

      setIntelligence(recurringIntelligence);
      setAnomalies(spendingAnomalies);
    } catch (err) {
      setInsightsError(
        err instanceof Error
          ? err.message
          : "Unable to load recurring intelligence and spending anomalies"
      );
    } finally {
      setInsightsLoading(false);
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
        await loadData(id);
        void loadInsights(id);
      } catch {
        session.clear();
        router.replace("/");
      }
    }

    void initialize();
  }, [router, loadData, loadInsights]);

  const savedByMerchant = useMemo(
    () =>
      new Map(
        items.map((item) => [item.normalized_merchant, item])
      ),
    [items]
  );

  const visibleDetected = useMemo(
    () =>
      payments.filter(
        (payment) =>
          !savedByMerchant.has(normalizeMerchant(payment.merchant))
      ),
    [payments, savedByMerchant]
  );

  const managedItems = useMemo(
    () => items.filter((item) => item.status !== "dismissed"),
    [items]
  );

  const activeItems = useMemo(
    () =>
      managedItems.filter(
        (item) =>
          item.status === "active" ||
          item.status === "suggested"
      ),
    [managedItems]
  );

  const summary = useMemo(
    () =>
      activeItems.reduce(
        (result, item) => {
          const days = daysUntil(item.next_payment);

          return {
            monthly:
              result.monthly + monthlyEquivalent(item),
            upcoming:
              result.upcoming +
              (days >= 0 && days <= 30
                ? item.amount_cents
                : 0),
            warnings:
              result.warnings +
              (item.price_change_warning ? 1 : 0),
          };
        },
        { monthly: 0, upcoming: 0, warnings: 0 }
      ),
    [activeItems]
  );

  const filteredItems = useMemo(() => {
    const query = search.trim().toLowerCase();

    return managedItems.filter((item) => {
      const days = daysUntil(item.next_payment);
      const matchesSearch =
        item.merchant.toLowerCase().includes(query) ||
        item.frequency.toLowerCase().includes(query) ||
        item.status.toLowerCase().includes(query);

      const matchesFilter =
        filter === "all" ||
        (filter === "upcoming" && days >= 0 && days <= 30) ||
        (filter === "alerts" && item.price_change_warning);

      return matchesSearch && matchesFilter;
    });
  }, [managedItems, search, filter]);

  const upcomingItems = useMemo(
    () =>
      activeItems
        .map((item) => ({
          item,
          days: daysUntil(item.next_payment),
        }))
        .filter(({ days }) => days >= 0)
        .sort((a, b) => a.days - b.days)
        .slice(0, 4),
    [activeItems]
  );

  async function saveDetected(
    payment: RecurringPayment,
    status: "active" | "dismissed"
  ) {
    if (!userId) return;

    setWorking(true);
    setError("");

    try {
      const created = await api.createRecurringItem(userId, {
        merchant: payment.merchant,
        normalized_merchant: normalizeMerchant(payment.merchant),
        category: "Subscriptions",
        amount_cents: payment.amount_cents,
        frequency: payment.frequency as
          | "Weekly"
          | "Biweekly"
          | "Monthly",
        last_payment: payment.last_payment,
        next_payment: payment.next_payment,
        status,
        confidence_score: payment.confidence_score,
        price_change_percent: payment.price_change_percent,
        price_change_warning: payment.price_change_warning,
      });

      setItems((current) => [...current, created]);
      setSelection(null);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to save recurring item"
      );
    } finally {
      setWorking(false);
    }
  }

  async function updateStatus(
    item: RecurringItem,
    status: RecurringItemStatus
  ) {
    if (!userId) return;

    setWorking(true);
    setError("");

    try {
      const updated = await api.updateRecurringItem(
        userId,
        item.id,
        { status }
      );

      setItems((current) =>
        current.map((entry) =>
          entry.id === updated.id ? updated : entry
        )
      );
      setSelection({ kind: "saved", item: updated });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to update recurring item"
      );
    } finally {
      setWorking(false);
    }
  }

  async function deleteItem(item: RecurringItem) {
    if (!userId) return;
    if (!window.confirm(`Delete ${item.merchant}?`)) return;

    setWorking(true);
    setError("");

    try {
      await api.deleteRecurringItem(userId, item.id);
      setItems((current) =>
        current.filter((entry) => entry.id !== item.id)
      );
      setSelection(null);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to delete recurring item"
      );
    } finally {
      setWorking(false);
    }
  }

  const hasContent =
    managedItems.length > 0 || visibleDetected.length > 0;

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
                  Confirm detected patterns, manage active bills, and
                  stay ahead of upcoming charges.
                </p>
              </div>
            </header>
          </Reveal>

          {error && (
            <div className="mt-5">
              <PageError
                message={error}
                onRetry={
                  userId ? () => void loadData(userId) : undefined
                }
              />
            </div>
          )}

          {loading ? (
            <section className="mt-8">
              <CardSkeleton count={3} />
            </section>
          ) : !hasContent ? (
            error ? null : (
            <div className="mt-8">
              <EmptyState
                title="No recurring bills detected"
                description="Add more transaction history or synchronize your bank account so Discero can identify repeating payments."
                actionLabel="View transactions"
                onAction={() => router.push("/transactions")}
              />
            </div>
            )
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
                        Estimated from active and confirmed recurring
                        payments.
                      </p>

                      <div className="mt-10 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-3">
                        <RecurringMetric
                          label="Managed"
                          value={String(managedItems.length)}
                          tone="neutral"
                        />
                        <RecurringMetric
                          label="Due in 30 days"
                          value={formatCents(-summary.upcoming)}
                          tone="warning"
                        />
                        <RecurringMetric
                          label="Suggestions"
                          value={String(visibleDetected.length)}
                          tone={
                            visibleDetected.length > 0
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
                      {upcomingItems.length === 0 ? (
                        <p className="text-sm text-[#6b5d39]">
                          No active charges are currently scheduled.
                        </p>
                      ) : (
                        upcomingItems.map(({ item, days }) => (
                          <div
                            key={item.id}
                            className="flex items-center justify-between gap-4 border-b border-[#14241e]/10 pb-4 last:border-b-0 last:pb-0"
                          >
                            <div className="min-w-0">
                              <p className="truncate text-sm font-semibold">
                                {item.merchant}
                              </p>
                              <p className="mt-1 text-xs text-[#6b5d39]">
                                {dueLabel(days)}
                              </p>
                            </div>
                            <p className="shrink-0 text-sm font-semibold text-[#a64b3d]">
                              {formatCents(-item.amount_cents)}
                            </p>
                          </div>
                        ))
                      )}
                    </div>
                  </article>
                </section>
              </Reveal>

              <Reveal delay={0.08}>
                <RecurringIntelligenceSection
                  intelligence={intelligence}
                  loading={insightsLoading}
                  error={insightsError}
                  onRetry={
                    userId ? () => void loadInsights(userId) : undefined
                  }
                />
              </Reveal>

              <Reveal delay={0.1}>
                <SpendingAnomaliesSection
                  anomalies={anomalies}
                  loading={insightsLoading}
                  error={insightsError}
                  onRetry={
                    userId ? () => void loadInsights(userId) : undefined
                  }
                />
              </Reveal>

              {visibleDetected.length > 0 && (
                <Reveal>
                  <section className="mt-8">
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
                      Needs review
                    </p>
                    <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
                      Detected suggestions
                    </h2>

                    <div className="mt-5 grid gap-4 lg:grid-cols-2">
                      {visibleDetected.map((payment) => (
                        <article
                          key={`${payment.merchant}-${payment.last_payment}`}
                          className="rounded-[24px] border border-[#14241e]/10 bg-white p-5"
                        >
                          <div className="flex items-start gap-3">
                            <MerchantAvatar merchant={payment.merchant} />
                            <div className="min-w-0 flex-1">
                              <p className="truncate font-semibold">
                                {payment.merchant}
                              </p>
                              <p className="mt-1 text-xs text-[#7b8781]">
                                {payment.frequency} ·{" "}
                                {payment.confidence_score}% confidence
                              </p>
                            </div>
                            <p className="font-semibold text-[#a64b3d]">
                              {formatCents(-payment.amount_cents)}
                            </p>
                          </div>

                          <div className="mt-5 flex flex-wrap gap-2">
                            <button
                              type="button"
                              disabled={working}
                              onClick={() =>
                                void saveDetected(payment, "active")
                              }
                              className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#167c5a] px-4 text-sm font-semibold text-white disabled:opacity-50"
                            >
                              <Check className="h-4 w-4" />
                              Confirm
                            </button>
                            <button
                              type="button"
                              disabled={working}
                              onClick={() =>
                                void saveDetected(payment, "dismissed")
                              }
                              className="inline-flex h-10 items-center gap-2 rounded-xl border border-[#14241e]/10 px-4 text-sm font-semibold disabled:opacity-50"
                            >
                              <XCircle className="h-4 w-4" />
                              Dismiss
                            </button>
                            <button
                              type="button"
                              onClick={() =>
                                setSelection({
                                  kind: "detected",
                                  payment,
                                })
                              }
                              className="ml-auto h-10 rounded-xl px-3 text-sm font-semibold text-[#167c5a]"
                            >
                              Details
                            </button>
                          </div>
                        </article>
                      ))}
                    </div>
                  </section>
                </Reveal>
              )}

              {managedItems.length > 0 && (
                <Reveal>
                  <section className="mt-8">
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
                          Managed patterns
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
                            aria-label="Search recurring payments"
                            placeholder="Search merchant, frequency, or status"
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
                        <span>Payment</span>
                        <span>Next charge</span>
                        <span>Status</span>
                        <span />
                      </header>

                      <div className="divide-y divide-[#14241e]/8">
                        {filteredItems.map((item) => (
                          <RecurringItemRow
                            key={item.id}
                            item={item}
                            onOpen={() =>
                              setSelection({ kind: "saved", item })
                            }
                          />
                        ))}
                      </div>

                      {filteredItems.length === 0 && (
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
              )}

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
        {selection && (
          <RecurringDrawer
            selection={selection}
            working={working}
            onClose={() => setSelection(null)}
            onConfirm={(payment) =>
              void saveDetected(payment, "active")
            }
            onDismiss={(payment) =>
              void saveDetected(payment, "dismissed")
            }
            onStatusChange={(item, status) =>
              void updateStatus(item, status)
            }
            onDelete={(item) => void deleteItem(item)}
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

function RecurringItemRow({
  item,
  onOpen,
}: {
  item: RecurringItem;
  onOpen: () => void;
}) {
  const reduceMotion = useReducedMotion();
  const days = daysUntil(item.next_payment);

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
        <MerchantAvatar merchant={item.merchant} />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">
            {item.merchant}
          </p>
          <p className="mt-1 text-xs text-[#87928d]">
            {item.category ?? "Uncategorized"}
          </p>
        </div>
      </div>

      <p className="text-sm font-medium">{item.frequency}</p>
      <p className="text-sm font-semibold text-[#a64b3d]">
        {formatCents(-item.amount_cents)}
      </p>

      <div>
        <p className="text-sm font-medium">{dueLabel(days)}</p>
        <p className="mt-1 text-xs text-[#87928d]">
          {new Date(
            `${item.next_payment}T00:00:00`
          ).toLocaleDateString("en-US")}
        </p>
      </div>

      <span
        className={`w-fit rounded-full px-3 py-1.5 text-xs font-semibold ${
          item.status === "active"
            ? "bg-[#edf5ee] text-[#167c5a]"
            : item.status === "paused"
              ? "bg-[#f7e8b5] text-[#8b6518]"
              : item.status === "cancelled"
                ? "bg-[#f8ddd5] text-[#923f32]"
                : "bg-[#eef0ef] text-[#66746e]"
        }`}
      >
        {statusLabel(item.status)}
      </span>

      <ChevronRight className="h-4 w-4 text-[#87928d]" />
    </motion.button>
  );
}

function RecurringDrawer({
  selection,
  working,
  onClose,
  onConfirm,
  onDismiss,
  onStatusChange,
  onDelete,
}: {
  selection: DrawerSelection;
  working: boolean;
  onClose: () => void;
  onConfirm: (payment: RecurringPayment) => void;
  onDismiss: (payment: RecurringPayment) => void;
  onStatusChange: (
    item: RecurringItem,
    status: RecurringItemStatus
  ) => void;
  onDelete: (item: RecurringItem) => void;
}) {
  const reduceMotion = useReducedMotion();
  const payment =
    selection.kind === "detected"
      ? selection.payment
      : selection.item;
  const days =
    selection.kind === "detected"
      ? selection.payment.days_until_due
      : daysUntil(selection.item.next_payment);

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
      />

      <motion.aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="recurring-drawer-title"
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
                {selection.kind === "detected"
                  ? "Detected suggestion"
                  : "Managed recurring payment"}
              </p>
              <h2
                id="recurring-drawer-title"
                className="mt-1 truncate text-xl font-semibold"
              >
                {payment.merchant}
              </h2>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close recurring payment details"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[#14241e]/10 bg-white"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          <p className="text-sm text-[#728078]">Typical payment</p>
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
              value={dueLabel(days)}
            />
            <DrawerDetail
              label="Monthly equivalent"
              value={formatCents(-monthlyEquivalent(payment))}
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
            {selection.kind === "saved" && (
              <DrawerDetail
                label="Status"
                value={statusLabel(selection.item.status)}
              />
            )}
          </dl>

          <div className="mt-7 rounded-2xl bg-[#edf5ee] p-5">
            <div className="flex gap-3">
              <Sparkles className="mt-0.5 h-5 w-5 shrink-0 text-[#167c5a]" />
              <div>
                <p className="text-sm font-semibold">
                  Detection insight
                </p>
                <p className="mt-1 text-sm leading-6 text-[#66746e]">
                  Discero identified this pattern from repeated timing
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

        <footer className="border-t border-[#14241e]/10 bg-white px-6 py-5">
          {selection.kind === "detected" ? (
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                disabled={working}
                onClick={() => onConfirm(selection.payment)}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-[#167c5a] text-sm font-semibold text-white disabled:opacity-50"
              >
                <Check className="h-4 w-4" />
                Confirm
              </button>
              <button
                type="button"
                disabled={working}
                onClick={() => onDismiss(selection.payment)}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-xl border border-[#14241e]/10 text-sm font-semibold disabled:opacity-50"
              >
                <XCircle className="h-4 w-4" />
                Dismiss
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                {selection.item.status === "active" ? (
                  <button
                    type="button"
                    disabled={working}
                    onClick={() =>
                      onStatusChange(selection.item, "paused")
                    }
                    className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-[#f7e8b5] text-sm font-semibold text-[#8b6518] disabled:opacity-50"
                  >
                    <Pause className="h-4 w-4" />
                    Pause
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={working}
                    onClick={() =>
                      onStatusChange(selection.item, "active")
                    }
                    className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-[#167c5a] text-sm font-semibold text-white disabled:opacity-50"
                  >
                    <Play className="h-4 w-4" />
                    Activate
                  </button>
                )}

                <button
                  type="button"
                  disabled={working}
                  onClick={() =>
                    onStatusChange(selection.item, "cancelled")
                  }
                  className="inline-flex h-11 items-center justify-center gap-2 rounded-xl border border-[#c56755]/20 text-sm font-semibold text-[#923f32] disabled:opacity-50"
                >
                  <XCircle className="h-4 w-4" />
                  Cancel
                </button>
              </div>

              <button
                type="button"
                disabled={working}
                onClick={() => onDelete(selection.item)}
                className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl border border-[#14241e]/10 text-sm font-semibold text-[#66746e] disabled:opacity-50"
              >
                <Trash2 className="h-4 w-4" />
                Delete permanently
              </button>
            </div>
          )}
        </footer>
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
function InsightsSkeleton() {
  return (
    <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: 4 }).map((_, index) => (
        <div
          key={index}
          className="h-32 animate-pulse rounded-[24px] border border-[#14241e]/10 bg-white"
        />
      ))}
    </div>
  );
}

function SignalCard({
  icon,
  label,
  tone,
  children,
}: {
  icon: ReactNode;
  label: string;
  tone: "warning" | "neutral" | "positive";
  children: ReactNode;
}) {
  const toneClass = {
    warning: "bg-[#f7e8b5] text-[#8b6518]",
    neutral: "bg-[#eef0ef] text-[#66746e]",
    positive: "bg-[#edf5ee] text-[#167c5a]",
  }[tone];

  return (
    <article className="rounded-[24px] border border-[#14241e]/10 bg-white p-5">
      <div className="flex items-center gap-3">
        <span
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${toneClass}`}
        >
          {icon}
        </span>
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#7a8780]">
          {label}
        </p>
      </div>
      <div className="mt-4">{children}</div>
    </article>
  );
}

function RecurringIntelligenceSection({
  intelligence,
  loading,
  error,
  onRetry,
}: {
  intelligence: RecurringIntelligence | null;
  loading: boolean;
  error: string;
  onRetry?: () => void;
}) {
  if (loading) {
    return (
      <section className="mt-8">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
          Recurring intelligence
        </p>
        <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
          What&apos;s changed
        </h2>
        <InsightsSkeleton />
      </section>
    );
  }

  if (error) {
    return (
      <section className="mt-8">
        <PageError message={error} onRetry={onRetry} />
      </section>
    );
  }

  if (!intelligence) return null;

  const { burden } = intelligence;
  const increased = intelligence.amount_changes.filter(
    (change) => change.status === "increased"
  );
  const changesDetected =
    intelligence.amount_changes.length +
    intelligence.new_recurring.length +
    intelligence.possibly_missing.length +
    intelligence.possible_duplicates.length;

  return (
    <section className="mt-8">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
        Recurring intelligence
      </p>
      <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
        What&apos;s changed
      </h2>

      {burden.active_recurring_count === 0 ? (
        <p className="mt-4 text-sm text-[#66746e]">
          {intelligence.data_quality_note ??
            "No active recurring items yet -- confirm a detected suggestion below to start tracking intelligence on it."}
        </p>
      ) : (
        <>
          <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-[24px] border border-[#14241e]/10 bg-white p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#7a8780]">
                Monthly burden
              </p>
              <p className="mt-3 text-2xl font-semibold tracking-[-0.03em]">
                {formatCents(-burden.monthly_recurring_cents)}
              </p>
              {burden.percent_of_income !== null && (
                <p className="mt-1 text-xs text-[#87928d]">
                  {burden.percent_of_income.toFixed(0)}% of average income
                </p>
              )}
            </div>
            <div className="rounded-[24px] border border-[#14241e]/10 bg-white p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#7a8780]">
                Active recurring
              </p>
              <p className="mt-3 text-2xl font-semibold tracking-[-0.03em]">
                {burden.active_recurring_count}
              </p>
            </div>
            <div className="rounded-[24px] border border-[#14241e]/10 bg-white p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#7a8780]">
                Next 30 days
              </p>
              <p className="mt-3 text-2xl font-semibold tracking-[-0.03em]">
                {formatCents(-burden.next_30_days_cents)}
              </p>
            </div>
            <div className="rounded-[24px] border border-[#14241e]/10 bg-white p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#7a8780]">
                Changes detected
              </p>
              <p className="mt-3 text-2xl font-semibold tracking-[-0.03em]">
                {changesDetected}
              </p>
            </div>
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <SignalCard
              icon={<TrendingUp className="h-4 w-4" />}
              label="Increased"
              tone={increased.length > 0 ? "warning" : "positive"}
            >
              {increased.length === 0 ? (
                <p className="text-sm text-[#66746e]">
                  No recurring bills have increased recently.
                </p>
              ) : (
                <div>
                  <p className="text-sm font-semibold">
                    {increased[0].merchant}
                  </p>
                  <p className="mt-1 text-xs text-[#a64b3d]">
                    {formatCents(-increased[0].current_amount_cents)}, up{" "}
                    {increased[0].change_percent.toFixed(0)}% from{" "}
                    {formatCents(-increased[0].baseline_amount_cents)}
                  </p>
                  {increased.length > 1 && (
                    <p className="mt-2 text-xs text-[#87928d]">
                      +{increased.length - 1} more
                    </p>
                  )}
                </div>
              )}
            </SignalCard>

            <SignalCard
              icon={<Sparkles className="h-4 w-4" />}
              label="New"
              tone={
                intelligence.new_recurring.length > 0 ? "neutral" : "positive"
              }
            >
              {intelligence.new_recurring.length === 0 ? (
                <p className="text-sm text-[#66746e]">
                  No newly established recurring payments.
                </p>
              ) : (
                <div>
                  <p className="text-sm font-semibold">
                    {intelligence.new_recurring[0].merchant}
                  </p>
                  <p className="mt-1 text-xs text-[#87928d]">
                    {formatCents(
                      -intelligence.new_recurring[0].amount_cents
                    )}{" "}
                    · {intelligence.new_recurring[0].occurrences_seen} seen
                    so far
                  </p>
                  {intelligence.new_recurring.length > 1 && (
                    <p className="mt-2 text-xs text-[#87928d]">
                      +{intelligence.new_recurring.length - 1} more
                    </p>
                  )}
                </div>
              )}
            </SignalCard>

            <SignalCard
              icon={<HelpCircle className="h-4 w-4" />}
              label="Possibly missing"
              tone={
                intelligence.possibly_missing.length > 0
                  ? "warning"
                  : "positive"
              }
            >
              {intelligence.possibly_missing.length === 0 ? (
                <p className="text-sm text-[#66746e]">
                  Every active bill has arrived as expected.
                </p>
              ) : (
                <div>
                  <p className="text-sm font-semibold">
                    {intelligence.possibly_missing[0].merchant}
                  </p>
                  <p className="mt-1 text-xs text-[#8b6518]">
                    {intelligence.possibly_missing[0].days_overdue} days
                    past expected
                  </p>
                  {intelligence.possibly_missing.length > 1 && (
                    <p className="mt-2 text-xs text-[#87928d]">
                      +{intelligence.possibly_missing.length - 1} more
                    </p>
                  )}
                </div>
              )}
            </SignalCard>

            <SignalCard
              icon={<Copy className="h-4 w-4" />}
              label="Possible duplicate"
              tone={
                intelligence.possible_duplicates.length > 0
                  ? "warning"
                  : "positive"
              }
            >
              {intelligence.possible_duplicates.length === 0 ? (
                <p className="text-sm text-[#66746e]">
                  No possible duplicate subscriptions found.
                </p>
              ) : (
                <div>
                  <p className="text-sm font-semibold">
                    {intelligence.possible_duplicates[0].merchant_a} &{" "}
                    {intelligence.possible_duplicates[0].merchant_b}
                  </p>
                  <p className="mt-1 text-xs text-[#87928d]">
                    Similar name, amount, and cadence
                  </p>
                  {intelligence.possible_duplicates.length > 1 && (
                    <p className="mt-2 text-xs text-[#87928d]">
                      +{intelligence.possible_duplicates.length - 1} more
                    </p>
                  )}
                </div>
              )}
            </SignalCard>
          </div>

          {intelligence.possibly_missing.length > 0 && (
            <p className="mt-4 text-xs leading-5 text-[#87928d]">
              Discero has not seen these expected payments yet -- this
              does not necessarily mean a subscription was cancelled.
            </p>
          )}
        </>
      )}
    </section>
  );
}

function anomalySeverityClass(
  severity: SpendingAnomaly["severity"]
): string {
  if (severity === "high") return "bg-[#f8ddd5] text-[#923f32]";
  if (severity === "warning") return "bg-[#f7e8b5] text-[#8b6518]";
  return "bg-[#eef0ef] text-[#66746e]";
}

function anomalySeverityLabel(
  severity: SpendingAnomaly["severity"]
): string {
  if (severity === "high") return "High";
  if (severity === "warning") return "Warning";
  return "Info";
}

function anomalyTypeLabel(type: SpendingAnomaly["type"]): string {
  return {
    merchant_unusual_spend: "Unusual merchant charge",
    category_spike: "Category spike",
    large_transaction: "Large transaction",
    repeated_charge: "Repeated charge",
  }[type];
}

function SpendingAnomaliesSection({
  anomalies,
  loading,
  error,
  onRetry,
}: {
  anomalies: SpendingAnomalies | null;
  loading: boolean;
  error: string;
  onRetry?: () => void;
}) {
  if (loading) {
    return (
      <section className="mt-8">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
          Spending anomalies
        </p>
        <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
          Unusual activity
        </h2>
        <InsightsSkeleton />
      </section>
    );
  }

  if (error) {
    return (
      <section className="mt-8">
        <PageError message={error} onRetry={onRetry} />
      </section>
    );
  }

  if (!anomalies) return null;

  return (
    <section className="mt-8">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
        Spending anomalies
      </p>
      <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
        Unusual activity
      </h2>

      {anomalies.anomalies.length === 0 ? (
        <div className="mt-5 rounded-[24px] border border-dashed border-[#14241e]/15 bg-white px-6 py-10 text-center">
          <p className="text-sm font-semibold text-[#167c5a]">
            No unusual spending patterns detected from the available data.
          </p>
          {anomalies.data_quality_note && (
            <p className="mt-2 text-xs text-[#87928d]">
              {anomalies.data_quality_note}
            </p>
          )}
        </div>
      ) : (
        <div className="mt-5 space-y-3">
          {anomalies.anomalies.slice(0, 6).map((anomaly) => (
            <article
              key={anomaly.id}
              className="rounded-[24px] border border-[#14241e]/10 bg-white p-5"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] ${anomalySeverityClass(
                        anomaly.severity
                      )}`}
                    >
                      {anomalySeverityLabel(anomaly.severity)}
                    </span>
                    <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[#87928d]">
                      {anomalyTypeLabel(anomaly.type)}
                    </span>
                  </div>
                  <p className="mt-2 text-sm font-semibold">
                    {anomaly.title}
                  </p>
                  <p className="mt-1 text-sm leading-6 text-[#66746e]">
                    {anomaly.reason}
                  </p>
                </div>

                <div className="shrink-0 text-right">
                  <p className="text-sm font-semibold text-[#a64b3d]">
                    {formatCents(-anomaly.current_amount_cents)}
                    {anomaly.type === "repeated_charge" &&
                    anomaly.occurrence_count &&
                    anomaly.occurrence_count > 1
                      ? ` × ${anomaly.occurrence_count}`
                      : ""}
                  </p>
                  {anomaly.type !== "repeated_charge" &&
                    anomaly.baseline_amount_cents !== null && (
                      <p className="mt-1 text-xs text-[#87928d]">
                        vs {formatCents(-anomaly.baseline_amount_cents)}{" "}
                        usual
                      </p>
                    )}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
