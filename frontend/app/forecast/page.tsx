"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import { CardSkeleton, EmptyState, PageError } from "../components/PageFeedback";
import { api, CashFlowForecast, formatCents, session } from "../lib/api";

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function ForecastPage() {
  const router = useRouter();
  const [userId, setUserId] = useState<number | null>(null);
  const [forecast, setForecast] = useState<CashFlowForecast | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadForecast = useCallback(async (id: number) => {
    setLoading(true);
    setError("");

    try {
      setForecast(await api.getCashFlowForecast(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load forecast");
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

  return (
    <main className="min-h-screen bg-[#f5f1e8] text-[#14241e]">
      <AppSidebar />

      <div className="px-5 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-10">
        <div className="mx-auto max-w-7xl">
          <header>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
              Forward projection
            </p>

            <h1 className="mt-3 max-w-3xl text-4xl font-semibold leading-tight tracking-[-0.05em] sm:text-5xl">
              See where your balance
              <span className="block text-[#167c5a]">is headed next.</span>
            </h1>

            <p className="mt-4 max-w-2xl text-sm leading-6 text-[#66746e] sm:text-base">
              Estimate month-end cash using connected balances, expected income,
              and predicted recurring bills.
            </p>
          </header>

          {error && (
            <div className="mt-7">
              <PageError
                message={error}
                onRetry={userId ? () => void loadForecast(userId) : undefined}
              />
            </div>
          )}

          {loading ? (
            <div className="mt-8">
              <CardSkeleton count={4} />
            </div>
          ) : forecast ? (
            <>
              <section className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <MetricCard
                  label="Liquid balance"
                  value={formatCents(forecast.liquid_balance_cents)}
                  tone="blue"
                  description="Available connected cash"
                />
                <MetricCard
                  label="Expected income"
                  value={formatCents(forecast.expected_income_cents)}
                  tone="green"
                  description="Estimated remaining income"
                />
                <MetricCard
                  label="Upcoming bills"
                  value={formatCents(-forecast.upcoming_bills_cents)}
                  tone="coral"
                  description="Predicted before month-end"
                />
                <MetricCard
                  label="Projected month-end"
                  value={formatCents(forecast.projected_end_balance_cents)}
                  tone={forecast.low_balance_risk ? "coral" : "yellow"}
                  description={
                    forecast.low_balance_risk
                      ? "Balance may fall below zero"
                      : "Balance remains positive"
                  }
                />
              </section>

              <section className="mt-6 grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
                <div
                  className={`rounded-[32px] p-7 sm:p-8 ${
                    forecast.low_balance_risk ? "bg-[#f8ddd5]" : "bg-[#dff6c7]"
                  }`}
                >
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#52635b]">
                    Forecast outlook
                  </p>

                  <h2 className="mt-4 text-4xl font-semibold tracking-[-0.05em]">
                    {forecast.low_balance_risk
                      ? "Low-balance warning"
                      : "Positive cash-flow outlook"}
                  </h2>

                  <p className="mt-4 max-w-2xl text-sm leading-6 text-[#66746e]">
                    {forecast.low_balance_risk
                      ? "Predicted expenses may exceed your available cash and expected income."
                      : "Your available cash and expected income currently cover predicted bills."}
                  </p>

                  <div className="mt-8 flex flex-wrap gap-3">
                    <span className="rounded-full bg-white/65 px-4 py-2 text-sm font-medium">
                      {forecast.days_remaining} days remaining
                    </span>
                    <span className="rounded-full bg-white/65 px-4 py-2 text-sm font-medium">
                      Through {formatDate(forecast.month_end)}
                    </span>
                  </div>
                </div>

                <div className="rounded-[32px] bg-[#14241e] p-7 text-white sm:p-8">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#76dfbd]">
                    Forecast period
                  </p>

                  <div className="mt-5 space-y-5">
                    <PeriodRow label="As of" value={formatDate(forecast.as_of)} />
                    <PeriodRow
                      label="Month end"
                      value={formatDate(forecast.month_end)}
                    />
                    <PeriodRow
                      label="Predicted bills"
                      value={String(forecast.upcoming_cash_flows.length)}
                    />
                  </div>
                </div>
              </section>

              <section className="mt-8">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
                      Upcoming cash outflows
                    </p>
                    <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
                      Predicted bills before month-end
                    </h2>
                  </div>

                  <p className="text-sm text-[#7b8781]">
                    {forecast.upcoming_cash_flows.length} expected
                  </p>
                </div>

                {forecast.upcoming_cash_flows.length > 0 ? (
                  <div className="mt-5 grid gap-4 lg:grid-cols-2">
                    {forecast.upcoming_cash_flows.map((item, index) => (
                      <BillCard
                        key={`${item.merchant}-${item.expected_date}`}
                        merchant={item.merchant}
                        expectedDate={item.expected_date}
                        amount={item.amount_cents}
                        confidence={item.confidence_score}
                        index={index}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="mt-5 rounded-[30px] border border-dashed border-[#14241e]/15 bg-white px-6 py-14 text-center">
                    <p className="text-lg font-semibold">No predicted bills</p>
                    <p className="mt-2 text-sm text-[#728078]">
                      No recurring bills are currently expected before month-end.
                    </p>
                  </div>
                )}
              </section>

              <p className="mt-6 text-xs leading-5 text-[#7b8781]">
                Forecasts are estimates and may differ from actual balances or
                future transactions.
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
        </div>
      </div>
    </main>
  );
}

function MetricCard({
  label,
  value,
  tone,
  description,
}: {
  label: string;
  value: string;
  tone: "green" | "coral" | "yellow" | "blue";
  description: string;
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
      <p className="mt-2 text-xs text-[#66746e]">{description}</p>
    </article>
  );
}

function PeriodRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-5 border-b border-white/10 pb-4 last:border-b-0 last:pb-0">
      <span className="text-sm text-white/55">{label}</span>
      <span className="text-sm font-semibold">{value}</span>
    </div>
  );
}

function BillCard({
  merchant,
  expectedDate,
  amount,
  confidence,
  index,
}: {
  merchant: string;
  expectedDate: string;
  amount: number;
  confidence: number;
  index: number;
}) {
  const tones = ["bg-white", "bg-[#f8ddd5]", "bg-[#fbf0d1]", "bg-[#e8f1ef]"];

  return (
    <article
      className={`rounded-[28px] border border-[#14241e]/10 p-6 shadow-sm shadow-[#14241e]/5 ${
        tones[index % tones.length]
      }`}
    >
      <div className="flex items-start justify-between gap-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#7b8781]">
            Expected {formatDate(expectedDate)}
          </p>
          <h3 className="mt-2 text-xl font-semibold tracking-[-0.02em]">
            {merchant}
          </h3>
        </div>

        <span className="rounded-full bg-white/65 px-3 py-1.5 text-xs font-semibold text-[#52635b]">
          {confidence}% confidence
        </span>
      </div>

      <div className="mt-7 flex items-end justify-between gap-4">
        <div>
          <p className="text-sm text-[#66746e]">Predicted amount</p>
          <p className="mt-1 text-3xl font-semibold tracking-[-0.04em] text-[#a64b3d]">
            {formatCents(-amount)}
          </p>
        </div>

        <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/65 text-lg font-semibold text-[#a64b3d]">
          ↓
        </span>
      </div>
    </article>
  );
}
