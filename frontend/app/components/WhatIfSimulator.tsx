"use client";

import {
  CheckCircle2,
  CircleAlert,
  Gauge,
  Lightbulb,
  Plus,
  Scale,
  ShieldCheck,
  Sparkles,
  Trash2,
  Trophy,
  TriangleAlert,
} from "lucide-react";
import { FormEvent, useMemo, useRef, useState } from "react";
import {
  api,
  DecisionType,
  formatCents,
  WhatIfComparisonRequest,
  WhatIfComparisonResult,
  WhatIfComparisonScenarioRequest,
  WhatIfComparisonScenarioResult,
  WhatIfImpact,
  WhatIfScenarioType,
  WhatIfSimulationRequest,
  WhatIfSimulationResult,
} from "../lib/api";
import AdaptiveIntelligenceSection from "./AdaptiveIntelligenceSection";
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

const MAX_COMPARISON_SCENARIOS = 3;
const MIN_COMPARISON_SCENARIOS = 2;

export default function WhatIfSimulator({
  userId,
}: {
  userId: number | null;
}) {
  const [mode, setMode] = useState<"single" | "compare">("single");

  return (
    <section className="mt-8">
      <div className="inline-flex rounded-full border border-[#181713]/10 bg-[#FFFCF7] p-1">
        <button
          type="button"
          onClick={() => setMode("single")}
          className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
            mode === "single"
              ? "bg-[#181713] text-white"
              : "text-[#6d655c] hover:text-[#181713]"
          }`}
        >
          Single scenario
        </button>
        <button
          type="button"
          onClick={() => setMode("compare")}
          className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
            mode === "compare"
              ? "bg-[#181713] text-white"
              : "text-[#6d655c] hover:text-[#181713]"
          }`}
        >
          Compare scenarios
        </button>
      </div>

      {mode === "single" ? (
        <SingleWhatIfSimulator userId={userId} />
      ) : (
        <WhatIfComparisonPanel userId={userId} />
      )}
    </section>
  );
}

