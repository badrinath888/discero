"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  formatCents,
  SafeToSpendObligation,
  SafeToSpendResult,
} from "../lib/api";
import { AnimatedNumber } from "./PremiumMotion";

type SafeToSpendCardProps = {
  userId: number | null;
  refreshKey?: number;
};

const DEFAULT_RESERVE_CENTS = 0;
const DEFAULT_ESSENTIAL_SPENDING_CENTS = 0;
const DEFAULT_HORIZON_DAYS = 30;

export default function SafeToSpendCard({
  userId,
  refreshKey = 0,
}: SafeToSpendCardProps) {
  const [result, setResult] =
    useState<SafeToSpendResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState("");
  const [reserveAmount, setReserveAmount] = useState("0");
  const [essentialAmount, setEssentialAmount] = useState("0");
  const [horizonDays, setHorizonDays] = useState("30");

  const loadSafeToSpend = useCallback(async () => {
    if (userId === null) return;

    setLoading(true);
    setError("");

    try {
      const reserveCents = Math.round(Number(reserveAmount) * 100);
      const essentialCents = Math.round(Number(essentialAmount) * 100);
      const parsedHorizonDays = Number(horizonDays);

      const data = await api.getSafeToSpend(userId, {
        safety_reserve_cents: Number.isFinite(reserveCents)
          ? Math.max(reserveCents, 0)
          : DEFAULT_RESERVE_CENTS,
        essential_spending_cents: Number.isFinite(essentialCents)
          ? Math.max(essentialCents, 0)
          : DEFAULT_ESSENTIAL_SPENDING_CENTS,
        horizon_days: Number.isFinite(parsedHorizonDays)
          ? Math.min(Math.max(Math.round(parsedHorizonDays), 1), 365)
          : DEFAULT_HORIZON_DAYS,
      });

      setResult(data);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to calculate safe-to-spend"
      );
    } finally {
      setLoading(false);
    }
  }, [essentialAmount, horizonDays, reserveAmount, userId]);

