"use client";

import {
  ArrowRight,
  CalendarClock,
  Layers,
  Plus,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { FormEvent, useMemo, useRef, useState } from "react";
import {
  api,
  formatCents,
  MultiStepScenarioCheckpoint,
  MultiStepScenarioPlanRequest,
  MultiStepScenarioPlanResult,
  MultiStepScenarioStepType,
} from "../lib/api";
import GoalImpactList from "./GoalImpactList";

const MIN_STEPS = 2;
const MAX_STEPS = 5;

const STEP_TYPE_OPTIONS: { value: MultiStepScenarioStepType; label: string }[] =
  [
    { value: "one_time_expense", label: "One-time expense / purchase" },
    { value: "monthly_expense_increase", label: "Monthly expense increase" },
    { value: "monthly_expense_decrease", label: "Monthly expense decrease" },
    { value: "monthly_income_increase", label: "Monthly income increase" },
    { value: "monthly_income_decrease", label: "Monthly income decrease" },
    { value: "temporary_income_loss", label: "Temporary income loss" },
    { value: "temporary_expense_shock", label: "Unexpected expense / shock" },
  ];

const AMOUNT_STEP_TYPES = new Set<MultiStepScenarioStepType>([
  "one_time_expense",
  "monthly_expense_increase",
  "monthly_expense_decrease",
  "monthly_income_increase",
  "monthly_income_decrease",
  "temporary_expense_shock",
]);

const STATUS_CONTENT: Record<
  MultiStepScenarioCheckpoint["status"],
  { label: string; className: string }
> = {
  comfortable: {
    label: "Comfortable",
    className: "bg-[#dff6c7] text-[#315d31]",
  },
  tight: { label: "Tight", className: "bg-[#f5d66f] text-[#66500f]" },
  shortfall: {
    label: "Shortfall",
    className: "bg-[#f0b8a8] text-[#7b3528]",
  },
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

function formatPlanDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

type StepDraft = {
  id: number;
  stepType: MultiStepScenarioStepType;
  label: string;
  effectiveDate: string;
  amount: string;
  monthlyIncomeLoss: string;
  durationMonths: string;
};

function buildStepPayload(draft: StepDraft) {
  const base = {
    step_type: draft.stepType,
    label: draft.label.trim() || "Untitled step",
    effective_date: draft.effectiveDate,
  };

  if (draft.stepType === "temporary_income_loss") {
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
    amount_cents: dollarsToCents(draft.amount),
  };
}

function validateStepDraft(draft: StepDraft, index: number): string {
  if (!draft.label.trim()) {
    return `Step ${index + 1} needs a label.`;
  }

  if (!draft.effectiveDate) {
    return `Step ${index + 1} needs a date.`;
  }

  if (draft.stepType === "temporary_income_loss") {
    if (dollarsToCents(draft.monthlyIncomeLoss) <= 0) {
      return `Enter a monthly income loss greater than zero for step ${index + 1}.`;
    }
    return "";
  }

  if (dollarsToCents(draft.amount) <= 0) {
    return `Enter an amount greater than zero for step ${index + 1}.`;
  }

  return "";
}

export default function MultiStepScenarioPlanner({
  userId,
}: {
  userId: number | null;
}) {
  const today = useMemo(() => new Date(), []);
  const nextIdRef = useRef(2);

  const [planName, setPlanName] = useState("");
  const [horizonDays, setHorizonDays] = useState("90");
  const [safetyReserve, setSafetyReserve] = useState("0");
  const [essentialSpending, setEssentialSpending] = useState("0");

  const [steps, setSteps] = useState<StepDraft[]>([
    {
      id: 0,
      stepType: "one_time_expense",
      label: "Laptop purchase",
      effectiveDate: toDateInputValue(today),
      amount: "2000",
      monthlyIncomeLoss: "2500",
      durationMonths: "1",
    },
    {
      id: 1,
      stepType: "monthly_expense_increase",
      label: "Rent increase",
      effectiveDate: toDateInputValue(addDays(today, 30)),
      amount: "250",
      monthlyIncomeLoss: "2500",
      durationMonths: "1",
    },
  ]);

  const [result, setResult] = useState<MultiStepScenarioPlanResult | null>(
    null
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function updateStep(id: number, patch: Partial<StepDraft>) {
    setSteps((current) =>
      current.map((draft) => (draft.id === id ? { ...draft, ...patch } : draft))
    );
  }

  function addStep() {
    if (steps.length >= MAX_STEPS) return;

    const id = nextIdRef.current;
    nextIdRef.current += 1;

    setSteps((current) => [
      ...current,
      {
        id,
        stepType: "one_time_expense",
        label: `Step ${current.length + 1}`,
        effectiveDate: toDateInputValue(addDays(today, 14)),
        amount: "500",
        monthlyIncomeLoss: "2500",
        durationMonths: "1",
      },
    ]);
  }

  function removeStep(id: number) {
    if (steps.length <= MIN_STEPS) return;
    setSteps((current) => current.filter((draft) => draft.id !== id));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (userId === null) return;

    for (const [index, draft] of steps.entries()) {
      const validationError = validateStepDraft(draft, index);
      if (validationError) {
        setError(validationError);
        return;
      }
    }

    const payload: MultiStepScenarioPlanRequest = {
      name: planName.trim() || null,
      horizon_days: Math.min(
        Math.max(Math.round(Number(horizonDays) || 90), 1),
        90
      ),
      safety_reserve_cents: Math.max(dollarsToCents(safetyReserve), 0),
      essential_spending_cents: Math.max(
        dollarsToCents(essentialSpending),
        0
      ),
      steps: steps.map(buildStepPayload),
    };

    setLoading(true);
    setError("");

    try {
      const data = await api.runMultiStepScenarioPlan(userId, payload);
      setResult(data);
    } catch (err) {
      setResult(null);
      setError(
        err instanceof Error
          ? err.message
          : "Unable to run this plan just now."
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
            <Layers className="h-5 w-5" />
          </span>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
              Multi-step plan
            </p>
            <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em]">
              What happens over time?
            </h2>
          </div>
        </div>

        <label className="mt-6 block">
          <span className="text-sm font-semibold text-[#2F2930]">
            Plan name (optional)
          </span>
          <input
            type="text"
            value={planName}
            onChange={(event) => setPlanName(event.target.value)}
            placeholder="e.g. Laptop + income loss + rent increase"
            className="mt-2 h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
          />
        </label>

        <fieldset className="mt-6">
          <legend className="text-sm font-semibold text-[#2F2930]">
            Steps
          </legend>

          <div className="mt-3 space-y-4">
            {steps.map((draft, index) => (
              <div
                key={draft.id}
                className="border border-[#181713]/10 bg-white p-5"
              >
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold uppercase tracking-[0.13em] text-[#8A8178]">
                    Step {index + 1}
                  </p>
                  {steps.length > MIN_STEPS && (
                    <button
                      type="button"
                      onClick={() => removeStep(draft.id)}
                      aria-label={`Remove ${draft.label || `step ${index + 1}`}`}
                      className="focus-ring text-[#8A8178] transition hover:text-[#B75C50]"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>

                <label className="mt-3 block">
                  <span className="text-sm font-semibold text-[#2F2930]">
                    Step type
                  </span>
                  <select
                    value={draft.stepType}
                    onChange={(event) =>
                      updateStep(draft.id, {
                        stepType: event.target
                          .value as MultiStepScenarioStepType,
                      })
                    }
                    className="mt-2 h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
                  >
                    {STEP_TYPE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="mt-3 block">
                  <span className="text-sm font-semibold text-[#2F2930]">
                    Label
                  </span>
                  <input
                    type="text"
                    value={draft.label}
                    onChange={(event) =>
                      updateStep(draft.id, { label: event.target.value })
                    }
                    placeholder="e.g. Rent increase"
                    className="mt-2 h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
                  />
                </label>

                <label className="mt-3 block">
                  <span className="text-sm font-semibold text-[#2F2930]">
                    Date
                  </span>
                  <input
                    type="date"
                    value={draft.effectiveDate}
                    onChange={(event) =>
                      updateStep(draft.id, {
                        effectiveDate: event.target.value,
                      })
                    }
                    className="mt-2 h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
                  />
                </label>

                {AMOUNT_STEP_TYPES.has(draft.stepType) ? (
                  <label className="mt-3 block">
                    <span className="text-sm font-semibold text-[#2F2930]">
                      {draft.stepType.startsWith("monthly")
                        ? "Monthly amount"
                        : "Amount"}
                    </span>
                    <div className="relative mt-2">
                      <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-sm font-semibold text-[#777168]">
                        $
                      </span>
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={draft.amount}
                        onChange={(event) =>
                          updateStep(draft.id, { amount: event.target.value })
                        }
                        className="h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] pl-9 pr-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
                      />
                    </div>
                  </label>
                ) : (
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    <label className="block">
                      <span className="text-sm font-semibold text-[#2F2930]">
                        Monthly income loss
                      </span>
                      <div className="relative mt-2">
                        <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-sm font-semibold text-[#777168]">
                          $
                        </span>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          value={draft.monthlyIncomeLoss}
                          onChange={(event) =>
                            updateStep(draft.id, {
                              monthlyIncomeLoss: event.target.value,
                            })
                          }
                          className="h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] pl-9 pr-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
                        />
                      </div>
                    </label>
                    <label className="block">
                      <span className="text-sm font-semibold text-[#2F2930]">
                        Duration (months)
                      </span>
                      <input
                        type="number"
                        min="1"
                        max="24"
                        step="1"
                        value={draft.durationMonths}
                        onChange={(event) =>
                          updateStep(draft.id, {
                            durationMonths: event.target.value,
                          })
                        }
                        className="mt-2 h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
                      />
                    </label>
                  </div>
                )}
              </div>
            ))}
          </div>

          {steps.length < MAX_STEPS && (
            <button
              type="button"
              onClick={addStep}
              className="focus-ring mt-4 flex w-full items-center justify-center gap-2 border border-dashed border-[#181713]/20 py-3 text-sm font-semibold text-[#6E4B63] transition hover:border-[#6E4B63] hover:bg-[#EDE5DE]/40"
            >
              <Plus className="h-4 w-4" />
              Add step
            </button>
          )}
        </fieldset>

        <div className="mt-6 grid gap-4 border-t border-[#181713]/[0.07] pt-5 sm:grid-cols-3">
          <label className="block">
            <span className="text-sm font-semibold text-[#2F2930]">
              Safety reserve
            </span>
            <div className="relative mt-2">
              <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-sm font-semibold text-[#777168]">
                $
              </span>
              <input
                type="number"
                min="0"
                step="0.01"
                value={safetyReserve}
                onChange={(event) => setSafetyReserve(event.target.value)}
                className="h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] pl-9 pr-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
              />
            </div>
          </label>
          <label className="block">
            <span className="text-sm font-semibold text-[#2F2930]">
              Essential spending
            </span>
            <div className="relative mt-2">
              <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-sm font-semibold text-[#777168]">
                $
              </span>
              <input
                type="number"
                min="0"
                step="0.01"
                value={essentialSpending}
                onChange={(event) => setEssentialSpending(event.target.value)}
                className="h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] pl-9 pr-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
              />
            </div>
          </label>
          <label className="block">
            <span className="text-sm font-semibold text-[#2F2930]">
              Horizon (days)
            </span>
            <input
              type="number"
              min="1"
              max="90"
              step="1"
              value={horizonDays}
              onChange={(event) => setHorizonDays(event.target.value)}
              className="mt-2 h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
            />
          </label>
        </div>

        {error && (
          <div
            role="alert"
            className="mt-5 rounded-2xl border border-[#b65743]/20 bg-[#f0b8a8]/35 px-4 py-3 text-sm text-[#843d2f]"
          >
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading || userId === null}
          className="discero-button-primary mt-7 inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold transition disabled:cursor-not-allowed"
        >
          {loading ? "Running plan..." : "Run analysis"}
        </button>
      </form>

      {result ? (
        <MultiStepResultPanel result={result} />
      ) : (
        <article className="flex min-h-[420px] flex-col items-center justify-center border-y border-[#181713]/10 bg-[#FFFCF7] p-8 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-[#EDE5DE] text-[#6E4B63]">
            <CalendarClock className="h-7 w-7" />
          </span>
          <h2 className="mt-6 text-2xl font-semibold tracking-[-0.035em]">
            See how events add up over time
          </h2>
          <p className="mt-3 max-w-md text-sm leading-6 text-[#6d7a74]">
            Add 2-5 dated events -- a purchase, an income change, a bill
            increase -- and Discero walks through them in order against
            your real safe-to-spend baseline.
          </p>
        </article>
      )}
    </div>
  );
}

function MultiStepResultPanel({
  result,
}: {
  result: MultiStepScenarioPlanResult;
}) {
  const statusContent = STATUS_CONTENT[result.overall_status];

  return (
    <div className="space-y-3">
      <article className="relative overflow-hidden rounded-[30px] bg-[#181713] p-7 text-white shadow-[0_24px_70px_rgba(60,43,35,0.2)] sm:p-9">
        <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-[#C89A78]/15 blur-3xl" />

        <div className="relative">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#D2B199]">
                Multi-step result
              </p>
              <h2 className="mt-3 text-3xl font-semibold tracking-[-0.045em]">
                {result.name ?? "Multi-step plan"}
              </h2>
              <p className="mt-2 text-sm text-white/50">
                Through {formatPlanDate(result.through_date)}
              </p>
            </div>

            <span
              className={`inline-flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${statusContent.className}`}
            >
              {statusContent.label}
            </span>
          </div>

          <div className="mt-9 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-3">
            <div className="bg-white/[0.045] p-5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/35">
                Starting position
              </p>
              <p className="mt-2 text-3xl font-semibold tracking-[-0.04em]">
                {formatCents(result.starting_safe_to_spend_cents)}
              </p>
            </div>
            <div className="bg-white/[0.045] p-5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/35">
                Final position
              </p>
              <p className="mt-2 text-3xl font-semibold tracking-[-0.04em]">
                {formatCents(result.final_safe_to_spend_cents)}
              </p>
              {result.final_shortfall_cents > 0 && (
                <p className="mt-1 text-xs text-[#f4a594]">
                  Shortfall {formatCents(result.final_shortfall_cents)}
                </p>
              )}
            </div>
            <div className="bg-white/[0.045] p-5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/35">
                Worst point
              </p>
              <p className="mt-2 text-3xl font-semibold tracking-[-0.04em]">
                {formatCents(result.minimum_safe_to_spend_cents)}
              </p>
              {result.worst_checkpoint_label && (
                <p className="mt-1 text-xs text-white/50">
                  {result.worst_checkpoint_label}
                  {result.worst_checkpoint_date &&
                    ` on ${formatPlanDate(result.worst_checkpoint_date)}`}
                </p>
              )}
            </div>
          </div>

          <div className="mt-9">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-white/35">
              Timeline
            </p>
            <ol className="mt-3 space-y-3">
              {result.checkpoints.map((checkpoint) => (
                <li
                  key={checkpoint.sequence}
                  className="border border-white/10 bg-white/[0.045] p-4"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-semibold">
                      {checkpoint.sequence}. {formatPlanDate(checkpoint.effective_date)}{" "}
                      -- {checkpoint.label}
                    </p>
                    <div className="flex items-center gap-2">
                      {checkpoint.is_recurring && (
                        <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-white/60">
                          Recurring
                        </span>
                      )}
                      {checkpoint.is_temporary && (
                        <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-white/60">
                          Temporary
                          {checkpoint.expires_on &&
                            ` until ${formatPlanDate(checkpoint.expires_on)}`}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-white/60">
                    <span>{formatCents(checkpoint.safe_to_spend_before_cents)}</span>
                    <ArrowRight className="h-3.5 w-3.5 text-white/30" />
                    <span className="font-semibold text-white">
                      {formatCents(checkpoint.safe_to_spend_after_cents)}
                    </span>
                    <span
                      className={
                        checkpoint.impact_cents > 0
                          ? "text-[#f4a594]"
                          : checkpoint.impact_cents < 0
                            ? "text-[#9FC29F]"
                            : "text-white/40"
                      }
                    >
                      ({checkpoint.impact_cents >= 0 ? "-" : "+"}
                      {formatCents(Math.abs(checkpoint.impact_cents))})
                    </span>
                  </div>
                </li>
              ))}
            </ol>
          </div>

          {result.goal_impacts.length > 0 && (
            <GoalImpactList
              goalImpacts={result.goal_impacts}
              conflictIntelligence={result.goal_conflict_intelligence}
            />
          )}

          {result.warnings.length > 0 && (
            <div className="mt-7 rounded-2xl border border-white/10 bg-white/[0.045] p-5">
              <div className="flex items-start gap-3">
                <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0 text-[#D2B199]" />
                <div>
                  <p className="text-sm font-semibold">Warnings</p>
                  <ul className="mt-2 space-y-1.5 text-sm leading-6 text-white/58">
                    {result.warnings.map((warning, index) => (
                      <li key={index}>{warning}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}
        </div>
      </article>
    </div>
  );
}
