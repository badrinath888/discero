"use client";

import type { MonthTotal } from "../lib/api";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export default function MonthlyTrend({ data }: { data: MonthTotal[] }) {
  const chartData = data.map(({ month, income_cents, spending_cents }) => {
    const [year, monthNumber] = month.split("-").map(Number);

    return {
      month: new Intl.DateTimeFormat("en-US", {
        month: "short",
        year: "numeric",
      }).format(new Date(year, monthNumber - 1, 1)),
      income: income_cents / 100,
      spending: spending_cents / 100,
    };
  });

  return (
    <section className="rounded-3xl border border-white/10 bg-white/[0.06] p-6">
      <h2 className="text-lg font-semibold">Monthly cash flow</h2>
      <p className="mt-1 text-sm text-slate-400">
        Income and spending by month
      </p>

      <div className="mt-6 h-80">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartData}
            barGap={12}
            barCategoryGap="55%"
            accessibilityLayer={false}
          >
            <CartesianGrid
              vertical={false}
              stroke="rgba(255,255,255,0.08)"
              strokeDasharray="4 4"
            />

            <XAxis
              dataKey="month"
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#94a3b8", fontSize: 12 }}
            />

            <YAxis
              axisLine={false}
              tickLine={false}
              width={70}
              tick={{ fill: "#94a3b8", fontSize: 12 }}
              tickFormatter={(value) => `$${value.toLocaleString()}`}
            />

            <Tooltip
              cursor={{ fill: "rgba(255,255,255,0.03)" }}
              formatter={(value, name) => [
                Number(value ?? 0).toLocaleString("en-US", {
                  style: "currency",
                  currency: "USD",
                }),
                name === "income" ? "Income" : "Spending",
              ]}
              contentStyle={{
                background: "#0f172a",
                border: "1px solid rgba(255,255,255,0.12)",
                borderRadius: "12px",
              }}
              labelStyle={{ color: "#f8fafc" }}
            />

            <Legend
              formatter={(value) =>
                value === "income" ? "Income" : "Spending"
              }
            />

            <Bar
              dataKey="income"
              fill="#34d399"
              radius={[6, 6, 0, 0]}
              maxBarSize={72}
            />

            <Bar
              dataKey="spending"
              fill="#fb7185"
              radius={[6, 6, 0, 0]}
              maxBarSize={72}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}