useEffect(() => {
  if (userId === null) return;

  const timeoutId = window.setTimeout(() => {
    void loadSafeToSpend();
  }, 0);

  return () => {
    window.clearTimeout(timeoutId);
  };
}, [loadSafeToSpend, refreshKey, userId]);

  const statusLabel = {
    safe: "Safe",
    limited: "Limited",
    negative: "Shortfall",
  }[result?.status ?? "safe"];

  const statusClasses = {
    safe: "bg-[#dff6c7] text-[#315d31]",
    limited: "bg-[#f5d66f] text-[#66500f]",
    negative: "bg-[#f0b8a8] text-[#7b3528]",
  }[result?.status ?? "safe"];

  const recurringObligations =
    result?.obligations.filter(
      (obligation) => obligation.source === "recurring"
    ) ?? [];
  const budgetObligations =
    result?.obligations.filter(
      (obligation) => obligation.source === "budget"
    ) ?? [];
  const otherObligations =
    result?.obligations.filter(
      (obligation) =>
        obligation.source !== "recurring" &&
        obligation.source !== "budget"
    ) ?? [];

  const recurringTotalCents = recurringObligations.reduce(
    (total, obligation) => total + obligation.amount_cents,
    0
  );
  const budgetTotalCents = budgetObligations.reduce(
    (total, obligation) => total + obligation.amount_cents,
    0
  );

  return (
    <section className="mt-8">
      <article className="premium-hover relative overflow-hidden rounded-[30px] bg-[#12261f] p-7 text-white shadow-[0_24px_60px_rgba(23,49,40,0.18)] sm:p-9">
        <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-[#64d7aa]/20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-20 left-1/3 h-48 w-48 rounded-full bg-[#c9e7ff]/10 blur-3xl" />

        <div className="relative">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-2xl">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#83dcb9]">
                Financial decision signal
              </p>

              <h2 className="mt-3 text-3xl font-semibold tracking-[-0.045em] sm:text-4xl">
                Safe to spend
              </h2>

              <p className="mt-3 max-w-xl text-sm leading-6 text-white/55">
                Estimated money available for flexible spending after
                liquid balances, active recurring obligations, and
                remaining budget commitments are considered.
              </p>
            </div>

            {!loading && result && (
              <span
                className={`inline-flex w-fit rounded-full px-3 py-1.5 text-xs font-semibold ${statusClasses}`}
              >
                {statusLabel}
              </span>
            )}
          </div>

          <div data-testid="safe-to-spend-controls" className="mt-7 grid gap-3 rounded-2xl border border-white/10 bg-white/[0.04] p-4 md:grid-cols-4">
            <label>
              <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/40">
                Safety reserve
              </span>
              <input
                type="number"
                min="0"
                step="0.01"
                value={reserveAmount}
                onChange={(event) => setReserveAmount(event.target.value)}
                className="mt-2 w-full rounded-xl border border-white/10 bg-white/10 px-3 py-2 text-sm text-white outline-none"
              />
            </label>

            <label>
              <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/40">
                Essential spending
              </span>
              <input
                type="number"
                min="0"
                step="0.01"
                value={essentialAmount}
                onChange={(event) => setEssentialAmount(event.target.value)}
                className="mt-2 w-full rounded-xl border border-white/10 bg-white/10 px-3 py-2 text-sm text-white outline-none"
              />
            </label>

            <label>
              <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/40">
                Horizon days
              </span>
              <input
                type="number"
                min="1"
                max="365"
                value={horizonDays}
                onChange={(event) => setHorizonDays(event.target.value)}
                className="mt-2 w-full rounded-xl border border-white/10 bg-white/10 px-3 py-2 text-sm text-white outline-none"
              />
            </label>

            <button
              type="button"
              onClick={() => void loadSafeToSpend()}
              disabled={loading}
              className="min-h-11 self-end rounded-xl bg-[#83dcb9] px-4 text-sm font-semibold text-[#12261f] disabled:opacity-50"
            >
              {loading ? "Calculating..." : "Recalculate"}
            </button>
          </div>

          <div className="mt-8 grid gap-6 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
            <div>
              {loading ? (
                <div className="h-16 w-64 animate-pulse rounded-xl bg-white/10" />
              ) : error ? (
                <div>
                  <p className="text-sm font-semibold text-[#f4a594]">
                    Unable to calculate
                  </p>
                  <p className="mt-2 text-sm text-white/50">
                    {error}
                  </p>
                </div>
              ) : (
                <>
                  <AnimatedNumber
                    value={result?.safe_to_spend_cents ?? 0}
                    format={formatCents}
                    className="block text-5xl font-semibold tracking-[-0.06em] sm:text-6xl"
                  />

                  <p className="mt-3 text-sm text-white/50">
                    Through{" "}
                    {result
                      ? new Date(
                          `${result.through_date}T00:00:00`
                        ).toLocaleDateString("en-US", {
                          month: "short",
                          day: "numeric",
                          year: "numeric",
                        })
                      : "the next 30 days"}
                  </p>
                </>
              )}
            </div>

            <div className="grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-2">
              <SafeMetric
                label="Confidence"
                value={
  result
    ? `${Math.round(result.confidence_score)}%`
    : "—"
}
              />

              <SafeMetric
                label="Shortfall"
                value={
                  result
                    ? formatCents(-result.shortfall_cents)
                    : "—"
                }
                warning={(result?.shortfall_cents ?? 0) > 0}
              />
            </div>
          </div>

          {result && (
            <>
              <div className="mt-8 border-t border-white/10 pt-6">
                <button
                  type="button"
                  onClick={() => setExpanded((value) => !value)}
                  className="flex w-full items-center justify-between gap-4 text-left"
                  aria-expanded={expanded}
                >
                  <span className="text-sm font-semibold text-white">
                    Calculation breakdown
                  </span>

                  <span className="text-sm font-semibold text-[#83dcb9]">
                    {expanded ? "Hide details ↑" : "View details ↓"}
                  </span>
                </button>
              </div>

              {expanded && (
                <div className="mt-6">
                  <div className="grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-2 lg:grid-cols-5">
                    <SafeMetric
                      label="Liquid balance"
                      value={formatCents(
                        result.breakdown.liquid_balance_cents
                      )}
                    />

                    <SafeMetric
                      label="Recurring total"
                      value={formatCents(-recurringTotalCents)}
                    />

                    <SafeMetric
                      label="Budget total (remaining)"
                      value={formatCents(-budgetTotalCents)}
                    />

                    <SafeMetric
                      label="Essential spending"
                      value={formatCents(
                        -result.breakdown
                          .essential_spending_cents
                      )}
                    />

                    <SafeMetric
                      label="Safety reserve"
                      value={formatCents(
                        -result.breakdown
                          .safety_reserve_cents
                      )}
                    />
                  </div>

                  <div className="mt-7 grid gap-6 sm:grid-cols-2">
                    <ObligationSection
                      title="Recurring obligations"
                      badgeLabel="Recurring"
                      badgeClassName="bg-[#c9e7ff]/15 text-[#8fd0ff]"
                      obligations={recurringObligations}
                      emptyLabel="No active recurring obligations for this period."
                    />

                    <ObligationSection
                      title="Budget obligations"
                      badgeLabel="Budget"
                      badgeClassName="bg-[#83dcb9]/15 text-[#83dcb9]"
                      note="Remaining amount left in each budget — not the full monthly limit."
                      obligations={budgetObligations}
                      emptyLabel="No remaining budget obligations for this period."
                    />
                  </div>

                  {otherObligations.length > 0 && (
                    <div className="mt-7">
                      <ObligationSection
                        title="Other obligations"
                        badgeLabel="Manual"
                        badgeClassName="bg-white/10 text-white/60"
                        obligations={otherObligations}
                      />
                    </div>
                  )}

                  {result.warnings.length > 0 && (
                    <div className="mt-6 rounded-2xl border border-[#f5d66f]/20 bg-[#f5d66f]/10 px-4 py-4">
                      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#f5d66f]">
                        Data notes
                      </p>

                      <ul className="mt-3 space-y-2 text-sm leading-6 text-white/60">
                        {result.warnings.map((warning) => (
                          <li key={warning}>• {warning}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {error && (
            <button
              type="button"
              onClick={() => void loadSafeToSpend()}
              className="mt-6 text-sm font-semibold text-[#83dcb9] transition hover:opacity-70"
            >
              Try again →
            </button>
          )}
        </div>
      </article>
    </section>
  );
}

function SafeMetric({
  label,
  value,
  warning = false,
}: {
  label: string;
  value: string;
  warning?: boolean;
}) {
  return (
    <div className="bg-white/[0.045] p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/35">
        {label}
      </p>

      <p
        className={`mt-2 text-lg font-semibold ${
          warning ? "text-[#f4a594]" : "text-white"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function ObligationSection({
  title,
  badgeLabel,
  badgeClassName,
  note,
  obligations,
  emptyLabel,
}: {
  title: string;
  badgeLabel: string;
  badgeClassName: string;
  note?: string;
  obligations: SafeToSpendObligation[];
  emptyLabel?: string;
}) {
  return (
    <div data-testid={`obligation-section-${badgeLabel.toLowerCase()}`}>
      <div className="flex items-center gap-2">
        <p className="text-xs font-semibold uppercase tracking-[0.15em] text-white/40">
          {title}
        </p>

        <span
          className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ${badgeClassName}`}
        >
          {badgeLabel}
        </span>
      </div>

      {note && (
        <p className="mt-1 text-xs text-white/40">{note}</p>
      )}

      {obligations.length === 0 ? (
        <p className="mt-3 rounded-2xl border border-white/10 px-4 py-4 text-sm text-white/40">
          {emptyLabel}
        </p>
      ) : (
        <div className="mt-3 divide-y divide-white/10 rounded-2xl border border-white/10 px-4">
          {obligations.slice(0, 5).map((obligation, index) => (
            <div
              key={`${obligation.name}-${obligation.expected_date}-${index}`}
              className="grid gap-1.5 py-4"
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-white">
                  {obligation.name}
                </p>

                <p className="text-sm font-semibold text-[#f4a594]">
                  {formatCents(-obligation.amount_cents)}
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-white/45">
                <span>
                  {obligation.category || "Uncategorized"}
                </span>
                <span aria-hidden="true">·</span>
                <span>
                  {new Date(
                    `${obligation.expected_date}T00:00:00`
                  ).toLocaleDateString("en-US", {
                    month: "short",
                    day: "numeric",
                  })}
                </span>
                <span aria-hidden="true">·</span>
                <span>
                  {Math.round(obligation.confidence_score)}%
                  confidence
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}