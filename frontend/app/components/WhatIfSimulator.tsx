"use client";

import {
  CheckCircle2,
  CircleAlert,
  Gauge,
  Lightbulb,
  Scale,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import {
  api,
  DecisionType,
  formatCents,
  WhatIfImpact,
  WhatIfScenarioType,
  WhatIfSimulationRequest,
  WhatIfSimulationResult,
} from "../lib/api";
import GoalImpactList from "./GoalImpactList";

const SCENARIO_OPTIONS: { value: WhatIfScenarioType; label: string }[] = [
  { value: "one_time_expense", label: "One-time purchase" },
  { value: "monthly_expense_change", label: "Monthly expense change" },
  { value: "monthly_income_change", label: "Monthly income change" },
  { value: "monthly_savings_change", label: "Monthly savings change" },
  { value: "temporary_income_loss", label: "Temporary income loss" },
];

const IMPACT_CONTENT: Record<
  WhatIfImpact["level"],
  { label: string; className: string; icon: typeof CheckCircle2 }
> = {
  positive: {
    label: "Improves your position",
    className: "bg-[#E3EBE1] text-[#48634B]",
    icon: CheckCircle2,
  },
  neutral: {
    label: "No material change",
    className: "bg-white/10 text-white/70",
    icon: Scale,
  },
  caution: {
    label: "Reduces your buffer",
    className: "bg-[#FBF1DF] text-[#8A5A20]",
    icon: TriangleAlert,
  },
  negative: {
    label: "Creates financial risk",
    className: "bg-[#F8E6E1] text-[#8F3F33]",
    icon: CircleAlert,
  },
};

const CONFIDENCE_LABEL: Record<string, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

function toDateInputValue(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function dollarsToCents(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed * 100) : 0;
}

export default function WhatIfSimulator({
  userId,
}: {
  userId: number | null;
}) {
  const today = useMemo(() => new Date(), []);

  const [scenarioType, setScenarioType] =
    useState<WhatIfScenarioType>("one_time_expense");
  const [scenarioName, setScenarioName] = useState("New laptop");
  const [amount, setAmount] = useState("2000");
  const [effectiveDate, setEffectiveDate] = useState(
    toDateInputValue(addDays(today, 7))
  );
  const [monthlyAmountChange, setMonthlyAmountChange] = useState("300");
  const [monthlyIncomeLoss, setMonthlyIncomeLoss] = useState("2500");
  const [durationMonths, setDurationMonths] = useState("2");
  const [safetyReserve, setSafetyReserve] = useState("0");
  const [essentialSpending, setEssentialSpending] = useState("0");
  const [horizonDays, setHorizonDays] = useState("90");

  const [result, setResult] = useState<WhatIfSimulationResult | null>(null);
  const [lastInput, setLastInput] =
    useState<WhatIfSimulationRequest | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function buildPayload(): WhatIfSimulationRequest {
    const base = {
      scenario_type: scenarioType,
      scenario_name: scenarioName.trim() || "Untitled scenario",
      safety_reserve_cents: Math.max(dollarsToCents(safetyReserve), 0),
      essential_spending_cents: Math.max(
        dollarsToCents(essentialSpending),
        0
      ),
      horizon_days: Math.min(
        Math.max(Math.round(Number(horizonDays) || 30), 1),
        90
      ),
    };

    if (scenarioType === "one_time_expense") {
      return {
        ...base,
        amount_cents: dollarsToCents(amount),
        effective_date: effectiveDate,
      };
    }

    if (scenarioType === "temporary_income_loss") {
      return {
        ...base,
        monthly_income_loss_cents: dollarsToCents(monthlyIncomeLoss),
        duration_months: Math.min(
          Math.max(Math.round(Number(durationMonths) || 1), 1),
          24
        ),
      };
    }

    return {
      ...base,
      monthly_amount_change_cents: dollarsToCents(monthlyAmountChange),
    };
  }

  function validate(payload: WhatIfSimulationRequest): string {
    if (payload.scenario_type === "one_time_expense") {
      if (!payload.amount_cents || payload.amount_cents <= 0) {
        return "Enter an amount greater than zero.";
      }
    } else if (payload.scenario_type === "temporary_income_loss") {
      if (
        !payload.monthly_income_loss_cents ||
        payload.monthly_income_loss_cents <= 0
      ) {
        return "Enter a monthly income loss greater than zero.";
      }
    } else if (
      !payload.monthly_amount_change_cents ||
      payload.monthly_amount_change_cents === 0
    ) {
      return "Enter a non-zero monthly amount (positive for an increase, negative for a decrease).";
    }

    return "";
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (userId === null) return;

    const payload = buildPayload();
    const validationError = validate(payload);

    if (validationError) {
      setError(validationError);
      return;
    }

    setLoading(true);
    setError("");

    try {
      const data = await api.simulateWhatIf(userId, payload);
      setResult(data);
      setLastInput(payload);
    } catch (err) {
      setResult(null);
      setError(
        err instanceof Error ? err.message : "Unable to run this simulation"
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="mt-8 grid gap-8 xl:grid-cols-[0.76fr_1.24fr]">
      <form
        onSubmit={handleSubmit}
        className="border-y border-[#181713]/10 bg-[#FFFCF7] p-6 sm:p-8"
      >
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#EDE5DE] text-[#6E4B63]">
            <Sparkles className="h-5 w-5" />
          </span>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
              Scenario inputs
            </p>
            <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em]">
              What would you like to test?
            </h2>
          </div>
        </div>

        <label className="mt-6 block">
          <span className="text-sm font-semibold text-[#2F2930]">
            Scenario type
          </span>
          <select
            value={scenarioType}
            onChange={(event) =>
              setScenarioType(event.target.value as WhatIfScenarioType)
            }
            className="mt-2 h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
          >
            {SCENARIO_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <div className="mt-4">
          <WhatIfField
            label="Scenario name"
            value={scenarioName}
            onChange={setScenarioName}
            placeholder="e.g. New laptop"
          />
        </div>

        {scenarioType === "one_time_expense" && (
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <WhatIfField
              label="Amount"
              value={amount}
              onChange={setAmount}
              type="number"
              prefix="$"
              min="0"
              step="0.01"
            />
            <label className="block">
              <span className="text-sm font-semibold text-[#2F2930]">
                Date
              </span>
              <input
                type="date"
                value={effectiveDate}
                onChange={(event) => setEffectiveDate(event.target.value)}
                className="mt-2 h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
              />
            </label>
          </div>
        )}

        {(scenarioType === "monthly_expense_change" ||
          scenarioType === "monthly_income_change" ||
          scenarioType === "monthly_savings_change") && (
          <div className="mt-4">
            <WhatIfField
              label="Monthly amount change"
              value={monthlyAmountChange}
              onChange={setMonthlyAmountChange}
              type="number"
              prefix="$"
              step="0.01"
              placeholder="Positive to increase, negative to decrease"
            />
            <p className="mt-1.5 text-xs text-[#8A8178]">
              Use a positive number for an increase, a negative number for a
              decrease.
            </p>
          </div>
        )}

        {scenarioType === "temporary_income_loss" && (
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <WhatIfField
              label="Monthly income loss"
              value={monthlyIncomeLoss}
              onChange={setMonthlyIncomeLoss}
              type="number"
              prefix="$"
              min="0"
              step="0.01"
            />
            <WhatIfField
              label="Duration"
              value={durationMonths}
              onChange={setDurationMonths}
              type="number"
              min="1"
              step="1"
            />
          </div>
        )}

        <div className="mt-6 grid gap-4 border-t border-[#181713]/[0.07] pt-5 sm:grid-cols-3">
          <WhatIfField
            label="Safety reserve"
            value={safetyReserve}
            onChange={setSafetyReserve}
            type="number"
            prefix="$"
            min="0"
            step="0.01"
          />
          <WhatIfField
            label="Essential spending"
            value={essentialSpending}
            onChange={setEssentialSpending}
            type="number"
            prefix="$"
            min="0"
            step="0.01"
          />
          <WhatIfField
            label="Horizon (days)"
            value={horizonDays}
            onChange={setHorizonDays}
            type="number"
            min="1"
            max="90"
            step="1"
          />
        </div>

        {error && (
          <div className="mt-5 rounded-2xl border border-[#b65743]/20 bg-[#f0b8a8]/35 px-4 py-3 text-sm text-[#843d2f]">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading || userId === null}
          className="discero-button-primary mt-7 inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold transition disabled:cursor-not-allowed"
        >
          {loading ? "Running simulation..." : "Run simulation"}
        </button>
      </form>

      {result ? (
        <div className="space-y-3">
          <WhatIfResultPanel result={result} />
          {userId !== null && lastInput && (
            <SaveWhatIfButton
              userId={userId}
              defaultTitle={result.scenario_name}
              input={lastInput}
            />
          )}
        </div>
      ) : (
        <article className="flex min-h-[420px] flex-col items-center justify-center border-y border-[#181713]/10 bg-[#FFFCF7] p-8 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-[#EDE5DE] text-[#6E4B63]">
            <Sparkles className="h-7 w-7" />
          </span>
          <h2 className="mt-6 text-2xl font-semibold tracking-[-0.035em]">
            See what changes before it happens
          </h2>
          <p className="mt-3 max-w-md text-sm leading-6 text-[#6d7a74]">
            Model a hypothetical change and compare it against your real
            safe-to-spend baseline -- nothing is saved unless you choose to.
          </p>
        </article>
      )}
    </section>
  );
}

function WhatIfResultPanel({ result }: { result: WhatIfSimulationResult }) {
  const impactContent = IMPACT_CONTENT[result.impact.level];
  const ImpactIcon = impactContent.icon;
  const confidenceLabel =
    CONFIDENCE_LABEL[result.scenario.confidence_level] ?? "Medium";

  return (
    <article className="relative overflow-hidden rounded-[30px] bg-[#181713] p-7 text-white shadow-[0_24px_70px_rgba(60,43,35,0.2)] sm:p-9">
      <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-[#C89A78]/15 blur-3xl" />

      <div className="relative">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#D2B199]">
              What-if result
            </p>
            <h2 className="mt-3 text-3xl font-semibold tracking-[-0.045em]">
              {result.scenario_name}
            </h2>
            <p className="mt-2 text-sm text-white/50">
              Through{" "}
              {new Date(`${result.through_date}T00:00:00`).toLocaleDateString(
                "en-US",
                { month: "long", day: "numeric", year: "numeric" }
              )}
            </p>
          </div>

          <span
            className={`inline-flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${impactContent.className}`}
          >
            <ImpactIcon className="h-4 w-4" />
            {impactContent.label}
          </span>
        </div>

        <div className="mt-9 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-2">
          <div className="bg-white/[0.045] p-5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/35">
              Baseline
            </p>
            <p className="mt-2 text-3xl font-semibold tracking-[-0.04em]">
              {formatCents(result.baseline.safe_to_spend_cents)}
            </p>
            {result.baseline.shortfall_cents > 0 && (
              <p className="mt-1 text-xs text-[#f4a594]">
                Shortfall {formatCents(result.baseline.shortfall_cents)}
              </p>
            )}
          </div>
          <div className="bg-white/[0.045] p-5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/35">
              After this change
            </p>
            <p className="mt-2 text-3xl font-semibold tracking-[-0.04em]">
              {formatCents(result.scenario.safe_to_spend_cents)}
            </p>
            {result.scenario.shortfall_cents > 0 && (
              <p className="mt-1 text-xs text-[#f4a594]">
                Shortfall {formatCents(result.scenario.shortfall_cents)}
              </p>
            )}
          </div>
        </div>

        <div className="mt-9 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-3">
          <WhatIfResultMetric
            label="Safe-to-spend impact"
            value={`${result.impact.safe_to_spend_delta_cents >= 0 ? "+" : ""}${formatCents(
              result.impact.safe_to_spend_delta_cents
            )}`}
            warning={result.impact.safe_to_spend_delta_cents < 0}
          />
          <WhatIfResultMetric
            label="Shortfall impact"
            value={`${result.impact.shortfall_delta_cents >= 0 ? "+" : ""}${formatCents(
              result.impact.shortfall_delta_cents
            )}`}
            warning={result.impact.shortfall_delta_cents > 0}
          />
          <WhatIfResultMetric
            label="Confidence"
            value={`${confidenceLabel} (${Math.round(
              result.scenario.confidence_score
            )}%)`}
          />
        </div>

        <div className="mt-7 rounded-2xl border border-white/10 bg-white/[0.045] p-5">
          <div className="flex items-start gap-3">
            <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-[#D2B199]" />
            <div>
              <p className="text-sm font-semibold">Why this changes</p>
              <ul className="mt-2 space-y-1.5 text-sm leading-6 text-white/58">
                {result.explanation.map((item) => (
                  <li key={item.code}>{item.message}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        {result.goal_impacts.length > 0 && (
          <GoalImpactList goalImpacts={result.goal_impacts} />
        )}

        <div className="mt-7 grid gap-4 sm:grid-cols-2">
          <div className="flex items-start gap-3 border border-white/10 bg-white/[0.045] p-4">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-[#D2B199]" />
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-white/35">
                Safety reserve protected
              </p>
              <p className="mt-2 text-lg font-semibold">
                {formatCents(
                  result.safe_to_spend.breakdown.safety_reserve_cents
                )}
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3 border border-white/10 bg-white/[0.045] p-4">
            <Gauge className="mt-0.5 h-5 w-5 shrink-0 text-[#D2B199]" />
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-white/35">
                Upcoming obligations protected
              </p>
              <p className="mt-2 text-lg font-semibold">
                {formatCents(
                  result.safe_to_spend.breakdown.upcoming_obligations_cents
                )}
              </p>
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}

function WhatIfResultMetric({
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
          warning ? "text-[#f4a594]" : ""
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function WhatIfField({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  prefix,
  min,
  max,
  step,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "number";
  placeholder?: string;
  prefix?: string;
  min?: string;
  max?: string;
  step?: string;
}) {
  return (
    <label className="block">
      <span className="text-sm font-semibold text-[#2F2930]">{label}</span>
      <div className="relative mt-2">
        {prefix && (
          <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-sm font-semibold text-[#777168]">
            {prefix}
          </span>
        )}
        <input
          type={type}
          value={value}
          min={min}
          max={max}
          step={step}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          className={`h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] pr-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white ${
            prefix ? "pl-9" : "pl-4"
          }`}
        />
      </div>
    </label>
  );
}

function SaveWhatIfButton({
  userId,
  defaultTitle,
  input,
}: {
  userId: number;
  defaultTitle: string;
  input: WhatIfSimulationRequest;
}) {
  const [status, setStatus] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");

  async function handleSave() {
    setStatus("saving");

    try {
      await api.saveDecision(userId, {
        decision_type: "what_if" as DecisionType,
        title: defaultTitle.trim() || "Saved scenario",
        input: input as unknown as Record<string, unknown>,
      });
      setStatus("saved");
    } catch {
      setStatus("error");
    }
  }

  if (status === "saved") {
    return (
      <p className="text-sm font-semibold text-[#6E4B63]">
        Saved to your decision history.
      </p>
    );
  }

  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={handleSave}
        disabled={status === "saving"}
        className="discero-button-secondary rounded-full border px-4 py-2 text-sm font-semibold transition disabled:opacity-50"
      >
        {status === "saving" ? "Saving..." : "Save this scenario"}
      </button>

      {status === "error" && (
        <span className="text-xs font-medium text-[#a64b3d]">
          Couldn&apos;t save just now.
        </span>
      )}
    </div>
  );
}