function SingleWhatIfSimulator({ userId }: { userId: number | null }) {
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
    <div className="mt-6 grid gap-8 xl:grid-cols-[0.76fr_1.24fr]">
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

        <ScenarioTypeFields
          scenarioType={scenarioType}
          amount={amount}
          onAmountChange={setAmount}
          effectiveDate={effectiveDate}
          onEffectiveDateChange={setEffectiveDate}
          monthlyAmountChange={monthlyAmountChange}
          onMonthlyAmountChangeChange={setMonthlyAmountChange}
          monthlyIncomeLoss={monthlyIncomeLoss}
          onMonthlyIncomeLossChange={setMonthlyIncomeLoss}
          durationMonths={durationMonths}
          onDurationMonthsChange={setDurationMonths}
        />

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
          {userId !== null && (
            <AdaptiveIntelligenceSection userId={userId} />
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
    </div>
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
          <GoalImpactList
            goalImpacts={result.goal_impacts}
            conflictIntelligence={result.goal_conflict_intelligence}
          />
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

function ScenarioTypeFields({
  scenarioType,
  amount,
  onAmountChange,
  effectiveDate,
  onEffectiveDateChange,
  monthlyAmountChange,
  onMonthlyAmountChangeChange,
  monthlyIncomeLoss,
  onMonthlyIncomeLossChange,
  durationMonths,
  onDurationMonthsChange,
}: {
  scenarioType: WhatIfScenarioType;
  amount: string;
  onAmountChange: (value: string) => void;
  effectiveDate: string;
  onEffectiveDateChange: (value: string) => void;
  monthlyAmountChange: string;
  onMonthlyAmountChangeChange: (value: string) => void;
  monthlyIncomeLoss: string;
  onMonthlyIncomeLossChange: (value: string) => void;
  durationMonths: string;
  onDurationMonthsChange: (value: string) => void;
}) {
  if (scenarioType === "one_time_expense") {
    return (
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <WhatIfField
          label="Amount"
          value={amount}
          onChange={onAmountChange}
          type="number"
          prefix="$"
          min="0"
          step="0.01"
        />
        <label className="block">
          <span className="text-sm font-semibold text-[#2F2930]">Date</span>
          <input
            type="date"
            value={effectiveDate}
            onChange={(event) => onEffectiveDateChange(event.target.value)}
            className="mt-2 h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
          />
        </label>
      </div>
    );
  }

  if (scenarioType === "temporary_income_loss") {
    return (
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <WhatIfField
          label="Monthly income loss"
          value={monthlyIncomeLoss}
          onChange={onMonthlyIncomeLossChange}
          type="number"
          prefix="$"
          min="0"
          step="0.01"
        />
        <WhatIfField
          label="Duration"
          value={durationMonths}
          onChange={onDurationMonthsChange}
          type="number"
          min="1"
          step="1"
        />
      </div>
    );
  }

  return (
    <div className="mt-4">
      <WhatIfField
        label="Monthly amount change"
        value={monthlyAmountChange}
        onChange={onMonthlyAmountChangeChange}
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

type ComparisonScenarioDraft = {
  id: number;
  label: string;
  scenarioType: WhatIfScenarioType;
  amount: string;
  effectiveDate: string;
  monthlyAmountChange: string;
  monthlyIncomeLoss: string;
  durationMonths: string;
};

function buildComparisonScenarioPayload(
  draft: ComparisonScenarioDraft
): WhatIfComparisonScenarioRequest {
  const base = {
    label: draft.label.trim() || "Untitled scenario",
    scenario_type: draft.scenarioType,
  };

  if (draft.scenarioType === "one_time_expense") {
    return {
      ...base,
      amount_cents: dollarsToCents(draft.amount),
      effective_date: draft.effectiveDate,
    };
  }

  if (draft.scenarioType === "temporary_income_loss") {
    return {
      ...base,
      monthly_income_loss_cents: dollarsToCents(draft.monthlyIncomeLoss),
      duration_months: Math.min(
        Math.max(Math.round(Number(draft.durationMonths) || 1), 1),
        24
      ),
    };
  }

  return {
    ...base,
    monthly_amount_change_cents: dollarsToCents(draft.monthlyAmountChange),
  };
}

function validateComparisonDraft(draft: ComparisonScenarioDraft): string {
  if (!draft.label.trim()) {
    return "Every scenario needs a label.";
  }

  if (draft.scenarioType === "one_time_expense") {
    if (dollarsToCents(draft.amount) <= 0) {
      return `Enter an amount greater than zero for "${draft.label}".`;
    }
  } else if (draft.scenarioType === "temporary_income_loss") {
    if (dollarsToCents(draft.monthlyIncomeLoss) <= 0) {
      return `Enter a monthly income loss greater than zero for "${draft.label}".`;
    }
  } else if (dollarsToCents(draft.monthlyAmountChange) === 0) {
    return `Enter a non-zero monthly amount for "${draft.label}".`;
  }

  return "";
}

const KEY_DRIVER_LABEL: Record<WhatIfComparisonResult["key_driver"], string> =
  {
    shortfall: "Shortfall risk",
    safe_to_spend: "Remaining safe-to-spend",
    goal_impact: "Goal impact",
    tie: "No meaningful difference",
  };

function WhatIfComparisonPanel({ userId }: { userId: number | null }) {
  const today = useMemo(() => new Date(), []);
  const nextIdRef = useRef(2);

  const [scenarios, setScenarios] = useState<ComparisonScenarioDraft[]>([
    {
      id: 0,
      label: "Buy now",
      scenarioType: "one_time_expense",
      amount: "2000",
      effectiveDate: toDateInputValue(addDays(today, 7)),
      monthlyAmountChange: "300",
      monthlyIncomeLoss: "2500",
      durationMonths: "2",
    },
    {
      id: 1,
      label: "Wait 3 months",
      scenarioType: "one_time_expense",
      amount: "2000",
      effectiveDate: toDateInputValue(addDays(today, 90)),
      monthlyAmountChange: "300",
      monthlyIncomeLoss: "2500",
      durationMonths: "2",
    },
  ]);
  const [horizonDays, setHorizonDays] = useState("90");
  const [safetyReserve, setSafetyReserve] = useState("0");
  const [essentialSpending, setEssentialSpending] = useState("0");

  const [result, setResult] = useState<WhatIfComparisonResult | null>(null);
  const [lastInput, setLastInput] =
    useState<WhatIfComparisonRequest | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function updateScenario(
    id: number,
    patch: Partial<ComparisonScenarioDraft>
  ) {
    setScenarios((current) =>
      current.map((draft) =>
        draft.id === id ? { ...draft, ...patch } : draft
      )
    );
  }

  function addScenario() {
    if (scenarios.length >= MAX_COMPARISON_SCENARIOS) return;

    const id = nextIdRef.current;
    nextIdRef.current += 1;

    setScenarios((current) => [
      ...current,
      {
        id,
        label: `Scenario ${current.length + 1}`,
        scenarioType: "one_time_expense",
        amount: "2000",
        effectiveDate: toDateInputValue(addDays(today, 7)),
        monthlyAmountChange: "300",
        monthlyIncomeLoss: "2500",
        durationMonths: "2",
      },
    ]);
  }

  function removeScenario(id: number) {
    if (scenarios.length <= MIN_COMPARISON_SCENARIOS) return;
    setScenarios((current) => current.filter((draft) => draft.id !== id));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (userId === null) return;

    for (const draft of scenarios) {
      const validationError = validateComparisonDraft(draft);
      if (validationError) {
        setError(validationError);
        return;
      }
    }

    const labels = scenarios.map((draft) => draft.label.trim().toLowerCase());
    if (new Set(labels).size !== labels.length) {
      setError("Scenario labels must be unique.");
      return;
    }

    const payload: WhatIfComparisonRequest = {
      horizon_days: Math.min(
        Math.max(Math.round(Number(horizonDays) || 30), 1),
        90
      ),
      safety_reserve_cents: Math.max(dollarsToCents(safetyReserve), 0),
      essential_spending_cents: Math.max(
        dollarsToCents(essentialSpending),
        0
      ),
      scenarios: scenarios.map(buildComparisonScenarioPayload),
    };

    setLoading(true);
    setError("");

    try {
      const data = await api.compareWhatIfScenarios(userId, payload);
      setResult(data);
      setLastInput(payload);
    } catch (err) {
      setResult(null);
      setError(
        err instanceof Error ? err.message : "Unable to run this comparison"
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mt-6">
      <form
        onSubmit={handleSubmit}
        className="border-y border-[#181713]/10 bg-[#FFFCF7] p-6 sm:p-8"
      >
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#EDE5DE] text-[#6E4B63]">
            <Scale className="h-5 w-5" />
          </span>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
              Scenario comparison
            </p>
            <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em]">
              Which option is financially stronger?
            </h2>
          </div>
        </div>

        <div className="mt-6 grid gap-4 sm:grid-cols-3">
          {scenarios.map((draft, index) => (
            <div
              key={draft.id}
              className="rounded-2xl border border-[#181713]/10 bg-white p-5"
            >
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-[0.13em] text-[#8A8178]">
                  Scenario {index + 1}
                </p>
                {scenarios.length > MIN_COMPARISON_SCENARIOS && (
                  <button
                    type="button"
                    onClick={() => removeScenario(draft.id)}
                    aria-label={`Remove ${draft.label || `scenario ${index + 1}`}`}
                    className="text-[#8A8178] transition hover:text-[#B75C50]"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>

              <div className="mt-3">
                <WhatIfField
                  label="Label"
                  value={draft.label}
                  onChange={(value) =>
                    updateScenario(draft.id, { label: value })
                  }
                  placeholder="e.g. Buy now"
                />
              </div>

              <label className="mt-3 block">
                <span className="text-sm font-semibold text-[#2F2930]">
                  Scenario type
                </span>
                <select
                  value={draft.scenarioType}
                  onChange={(event) =>
                    updateScenario(draft.id, {
                      scenarioType: event.target.value as WhatIfScenarioType,
                    })
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

              <ScenarioTypeFields
                scenarioType={draft.scenarioType}
                amount={draft.amount}
                onAmountChange={(value) =>
                  updateScenario(draft.id, { amount: value })
                }
                effectiveDate={draft.effectiveDate}
                onEffectiveDateChange={(value) =>
                  updateScenario(draft.id, { effectiveDate: value })
                }
                monthlyAmountChange={draft.monthlyAmountChange}
                onMonthlyAmountChangeChange={(value) =>
                  updateScenario(draft.id, { monthlyAmountChange: value })
                }
                monthlyIncomeLoss={draft.monthlyIncomeLoss}
                onMonthlyIncomeLossChange={(value) =>
                  updateScenario(draft.id, { monthlyIncomeLoss: value })
                }
                durationMonths={draft.durationMonths}
                onDurationMonthsChange={(value) =>
                  updateScenario(draft.id, { durationMonths: value })
                }
              />
            </div>
          ))}

          {scenarios.length < MAX_COMPARISON_SCENARIOS && (
            <button
              type="button"
              onClick={addScenario}
              className="flex min-h-[160px] flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-[#181713]/20 text-sm font-semibold text-[#6E4B63] transition hover:border-[#6E4B63] hover:bg-[#EDE5DE]/40"
            >
              <Plus className="h-5 w-5" />
              Add scenario C
            </button>
          )}
        </div>

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
          {loading ? "Comparing scenarios..." : "Run comparison"}
        </button>
      </form>

      {result && (
        <div className="mt-8 space-y-3">
          <WhatIfComparisonResultPanel result={result} />
          {userId !== null && lastInput && (
            <SaveWhatIfComparisonButton
              userId={userId}
              defaultTitle={
                result.recommended_label
                  ? `${result.scenarios.map((s) => s.label).join(" vs ")}`
                  : "Scenario comparison"
              }
              input={lastInput}
            />
          )}
          {userId !== null && (
            <AdaptiveIntelligenceSection userId={userId} />
          )}
        </div>
      )}
    </div>
  );
}

function WhatIfComparisonResultPanel({
  result,
}: {
  result: WhatIfComparisonResult;
}) {
  return (
    <article className="relative overflow-hidden rounded-[30px] bg-[#181713] p-7 text-white shadow-[0_24px_70px_rgba(60,43,35,0.2)] sm:p-9">
      <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-[#C89A78]/15 blur-3xl" />

      <div className="relative">
        <div className="flex items-start gap-3">
          <span
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ${
              result.is_tie
                ? "bg-white/10 text-white/70"
                : "bg-[#58715A]/25 text-[#9FC29F]"
            }`}
          >
            <Trophy className="h-5 w-5" />
          </span>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#D2B199]">
              {result.is_tie ? "No clear winner" : "Recommended"}
            </p>
            <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] sm:text-3xl">
              {result.recommended_label ?? "These scenarios are close"}
            </h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-white/65">
              {result.recommendation_reason}
            </p>
          </div>
        </div>

        <div className="mt-8 grid gap-4 lg:grid-cols-3">
          {result.scenarios.map((scenario) => (
            <ComparisonScenarioResultCard
              key={scenario.label}
              scenario={scenario}
              isRecommended={scenario.label === result.recommended_label}
            />
          ))}
        </div>

        {result.key_tradeoff && (
          <div className="mt-7 rounded-2xl border border-white/10 bg-white/[0.045] p-5">
            <div className="flex items-start gap-3">
              <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-[#D2B199]" />
              <div>
                <p className="text-sm font-semibold">Key tradeoff</p>
                <p className="mt-1.5 text-sm leading-6 text-white/58">
                  {result.key_tradeoff}
                </p>
              </div>
            </div>
          </div>
        )}

        <p className="mt-5 text-xs uppercase tracking-[0.13em] text-white/35">
          Key driver: {KEY_DRIVER_LABEL[result.key_driver]}
        </p>
      </div>
    </article>
  );
}

function ComparisonScenarioResultCard({
  scenario,
  isRecommended,
}: {
  scenario: WhatIfComparisonScenarioResult;
  isRecommended: boolean;
}) {
  const confidenceLabel =
    CONFIDENCE_LABEL[scenario.confidence_level] ?? "Medium";

  return (
    <div
      className={`rounded-2xl border p-5 ${
        isRecommended
          ? "border-[#58715A]/60 bg-[#58715A]/[0.12]"
          : "border-white/10 bg-white/[0.045]"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-white">{scenario.label}</p>
        {isRecommended && (
          <span className="rounded-full bg-[#58715A]/25 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-[#9FC29F]">
            Recommended
          </span>
        )}
      </div>

      <dl className="mt-4 space-y-2.5 text-sm">
        <div className="flex items-center justify-between">
          <dt className="text-white/45">Safe to spend</dt>
          <dd className="font-semibold">
            {formatCents(scenario.safe_to_spend_cents)}
          </dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-white/45">Shortfall</dt>
          <dd
            className={`font-semibold ${
              scenario.shortfall_cents > 0 ? "text-[#f4a594]" : ""
            }`}
          >
            {formatCents(scenario.shortfall_cents)}
          </dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-white/45">Confidence</dt>
          <dd className="font-semibold">
            {confidenceLabel} ({Math.round(scenario.confidence_score)}%)
          </dd>
        </div>
      </dl>

      {scenario.goal_impacts.length > 0 && (
        <p className="mt-4 text-xs leading-5 text-white/50">
          Affects {scenario.goal_impacts.length} active goal
          {scenario.goal_impacts.length === 1 ? "" : "s"}.
        </p>
      )}
    </div>
  );
}

function SaveWhatIfComparisonButton({
  userId,
  defaultTitle,
  input,
}: {
  userId: number;
  defaultTitle: string;
  input: WhatIfComparisonRequest;
}) {
  const [status, setStatus] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");

  async function handleSave() {
    setStatus("saving");

    try {
      await api.saveDecision(userId, {
        decision_type: "what_if_comparison" as DecisionType,
        title: defaultTitle.trim() || "Saved comparison",
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
        {status === "saving" ? "Saving..." : "Save this comparison"}
      </button>

      {status === "error" && (
        <span className="text-xs font-medium text-[#a64b3d]">
          Couldn&apos;t save just now.
        </span>
      )}
    </div>
  );
}
