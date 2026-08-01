"use client";

import type { MonthTotal } from "../lib/api";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export default function MonthlyTrend({
  data,
}: {
  data: MonthTotal[];
}) {
  const chartData = data.map(
    ({ month, income_cents, spending_cents }) => {
      const [year, monthNumber] = month
        .split("-")
        .map(Number);

      return {
        month: new Intl.DateTimeFormat("en-US", {
          month: "short",
        }).format(
          new Date(year, monthNumber - 1, 1)
        ),
        income: income_cents / 100,
        spending: spending_cents / 100,
      };
    }
  );

  return (
    <section className="border-b border-white/[0.08] py-8">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-[-0.02em] text-slate-100">
            Monthly cash flow
          </h2>

          <p className="mt-1 text-sm text-slate-500">
            Income and spending trends over time
          </p>
        </div>

        <div className="flex items-center gap-5 text-xs text-slate-500">
          <span className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-sm bg-[#55d6a7]" />
            Income
          </span>

          <span className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-sm bg-rose-400" />
            Spending
          </span>
        </div>
      </div>

      <div className="mt-6 h-[290px] rounded-xl border border-white/[0.08] bg-[#101916] px-3 pb-3 pt-5 sm:px-5">
        {chartData.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-600">
            No monthly cash-flow data available.
          </div>
        ) : (
          <ResponsiveContainer
            width="100%"
            height="100%"
          >
            <BarChart
              data={chartData}
              barGap={5}
              barCategoryGap="48%"
              accessibilityLayer={false}
              margin={{
                top: 4,
                right: 10,
                bottom: 0,
                left: 0,
              }}
            >
              <CartesianGrid
                vertical={false}
                stroke="rgba(148,163,184,0.09)"
                strokeDasharray="3 5"
              />

              <XAxis
                dataKey="month"
                axisLine={false}
                tickLine={false}
                tick={{
                  fill: "#64748b",
                  fontSize: 11,
                }}
              />

              <YAxis
                axisLine={false}
                tickLine={false}
                width={66}
                tick={{
                  fill: "#64748b",
                  fontSize: 11,
                }}
                tickFormatter={(value) =>
                  `$${Number(value).toLocaleString(
                    "en-US",
                    {
                      notation: "compact",
                    }
                  )}`
                }
              />

              <Tooltip
                cursor={{
                  fill: "rgba(255,255,255,0.025)",
                }}
                formatter={(value, name) => [
                  Number(value ?? 0).toLocaleString(
                    "en-US",
                    {
                      style: "currency",
                      currency: "USD",
                    }
                  ),
                  name === "income"
                    ? "Income"
                    : "Spending",
                ]}
                contentStyle={{
                  background: "#111925",
                  border:
                    "1px solid rgba(148,163,184,0.14)",
                  borderRadius: "8px",
                  boxShadow:
                    "0 18px 40px rgba(0,0,0,0.3)",
                }}
                itemStyle={{
                  color: "#cbd5e1",
                  fontSize: "12px",
                }}
                labelStyle={{
                  color: "#f1f5f9",
                  fontSize: "12px",
                  marginBottom: "6px",
                }}
              />

              <Bar
                dataKey="income"
                fill="#55d6a7"
                radius={[3, 3, 0, 0]}
                maxBarSize={42}
              />

              <Bar
                dataKey="spending"
                fill="#fb7185"
                radius={[3, 3, 0, 0]}
                maxBarSize={42}
              />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}
