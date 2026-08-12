"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, formatCents, SafeToSpendResult } from "../lib/api";
import { AnimatedNumber } from "./PremiumMotion";

type SafeToSpendCardProps = {
  userId: number | null;
  refreshKey?: number;
};

const INPUT_DEBOUNCE_MS = 400;

export default function SafeToSpendCard({
  userId,
  refreshKey = 0,
}: SafeToSpendCardProps) {
  const reduceMotion = useReducedMotion();
  const [result, setResult] = useState<SafeToSpendResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState("");
  const [reserveAmount, setReserveAmount] = useState("0");
  const [essentialAmount, setEssentialAmount] = useState("0");
  const [horizonDays, setHorizonDays] = useState("30");
  const hasLoadedOnce = useRef(false);

  const loadSafeToSpend = useCallback(async () => {
    if (userId === null) return;

    setLoading(true);
    setError("");

    try {
      const reserveCents = Math.round(Number(reserveAmount) * 100);
      const essentialCents = Math.round(Number(essentialAmount) * 100);
      const parsedHorizonDays = Number(horizonDays);

      setResult(
        await api.getSafeToSpend(userId, {
          safety_reserve_cents: Number.isFinite(reserveCents)
            ? Math.max(reserveCents, 0)
            : 0,
          essential_spending_cents: Number.isFinite(essentialCents)
            ? Math.max(essentialCents, 0)
            : 0,
          horizon_days: Number.isFinite(parsedHorizonDays)
            ? Math.min(Math.max(Math.round(parsedHorizonDays), 1), 365)
            : 30,
        })
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to calculate safe-to-spend"
      );
    } finally {
      setLoading(false);
    }
  }, [essentialAmount, horizonDays, reserveAmount, userId]);

  useEffect(() => {
    if (userId === null) return;

    const timeoutId = window.setTimeout(() => {
      hasLoadedOnce.current = true;
      void loadSafeToSpend();
    }, hasLoadedOnce.current ? INPUT_DEBOUNCE_MS : 0);

    return () => window.clearTimeout(timeoutId);
  }, [loadSafeToSpend, refreshKey, userId]);

  const status = {
    safe: { label: "Healthy", className: "bg-[#E8EEE7] text-[#58715A]" },
    limited: { label: "Limited", className: "bg-[#fff3d6] text-[#976716]" },
    negative: { label: "At risk", className: "bg-[#fbe9e5] text-[#ad4b3d]" },
  }[result?.status ?? "safe"];

  return (
    <section className="mt-8 overflow-hidden border-y border-[#181713]/10 bg-[#FFFCF7]">
      <div className="grid gap-6 px-6 py-7 sm:px-8 lg:grid-cols-[1fr_auto] lg:items-end">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">
              Safe to spend
            </p>
            {!loading && result && (
              <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${status.className}`}>
                {status.label}
              </span>
            )}
          </div>

          {!result && !error ? (
            <div className="mt-4 h-12 w-52 animate-pulse rounded-xl bg-[#181713]/[0.06]" />
          ) : error && !result ? (
            <p className="mt-4 text-sm font-semibold text-[#ad4b3d]">Unable to calculate</p>
          ) : (
            <AnimatedNumber
              value={result?.safe_to_spend_cents ?? 0}
              format={formatCents}
              className="mt-3 block text-[clamp(2.4rem,5vw,4rem)] font-semibold leading-none tracking-[-0.06em] text-[#181713]"
            />
          )}

          <p className="mt-3 text-sm text-[#706961]">
            {result ? `${Math.round(result.confidence_score)}% confidence · through ${new Date(`${result.through_date}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" })}` : "Based on your liquid balance and known obligations."}
          </p>
        </div>

        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="focus-ring flex w-fit items-center gap-2 rounded-full px-3 py-2 text-sm font-semibold text-[#6E4B63] transition hover:bg-[#F0E9EE]"
        >
          Adjust assumptions
          <span aria-hidden="true" className={`transition-transform ${expanded ? "rotate-180" : ""}`}>⌄</span>
        </button>
      </div>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={reduceMotion ? false : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={reduceMotion ? undefined : { height: 0, opacity: 0 }}
            transition={{ duration: reduceMotion ? 0 : 0.24, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden border-t border-[#181713]/[0.07] bg-[#F5F1EA]/70"
          >
            <div data-testid="safe-to-spend-controls" className="grid gap-4 px-6 py-5 sm:px-8 md:grid-cols-[1fr_1fr_0.7fr_auto] md:items-end">
              <AssumptionInput label="Safety reserve" value={reserveAmount} onChange={setReserveAmount} min="0" step="0.01" />
              <AssumptionInput label="Essential spending" value={essentialAmount} onChange={setEssentialAmount} min="0" step="0.01" />
              <AssumptionInput label="Horizon" value={horizonDays} onChange={setHorizonDays} min="1" max="365" suffix="days" />
              <button
                type="button"
                onClick={() => void loadSafeToSpend()}
                disabled={loading}
                className="focus-ring h-10 rounded-xl bg-[#6E4B63] px-4 text-sm font-semibold text-white transition hover:bg-[#5B3C51] disabled:opacity-50"
              >
                {loading ? "Updating…" : "Update"}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {error && result && (
        <p role="status" className="border-t border-[#d46a59]/15 bg-[#fff7f5] px-8 py-3 text-sm text-[#ad4b3d]">
          {error}
        </p>
      )}
    </section>
  );
}

function AssumptionInput({
  label,
  value,
  onChange,
  suffix,
  ...inputProps
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  suffix?: string;
  min?: string;
  max?: string;
  step?: string;
}) {
  return (
    <label>
      <span className="text-xs font-medium text-[#706961]">{label}</span>
      <span className="mt-1.5 flex h-10 items-center rounded-xl bg-white px-3 ring-1 ring-[#181713]/10 focus-within:ring-2 focus-within:ring-[#6E4B63]/40">
        <input
          type="number"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="min-w-0 flex-1 bg-transparent text-sm text-[#181713] outline-none"
          {...inputProps}
        />
        {suffix && <span className="text-xs text-[#8A8178]">{suffix}</span>}
      </span>
    </label>
  );
}
