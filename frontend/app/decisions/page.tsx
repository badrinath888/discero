"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  BadgeDollarSign,
  CalendarDays,
  CheckCircle2,
  CircleAlert,
  Gauge,
  Lightbulb,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import { PageReveal, Reveal } from "../components/PremiumMotion";
import {
  api,
  formatCents,
  MajorPurchaseSimulationResult,
  session,
} from "../lib/api";

function toDateInputValue(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function addDays(date: Date, days: number): Date {
  const result = new Date(date);
  result.setDate(result.getDate() + days);
  return result;
}

function dollarsToCents(value: string): number {
  const amount = Number(value);

  if (!Number.isFinite(amount)) {
    return 0;
  }

  return Math.round(amount * 100);
}

export default function DecisionsPage() {
  const router = useRouter();
  const today = useMemo(() => new Date(), []);

  const [userId, setUserId] = useState<number | null>(null);
  const [purchaseName, setPurchaseName] = useState("New laptop");
  const [purchaseAmount, setPurchaseAmount] = useState("2000");
  const [purchaseDate, setPurchaseDate] = useState(
    toDateInputValue(addDays(today, 7))
  );
  const [safetyReserve, setSafetyReserve] = useState("1000");
  const [essentialSpending, setEssentialSpending] = useState("500");
  const [horizonDays, setHorizonDays] = useState("30");
  const [result, setResult] =
    useState<MajorPurchaseSimulationResult | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [simulating, setSimulating] = useState(false);
  const [error, setError] = useState("");

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
      } catch {
        session.clear();
        router.replace("/");
      } finally {
        setInitializing(false);
      }
    }

    void initialize();
  }, [router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (userId === null) return;

    setError("");
    setSimulating(true);

    try {
      const data = await api.simulateMajorPurchase(userId, {
        purchase_name: purchaseName.trim(),
        purchase_amount_cents: dollarsToCents(purchaseAmount),
        purchase_date: purchaseDate,
        safety_reserve_cents: dollarsToCents(safetyReserve),
        essential_spending_cents: dollarsToCents(essentialSpending),
        horizon_days: Number(horizonDays),
      });

      setResult(data);
    } catch (err) {
      setResult(null);
      setError(
        err instanceof Error
          ? err.message
          : "Unable to simulate this purchase"
      );
    } finally {
      setSimulating(false);
    }
  }

  const statusContent = {
    affordable: {
      label: "Affordable",
      description:
        "This purchase stays within the recommended decision range.",
      className: "bg-[#dff6c7] text-[#315d31]",
      icon: CheckCircle2,
    },
    caution: {
      label: "Proceed with caution",
      description:
        "The purchase fits, but it uses more than the recommended ceiling.",
      className: "bg-[#f5d66f] text-[#66500f]",
      icon: TriangleAlert,
    },
    not_affordable: {
      label: "Not affordable",
      description:
        "This purchase exceeds the current safe-to-spend amount.",
      className: "bg-[#f0b8a8] text-[#7b3528]",
      icon: CircleAlert,
    },
  }[result?.affordability_status ?? "affordable"];

  const StatusIcon = statusContent.icon;

  return (
    <main className="min-h-screen bg-[#f5f1e8] text-[#14241e]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[1500px]">
          <Reveal>
            <header className="border-b border-[#14241e]/10 pb-7">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
                Decision intelligence
              </p>

              <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
                Major purchase simulator
              </h1>

              <p className="mt-3 max-w-3xl text-sm leading-6 text-[#66746e]">
                Test a purchase before making it. FinSight compares the
                cost with your liquid balance, active obligations, safety
                reserve, and essential spending.
              </p>
            </header>
          </Reveal>

          <section className="mt-8 grid gap-6 xl:grid-cols-[0.78fr_1.22fr]">
            <Reveal>
              <form
                onSubmit={handleSubmit}
                className="rounded-[30px] border border-[#14241e]/10 bg-white p-6 shadow-[0_18px_50px_rgba(20,36,30,0.08)] sm:p-8"
              >
                <div className="flex items-center gap-3">
                  <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#dff6c7] text-[#167c5a]">
                    <BadgeDollarSign className="h-5 w-5" />
                  </span>

                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#167c5a]">
                      Scenario inputs
                    </p>
                    <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em]">
                      What are you planning to buy?
                    </h2>
                  </div>
                </div>

                <div className="mt-7 space-y-5">
                  <Field
                    label="Purchase name"
                    value={purchaseName}
                    onChange={setPurchaseName}
                    placeholder="New laptop"
                    required
                  />

                  <Field
                    label="Purchase amount"
                    value={purchaseAmount}
                    onChange={setPurchaseAmount}
                    type="number"
                    min="0.01"
                    step="0.01"
                    prefix="$"
                    required
                  />

                  <label className="block">
                    <span className="text-sm font-semibold text-[#263c34]">
                      Purchase date
                    </span>
                    <div className="relative mt-2">
                      <CalendarDays className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[#7f8c86]" />
                      <input
                        type="date"
                        value={purchaseDate}
                        min={toDateInputValue(today)}
                        onChange={(event) =>
                          setPurchaseDate(event.target.value)
                        }
                        required
                        className="h-12 w-full rounded-xl border border-[#14241e]/10 bg-[#fbfaf7] pl-11 pr-4 text-sm outline-none transition focus:border-[#167c5a] focus:bg-white"
                      />
                    </div>
                  </label>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field
                      label="Safety reserve"
                      value={safetyReserve}
                      onChange={setSafetyReserve}
                      type="number"
                      min="0"
                      step="0.01"
                      prefix="$"
                    />

                    <Field
                      label="Essential spending"
                      value={essentialSpending}
                      onChange={setEssentialSpending}
                      type="number"
                      min="0"
                      step="0.01"
                      prefix="$"
                    />
                  </div>

                  <label className="block">
                    <span className="text-sm font-semibold text-[#263c34]">
                      Decision horizon
                    </span>
                    <select
                      value={horizonDays}
                      onChange={(event) =>
                        setHorizonDays(event.target.value)
                      }
                      className="mt-2 h-12 w-full rounded-xl border border-[#14241e]/10 bg-[#fbfaf7] px-4 text-sm outline-none transition focus:border-[#167c5a] focus:bg-white"
                    >
                      <option value="14">Next 14 days</option>
                      <option value="30">Next 30 days</option>
                      <option value="60">Next 60 days</option>
                      <option value="90">Next 90 days</option>
                    </select>
                  </label>
                </div>

                {error && (
                  <div className="mt-5 rounded-2xl border border-[#b65743]/20 bg-[#f0b8a8]/35 px-4 py-3 text-sm text-[#843d2f]">
                    {error}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={initializing || simulating || userId === null}
                  className="mt-7 inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#14241e] px-5 text-sm font-semibold text-white transition hover:bg-[#25443a] disabled:cursor-not-allowed disabled:opacity-55"
                >
                  {simulating ? "Running simulation..." : "Simulate purchase"}
                  {!simulating && <ArrowRight className="h-4 w-4" />}
                </button>
              </form>
            </Reveal>

            <Reveal delay={0.06}>
              {result ? (
                <article className="relative overflow-hidden rounded-[30px] bg-[#14241e] p-7 text-white shadow-[0_24px_70px_rgba(20,36,30,0.2)] sm:p-9">
                  <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-[#76dfbd]/15 blur-3xl" />

                  <div className="relative">
                    <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#83dcb9]">
                          Simulation result
                        </p>
                        <h2 className="mt-3 text-3xl font-semibold tracking-[-0.045em]">
                          {result.purchase_name}
                        </h2>
                        <p className="mt-2 text-sm text-white/50">
                          {new Date(
                            `${result.purchase_date}T00:00:00`
                          ).toLocaleDateString("en-US", {
                            month: "long",
                            day: "numeric",
                            year: "numeric",
                          })}
                        </p>
                      </div>

                      <span
                        className={`inline-flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${statusContent.className}`}
                      >
                        <StatusIcon className="h-4 w-4" />
                        {statusContent.label}
                      </span>
                    </div>

                    <div className="mt-8">
                      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-white/35">
                        Safe to spend after purchase
                      </p>
                      <p className="mt-3 text-5xl font-semibold tracking-[-0.06em] sm:text-6xl">
                        {formatCents(
                          result.safe_to_spend_after_purchase_cents
                        )}
                      </p>
                      <p className="mt-3 max-w-2xl text-sm leading-6 text-white/55">
                        {statusContent.description}
                      </p>
                    </div>

                    <div className="mt-9 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-2 xl:grid-cols-4">
                      <ResultMetric
                        label="Purchase"
                        value={formatCents(
                          -result.purchase_amount_cents
                        )}
                      />
                      <ResultMetric
                        label="Before purchase"
                        value={formatCents(
                          result.safe_to_spend_before_purchase_cents
                        )}
                      />
                      <ResultMetric
                        label="Impact"
                        value={`${result.purchase_impact_percent}%`}
                      />
                      <ResultMetric
                        label="Confidence"
                        value={`${Math.round(
                          result.confidence_score
                        )}%`}
                      />
                    </div>

                    <div className="mt-7 rounded-2xl border border-white/10 bg-white/[0.045] p-5">
                      <div className="flex items-start gap-3">
                        <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-[#83dcb9]" />
                        <div>
                          <p className="text-sm font-semibold">
                            FinSight explanation
                          </p>
                          <p className="mt-2 text-sm leading-6 text-white/58">
                            {result.explanation}
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className="mt-7 grid gap-4 sm:grid-cols-2">
                      <DecisionStat
                        icon={ShieldCheck}
                        label="Recommended maximum"
                        value={formatCents(
                          result.recommended_max_purchase_cents
                        )}
                      />
                      <DecisionStat
                        icon={Gauge}
                        label="Shortfall after purchase"
                        value={formatCents(
                          -result.shortfall_after_purchase_cents
                        )}
                        warning={
                          result.shortfall_after_purchase_cents > 0
                        }
                      />
                    </div>

                    {result.alternatives.length > 0 && (
                      <div className="mt-8 border-t border-white/10 pt-7">
                        <p className="text-xs font-semibold uppercase tracking-[0.15em] text-white/40">
                          Safer alternatives
                        </p>

                        <div className="mt-4 grid gap-4 sm:grid-cols-2">
                          {result.alternatives.map((alternative) => (
                            <div
                              key={`${alternative.label}-${alternative.purchase_amount_cents}`}
                              className="rounded-2xl border border-white/10 bg-white/[0.045] p-5"
                            >
                              <p className="text-sm font-semibold text-[#83dcb9]">
                                {alternative.label}
                              </p>
                              <p className="mt-2 text-2xl font-semibold tracking-[-0.035em]">
                                {formatCents(
                                  alternative.purchase_amount_cents
                                )}
                              </p>
                              <p className="mt-2 text-xs leading-5 text-white/45">
                                {alternative.description}
                              </p>
                              <p className="mt-4 text-xs text-white/55">
                                Leaves{" "}
                                {formatCents(
                                  alternative.remaining_safe_to_spend_cents
                                )}{" "}
                                safe to spend
                              </p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </article>
              ) : (
                <article className="flex min-h-[620px] flex-col items-center justify-center rounded-[30px] border border-dashed border-[#14241e]/15 bg-white p-8 text-center">
                  <span className="flex h-16 w-16 items-center justify-center rounded-[24px] bg-[#dff6c7] text-[#167c5a]">
                    <Sparkles className="h-7 w-7" />
                  </span>

                  <h2 className="mt-6 text-2xl font-semibold tracking-[-0.035em]">
                    See the impact before you spend
                  </h2>

                  <p className="mt-3 max-w-md text-sm leading-6 text-[#6d7a74]">
                    Enter a purchase scenario to compare affordability,
                    remaining safe-to-spend, shortfall risk, and safer
                    alternatives.
                  </p>
                </article>
              )}
            </Reveal>
          </section>
        </PageReveal>
      </div>
    </main>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  prefix,
  min,
  step,
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "number";
  placeholder?: string;
  prefix?: string;
  min?: string;
  step?: string;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="text-sm font-semibold text-[#263c34]">
        {label}
      </span>

      <div className="relative mt-2">
        {prefix && (
          <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-sm font-semibold text-[#728078]">
            {prefix}
          </span>
        )}

        <input
          type={type}
          value={value}
          min={min}
          step={step}
          required={required}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          className={`h-12 w-full rounded-xl border border-[#14241e]/10 bg-[#fbfaf7] pr-4 text-sm outline-none transition focus:border-[#167c5a] focus:bg-white ${
            prefix ? "pl-9" : "pl-4"
          }`}
        />
      </div>
    </label>
  );
}

function ResultMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="bg-white/[0.045] p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/35">
        {label}
      </p>
      <p className="mt-2 text-lg font-semibold">{value}</p>
    </div>
  );
}

function DecisionStat({
  icon: Icon,
  label,
  value,
  warning = false,
}: {
  icon: typeof ShieldCheck;
  label: string;
  value: string;
  warning?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.045] p-5">
      <div className="flex items-center gap-3">
        <span
          className={`flex h-10 w-10 items-center justify-center rounded-xl ${
            warning
              ? "bg-[#f0b8a8]/15 text-[#f4a594]"
              : "bg-[#83dcb9]/10 text-[#83dcb9]"
          }`}
        >
          <Icon className="h-5 w-5" />
        </span>
        <div>
          <p className="text-xs text-white/40">{label}</p>
          <p
            className={`mt-1 text-lg font-semibold ${
              warning ? "text-[#f4a594]" : "text-white"
            }`}
          >
            {value}
          </p>
        </div>
      </div>
    </div>
  );
}
