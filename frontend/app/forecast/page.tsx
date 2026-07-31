"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import {
  api,
  CashFlowForecast,
  formatCents,
  session,
} from "../lib/api";

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString(
    "en-US",
    {
      month: "short",
      day: "numeric",
      year: "numeric",
    }
  );
}

export default function ForecastPage() {
  const router = useRouter();

  const [forecast, setForecast] =
    useState<CashFlowForecast | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadForecast = useCallback(async (userId: number) => {
    setLoading(true);
    setError("");

    try {
      setForecast(await api.getCashFlowForecast(userId));
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to load forecast"
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

        await loadForecast(userId);
      } catch {
        session.clear();
        router.replace("/");
      }
    }

    void initialize();
  }, [router, loadForecast]);

  return (
    <main
      className="relative min-h-screen overflow-hidden bg-[#07111f] text-white"
      style={{
        backgroundImage: `
          radial-gradient(circle at 15% 10%, rgba(139,92,246,0.15), transparent 30%),
          radial-gradient(circle at 85% 20%, rgba(14,165,233,0.10), transparent 28%),
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
            <div className="inline-flex items-center gap-2 rounded-full border border-violet-400/20 bg-violet-400/10 px-3 py-1 text-xs font-medium text-violet-300">
              <span className="h-2 w-2 rounded-full bg-violet-400" />
              Forward projection
            </div>

            <h1 className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">
              Cash-flow forecast
            </h1>

            <p className="mt-2 max-w-2xl text-sm text-slate-400 sm:text-base">
              Estimate your month-end balance using connected
              accounts, income pace, and predicted recurring bills.
            </p>
          </header>

          {error && (
            <div className="mt-7 rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-300">
              {error}
            </div>
          )}

          {loading ? (
            <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <div
                  key={index}
                  className="h-32 animate-pulse rounded-3xl bg-white/[0.05]"
                />
              ))}
            </div>
          ) : forecast ? (
            <>
              <section className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
                <MetricCard
                  label="Liquid balance"
                  value={formatCents(
                    forecast.liquid_balance_cents
                  )}
                  description="Available connected cash"
                  accent="cyan"
                />

                <MetricCard
                  label="Expected income"
                  value={formatCents(
                    forecast.expected_income_cents
                  )}
                  description="Estimated remaining income"
                  accent="emerald"
                />

                <MetricCard
                  label="Upcoming bills"
                  value={formatCents(
                    -forecast.upcoming_bills_cents
                  )}
                  description="Predicted before month-end"
                  accent="rose"
                />

                <MetricCard
                  label="Projected month-end"
                  value={formatCents(
                    forecast.projected_end_balance_cents
                  )}
                  description={
                    forecast.low_balance_risk
                      ? "Balance may fall below zero"
                      : "Balance remains positive"
                  }
                  accent={
                    forecast.low_balance_risk
                      ? "rose"
                      : "violet"
                  }
                />
              </section>

              <section
                className={`mt-6 rounded-3xl border p-6 backdrop-blur-xl ${
                  forecast.low_balance_risk
                    ? "border-rose-400/20 bg-rose-400/[0.07]"
                    : "border-emerald-400/20 bg-emerald-400/[0.07]"
                }`}
              >
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p
                      className={`text-sm font-semibold ${
                        forecast.low_balance_risk
                          ? "text-rose-300"
                          : "text-emerald-300"
                      }`}
                    >
                      {forecast.low_balance_risk
                        ? "Low-balance warning"
                        : "Positive cash-flow outlook"}
                    </p>

                    <p className="mt-2 text-sm leading-6 text-slate-300">
                      {forecast.low_balance_risk
                        ? "Predicted expenses may exceed your available cash and expected income."
                        : "Your available cash and expected income currently cover predicted bills."}
                    </p>
                  </div>

                  <div className="rounded-2xl border border-white/10 bg-slate-950/40 px-5 py-4">
                    <p className="text-xs text-slate-500">
                      Forecast period
                    </p>

                    <p className="mt-1 text-sm font-medium text-slate-200">
                      {formatDate(forecast.as_of)} –{" "}
                      {formatDate(forecast.month_end)}
                    </p>

                    <p className="mt-1 text-xs text-slate-500">
                      {forecast.days_remaining} days remaining
                    </p>
                  </div>
                </div>
              </section>

              <section className="mt-6 rounded-3xl border border-white/10 bg-white/[0.06] p-5 shadow-xl shadow-black/20 backdrop-blur-xl sm:p-7">
                <div>
                  <h2 className="text-lg font-semibold">
                    Upcoming predicted bills
                  </h2>

                  <p className="mt-1 text-sm text-slate-400">
                    Recurring expenses expected before month-end
                  </p>
                </div>

                <div className="mt-6 space-y-3">
                  {forecast.upcoming_cash_flows.map((item) => (
                    <article
                      key={`${item.merchant}-${item.expected_date}`}
                      className="flex flex-col gap-4 rounded-2xl border border-white/[0.08] bg-slate-950/35 p-4 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="flex items-center gap-4">
                        <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-rose-400/10 font-semibold text-rose-300">
                          ↓
                        </span>

                        <div>
                          <p className="font-medium text-slate-100">
                            {item.merchant}
                          </p>

                          <p className="mt-1 text-xs text-slate-500">
                            Expected {formatDate(item.expected_date)}
                            {" · "}
                            {item.confidence_score}% confidence
                          </p>
                        </div>
                      </div>

                      <p className="text-lg font-bold text-rose-300">
                        {formatCents(-item.amount_cents)}
                      </p>
                    </article>
                  ))}

                  {forecast.upcoming_cash_flows.length === 0 && (
                    <div className="rounded-2xl border border-dashed border-white/10 px-5 py-12 text-center">
                      <p className="text-sm text-slate-500">
                        No recurring bills are currently predicted
                        before month-end.
                      </p>
                    </div>
                  )}
                </div>
              </section>

              <p className="mt-5 text-xs leading-5 text-slate-500">
                Forecasts are estimates and may differ from actual
                balances or future transactions.
              </p>
            </>
          ) : (
            <div className="mt-8 rounded-3xl border border-dashed border-white/10 px-5 py-16 text-center text-sm text-slate-500">
              Forecast data is unavailable.
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
  description,
  accent,
}: {
  label: string;
  value: string;
  description: string;
  accent: "cyan" | "emerald" | "rose" | "violet";
}) {
  const styles = {
    cyan: "text-cyan-300",
    emerald: "text-emerald-300",
    rose: "text-rose-300",
    violet: "text-violet-300",
  };

  return (
    <article className="rounded-3xl border border-white/10 bg-white/[0.06] p-5 shadow-xl shadow-black/20 backdrop-blur-xl">
      <p className="text-sm text-slate-400">{label}</p>

      <p className={`mt-3 text-2xl font-bold ${styles[accent]}`}>
        {value}
      </p>

      <p className="mt-2 text-xs text-slate-500">
        {description}
      </p>
    </article>
  );
}
