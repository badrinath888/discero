"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import { CardSkeleton, EmptyState, PageError } from "../components/PageFeedback";
import { api, formatCents, RecurringPayment, session } from "../lib/api";

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

export default function RecurringPage() {
  const router = useRouter();
  const [userId, setUserId] = useState<number | null>(null);
  const [payments, setPayments] = useState<RecurringPayment[]>([]);
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
            (payment.days_until_due >= 0 && payment.days_until_due <= 30
              ? payment.amount_cents
              : 0),
          warnings:
            result.warnings + (payment.price_change_warning ? 1 : 0),
        }),
        { monthly: 0, upcoming: 0, warnings: 0 }
      ),
    [payments]
  );

  return (
    <main className="min-h-screen bg-[#f5f1e8] text-[#14241e]">
      <AppSidebar />

      <div className="px-5 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-10">
        <div className="mx-auto max-w-7xl">
          <header>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
              Subscription intelligence
            </p>

            <h1 className="mt-3 max-w-3xl text-4xl font-semibold leading-tight tracking-[-0.05em] sm:text-5xl">
              Know what repeats
              <span className="block text-[#167c5a]">
                before it charges again.
              </span>
            </h1>

            <p className="mt-4 max-w-2xl text-sm leading-6 text-[#66746e] sm:text-base">
              Review recurring payments, upcoming due dates, confidence
              scores, and meaningful price changes.
            </p>
          </header>

          {error && (
            <div className="mt-7">
              <PageError
                message={error}
                onRetry={userId ? () => void loadPayments(userId) : undefined}
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
              <section className="mt-8 grid gap-4 md:grid-cols-3">
                <MetricCard label="Detected bills" value={String(payments.length)} tone="blue" />
                <MetricCard label="Monthly estimate" value={formatCents(-summary.monthly)} tone="coral" />
                <MetricCard
                  label="Price alerts"
                  value={String(summary.warnings)}
                  tone={summary.warnings > 0 ? "yellow" : "green"}
                />
              </section>

              <section className="mt-6 grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
                <div className="rounded-[32px] bg-[#14241e] p-7 text-white sm:p-8">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#76dfbd]">
                    Monthly recurring load
                  </p>
                  <p className="mt-5 text-5xl font-semibold tracking-[-0.06em]">
                    {formatCents(-summary.monthly)}
                  </p>
                  <p className="mt-3 max-w-xl text-sm leading-6 text-white/65">
                    Approximate monthly cost based on detected billing frequencies.
                  </p>
                </div>

                <div className="rounded-[32px] bg-[#f7e8b5] p-7 sm:p-8">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#7d641e]">
                    Due within 30 days
                  </p>
                  <p className="mt-5 text-5xl font-semibold tracking-[-0.06em]">
                    {formatCents(-summary.upcoming)}
                  </p>
                  <p className="mt-3 text-sm leading-6 text-[#6f632f]">
                    Estimated upcoming recurring charges in the next month.
                  </p>
                </div>
              </section>

              <section className="mt-8">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
                      Detected patterns
                    </p>
                    <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
                      Recurring payments
                    </h2>
                  </div>
                  <p className="text-sm text-[#7b8781]">{payments.length} detected</p>
                </div>

                <div className="mt-5 grid gap-5 lg:grid-cols-2">
                  {payments.map((payment, index) => (
                    <RecurringCard
                      key={`${payment.merchant}-${payment.last_payment}`}
                      payment={payment}
                      index={index}
                    />
                  ))}
                </div>
              </section>

              <p className="mt-6 text-xs leading-5 text-[#7b8781]">
                Recurring payments are inferred from transaction timing and amount consistency.
                Predictions may not match future charges exactly.
              </p>
            </>
          )}
        </div>
      </div>
    </main>
  );
}

function MetricCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "green" | "coral" | "yellow" | "blue";
}) {
  const styles = {
    green: "bg-[#dff6c7]",
    coral: "bg-[#f8ddd5]",
    yellow: "bg-[#f7e8b5]",
    blue: "bg-[#dceeea]",
  };

  return (
    <article className={`rounded-[26px] p-5 ${styles[tone]}`}>
      <p className="text-sm text-[#52635b]">{label}</p>
      <p className="mt-3 text-3xl font-semibold tracking-[-0.04em]">{value}</p>
    </article>
  );
}

function RecurringCard({
  payment,
  index,
}: {
  payment: RecurringPayment;
  index: number;
}) {
  const tones = ["bg-white", "bg-[#eef6e9]", "bg-[#fbf0d1]", "bg-[#f5e4de]"];

  return (
    <article
      className={`rounded-[30px] border border-[#14241e]/10 p-6 shadow-sm shadow-[#14241e]/5 ${
        tones[index % tones.length]
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#7b8781]">
            {payment.frequency}
          </p>
          <h3 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
            {payment.merchant}
          </h3>
        </div>

        {payment.price_change_warning && (
          <span className="rounded-full bg-[#f8ddd5] px-3 py-1.5 text-xs font-semibold text-[#923f32]">
            Price changed
          </span>
        )}
      </div>

      <div className="mt-7 flex items-end justify-between gap-5">
        <div>
          <p className="text-sm text-[#66746e]">Typical payment</p>
          <p className="mt-1 text-3xl font-semibold tracking-[-0.04em] text-[#a64b3d]">
            {formatCents(-payment.amount_cents)}
          </p>
        </div>

        <div className="text-right">
          <p className="text-sm text-[#66746e]">Due in</p>
          <p className="mt-1 text-lg font-semibold">
            {payment.days_until_due === 0
              ? "Today"
              : payment.days_until_due > 0
              ? `${payment.days_until_due} days`
              : "Past due"}
          </p>
        </div>
      </div>

      <div className="mt-6 grid gap-4 border-t border-[#14241e]/10 pt-5 sm:grid-cols-3">
        <Detail label="Occurrences" value={String(payment.occurrences)} />
        <Detail label="Confidence" value={`${payment.confidence_score}%`} />
        <Detail
          label="Last paid"
          value={new Date(`${payment.last_payment}T00:00:00`).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
          })}
        />
      </div>
    </article>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-[#7b8781]">{label}</p>
      <p className="mt-1 text-sm font-semibold">{value}</p>
    </div>
  );
}
