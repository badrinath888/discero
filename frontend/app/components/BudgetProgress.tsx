import type { Budget, CategoryTotal } from "../lib/api";
import { formatCents } from "../lib/api";

type Props = {
  budgets: Budget[];
  categories: CategoryTotal[];
};

function progressColor(percentage: number) {
  if (percentage >= 100) return "bg-rose-400";
  if (percentage >= 75) return "bg-amber-400";
  return "bg-emerald-400";
}

function statusColor(percentage: number) {
  if (percentage >= 100) return "text-rose-300";
  if (percentage >= 75) return "text-amber-300";
  return "text-slate-500";
}

export default function BudgetProgress({ budgets, categories }: Props) {
  const spending = Object.fromEntries(
    categories.map(({ category, total_cents }) => [
      category,
      Math.max(0, -total_cents),
    ])
  );

  return (
    <section className="rounded-3xl border border-white/10 bg-white/[0.06] p-6">
      <h2 className="text-lg font-semibold">Budget progress</h2>
      <p className="mt-1 text-sm text-slate-400">
        Monthly spending against your limits
      </p>

      <div className="mt-6 space-y-5">
        {budgets.map((budget) => {
          const spent = spending[budget.category] ?? 0;
          const percentage = Math.round(
            (spent / budget.limit_cents) * 100
          );

          return (
            <div key={budget.id}>
              <div className="flex justify-between text-sm">
                <span>{budget.category}</span>

                <span className="text-slate-400">
                  {formatCents(spent)} /{" "}
                  {formatCents(budget.limit_cents)}
                </span>
              </div>

              <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/10">
                <div
                  className={`h-full rounded-full ${progressColor(
                    percentage
                  )}`}
                  style={{
                    width: `${Math.min(percentage, 100)}%`,
                  }}
                />
              </div>

              <p
                className={`mt-1 text-xs ${statusColor(
                  percentage
                )}`}
              >
                {percentage}% used
              </p>
            </div>
          );
        })}

        {budgets.length === 0 && (
          <p className="text-sm text-slate-500">
            Set a budget to begin tracking progress.
          </p>
        )}
      </div>
    </section>
  );
}