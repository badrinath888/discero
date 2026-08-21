import {
  CheckCircle2,
  Clock,
  TrendingDown,
  TriangleAlert,
  XCircle,
} from "lucide-react";
import {
  formatCents,
  GoalConflictIntelligence,
  GoalConflictSeverity,
  GoalImpact,
  GoalImpactStatus,
} from "../lib/api";

const SEVERITY_LABEL: Record<GoalConflictSeverity, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
  none: "None",
};

const SEVERITY_TONE: Record<GoalConflictSeverity, string> = {
  high: "bg-[#f0b8a8] text-[#7b3528]",
  medium: "bg-[#f5d66f] text-[#66500f]",
  low: "bg-[#bcd6f5] text-[#1f3a5f]",
  none: "bg-[#dff6c7] text-[#315d31]",
};

const GOAL_STATUS_CONTENT: Record<
  GoalImpactStatus,
  { label: string; className: string; icon: typeof CheckCircle2 }
> = {
  unaffected: {
    label: "Unaffected",
    className: "bg-[#dff6c7] text-[#315d31]",
    icon: CheckCircle2,
  },
  reduced: {
    label: "Reduced",
    className: "bg-[#bcd6f5] text-[#1f3a5f]",
    icon: TrendingDown,
  },
  delayed: {
    label: "Delayed",
    className: "bg-[#f5d66f] text-[#66500f]",
    icon: Clock,
  },
  at_risk: {
    label: "At risk",
    className: "bg-[#f3c9a0] text-[#7a4a12]",
    icon: TriangleAlert,
  },
  impossible: {
    label: "Impossible",
    className: "bg-[#f0b8a8] text-[#7b3528]",
    icon: XCircle,
  },
};

function formatMonthYear(value: string | null): string {
  if (!value) {
    return "Not determinable";
  }

  return new Date(`${value}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
  });
}

export default function GoalImpactList({
  goalImpacts,
  conflictIntelligence,
}: {
  goalImpacts: GoalImpact[];
  conflictIntelligence?: GoalConflictIntelligence;
}) {
  const severityByGoalId = new Map(
    conflictIntelligence?.supported
      ? conflictIntelligence.goals.map((goal) => [goal.goal_id, goal])
      : []
  );

  const orderedGoalImpacts = severityByGoalId.size
    ? [...goalImpacts].sort(
        (a, b) =>
          (severityByGoalId.get(a.goal_id)?.rank ?? 0) -
          (severityByGoalId.get(b.goal_id)?.rank ?? 0)
      )
    : goalImpacts;

  // A goal already off track BEFORE this scenario is never counted as
  // something the scenario "caused" -- only scenario_created_conflict/
  // scenario_worsened_conflict goals count as new, so a baseline
  // conflict the scenario merely leaves alone is never folded into a
  // single misleading "N in conflict" figure.
  const newConflictCount = conflictIntelligence
    ? conflictIntelligence.scenario_created_conflict_count +
      conflictIntelligence.scenario_worsened_conflict_count
    : 0;
  const preExistingCount = conflictIntelligence
    ? conflictIntelligence.pre_existing_conflict_count
    : 0;

  return (
    <section
      aria-label="Impact on your goals"
      className="mt-7 rounded-2xl border border-white/10 bg-white/[0.045] p-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-[0.15em] text-white/40">
          Impact on your goals
        </p>
        {conflictIntelligence &&
          (newConflictCount > 0 || preExistingCount > 0) && (
            <div className="flex flex-col items-end gap-0.5">
              {newConflictCount > 0 && (
                <span
                  data-testid="goal-impact-new-conflict-count"
                  className="text-[11px] font-semibold text-[#f4a594]"
                >
                  {newConflictCount} new conflict
                  {newConflictCount === 1 ? "" : "s"}
                </span>
              )}
              {preExistingCount > 0 && (
                <span
                  data-testid="goal-impact-pre-existing-count"
                  className="text-[11px] font-semibold text-white/40"
                >
                  {preExistingCount} already off track
                </span>
              )}
            </div>
          )}
      </div>

      {goalImpacts.length === 0 ? (
        <p className="mt-4 text-sm leading-6 text-white/55">
          You don&apos;t have any active savings goals yet, so there&apos;s
          nothing to evaluate. Create a goal to see how this decision would
          affect it.
        </p>
      ) : (
        <ul className="mt-4 space-y-3">
          {orderedGoalImpacts.map((impact) => {
            const statusContent = GOAL_STATUS_CONTENT[impact.status];
            const StatusIcon = statusContent.icon;
            const conflictItem = severityByGoalId.get(impact.goal_id);
            const severity = conflictItem?.severity;

            return (
              <li
                key={impact.goal_id}
                className="rounded-2xl border border-white/10 bg-white/[0.04] p-5"
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <h3 className="text-sm font-semibold text-white">
                    {impact.goal_name}
                  </h3>
                  <div className="flex flex-wrap items-center gap-2">
                    {severity && severity !== "none" && (
                      <span
                        data-testid="goal-impact-severity"
                        className={`inline-flex w-fit items-center rounded-full px-2.5 py-1 text-[11px] font-semibold ${SEVERITY_TONE[severity]}`}
                      >
                        {SEVERITY_LABEL[severity]} severity
                      </span>
                    )}
                    <span
                      role="status"
                      className={`inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ${statusContent.className}`}
                    >
                      <StatusIcon aria-hidden="true" className="h-3.5 w-3.5" />
                      {statusContent.label}
                    </span>
                  </div>
                </div>

                <dl className="mt-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
                  <div>
                    <dt className="text-white/40">Baseline allocation</dt>
                    <dd className="mt-1 font-semibold text-white/85">
                      {formatCents(
                        impact.baseline_monthly_allocation_cents
                      )}
                      /mo
                    </dd>
                  </div>
                  <div>
                    <dt className="text-white/40">Adjusted allocation</dt>
                    <dd className="mt-1 font-semibold text-white/85">
                      {formatCents(
                        impact.adjusted_monthly_allocation_cents
                      )}
                      /mo
                    </dd>
                  </div>
                  <div>
                    <dt className="text-white/40">Allocation change</dt>
                    <dd
                      className={`mt-1 font-semibold ${
                        impact.monthly_allocation_change_cents < 0
                          ? "text-[#f4a594]"
                          : "text-white/85"
                      }`}
                    >
                      {impact.monthly_allocation_change_cents >= 0
                        ? "+"
                        : "-"}
                      {formatCents(
                        Math.abs(impact.monthly_allocation_change_cents)
                      )}
                      /mo
                    </dd>
                  </div>
                  <div>
                    <dt className="text-white/40">Est. completion</dt>
                    <dd className="mt-1 font-semibold text-white/85">
                      {formatMonthYear(
                        impact.adjusted_estimated_completion_date
                      )}
                    </dd>
                  </div>
                </dl>

                {(impact.delay_months > 0 ||
                  impact.funding_shortfall_cents > 0) && (
                  <p className="mt-3 text-xs font-semibold text-[#f4a594]">
                    {impact.delay_months > 0 &&
                      `Delayed by ~${impact.delay_months} month(s). `}
                    {impact.funding_shortfall_cents > 0 &&
                      `Expected shortfall of ${formatCents(
                        impact.funding_shortfall_cents
                      )} by the target date.`}
                  </p>
                )}

                <p className="mt-3 text-xs leading-5 text-white/55">
                  {conflictItem?.attribution_text ?? impact.explanation}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
