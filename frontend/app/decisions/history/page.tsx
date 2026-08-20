"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  CheckCircle2,
  Clock,
  History,
  Layers,
  RotateCcw,
  Search,
  Trash2,
  TrendingDown,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AppSidebar from "../../components/AppSidebar";
import Toast from "../../components/Toast";
import { PageReveal, Reveal, Stagger } from "../../components/PremiumMotion";
import {
  api,
  CalibrationLabel,
  DecisionCalibration,
  DecisionCalibrationMetricGroup,
  DecisionChangeExplanation,
  DecisionOutcome,
  DecisionOutcomeComparisonMetric,
  DecisionPortfolioContributionLevel,
  DecisionPortfolioItem,
  DecisionPortfolioResult,
  DecisionPortfolioStatus,
  DecisionReviewQueueItem,
  DecisionTimeline,
  DecisionTimelineEvent,
  DecisionType,
  formatCents,
  GoalConflictSeverity,
  SavedDecision,
  session,
} from "../../lib/api";

// Every type here is reconstructed from persisted input into a
// deterministic portfolio effect (see decision_portfolio_service) --
// other types stay visible but disabled instead of being hidden or
// silently reinterpreted. scenario_comparison stays unsupported:
// nothing persisted records which option (if either) was actually
// chosen after saving.
const PORTFOLIO_SUPPORTED_TYPES: DecisionType[] = [
  "major_purchase",
  "what_if",
  "stress_test",
  "buy_now_vs_wait",
  "what_if_comparison",
];
// These decision types represent alternative branches, not a single
// adjustment -- an explicit branch must be chosen before they can be
// added to a portfolio. Never defaulted to the recommended option.
const PORTFOLIO_VARIANT_REQUIRED_TYPES: DecisionType[] = [
  "buy_now_vs_wait",
  "what_if_comparison",
];
const MIN_PORTFOLIO_SELECTION = 2;
const MAX_PORTFOLIO_SELECTION = 5;

type PortfolioVariantOption = { value: string; label: string };

// Stable, display-label-independent branch keys, matching the
// scenario_comparison option_a/option_b convention. Position in the
// persisted list is the branch's identity; the label is shown, never
// matched on.
const WHAT_IF_COMPARISON_OPTION_KEYS = ["option_a", "option_b", "option_c"];

// Branch options are read from the decision's own persisted
// input_snapshot -- never fabricated -- and simply omitted (leaving
// no selectable options) when the shape doesn't match what's
// expected, the same defensive convention `summaryChips` uses for
// result_snapshot.
function portfolioVariantOptions(
  decision: SavedDecision
): PortfolioVariantOption[] {
  const input = decision.input_snapshot;

  if (decision.decision_type === "buy_now_vs_wait") {
    const buyNowDate = asNonEmptyString(input.buy_now_date);

    if (!buyNowDate) return [];

    // WAIT isn't offered here: the portfolio evaluates every selected
    // decision against one shared baseline as of today, so it has no
    // way to honor WAIT's real meaning (safe-to-spend re-evaluated as
    // of the wait date) without silently presenting it as identical to
    // BUY_NOW. Wait vs. buy-now can still be compared on its own,
    // outside a portfolio.
    return [{ value: "buy_now", label: "Buy now" }];
  }

  if (decision.decision_type === "what_if_comparison") {
    const scenarios = input.scenarios;
    if (!Array.isArray(scenarios)) return [];

    return scenarios
      .map((scenario) =>
        typeof scenario === "object" && scenario !== null
          ? asNonEmptyString((scenario as Record<string, unknown>).label)
          : undefined
      )
      .filter((label): label is string => label !== undefined)
      .map((label, index) => ({
        value: WHAT_IF_COMPARISON_OPTION_KEYS[index],
        label,
      }));
  }

  return [];
}

const TYPE_LABEL: Record<DecisionType, string> = {
  major_purchase: "Major Purchase",
  scenario_comparison: "Scenario Comparison",
  stress_test: "Stress Test",
  buy_now_vs_wait: "Buy Now vs Wait",
  what_if: "What-If",
  what_if_comparison: "Scenario Comparison",
};

