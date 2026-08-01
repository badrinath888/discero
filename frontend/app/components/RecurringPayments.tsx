import type { RecurringPayment } from "../lib/api";
import { formatCents } from "../lib/api";

export default function RecurringPayments({
  payments,
}: {
  payments: RecurringPayment[];
}) {
  const monthlyTotal = payments.reduce(
    (total, payment) => total + payment.amount_cents,
    0
  );

  return (
    <section className="rounded-xl border border-white/[0.08] bg-[#0d141e] p-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold">
            Recurring payments
          </h2>
          <p className="mt-1 text-sm text-slate-400">
            Detected monthly subscriptions and bills
          </p>
        </div>

        <div className="rounded-xl border border-white/[0.08] bg-slate-900/60 px-4 py-2">
          <p className="text-xs text-slate-500">
            Estimated monthly total
          </p>
          <p className="mt-1 font-semibold text-rose-300">
            {formatCents(-monthlyTotal)}
          </p>
        </div>
      </div>

      <div className="mt-6 space-y-3">
        {payments.map((payment) => (
          <div
            key={`${payment.merchant}-${payment.last_payment}`}
            className="flex flex-col gap-3 rounded-lg border border-white/[0.08] bg-[#0d141e] p-4 sm:flex-row sm:items-center sm:justify-between"
          >
            <div>
              <p className="font-medium">{payment.merchant}</p>
              <p className="mt-1 text-xs text-slate-500">
                {payment.frequency} · {payment.occurrences} payments
              </p>
            </div>

            <div className="sm:text-right">
              <p className="font-semibold text-rose-300">
                {formatCents(-payment.amount_cents)}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Last paid{" "}
                {new Date(
                  `${payment.last_payment}T00:00:00`
                ).toLocaleDateString("en-US")}
              </p>
            </div>
          </div>
        ))}

        {payments.length === 0 && (
          <p className="rounded-lg border border-dashed border-white/[0.08] px-5 py-10 text-center text-sm text-slate-500">
            No recurring payments detected yet.
          </p>
        )}
      </div>
    </section>
  );
}