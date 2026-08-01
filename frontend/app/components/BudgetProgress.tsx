import type {
  Budget,
  CategoryTotal,
} from "../lib/api";
import { formatCents } from "../lib/api";

type Props = {
  budgets: Budget[];
  categories: CategoryTotal[];
};

function progressColor(percentage: number) {
  if (percentage >= 100) return "bg-rose-400";
  if (percentage >= 75) return "bg-amber-400";
  return "bg-[#55d6a7]";
}

function statusColor(percentage: number) {
  if (percentage >= 100) return "text-rose-300";
  if (percentage >= 75) return "text-amber-300";
  return "text-slate-500";
}

function statusLabel(percentage: number) {
  if (percentage >= 100) return "Over budget";
  if (percentage >= 75) return "Approaching limit";
  return "On track";
}

export default function BudgetProgress({
  budgets,
  categories,
}: Props) {
  const spending = Object.fromEntries(
    categories.map(
      ({ category, total_cents }) => [
        category,
        Math.max(0, -total_cents),
      ]
    )
  );

  if (budgets.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-white/[0.1] px-5 py-10 text-center">
        <p className="text-sm font-medium text-slate-300">
          No budgets configured
        </p>

        <p className="mt-1 text-sm text-slate-600">
          Set monthly limits to begin tracking
          category spending.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-white/[0.08] bg-[#101916]">
      {budgets.map((budget, index) => {
        const spent =
          spending[budget.category] ?? 0;

        const percentage = Math.round(
          (spent / budget.limit_cents) * 100
        );

        const remaining = Math.max(
          budget.limit_cents - spent,
          0
        );

        return (
          <div
            key={budget.id}
            className={`grid gap-4 px-5 py-5 sm:grid-cols-[minmax(140px,0.8fr)_minmax(220px,1.6fr)_130px] sm:items-center ${
              index > 0
                ? "border-t border-white/[0.08]"
                : ""
            }`}
          >
            <div>
              <p className="text-sm font-medium text-slate-200">
                {budget.category}
              </p>

              <p
                className={`mt-1 text-xs ${statusColor(
                  percentage
                )}`}
              >
                {statusLabel(percentage)}
              </p>
            </div>

            <div>
              <div className="flex items-center justify-between gap-4 text-xs">
                <span className="text-slate-500">
                  {formatCents(spent)} spent
                </span>

                <span className="text-slate-600">
                  {percentage}%
                </span>
              </div>

              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.07]">
                <div
                  className={`h-full rounded-full transition-all ${progressColor(
                    percentage
                  )}`}
                  style={{
                    width: `${Math.min(
                      percentage,
                      100
                    )}%`,
                  }}
                />
              </div>
            </div>

            <div className="sm:text-right">
              <p className="text-sm font-medium text-slate-300">
                {formatCents(
                  budget.limit_cents
                )}
              </p>

              <p className="mt-1 text-xs text-slate-600">
                {percentage >= 100
                  ? `${formatCents(
                      spent -
                        budget.limit_cents
                    )} over`
                  : `${formatCents(
                      remaining
                    )} left`}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