const STATUS_TONE: Record<string, string> = {
  affordable: "bg-[#dff6c7] text-[#315d31]",
  caution: "bg-[#f5d66f] text-[#66500f]",
  not_affordable: "bg-[#f0b8a8] text-[#7b3528]",
  resilient: "bg-[#dff6c7] text-[#315d31]",
  strained: "bg-[#f5d66f] text-[#66500f]",
  critical: "bg-[#f0b8a8] text-[#7b3528]",
  buy_now: "bg-[#dff6c7] text-[#315d31]",
  wait: "bg-[#dff6c7] text-[#315d31]",
  either: "bg-[#f5d66f] text-[#66500f]",
  neither: "bg-[#f0b8a8] text-[#7b3528]",
  positive: "bg-[#dff6c7] text-[#315d31]",
  neutral: "bg-[#eef1ec] text-[#5F5751]",
  negative: "bg-[#f0b8a8] text-[#7b3528]",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// result_snapshot is a free-form JSON blob (see SavedDecision) -- it
// should always match the decision type's real output schema, but a
// decision saved under a different/older shape must never crash the
// history page. Every chip is built from one of these guarded reads,
// and simply omitted (never a made-up placeholder) when its field is
// missing or the wrong type.
function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

function asNonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function humanize(value: string): string {
  return value.replace(/_/g, " ");
}

// comparison_snapshot paths are raw JSON leaf paths (e.g.
// "safe_to_spend_after_purchase_cents" or "goal_impacts[0].status")
// -- never shown to the user as-is. This turns any such path into a
// short readable label without hard-coding per-decision-type field
// names.
function metricLabel(path: string): string {
  return path
    .split(".")
    .map((segment) => {
      const match = segment.match(/^(.*?)(\[(\d+)\])?$/);
      const name = (match?.[1] ?? segment).replace(/_cents$/, "");
      const index = match?.[3];
      const label = humanize(name);
      return index !== undefined ? `${label} ${Number(index) + 1}` : label;
    })
    .join(" · ");
}

function isCurrencyMetric(path: string): boolean {
  const leaf = path
    .split(".")
    .pop()
    ?.replace(/\[\d+\]$/, "");
  return leaf?.endsWith("cents") ?? false;
}

function formatMetricValue(
  value: number | boolean | string,
  changeType: DecisionOutcomeComparisonMetric["change_type"],
  currency: boolean
): string {
  if (changeType === "boolean") {
    return value ? "Yes" : "No";
  }

  if (changeType === "numeric" && typeof value === "number") {
    return currency ? formatCents(value) : `${value}`;
  }

  return `${value}`;
}

function summaryChips(
  decision: SavedDecision
): { label: string; value: string; wide?: boolean }[] {
  const r = decision.result_snapshot as Record<string, unknown>;
  const chips: { label: string; value: string; wide?: boolean }[] = [];

  if (decision.decision_type === "major_purchase") {
    const amount = asNumber(r.purchase_amount_cents);
    if (amount !== undefined) {
      chips.push({ label: "Amount", value: formatCents(amount) });
    }

    const safeAfter = asNumber(r.safe_to_spend_after_purchase_cents);
    if (safeAfter !== undefined) {
      chips.push({
        label: "Safe to spend after",
        value: formatCents(safeAfter),
      });
    }

    const confidence = asNumber(r.confidence_score);
    if (confidence !== undefined) {
      chips.push({
        label: "Confidence",
        value: `${Math.round(confidence)}%`,
      });
    }

    return chips;
  }

  if (decision.decision_type === "scenario_comparison") {
    const recommended = asNonEmptyString(r.recommended_option);
    const label =
      recommended === "option_a"
        ? "Option A"
        : recommended === "option_b"
          ? "Option B"
          : recommended === "tie"
            ? "Tie"
            : undefined;

    if (label !== undefined) {
      chips.push({ label: "Recommended", value: label });
    }

    return chips;
  }

  if (decision.decision_type === "buy_now_vs_wait") {
    const timing = asNonEmptyString(r.recommended_timing);
    if (timing !== undefined) {
      chips.push({ label: "Recommendation", value: humanize(timing) });
    }

    const buffer = asNumber(r.buffer_difference_cents);
    if (buffer !== undefined) {
      chips.push({
        label: "Buffer difference",
        value: formatCents(buffer),
      });
    }

    const confidenceDifference = asNumber(r.confidence_difference);
    if (confidenceDifference !== undefined) {
      chips.push({
        label: "Confidence difference",
        value: `${Math.round(confidenceDifference)} pts`,
      });
    }

    const assumption = asNonEmptyString(r.assumption);
    if (assumption !== undefined) {
      chips.push({
        label: "Assumption",
        value: assumption,
        wide: true,
      });
    }

    return chips;
  }

  if (decision.decision_type === "what_if") {
    const impact = r.impact as Record<string, unknown> | undefined;
    const scenario = r.scenario as Record<string, unknown> | undefined;

    const delta = asNumber(impact?.safe_to_spend_delta_cents);
    if (delta !== undefined) {
      chips.push({
        label: "Safe-to-spend impact",
        value: `${delta >= 0 ? "+" : ""}${formatCents(delta)}`,
      });
    }

    const confidence = asNumber(scenario?.confidence_score);
    if (confidence !== undefined) {
      chips.push({
        label: "Confidence",
        value: `${Math.round(confidence)}%`,
      });
    }

    return chips;
  }

  if (decision.decision_type === "what_if_comparison") {
    const recommended = asNonEmptyString(r.recommended_label);
    chips.push({
      label: "Recommended",
      value: recommended ?? "Tie",
    });

    const keyDriver = asNonEmptyString(r.key_driver);
    if (keyDriver !== undefined) {
      chips.push({ label: "Key driver", value: humanize(keyDriver) });
    }

    return chips;
  }

  // stress_test (and any other/future decision type)
  const resilience = asNumber(r.resilience_score);
  if (resilience !== undefined) {
    chips.push({
      label: "Resilience score",
      value: `${Math.round(resilience)}`,
    });
  }

  const confidence = asNumber(r.confidence_score);
  if (confidence !== undefined) {
    chips.push({
      label: "Confidence",
      value: `${Math.round(confidence)}%`,
    });
  }

  return chips;
}

function statusLabel(decision: SavedDecision): string | null {
  const r = decision.result_snapshot as Record<string, unknown>;
  const impact = r.impact as Record<string, unknown> | undefined;
  const status =
    asNonEmptyString(r.affordability_status) ??
    asNonEmptyString(r.risk_level) ??
    asNonEmptyString(r.recommended_timing) ??
    asNonEmptyString(impact?.level);
  return status ? humanize(status) : null;
}

const CALIBRATION_LABEL_TEXT: Record<CalibrationLabel, string> = {
  mostly_conservative: "Mostly conservative",
  mostly_optimistic: "Mostly optimistic",
  balanced: "Balanced",
  insufficient_data: "Insufficient data",
};

const CALIBRATION_LABEL_TONE: Record<CalibrationLabel, string> = {
  mostly_conservative: "bg-[#58715A]/10 text-[#58715A]",
  mostly_optimistic: "bg-[#B75C50]/10 text-[#B75C50]",
  balanced: "bg-[#C59A52]/10 text-[#C59A52]",
  insufficient_data: "bg-[#777168]/10 text-[#777168]",
};

function calibrationNarrative(label: CalibrationLabel): string {
  switch (label) {
    case "mostly_conservative":
      return "Discero has been mostly conservative across your tracked outcomes.";
    case "mostly_optimistic":
      return "Discero has been mostly optimistic across your tracked outcomes.";
    case "balanced":
      return "Discero has been balanced across your tracked outcomes.";
    default:
      return "More tracked outcomes are needed before Discero can identify a calibration pattern.";
  }
}

function formatSignedCents(cents: number): string {
  return cents > 0 ? `+${formatCents(cents)}` : formatCents(cents);
}

const PORTFOLIO_STATUS_TEXT: Record<DecisionPortfolioStatus, string> = {
  comfortable: "Comfortable",
  tight: "Tight",
  high_risk: "High risk",
};

const PORTFOLIO_STATUS_TONE: Record<DecisionPortfolioStatus, string> = {
  comfortable: "bg-[#58715A]/10 text-[#58715A]",
  tight: "bg-[#C59A52]/10 text-[#C59A52]",
  high_risk: "bg-[#B75C50]/10 text-[#B75C50]",
};

const CONTRIBUTION_TONE: Record<DecisionPortfolioContributionLevel, string> = {
  high: "text-[#B75C50]",
  medium: "text-[#C59A52]",
  low: "text-[#58715A]",
};

const SEVERITY_LABEL: Record<GoalConflictSeverity, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
  none: "None",
};

const SEVERITY_TONE: Record<GoalConflictSeverity, string> = {
  high: "bg-[#B75C50]/10 text-[#B75C50]",
  medium: "bg-[#C59A52]/10 text-[#C59A52]",
  low: "bg-[#58715A]/10 text-[#58715A]",
  none: "bg-[#eef1ec] text-[#5F5751]",
};

