"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import {
  CardSkeleton,
  EmptyState,
  PageError,
} from "../components/PageFeedback";
import RecurringPayments from "../components/RecurringPayments";
import {
  api,
  formatCents,
  RecurringPayment,
  session,
} from "../lib/api";

function monthlyEquivalent(payment: RecurringPayment): number {
  const multipliers: Record<string, number> = {
    Weekly: 52 / 12,
    Biweekly: 26 / 12,
    Monthly: 1,
  };

  return Math.round(
    payment.amount_cents *
      (multipliers[payment.frequency] ?? 1)
  );
}

export default function RecurringPage() {
  const router = useRouter();

  const [userId, setUserId] = useState<number | null>(null);
  const [payments, setPayments] = useState<
    RecurringPayment[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadPayments = useCallback(async (userId: number) => {
    setLoading(true);
    setError("");

    try {
      setPayments(await api.getRecurringPayments(userId));
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

        setUserId(userId);
        await loadPayments(userId);
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
          monthly:
            result.monthly +
            monthlyEquivalent(payment),
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
        {
          monthly: 0,
          upcoming: 0,
          warnings: 0,
        }
      ),
    [payments]
  );

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
          <header>
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs font-medium text-cyan-300">
              <span className="h-2 w-2 rounded-full bg-cyan-400" />
              Subscription intelligence
            </div>

            <h1 className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">
              Recurring bills
            </h1>

            <p className="mt-2 max-w-2xl text-sm text-slate-400 sm:text-base">
              Review detected subscriptions, upcoming payment
              dates, confidence scores, and price changes.
            </p>
          </header>

          {error && (
            <div className="mt-7">
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
                onAction={() =>
                  router.push("/transactions")
                }
              />
            </div>
          ) : (
            <>
              <section className="mt-8 grid gap-5 sm:grid-cols-3">
                <SummaryCard
                  label="Detected bills"
                  value={String(payments.length)}
                  description="Recurring payment patterns"
                  accent="cyan"
                />

                <SummaryCard
                  label="Monthly estimate"
                  value={formatCents(-summary.monthly)}
                  description="Approximate monthly cost"
                  accent="rose"
                />

                <SummaryCard
                  label="Price alerts"
                  value={String(summary.warnings)}
                  description="Meaningful amount changes"
                  accent={
                    summary.warnings > 0
                      ? "amber"
                      : "emerald"
                  }
                />
              </section>

              <section className="mt-6">
                <RecurringPayments payments={payments} />
              </section>

              <p className="mt-5 text-xs leading-5 text-slate-500">
                Recurring payments are inferred from transaction
                timing and amount consistency. Predictions may not
                match future charges exactly.
              </p>
            </>
          )}
        </div>
      </div>
    </main>
  );
}

function SummaryCard({
  label,
  value,
  description,
  accent,
}: {
  label: string;
  value: string;
  description: string;
  accent: "cyan" | "rose" | "amber" | "emerald";
}) {
  const styles = {
    cyan: "text-cyan-300",
    rose: "text-rose-300",
    amber: "text-amber-300",
    emerald: "text-emerald-300",
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