function PortfolioSection({
  result,
  onChangeSelection,
  onClearAnalysis,
}: {
  result: DecisionPortfolioResult;
  onChangeSelection: () => void;
  onClearAnalysis: () => void;
}) {
  const hasGoalEffects = result.goal_conflict_intelligence.goals.length > 0;
  const hasConflictsOrWarnings =
    result.conflicts.conflict_status !== "no_conflict" ||
    result.warnings.length > 0;
  const goalExplanationById = new Map(
    result.goal_impacts.map((goal) => [goal.goal_id, goal.explanation])
  );
  const variantLabelById = new Map(
    result.selected_decisions
      .filter((decision) => decision.variant_label !== null)
      .map((decision) => [decision.decision_id, decision.variant_label])
  );

  return (
    <div
      data-testid="decision-portfolio-section"
      className="border border-[#181713]/10 bg-[#FFFCF7] px-6 py-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
            Decision portfolio
          </p>
          <p className="mt-1 max-w-lg text-sm leading-6 text-[#777168]">
            How these decisions interact when considered together.
          </p>
        </div>
        <span
          data-testid="portfolio-status"
          className={`inline-flex items-center rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.1em] ${
            PORTFOLIO_STATUS_TONE[result.portfolio_status]
          }`}
        >
          {PORTFOLIO_STATUS_TEXT[result.portfolio_status]}
        </span>
      </div>

      <div className="mt-4 grid gap-px overflow-hidden bg-[#181713]/10 sm:grid-cols-4">
        <div className="bg-[#FFFCF7] px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8a978f]">
            Baseline safe to spend
          </p>
          <p className="mt-0.5 text-base font-semibold tracking-[-0.02em] text-[#181713]">
            {formatCents(result.baseline.safe_to_spend_cents)}
          </p>
        </div>
        <div className="bg-[#FFFCF7] px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8a978f]">
            Combined safe to spend
          </p>
          <p className="mt-0.5 text-base font-semibold tracking-[-0.02em] text-[#181713]">
            {formatCents(result.combined.safe_to_spend_cents)}
          </p>
        </div>
        <div className="bg-[#FFFCF7] px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8a978f]">
            Total change
          </p>
          <p
            className={`mt-0.5 text-base font-semibold tracking-[-0.02em] ${
              result.combined.safe_to_spend_delta_cents < 0
                ? "text-[#B75C50]"
                : "text-[#58715A]"
            }`}
          >
            {formatSignedCents(result.combined.safe_to_spend_delta_cents)}
          </p>
        </div>
        <div className="bg-[#FFFCF7] px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8a978f]">
            Confidence
          </p>
          <p className="mt-0.5 text-base font-semibold tracking-[-0.02em] text-[#181713]">
            {Math.round(result.combined.confidence_score)}%
          </p>
        </div>
      </div>

      <div className="mt-5 border-t border-[#181713]/8 pt-4">
        <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#777168]">
          <TrendingDown className="h-3.5 w-3.5" />
          Biggest pressure
        </p>
        <ol className="mt-2 divide-y divide-[#181713]/8">
          {result.decision_impacts.map((impact) => (
            <li
              key={impact.decision_id}
              className="flex flex-wrap items-center justify-between gap-2 py-2"
            >
              <span
                data-testid="portfolio-impact-title"
                className="text-xs font-medium text-[#181713]"
              >
                {impact.risk_rank}. {impact.title}
                {variantLabelById.get(impact.decision_id) && (
                  <span className="text-[#777168]">
                    {" "}
                    — {variantLabelById.get(impact.decision_id)}
                  </span>
                )}
              </span>
              <span
                className={`text-xs font-semibold ${
                  CONTRIBUTION_TONE[impact.contribution_level]
                }`}
              >
                {formatSignedCents(
                  impact.incremental_safe_to_spend_impact_cents
                )}
              </span>
            </li>
          ))}
        </ol>
      </div>

      {hasGoalEffects && (
        <div
          data-testid="portfolio-goal-effects"
          className="mt-5 border-t border-[#181713]/8 pt-4"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#777168]">
              Goal effects
            </p>
            {result.goal_conflict_intelligence.conflict_count > 0 && (
              <span
                data-testid="portfolio-goal-conflict-count"
                className="text-[11px] font-semibold text-[#B75C50]"
              >
                {result.goal_conflict_intelligence.conflict_count} in
                conflict
              </span>
            )}
          </div>
          <div className="mt-2 divide-y divide-[#181713]/8">
            {result.goal_conflict_intelligence.goals.map((goal) => (
              <div
                key={goal.goal_id}
                data-testid="portfolio-goal-effect-item"
                className="py-2 text-xs leading-5 text-[#181713]"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">
                    {goal.rank}. {goal.goal_name}
                  </span>
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${
                      SEVERITY_TONE[goal.severity]
                    }`}
                  >
                    {SEVERITY_LABEL[goal.severity]}
                  </span>
                </div>
                <span className="text-[#777168]">
                  {goalExplanationById.get(goal.goal_id)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {hasConflictsOrWarnings && (
        <div
          data-testid="portfolio-conflicts-warnings"
          className="mt-5 border-t border-[#181713]/8 pt-4"
        >
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#777168]">
            <AlertTriangle className="h-3.5 w-3.5" />
            Conflicts &amp; warnings
          </p>
          {result.conflicts.conflict_status !== "no_conflict" && (
            <p className="mt-2 text-xs leading-5 text-[#181713]">
              {result.conflicts.explanation}
            </p>
          )}
          {result.warnings.length > 0 && (
            <ul className="mt-2 space-y-1">
              {result.warnings.map((warning) => (
                <li
                  key={warning}
                  className="text-xs leading-5 text-[#777168]"
                >
                  {warning}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-[#181713]/8 pt-4">
        <button
          type="button"
          onClick={onChangeSelection}
          className="focus-ring inline-flex items-center gap-1.5 rounded-full border border-[#6E4B63]/25 bg-[#F8F4EE] px-3.5 py-1.5 text-xs font-semibold text-[#6E4B63] transition hover:bg-[#F0E9EE]"
        >
          Change selection
        </button>
        <button
          type="button"
          onClick={onClearAnalysis}
          className="focus-ring inline-flex items-center gap-1.5 rounded-full border border-[#181713]/15 bg-[#FFFCF7] px-3.5 py-1.5 text-xs font-semibold text-[#706961] transition hover:bg-[#eef1ec]"
        >
          Clear analysis
        </button>
      </div>
    </div>
  );
}

function ReviewQueueSection({
  items,
  busyId,
  onMarkActedOn,
  onDismiss,
  onCheckOutcome,
}: {
  items: DecisionReviewQueueItem[];
  busyId: number | null;
  onMarkActedOn: (decisionId: number) => void;
  onDismiss: (decisionId: number) => void;
  onCheckOutcome: (decisionId: number) => void;
}) {
  return (
    <div
      data-testid="decision-review-queue-section"
      className="border border-[#181713]/10 bg-[#FFFCF7] px-6 py-6"
    >
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
        Decisions to review
      </p>
      <p className="mt-1 max-w-lg text-sm leading-6 text-[#777168]">
        Follow up on decisions that may need an outcome check.
      </p>

      <ul className="mt-4 divide-y divide-[#181713]/8">
        {items.map((item) => (
          <li
            key={item.decision_id}
            data-testid="decision-review-queue-item"
            className="flex flex-wrap items-center justify-between gap-3 py-3"
          >
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center rounded-full bg-[#eef1ec] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-[#5F5751]">
                  {TYPE_LABEL[item.decision_type]}
                </span>
                <span className="text-sm font-semibold text-[#2F2930]">
                  {item.title}
                </span>
              </div>
              <p className="mt-1 text-xs leading-5 text-[#777168]">
                {item.review_reason_text}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {item.review_reason === "saved_unresolved" && (
                <>
                  <button
                    type="button"
                    disabled={busyId === item.decision_id}
                    onClick={() => onMarkActedOn(item.decision_id)}
                    className="focus-ring inline-flex items-center gap-1.5 rounded-full bg-[#181713] px-3.5 py-1.5 text-xs font-semibold text-white transition hover:bg-[#2F2930] disabled:opacity-50"
                  >
                    I made this decision
                  </button>
                  <button
                    type="button"
                    disabled={busyId === item.decision_id}
                    onClick={() => onDismiss(item.decision_id)}
                    className="focus-ring inline-flex items-center gap-1.5 rounded-full border border-[#181713]/15 bg-[#FFFCF7] px-3.5 py-1.5 text-xs font-semibold text-[#706961] transition hover:bg-[#eef1ec] disabled:opacity-50"
                  >
                    Dismiss
                  </button>
                </>
              )}

              {item.review_reason === "acted_on_never_checked" && (
                <button
                  type="button"
                  disabled={busyId === item.decision_id}
                  onClick={() => onCheckOutcome(item.decision_id)}
                  className="focus-ring inline-flex items-center gap-1.5 rounded-full border border-[#6E4B63]/25 bg-[#F8F4EE] px-3.5 py-1.5 text-xs font-semibold text-[#6E4B63] transition hover:bg-[#dff6c7] disabled:opacity-50"
                >
                  Check outcome
                </button>
              )}

              {item.review_reason === "acted_on_recheck_due" && (
                <button
                  type="button"
                  disabled={busyId === item.decision_id}
                  onClick={() => onCheckOutcome(item.decision_id)}
                  className="focus-ring inline-flex items-center gap-1.5 rounded-full border border-[#6E4B63]/25 bg-[#F8F4EE] px-3.5 py-1.5 text-xs font-semibold text-[#6E4B63] transition hover:bg-[#dff6c7] disabled:opacity-50"
                >
                  Review again
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

const TIMELINE_EVENT_LABEL: Record<
  DecisionTimelineEvent["event_type"],
  string
> = {
  decision_saved: "Analyzed & saved",
  decision_acted_on: "Acted on",
  outcome_checked: "Outcome checked",
};

function TimelineSection({
  timeline,
  loading,
  error,
}: {
  timeline: DecisionTimeline | undefined;
  loading: boolean;
  error: boolean;
}) {
  return (
    <div
      data-testid="decision-timeline-panel"
      className="mt-4 border border-[#181713]/10 bg-[#FFFCF7] px-4 py-3"
    >
      {loading && (
        <p
          data-testid="decision-timeline-loading"
          className="text-xs text-[#706961]"
        >
          Loading timeline…
        </p>
      )}

      {!loading && error && (
        <p
          role="alert"
          data-testid="decision-timeline-error"
          className="text-xs text-[#a64b3d]"
        >
          Couldn&apos;t load the timeline just now.
        </p>
      )}

      {!loading && !error && timeline && (
        <ol className="space-y-2.5">
          {timeline.events.map((event, index) => (
            <li
              key={`${event.event_type}-${event.occurred_at}-${index}`}
              className="flex items-baseline justify-between gap-3 text-xs"
            >
              <span className="font-medium text-[#2F2930]">
                {TIMELINE_EVENT_LABEL[event.event_type]}
                {event.event_type === "outcome_checked" &&
                  event.changed !== null &&
                  (event.changed
                    ? " · change found"
                    : " · no change")}
              </span>
              <span className="text-[#8a978f]">
                {formatDate(event.occurred_at)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function directionLabel(
  direction: DecisionCalibrationMetricGroup["direction"]
): string {
  if (direction === "higher_is_better") return "Higher is better";
  if (direction === "lower_is_better") return "Lower is better";
  return "Direction unknown";
}

function formatCalibrationMagnitude(
  value: number,
  unit: DecisionCalibrationMetricGroup["unit"]
): string {
  if (unit === "currency") return formatCents(Math.round(value));
  if (unit === "percentage") return `${value.toFixed(1)}%`;
  if (unit === "score") return `${value.toFixed(1)} pts`;
  if (unit === "days") return `${value.toFixed(1)} days`;
  return value.toFixed(2);
}

function formatSignedCalibrationValue(
  value: number,
  unit: DecisionCalibrationMetricGroup["unit"]
): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${formatCalibrationMagnitude(Math.abs(value), unit)}`;
}

function CalibrationSection({
  calibration,
}: {
  calibration: DecisionCalibration;
}) {
  if (calibration.tracked_decisions === 0) {
    return (
      <div
        data-testid="calibration-empty"
        className="border border-[#181713]/10 bg-[#FFFCF7] px-6 py-6"
      >
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
          Decision calibration
        </p>
        <p className="mt-2 text-sm leading-6 text-[#777168]">
          Calibration appears after you act on saved decisions and check
          their outcomes.
        </p>
      </div>
    );
  }

  const topMetrics = calibration.metric_groups.slice(0, 5);

  return (
    <div
      data-testid="decision-calibration-section"
      className="border border-[#181713]/10 bg-[#FFFCF7] px-6 py-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
            Decision calibration
          </p>
          <p className="mt-1 max-w-lg text-sm leading-6 text-[#777168]">
            How Discero&apos;s tracked decisions have compared with later
            outcomes.
          </p>
        </div>
        <span
          data-testid="calibration-label"
          className={`inline-flex items-center rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.1em] ${
            CALIBRATION_LABEL_TONE[calibration.calibration_label]
          }`}
        >
          {CALIBRATION_LABEL_TEXT[calibration.calibration_label]}
        </span>
      </div>

      <p className="mt-3 text-sm leading-6 text-[#181713]">
        {calibrationNarrative(calibration.calibration_label)}
      </p>

      <div className="mt-4 grid gap-px overflow-hidden bg-[#181713]/10 sm:grid-cols-3">
        <div className="bg-[#FFFCF7] px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8a978f]">
            Tracked decisions
          </p>
          <p className="mt-0.5 text-base font-semibold tracking-[-0.02em] text-[#181713]">
            {calibration.tracked_decisions}
          </p>
        </div>
        <div className="bg-[#FFFCF7] px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8a978f]">
            Outcome checks
          </p>
          <p className="mt-0.5 text-base font-semibold tracking-[-0.02em] text-[#181713]">
            {calibration.outcome_checks}
          </p>
        </div>
        <div className="bg-[#FFFCF7] px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8a978f]">
            Directional observations
          </p>
          <p className="mt-0.5 text-base font-semibold tracking-[-0.02em] text-[#181713]">
            {calibration.directional_metrics_compared}
          </p>
        </div>
      </div>

      {calibration.decision_types.length > 0 && (
        <div
          data-testid="calibration-type-breakdown"
          className="mt-5 border-t border-[#181713]/8 pt-4"
        >
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#777168]">
            By decision type
          </p>
          <div className="mt-2 divide-y divide-[#181713]/8">
            {calibration.decision_types.map((breakdown) => (
              <div
                key={breakdown.decision_type}
                className="flex flex-wrap items-center justify-between gap-2 py-2"
              >
                <span className="text-xs font-medium text-[#181713]">
                  {TYPE_LABEL[breakdown.decision_type]}
                </span>
                <span className="flex items-center gap-2 text-xs text-[#777168]">
                  {breakdown.tracked_decisions} tracked
                  {breakdown.favorable_rate !== null &&
                    ` · ${Math.round(breakdown.favorable_rate * 100)}% favorable`}
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${
                      CALIBRATION_LABEL_TONE[breakdown.calibration_label]
                    }`}
                  >
                    {CALIBRATION_LABEL_TEXT[breakdown.calibration_label]}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {topMetrics.length > 0 && (
        <div
          data-testid="calibration-metric-groups"
          className="mt-5 border-t border-[#181713]/8 pt-4"
        >
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#777168]">
            Most-tracked metrics
          </p>
          <div className="mt-2 divide-y divide-[#181713]/8">
            {topMetrics.map((metric) => (
              <div
                key={metric.path}
                className="flex flex-wrap items-center justify-between gap-2 py-2"
              >
                <span className="text-xs font-medium text-[#181713]">
                  {metricLabel(metric.path)}
                </span>
                <span className="flex items-center gap-2 text-xs text-[#777168]">
                  {metric.observations} checks
                  <span className="font-semibold text-[#181713]">
                    {formatSignedCalibrationValue(
                      metric.mean_signed_delta,
                      metric.unit
                    )}
                  </span>
                  avg
                  {metric.direction !== "unknown" && (
                    <span
                      className={
                        metric.direction === "higher_is_better"
                          ? "text-[#58715A]"
                          : "text-[#B86D4B]"
                      }
                    >
                      {directionLabel(metric.direction)}
                    </span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function DecisionHistoryPage() {
  const router = useRouter();
  const [initializing, setInitializing] = useState(true);
  const [userId, setUserId] = useState<number | null>(null);
  const [decisions, setDecisions] = useState<SavedDecision[] | null>(null);
  const [calibration, setCalibration] = useState<DecisionCalibration | null>(
    null
  );
  const [reviewQueue, setReviewQueue] = useState<
    DecisionReviewQueueItem[] | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [rerunResults, setRerunResults] = useState<
    Record<number, Record<string, unknown>>
  >({});
  const [rerunChangeExplanations, setRerunChangeExplanations] = useState<
    Record<number, DecisionChangeExplanation | null>
  >({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [outcomesByDecision, setOutcomesByDecision] = useState<
    Record<number, DecisionOutcome[]>
  >({});
  const [expandedOutcomeId, setExpandedOutcomeId] = useState<number | null>(
    null
  );
  const [outcomesLoadingId, setOutcomesLoadingId] = useState<number | null>(
    null
  );
  const [timelinesByDecision, setTimelinesByDecision] = useState<
    Record<number, DecisionTimeline>
  >({});
  const [expandedTimelineId, setExpandedTimelineId] = useState<number | null>(
    null
  );
  const [timelineLoadingId, setTimelineLoadingId] = useState<number | null>(
    null
  );
  const [timelineErrorId, setTimelineErrorId] = useState<number | null>(
    null
  );
  const [message, setMessage] = useState("");
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedDecisionIds, setSelectedDecisionIds] = useState<number[]>(
    []
  );
  const [selectedVariants, setSelectedVariants] = useState<
    Record<number, string>
  >({});
  const [portfolioResult, setPortfolioResult] =
    useState<DecisionPortfolioResult | null>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(false);
  const [portfolioError, setPortfolioError] = useState<string | null>(null);

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

        const [decisionsResult, calibrationResult, reviewQueueResult] =
          await Promise.allSettled([
            api.getSavedDecisions(id),
            api.getDecisionCalibration(id),
            api.getDecisionReviewQueue(id),
          ]);

        if (decisionsResult.status === "fulfilled") {
          setDecisions(decisionsResult.value);
        } else {
          setError("Couldn't load your saved decisions just now.");
        }

        if (calibrationResult.status === "fulfilled") {
          setCalibration(calibrationResult.value);
        }

        if (reviewQueueResult.status === "fulfilled") {
          setReviewQueue(reviewQueueResult.value.items);
        }
      } catch {
        session.clear();
        router.replace("/");
      } finally {
        setInitializing(false);
      }
    }

    void initialize();
  }, [router]);

  async function handleDelete(decisionId: number) {
    if (userId === null) return;

    setBusyId(decisionId);
    try {
      await api.deleteSavedDecision(userId, decisionId);
      setDecisions(
        (prev) => prev?.filter((d) => d.id !== decisionId) ?? null
      );
    } catch {
      setError("Couldn't delete that decision just now.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleRerun(decisionId: number) {
    if (userId === null) return;

    setBusyId(decisionId);
    try {
      const outcome = await api.rerunSavedDecision(userId, decisionId);
      setRerunResults((prev) => ({
        ...prev,
        [decisionId]: outcome.result_snapshot,
      }));
      setRerunChangeExplanations((prev) => ({
        ...prev,
        [decisionId]: outcome.change_explanation,
      }));
    } catch {
      setError("Couldn't re-run that decision just now.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleUpdateStatus(
    decisionId: number,
    status: "acted_on" | "dismissed"
  ) {
    if (userId === null) return;

    setBusyId(decisionId);
    try {
      const updated = await api.updateDecisionStatus(
        userId,
        decisionId,
        status
      );
      setDecisions(
        (prev) =>
          prev?.map((d) => (d.id === decisionId ? updated : d)) ?? null
      );
      setReviewQueue(
        (prev) => prev?.filter((item) => item.decision_id !== decisionId) ?? null
      );
      setMessage(
        status === "acted_on"
          ? "Marked as acted on."
          : "Decision dismissed."
      );
    } catch {
      setError("Couldn't update that decision just now.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleCheckOutcome(decisionId: number) {
    if (userId === null) return;

    setBusyId(decisionId);
    try {
      const outcome = await api.evaluateDecisionOutcome(
        userId,
        decisionId
      );
      setOutcomesByDecision((prev) => ({
        ...prev,
        [decisionId]: [outcome, ...(prev[decisionId] ?? [])],
      }));
      setDecisions(
        (prev) =>
          prev?.map((d) =>
            d.id === decisionId
              ? {
                  ...d,
                  outcome_count: d.outcome_count + 1,
                  latest_outcome_at: outcome.evaluated_at,
                }
              : d
          ) ?? null
      );
      setReviewQueue(
        (prev) => prev?.filter((item) => item.decision_id !== decisionId) ?? null
      );
      setExpandedOutcomeId(decisionId);

      // Calibration is derived from outcomes and would otherwise stay
      // stale on this page until reload -- refreshed best-effort so a
      // failure here never affects the outcome operation that already
      // succeeded above.
      api
        .getDecisionCalibration(userId)
        .then(setCalibration)
        .catch(() => {});
    } catch {
      setError("Couldn't check the outcome just now.");
    } finally {
      setBusyId(null);
    }
  }

  // Detailed outcome history is never fetched for every card on load --
  // only when the user explicitly opens a card's history, and only
  // once per decision (subsequent toggles reuse what's already in
  // outcomesByDecision).
  async function handleToggleOutcomeHistory(decisionId: number) {
    if (userId === null) return;

    if (expandedOutcomeId === decisionId) {
      setExpandedOutcomeId(null);
      return;
    }

    setExpandedOutcomeId(decisionId);

    if (outcomesByDecision[decisionId]) return;

    setOutcomesLoadingId(decisionId);
    try {
      const outcomes = await api.getDecisionOutcomes(userId, decisionId);
      setOutcomesByDecision((prev) => ({
        ...prev,
        [decisionId]: outcomes,
      }));
    } catch {
      setError("Couldn't load the outcome history just now.");
    } finally {
      setOutcomesLoadingId(null);
    }
  }

  // A timeline is never fetched for every card on load -- only when the
  // user explicitly opens it, and only once per decision (subsequent
  // toggles reuse what's already cached in timelinesByDecision). A
  // fetch failure only affects this one panel, never the rest of the
  // page.
  async function handleToggleTimeline(decisionId: number) {
    if (userId === null) return;

    if (expandedTimelineId === decisionId) {
      setExpandedTimelineId(null);
      return;
    }

    setExpandedTimelineId(decisionId);
    setTimelineErrorId(null);

    if (timelinesByDecision[decisionId]) return;

    setTimelineLoadingId(decisionId);
    try {
      const timeline = await api.getDecisionTimeline(userId, decisionId);
      setTimelinesByDecision((prev) => ({
        ...prev,
        [decisionId]: timeline,
      }));
    } catch {
      setTimelineErrorId(decisionId);
    } finally {
      setTimelineLoadingId(null);
    }
  }

  function startPortfolioSelection() {
    setSelectionMode(true);
    setSelectedDecisionIds([]);
    setSelectedVariants({});
    setPortfolioResult(null);
    setPortfolioError(null);
  }

  function exitPortfolioSelection() {
    setSelectionMode(false);
    setSelectedDecisionIds([]);
    setSelectedVariants({});
    setPortfolioResult(null);
    setPortfolioError(null);
  }

  function togglePortfolioSelection(decisionId: number) {
    setSelectedDecisionIds((prev) => {
      if (prev.includes(decisionId)) {
        return prev.filter((id) => id !== decisionId);
      }
      if (prev.length >= MAX_PORTFOLIO_SELECTION) {
        return prev;
      }
      return [...prev, decisionId];
    });
    // A branch selection only means something for the decision it was
    // made on -- toggling a decision's inclusion always clears any
    // prior branch choice for it, whether it's being added (no choice
    // has been made yet) or removed (a stale choice must never survive
    // to a later re-selection).
    setSelectedVariants((prev) => {
      if (!(decisionId in prev)) return prev;
      const next = { ...prev };
      delete next[decisionId];
      return next;
    });
  }

  function setPortfolioVariant(decisionId: number, variant: string) {
    setSelectedVariants((prev) => ({ ...prev, [decisionId]: variant }));
  }

  const selectedPortfolioDecisions = (decisions ?? []).filter((decision) =>
    selectedDecisionIds.includes(decision.id)
  );
  const missingPortfolioVariantCount = selectedPortfolioDecisions.filter(
    (decision) =>
      PORTFOLIO_VARIANT_REQUIRED_TYPES.includes(decision.decision_type) &&
      !selectedVariants[decision.id]
  ).length;

  async function handleAnalyzeTogether() {
    if (
      userId === null ||
      selectedDecisionIds.length < MIN_PORTFOLIO_SELECTION ||
      missingPortfolioVariantCount > 0
    ) {
      return;
    }

    setPortfolioLoading(true);
    setPortfolioError(null);
    try {
      const items: DecisionPortfolioItem[] = selectedDecisionIds.map(
        (decisionId) => {
          const variant = selectedVariants[decisionId];
          return variant ? { decision_id: decisionId, variant } : { decision_id: decisionId };
        }
      );
      const result = await api.evaluateDecisionPortfolio(userId, items);
      setPortfolioResult(result);
    } catch {
      setPortfolioError("Couldn't analyze these decisions together just now.");
    } finally {
      setPortfolioLoading(false);
    }
  }

  function handleChangeSelection() {
    setPortfolioResult(null);
    setPortfolioError(null);
  }

  if (initializing) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#F5F1EA]">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#6E4B63] border-t-transparent" />
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#F5F1EA] text-[#181713]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-56 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[900px]">
          <Reveal>
            <header className="border-b border-[#181713]/10 pb-7">
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">
                <Clock className="h-3.5 w-3.5" />
                Decision history
              </p>

              <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
                Your decision record.
              </h1>

              <p className="mt-3 max-w-2xl text-sm leading-6 text-[#706961]">
                Purchases, comparisons, and stress tests you saved --
                with the exact deterministic result at the time.
              </p>

              <Link
                href="/decisions"
                className="focus-ring mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-[#6E4B63]"
              >
                Run a new analysis
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </header>
          </Reveal>

          {reviewQueue !== null && reviewQueue.length > 0 && (
            <Reveal>
              <div className="mt-8">
                <ReviewQueueSection
                  items={reviewQueue}
                  busyId={busyId}
                  onMarkActedOn={(decisionId) =>
                    handleUpdateStatus(decisionId, "acted_on")
                  }
                  onDismiss={(decisionId) =>
                    handleUpdateStatus(decisionId, "dismissed")
                  }
                  onCheckOutcome={handleCheckOutcome}
                />
              </div>
            </Reveal>
          )}

          {decisions !== null && decisions.length > 0 && (
            <Reveal>
              <div className="mt-6">
                {!selectionMode ? (
                  <button
                    type="button"
                    data-testid="start-portfolio-selection"
                    onClick={startPortfolioSelection}
                    className="focus-ring inline-flex items-center gap-2 rounded-full border border-[#6E4B63]/25 bg-[#F8F4EE] px-4 py-2 text-xs font-semibold uppercase tracking-[0.1em] text-[#6E4B63] transition hover:bg-[#F0E9EE]"
                  >
                    <Layers className="h-3.5 w-3.5" />
                    Compare decisions together
                  </button>
                ) : (
                  <div
                    data-testid="portfolio-selection-toolbar"
                    className="flex flex-wrap items-center justify-between gap-3 border border-[#181713]/10 bg-[#FFFCF7] px-5 py-4"
                  >
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
                        Compare decisions together
                      </p>
                      <p
                        data-testid="portfolio-selected-count"
                        className="mt-1 text-sm text-[#706961]"
                      >
                        Selected {selectedDecisionIds.length} of{" "}
                        {MAX_PORTFOLIO_SELECTION}
                      </p>
                      {missingPortfolioVariantCount > 0 && (
                        <p className="mt-1 text-xs font-medium text-[#a64b3d]">
                          Choose a branch for every selected decision that
                          needs one.
                        </p>
                      )}
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        data-testid="cancel-portfolio-selection"
                        onClick={exitPortfolioSelection}
                        className="focus-ring rounded-full border border-[#181713]/15 bg-[#FFFCF7] px-3.5 py-1.5 text-xs font-semibold text-[#706961] transition hover:bg-[#eef1ec]"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        data-testid="analyze-together"
                        disabled={
                          selectedDecisionIds.length <
                            MIN_PORTFOLIO_SELECTION ||
                          missingPortfolioVariantCount > 0 ||
                          portfolioLoading
                        }
                        onClick={handleAnalyzeTogether}
                        className="focus-ring inline-flex items-center gap-1.5 rounded-full bg-[#181713] px-4 py-1.5 text-xs font-semibold text-white transition hover:bg-[#2F2930] disabled:opacity-40"
                      >
                        {portfolioLoading ? "Analyzing…" : "Analyze together"}
                      </button>
                    </div>
                  </div>
                )}

                {portfolioError && (
                  <p
                    role="alert"
                    className="mt-3 text-sm font-medium text-[#a64b3d]"
                  >
                    {portfolioError}
                  </p>
                )}
              </div>
            </Reveal>
          )}

          {portfolioResult && (
            <Reveal>
              <div className="mt-6">
                <PortfolioSection
                  result={portfolioResult}
                  onChangeSelection={handleChangeSelection}
                  onClearAnalysis={exitPortfolioSelection}
                />
              </div>
            </Reveal>
          )}

          {calibration && (
            <Reveal>
              <div className="mt-8">
                <CalibrationSection calibration={calibration} />
              </div>
            </Reveal>
          )}

          <div className="mt-8">
            {error && (
              <p
                role="alert"
                className="mb-4 rounded-2xl border border-[#a64b3d]/20 bg-[#f8e6e1] px-4 py-3 text-sm font-medium text-[#a64b3d]"
              >
                {error}
              </p>
            )}

            {decisions !== null && decisions.length === 0 && (
              <Reveal>
                <div
                  data-testid="decisions-history-empty"
                  className="rounded-[26px] border border-[#181713]/10 bg-white px-6 py-10 text-center shadow-[0_14px_40px_rgba(60,43,35,0.06)]"
                >
                  <p className="text-lg font-semibold tracking-[-0.02em]">
                    No saved decisions yet
                  </p>
                  <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-[#706961]">
                    Save a major purchase, comparison, or stress test to
                    revisit it later.
                  </p>
                </div>
              </Reveal>
            )}

            {decisions !== null && decisions.length > 0 && (
              <Stagger className="divide-y divide-[#181713]/10 border-y border-[#181713]/10">
                {decisions.map((decision) => {
                  const status = statusLabel(decision);
                  const rerun = rerunResults[decision.id];
                  const rerunExplanation =
                    rerunChangeExplanations[decision.id];
                  const outcomes = outcomesByDecision[decision.id] ?? [];
                  const latestOutcome = outcomes[0];
                  const isOutcomeHistoryOpen =
                    expandedOutcomeId === decision.id;
                  const isOutcomeHistoryLoading =
                    outcomesLoadingId === decision.id;

                  return (
                    <Reveal key={decision.id}>
                      <article
                        data-testid="decision-history-card"
                        className={`py-6 sm:py-7 ${
                          decision.status === "dismissed"
                            ? "opacity-60"
                            : ""
                        }`}
                      >
                        {selectionMode &&
                          (() => {
                            const isDismissed =
                              decision.status === "dismissed";
                            const isUnsupported =
                              !PORTFOLIO_SUPPORTED_TYPES.includes(
                                decision.decision_type
                              );
                            const isSelected = selectedDecisionIds.includes(
                              decision.id
                            );
                            const isDisabled = isDismissed || isUnsupported;
                            const isSelectionFull =
                              selectedDecisionIds.length >=
                                MAX_PORTFOLIO_SELECTION && !isSelected;
                            const requiresVariant =
                              PORTFOLIO_VARIANT_REQUIRED_TYPES.includes(
                                decision.decision_type
                              );
                            const variantOptions = requiresVariant
                              ? portfolioVariantOptions(decision)
                              : [];
                            const selectedVariant =
                              selectedVariants[decision.id];

                            return (
                              <div className="mb-4">
                                <label
                                  data-testid={`portfolio-select-${decision.id}`}
                                  className={`flex items-center gap-2.5 border border-[#181713]/10 px-3 py-2 text-xs font-medium ${
                                    isDisabled
                                      ? "cursor-not-allowed bg-[#F5F1EA] text-[#8a978f]"
                                      : "cursor-pointer bg-[#FFFCF7] text-[#181713] hover:bg-[#F0E9EE]/40"
                                  }`}
                                >
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    disabled={isDisabled || isSelectionFull}
                                    onChange={() =>
                                      togglePortfolioSelection(decision.id)
                                    }
                                    className="h-4 w-4 accent-[#6E4B63]"
                                  />
                                  <span>
                                    {isDismissed
                                      ? "Dismissed decisions can't be compared."
                                      : isUnsupported
                                        ? "Not available for portfolio analysis yet."
                                        : "Include in portfolio analysis"}
                                  </span>
                                </label>

                                {isSelected && requiresVariant && (
                                  <fieldset
                                    data-testid={`portfolio-variant-${decision.id}`}
                                    className="mt-2 flex flex-col gap-1.5 border border-[#181713]/10 border-t-0 bg-[#FFFCF7] px-3 py-2.5"
                                  >
                                    <legend className="px-0.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#777168]">
                                      Choose a branch to include
                                    </legend>
                                    {variantOptions.length === 0 ? (
                                      <span className="text-xs text-[#8a978f]">
                                        This decision&apos;s saved details
                                        don&apos;t support portfolio analysis
                                        anymore.
                                      </span>
                                    ) : (
                                      variantOptions.map((option) => (
                                        <label
                                          key={option.value}
                                          className="flex cursor-pointer items-center gap-2 text-xs text-[#181713]"
                                        >
                                          <input
                                            type="radio"
                                            name={`portfolio-variant-${decision.id}`}
                                            value={option.value}
                                            checked={
                                              selectedVariant === option.value
                                            }
                                            onChange={() =>
                                              setPortfolioVariant(
                                                decision.id,
                                                option.value
                                              )
                                            }
                                            className="h-3.5 w-3.5 accent-[#6E4B63]"
                                          />
                                          {option.label}
                                        </label>
                                      ))
                                    )}
                                  </fieldset>
                                )}
                              </div>
                            );
                          })()}

                        <div className="flex flex-wrap items-center gap-2">
                          <span className="inline-flex items-center rounded-full bg-[#eef1ec] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-[#5F5751]">
                            {TYPE_LABEL[decision.decision_type]}
                          </span>

                          {status && (
                            <span
                              className={`inline-flex items-center rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.1em] ${
                                STATUS_TONE[status.replace(/ /g, "_")] ??
                                "bg-[#eef1ec] text-[#5F5751]"
                              }`}
                            >
                              {status}
                            </span>
                          )}

                          <span className="text-xs text-[#8a978f]">
                            Analyzed {formatDate(decision.created_at)}
                          </span>
                        </div>

                        <h2 className="mt-3 text-lg font-semibold tracking-[-0.02em] text-[#2F2930]">
                          {decision.title}
                        </h2>

                        <div className="mt-5 grid gap-px overflow-hidden bg-[#181713]/10 sm:grid-cols-3">
                          {summaryChips(decision).map((chip) => (
                            <div
                              key={chip.label}
                              className={`bg-[#FFFCF7] px-4 py-3 ${
                                chip.wide ? "sm:col-span-3" : ""
                              }`}
                            >
                              <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8a978f]">
                                {chip.label}
                              </p>
                              <p className="mt-0.5 text-base font-semibold tracking-[-0.02em] text-[#2F2930]">
                                {chip.value}
                              </p>
                            </div>
                          ))}
                        </div>

                        {rerun && (
                          <div
                            data-testid="decision-rerun-result"
                            className="mt-5 border-l-2 border-[#6E4B63] bg-[#F0E9EE]/55 px-5 py-4"
                          >
                            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
                              Now (re-run with current data)
                            </p>
                            <div className="mt-2 flex flex-wrap gap-2.5">
                              {summaryChips({
                                ...decision,
                                result_snapshot: rerun,
                              }).map((chip) => (
                                <div
                                  key={chip.label}
                                  className="rounded-xl bg-white px-3 py-2"
                                >
                                  <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8a978f]">
                                    {chip.label}
                                  </p>
                                  <p className="mt-0.5 text-sm font-semibold text-[#2F2930]">
                                    {chip.value}
                                  </p>
                                </div>
                              ))}
                            </div>

                            {rerunExplanation && (
                              <div
                                data-testid="decision-change-explanation"
                                className="mt-4 border-t border-[#181713]/10 pt-3"
                              >
                                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
                                  What changed
                                </p>

                                {rerunExplanation.changed_metrics.length ===
                                0 ? (
                                  <p className="mt-2 text-xs leading-5 text-[#706961]">
                                    No meaningful change since the saved
                                    analysis.
                                  </p>
                                ) : (
                                  <div className="mt-2 divide-y divide-[#181713]/8">
                                    {rerunExplanation.changed_metrics.map(
                                      (metric) => {
                                        const currency =
                                          metric.unit === "currency";

                                        return (
                                          <div
                                            key={metric.path}
                                            className="flex flex-wrap items-center justify-between gap-2 py-2"
                                          >
                                            <span className="text-xs font-medium capitalize text-[#2F2930]">
                                              {metric.label}
                                            </span>
                                            <span className="flex items-center gap-2 text-xs">
                                              <span className="text-[#8a978f]">
                                                {formatMetricValue(
                                                  metric.before,
                                                  metric.change_type,
                                                  currency
                                                )}
                                              </span>
                                              <ArrowRight className="h-3 w-3 text-[#c7bfb4]" />
                                              <span className="font-semibold text-[#2F2930]">
                                                {formatMetricValue(
                                                  metric.current,
                                                  metric.change_type,
                                                  currency
                                                )}
                                              </span>
                                              {metric.change_type ===
                                                "numeric" &&
                                                metric.delta !== null && (
                                                  <span
                                                    className={
                                                      metric.delta >= 0
                                                        ? "font-semibold text-[#48634B]"
                                                        : "font-semibold text-[#a64b3d]"
                                                    }
                                                  >
                                                    {metric.delta >= 0
                                                      ? "+"
                                                      : ""}
                                                    {formatMetricValue(
                                                      metric.delta,
                                                      metric.change_type,
                                                      currency
                                                    )}
                                                  </span>
                                                )}
                                            </span>
                                          </div>
                                        );
                                      }
                                    )}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )}

                        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[#181713]/8 pt-4">
                          {decision.status === "saved" && (
                            <>
                              <button
                                type="button"
                                disabled={busyId === decision.id}
                                onClick={() =>
                                  handleUpdateStatus(decision.id, "acted_on")
                                }
                                className="focus-ring inline-flex items-center gap-1.5 rounded-full bg-[#181713] px-3.5 py-1.5 text-xs font-semibold text-white transition hover:bg-[#2F2930] disabled:opacity-50"
                              >
                                <CheckCircle2 className="h-3.5 w-3.5" />
                                I made this decision
                              </button>

                              <button
                                type="button"
                                disabled={busyId === decision.id}
                                onClick={() =>
                                  handleUpdateStatus(decision.id, "dismissed")
                                }
                                className="focus-ring inline-flex items-center gap-1.5 rounded-full border border-[#181713]/15 bg-[#FFFCF7] px-3.5 py-1.5 text-xs font-semibold text-[#706961] transition hover:bg-[#eef1ec] disabled:opacity-50"
                              >
                                <Ban className="h-3.5 w-3.5" />
                                Dismiss
                              </button>
                            </>
                          )}

                          {decision.status === "acted_on" && (
                            <>
                              <span className="inline-flex items-center gap-1.5 rounded-full bg-[#E3EBE1] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-[#48634B]">
                                <CheckCircle2 className="h-3.5 w-3.5" />
                                Acted on
                                {decision.acted_on_at &&
                                  ` · ${formatDate(decision.acted_on_at)}`}
                              </span>

                              <button
                                type="button"
                                disabled={busyId === decision.id}
                                onClick={() => handleCheckOutcome(decision.id)}
                                className="focus-ring inline-flex items-center gap-1.5 rounded-full border border-[#6E4B63]/25 bg-[#F8F4EE] px-3.5 py-1.5 text-xs font-semibold text-[#6E4B63] transition hover:bg-[#dff6c7] disabled:opacity-50"
                              >
                                <Search className="h-3.5 w-3.5" />
                                Check outcome
                              </button>

                              {decision.outcome_count > 0 && (
                                <button
                                  type="button"
                                  onClick={() =>
                                    handleToggleOutcomeHistory(decision.id)
                                  }
                                  className="focus-ring inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-semibold text-[#6E4B63] underline decoration-[#6E4B63]/40 underline-offset-2 transition hover:text-[#2F2930]"
                                >
                                  {isOutcomeHistoryOpen
                                    ? "Hide outcome history"
                                    : `Checked ${decision.outcome_count}× outcome history`}
                                  {!isOutcomeHistoryOpen &&
                                    decision.latest_outcome_at &&
                                    ` · last ${formatDate(
                                      decision.latest_outcome_at
                                    )}`}
                                </button>
                              )}
                            </>
                          )}

                          {decision.status === "dismissed" && (
                            <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.1em] text-[#8a978f]">
                              <Ban className="h-3.5 w-3.5" />
                              Dismissed
                            </span>
                          )}

                          <button
                            type="button"
                            onClick={() => handleToggleTimeline(decision.id)}
                            className="focus-ring inline-flex items-center gap-1.5 rounded-full border border-[#6E4B63]/25 bg-[#F8F4EE] px-3.5 py-1.5 text-xs font-semibold text-[#6E4B63] transition hover:bg-[#dff6c7]"
                          >
                            <History className="h-3.5 w-3.5" />
                            {expandedTimelineId === decision.id
                              ? "Hide timeline"
                              : "View timeline"}
                          </button>

                          <button
                            type="button"
                            disabled={busyId === decision.id}
                            onClick={() => handleRerun(decision.id)}
                            className="focus-ring inline-flex items-center gap-1.5 rounded-full border border-[#6E4B63]/25 bg-[#F8F4EE] px-3.5 py-1.5 text-xs font-semibold text-[#6E4B63] transition hover:bg-[#dff6c7] disabled:opacity-50"
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                            Run again
                          </button>

                          <button
                            type="button"
                            disabled={busyId === decision.id}
                            onClick={() => handleDelete(decision.id)}
                            className="focus-ring inline-flex items-center gap-1.5 rounded-full border border-[#a64b3d]/25 bg-[#f8e6e1] px-3.5 py-1.5 text-xs font-semibold text-[#a64b3d] transition hover:bg-[#f0b8a8] disabled:opacity-50"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            Delete
                          </button>
                        </div>

                        {expandedTimelineId === decision.id && (
                          <TimelineSection
                            timeline={timelinesByDecision[decision.id]}
                            loading={timelineLoadingId === decision.id}
                            error={timelineErrorId === decision.id}
                          />
                        )}

                        {decision.status === "acted_on" &&
                          isOutcomeHistoryOpen &&
                          isOutcomeHistoryLoading && (
                            <div
                              data-testid="decision-outcome-loading"
                              className="mt-4 border border-[#181713]/10 bg-[#FFFCF7] px-4 py-3 text-xs text-[#706961]"
                            >
                              Loading outcome history…
                            </div>
                          )}

                        {decision.status === "acted_on" &&
                          isOutcomeHistoryOpen &&
                          latestOutcome && (
                            <div
                              data-testid="decision-outcome-panel"
                              className="mt-4 border border-[#181713]/10 bg-[#FFFCF7]"
                            >
                            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#181713]/10 px-4 py-3">
                              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
                                Predicted vs current
                              </p>
                              <p className="text-xs text-[#8a978f]">
                                Checked {formatDate(latestOutcome.evaluated_at)}
                              </p>
                            </div>

                            {latestOutcome.comparison_snapshot.metrics
                              .length === 0 ? (
                              <p className="px-4 py-3 text-xs leading-5 text-[#706961]">
                                Nothing comparable was found between the
                                original result and the current data.
                              </p>
                            ) : !latestOutcome.comparison_snapshot.changed ? (
                              <p className="px-4 py-3 text-xs leading-5 text-[#706961]">
                                No meaningful change since you acted on this
                                decision.
                              </p>
                            ) : (
                              <div className="divide-y divide-[#181713]/8">
                                {latestOutcome.comparison_snapshot.metrics
                                  .filter(
                                    (metric) =>
                                      metric.before !== metric.current
                                  )
                                  .map((metric) => {
                                    const currency = isCurrencyMetric(
                                      metric.path
                                    );

                                    return (
                                      <div
                                        key={metric.path}
                                        className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5"
                                      >
                                        <span className="text-xs font-medium text-[#2F2930]">
                                          {metricLabel(metric.path)}
                                        </span>

                                        <span className="flex items-center gap-2 text-xs">
                                          <span className="text-[#8a978f]">
                                            {formatMetricValue(
                                              metric.before,
                                              metric.change_type,
                                              currency
                                            )}
                                          </span>
                                          <ArrowRight className="h-3 w-3 text-[#c7bfb4]" />
                                          <span className="font-semibold text-[#2F2930]">
                                            {formatMetricValue(
                                              metric.current,
                                              metric.change_type,
                                              currency
                                            )}
                                          </span>
                                          {metric.change_type === "numeric" &&
                                            metric.delta !== null && (
                                              <span
                                                className={
                                                  metric.delta >= 0
                                                    ? "font-semibold text-[#48634B]"
                                                    : "font-semibold text-[#a64b3d]"
                                                }
                                              >
                                                {metric.delta >= 0 ? "+" : ""}
                                                {formatMetricValue(
                                                  metric.delta,
                                                  metric.change_type,
                                                  currency
                                                )}
                                              </span>
                                            )}
                                        </span>
                                      </div>
                                    );
                                  })}
                              </div>
                            )}

                            {outcomes.length > 1 && (
                              <p className="border-t border-[#181713]/8 px-4 py-2 text-[11px] text-[#8a978f]">
                                Also checked on{" "}
                                {outcomes
                                  .slice(1, 4)
                                  .map((o) => formatDate(o.evaluated_at))
                                  .join(", ")}
                                {outcomes.length > 4
                                  ? `, and ${outcomes.length - 4} more`
                                  : ""}
                              </p>
                            )}
                          </div>
                        )}
                      </article>
                    </Reveal>
                  );
                })}
              </Stagger>
            )}
          </div>
        </PageReveal>
      </div>

      <Toast
        message={message}
        type="success"
        onClose={() => setMessage("")}
      />
    </main>
  );
}
