"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  BadgeDollarSign,
  CalendarClock,
  CalendarDays,
  CheckCircle2,
  CircleAlert,
  Clock,
  Compass,
  Gauge,
  GitCompareArrows,
  Lightbulb,
  ListChecks,
  Scale,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AdaptiveIntelligenceSection from "../components/AdaptiveIntelligenceSection";
import DataFreshnessNote from "../components/DataFreshnessNote";
import AppSidebar from "../components/AppSidebar";
import GoalImpactList from "../components/GoalImpactList";
import MultiStepScenarioPlanner from "../components/MultiStepScenarioPlanner";
import { PageReveal, Reveal } from "../components/PremiumMotion";
import WhatIfSimulator from "../components/WhatIfSimulator";
import {
  api,
  BuyNowVsWaitRequest,
  BuyNowVsWaitResult,
  DecisionType,
  FinancialStressScenarioType,
  FinancialStressTestRequest,
  FinancialStressTestResult,
  formatCents,
  MajorPurchaseSimulationRequest,
  MajorPurchaseSimulationResult,
  ScenarioComparisonRequest,
  ScenarioComparisonResult,
  ScenarioComparisonScorecard,
  session,
} from "../lib/api";

type DecisionMode =
  | "single"
  | "compare"
  | "stress"
  | "buy_now_wait"
  | "what_if"
  | "multi_step";

const SCENARIO_OPTIONS: {
  value: FinancialStressScenarioType;
  label: string;
}[] = [
  { value: "emergency_expense", label: "Emergency expense" },
  {
    value: "temporary_income_loss",
    label: "Temporary income loss",
  },
  { value: "delayed_paycheck", label: "Delayed paycheck" },
  {
    value: "recurring_bill_increase",
    label: "Recurring bill increase",
  },
  {
    value: "income_reduction",
    label: "Temporary income reduction",
  },
  { value: "one_time_expense", label: "One-time expense" },
  {
    value: "recurring_expense_increase",
    label: "Recurring expense increase",
  },
  { value: "combined", label: "Combined downside scenario" },
];

const INCOME_PERCENT_SCENARIOS = new Set<FinancialStressScenarioType>([
  "income_reduction",
  "combined",
]);
const RECURRING_PERCENT_SCENARIOS = new Set<FinancialStressScenarioType>([
  "recurring_expense_increase",
  "combined",
]);
const AMOUNT_HIDDEN_SCENARIOS = new Set<FinancialStressScenarioType>([
  "income_reduction",
  "recurring_expense_increase",
]);

const DURATION_REQUIRED_SCENARIOS = new Set<FinancialStressScenarioType>([
  "temporary_income_loss",
  "delayed_paycheck",
]);

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

function validateStressInputs(input: {
  scenarioType: FinancialStressScenarioType;
  stressAmount: string;
  stressAmountRequired: boolean;
  showIncomePercent: boolean;
  incomeReductionPercent: string;
  showRecurringPercent: boolean;
  recurringIncreasePercent: string;
}): string {
  const {
    stressAmount,
    stressAmountRequired,
    showIncomePercent,
    incomeReductionPercent,
    showRecurringPercent,
    recurringIncreasePercent,
  } = input;

  if (stressAmountRequired) {
    const amount = Number(stressAmount);

    if (!stressAmount.trim() || !Number.isFinite(amount) || amount <= 0) {
      return "Enter a stress amount greater than $0.";
    }
  }

  if (showIncomePercent && incomeReductionPercent.trim()) {
    const percent = Number(incomeReductionPercent);

    if (!Number.isFinite(percent) || percent <= 0 || percent > 100) {
      return "Income reduction must be between 0 and 100 percent.";
    }
  } else if (showIncomePercent && input.scenarioType === "income_reduction") {
    return "Enter an income reduction percentage.";
  }

  if (showRecurringPercent && recurringIncreasePercent.trim()) {
    const percent = Number(recurringIncreasePercent);

    if (!Number.isFinite(percent) || percent <= 0 || percent > 500) {
      return "Recurring expense increase must be between 0 and 500 percent.";
    }
  } else if (
    showRecurringPercent &&
    input.scenarioType === "recurring_expense_increase"
  ) {
    return "Enter a recurring expense increase percentage.";
  }

  if (
    input.scenarioType === "combined" &&
    !stressAmount.trim() &&
    !incomeReductionPercent.trim() &&
    !recurringIncreasePercent.trim()
  ) {
    return "Enter at least one stress input for the combined scenario.";
  }

  return "";
}

const STATUS_CONTENT = {
  affordable: {
    label: "Affordable",
    description:
      "This purchase stays within the recommended decision range.",
    className: "bg-[#E3EBE1] text-[#48634B]",
    icon: CheckCircle2,
  },
  caution: {
    label: "Proceed with caution",
    description:
      "The purchase fits, but it uses more than the recommended ceiling.",
    className: "bg-[#FBF1DF] text-[#8A5A20]",
    icon: TriangleAlert,
  },
  not_affordable: {
    label: "Not affordable",
    description:
      "This purchase exceeds the current safe-to-spend amount.",
    className: "bg-[#F8E6E1] text-[#8F3F33]",
    icon: CircleAlert,
  },
} as const;

const RISK_CONTENT = {
  resilient: {
    label: "Resilient",
    description:
      "Your finances can comfortably absorb this stress event.",
    className: "bg-[#E3EBE1] text-[#48634B]",
    icon: ShieldCheck,
  },
  strained: {
    label: "Strained",
    description:
      "This event would strain your finances but not push you negative.",
    className: "bg-[#FBF1DF] text-[#8A5A20]",
    icon: TriangleAlert,
  },
  critical: {
    label: "Critical",
    description:
      "This event would push your safe-to-spend into a shortfall.",
    className: "bg-[#F8E6E1] text-[#8F3F33]",
    icon: CircleAlert,
  },
} as const;

const TIMING_CONTENT: Record<
  BuyNowVsWaitResult["recommended_timing"],
  { label: string; className: string; icon: typeof CheckCircle2 }
> = {
  buy_now: {
    label: "Buy now",
    className: "bg-[#E3EBE1] text-[#48634B]",
    icon: CheckCircle2,
  },
  wait: {
    label: "Wait",
    className: "bg-[#E3EBE1] text-[#48634B]",
    icon: Clock,
  },
  either: {
    label: "Either works",
    className: "bg-[#FBF1DF] text-[#8A5A20]",
    icon: Scale,
  },
  neither: {
    label: "Neither works right now",
    className: "bg-[#F8E6E1] text-[#8F3F33]",
    icon: CircleAlert,
  },
};

const SEVERITY_CONTENT: Record<
  FinancialStressTestResult["severity"],
  { label: string; className: string }
> = {
  low: { label: "Low", className: "bg-[#E3EBE1] text-[#48634B]" },
  moderate: {
    label: "Moderate",
    className: "bg-[#FBF1DF] text-[#8A5A20]",
  },
  high: { label: "High", className: "bg-[#FBF1DF] text-[#8A5A20]" },
  critical: {
    label: "Critical",
    className: "bg-[#F8E6E1] text-[#8F3F33]",
  },
};

const KEY_DRIVER_LABELS: Record<
  FinancialStressTestResult["key_driver"],
  string
> = {
  income_loss: "Lost or reduced income",
  recurring_expense_increase: "Recurring expense increase",
  emergency_expense: "One-time emergency expense",
  baseline_shortfall: "Existing shortfall before this scenario",
};

const CONFIDENCE_LEVEL_CONTENT: Record<
  "high" | "medium" | "low",
  { label: string; className: string }
> = {
  high: { label: "High", className: "bg-[#E3EBE1] text-[#48634B]" },
  medium: { label: "Medium", className: "bg-[#FBF1DF] text-[#8A5A20]" },
  low: { label: "Low", className: "bg-[#F8E6E1] text-[#8F3F33]" },
};

export default function DecisionsPage() {
  const router = useRouter();
  const today = useMemo(() => new Date(), []);

  const [mode, setMode] = useState<DecisionMode>("single");
  const [userId, setUserId] = useState<number | null>(null);
  const [purchaseName, setPurchaseName] = useState("New laptop");
  const [purchaseAmount, setPurchaseAmount] = useState("2000");
  const [purchaseDate, setPurchaseDate] = useState(
    toDateInputValue(addDays(today, 7))
  );
  const [optionAName, setOptionAName] = useState("New laptop");
  const [optionAAmount, setOptionAAmount] = useState("2000");
  const [optionADate, setOptionADate] = useState(
    toDateInputValue(addDays(today, 7))
  );
  const [optionBName, setOptionBName] = useState("Used laptop");
  const [optionBAmount, setOptionBAmount] = useState("1200");
  const [optionBDate, setOptionBDate] = useState(
    toDateInputValue(addDays(today, 7))
  );
  const [safetyReserve, setSafetyReserve] = useState("1000");
  const [essentialSpending, setEssentialSpending] = useState("500");
  const [horizonDays, setHorizonDays] = useState("30");
  const [scenarioType, setScenarioType] =
    useState<FinancialStressScenarioType>("emergency_expense");
  const [scenarioName, setScenarioName] = useState(
    "Emergency car repair"
  );
  const [stressAmount, setStressAmount] = useState("1500");
  const [incomeReductionPercent, setIncomeReductionPercent] =
    useState("20");
  const [recurringIncreasePercent, setRecurringIncreasePercent] =
    useState("15");
  const [eventDate, setEventDate] = useState(
    toDateInputValue(addDays(today, 7))
  );
  const [durationDays, setDurationDays] = useState("");
  const [waitPurchaseName, setWaitPurchaseName] = useState("New laptop");
  const [waitPurchaseAmount, setWaitPurchaseAmount] = useState("2000");
  const [buyNowDate, setBuyNowDate] = useState(toDateInputValue(today));
  const [waitUntilDate, setWaitUntilDate] = useState(
    toDateInputValue(addDays(today, 30))
  );
  const [result, setResult] =
    useState<MajorPurchaseSimulationResult | null>(null);
  const [compareResult, setCompareResult] =
    useState<ScenarioComparisonResult | null>(null);
  const [stressResult, setStressResult] =
    useState<FinancialStressTestResult | null>(null);
  const [buyNowVsWaitResult, setBuyNowVsWaitResult] =
    useState<BuyNowVsWaitResult | null>(null);
  const [lastPurchaseInput, setLastPurchaseInput] =
    useState<MajorPurchaseSimulationRequest | null>(null);
  const [lastComparisonInput, setLastComparisonInput] =
    useState<ScenarioComparisonRequest | null>(null);
  const [lastStressInput, setLastStressInput] =
    useState<FinancialStressTestRequest | null>(null);
  const [lastBuyNowVsWaitInput, setLastBuyNowVsWaitInput] =
    useState<BuyNowVsWaitRequest | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [simulating, setSimulating] = useState(false);
  const [error, setError] = useState("");
  const topControlsRef = useRef<HTMLDivElement>(null);

  function scrollToTopControls() {
    topControlsRef.current?.scrollIntoView?.({
      behavior: "smooth",
      block: "start",
    });
  }

  const durationRequired = DURATION_REQUIRED_SCENARIOS.has(scenarioType);
  const showIncomePercent = INCOME_PERCENT_SCENARIOS.has(scenarioType);
  const showRecurringPercent =
    RECURRING_PERCENT_SCENARIOS.has(scenarioType);
  const showStressAmount = !AMOUNT_HIDDEN_SCENARIOS.has(scenarioType);
  const stressAmountRequired =
    showStressAmount && scenarioType !== "combined";

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

  function handleModeChange(nextMode: DecisionMode) {
    setMode(nextMode);
    setError("");
    setResult(null);
    setCompareResult(null);
    setStressResult(null);
    setBuyNowVsWaitResult(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (userId === null) return;

    if (mode === "stress") {
      const validationError = validateStressInputs({
        scenarioType,
        stressAmount,
        stressAmountRequired,
        showIncomePercent,
        incomeReductionPercent,
        showRecurringPercent,
        recurringIncreasePercent,
      });

      if (validationError) {
        setError(validationError);
        return;
      }
    }

    if (mode === "buy_now_wait" && waitUntilDate <= buyNowDate) {
      setError("The wait date must be after the buy-now date.");
      return;
    }

    setError("");
    setSimulating(true);

    const sharedSettings = {
      safety_reserve_cents: dollarsToCents(safetyReserve),
      essential_spending_cents: dollarsToCents(essentialSpending),
      horizon_days: Number(horizonDays),
    };

    try {
      if (mode === "single") {
        const payload: MajorPurchaseSimulationRequest = {
          purchase_name: purchaseName.trim(),
          purchase_amount_cents: dollarsToCents(purchaseAmount),
          purchase_date: purchaseDate,
          ...sharedSettings,
        };
        const data = await api.simulateMajorPurchase(userId, payload);

        setResult(data);
        setCompareResult(null);
        setStressResult(null);
        setBuyNowVsWaitResult(null);
        setLastPurchaseInput(payload);
      } else if (mode === "compare") {
        const payload: ScenarioComparisonRequest = {
          option_a: {
            purchase_name: optionAName.trim(),
            purchase_amount_cents: dollarsToCents(optionAAmount),
            purchase_date: optionADate,
            ...sharedSettings,
          },
          option_b: {
            purchase_name: optionBName.trim(),
            purchase_amount_cents: dollarsToCents(optionBAmount),
            purchase_date: optionBDate,
            ...sharedSettings,
          },
        };
        const data = await api.compareMajorPurchaseScenarios(
          userId,
          payload
        );

        setCompareResult(data);
        setResult(null);
        setStressResult(null);
        setBuyNowVsWaitResult(null);
        setLastComparisonInput(payload);
      } else if (mode === "buy_now_wait") {
        const payload: BuyNowVsWaitRequest = {
          purchase_name: waitPurchaseName.trim(),
          purchase_amount_cents: dollarsToCents(waitPurchaseAmount),
          buy_now_date: buyNowDate,
          wait_until_date: waitUntilDate,
          ...sharedSettings,
        };
        const data = await api.evaluateBuyNowVsWait(userId, payload);

        setBuyNowVsWaitResult(data);
        setResult(null);
        setCompareResult(null);
        setStressResult(null);
        setLastBuyNowVsWaitInput(payload);
      } else {
        const payload: FinancialStressTestRequest = {
          scenario_type: scenarioType,
          scenario_name: scenarioName.trim(),
          stress_amount_cents:
            showStressAmount && stressAmount.trim()
              ? dollarsToCents(stressAmount)
              : null,
          income_reduction_percent:
            showIncomePercent && incomeReductionPercent.trim()
              ? Number(incomeReductionPercent)
              : null,
          recurring_expense_increase_percent:
            showRecurringPercent && recurringIncreasePercent.trim()
              ? Number(recurringIncreasePercent)
              : null,
          event_date: eventDate,
          duration_days: durationDays.trim()
            ? Number(durationDays)
            : null,
          ...sharedSettings,
        };
        const data = await api.runFinancialStressTest(userId, payload);
        setLastStressInput(payload);

        setStressResult(data);
        setResult(null);
        setCompareResult(null);
        setBuyNowVsWaitResult(null);
      }
    } catch (err) {
      setResult(null);
      setCompareResult(null);
      setStressResult(null);
      setBuyNowVsWaitResult(null);
      setError(
        err instanceof Error
          ? err.message
          : mode === "single"
            ? "Unable to simulate this purchase"
            : mode === "compare"
              ? "Unable to compare these options"
              : mode === "buy_now_wait"
                ? "Unable to compare buy now vs wait"
                : "Unable to run this stress test"
      );
    } finally {
      setSimulating(false);
    }
  }

  const statusContent =
    STATUS_CONTENT[result?.affordability_status ?? "affordable"];
  const StatusIcon = statusContent.icon;
  const riskContent =
    RISK_CONTENT[stressResult?.risk_level ?? "resilient"];
  const RiskIcon = riskContent.icon;
  const timingContent =
    TIMING_CONTENT[buyNowVsWaitResult?.recommended_timing ?? "either"];
  const TimingIcon = timingContent.icon;

  return (
    <main className="min-h-screen bg-[#F5F1EA] text-[#181713]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-56 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto w-full max-w-[1500px]">
          <Reveal>
            <header className="border-b border-[#181713]/10 pb-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
                Decision Lab
              </p>

              <h1 className="mt-1 text-[32px] font-semibold tracking-[-0.03em]">
                {mode === "stress"
                  ? "Financial stress test"
                  : mode === "buy_now_wait"
                    ? "Buy now vs wait"
                    : mode === "what_if"
                      ? "What-if simulator"
                      : mode === "multi_step"
                        ? "Multi-step plan"
                        : "Major purchase simulator"}
              </h1>

              <p className="mt-1 max-w-3xl text-sm leading-6 text-[#706961]">
                {mode === "stress"
                  ? "Model how an emergency expense, income loss, delayed paycheck, or bill increase would affect your safe-to-spend position."
                  : mode === "buy_now_wait"
                    ? "Compare buying a purchase today against waiting until a later date, and see which timing leaves you better off."
                    : mode === "what_if"
                      ? "Model a hypothetical change -- a purchase, a bill increase, a change in income -- and see the effect on your safe-to-spend position before it happens."
                      : mode === "multi_step"
                        ? "Sequence several dated financial events and see how they add up chronologically against your real safe-to-spend baseline."
                        : "Test a purchase before making it. Discero compares the cost with your liquid balance, active obligations, safety reserve, and essential spending."}
              </p>

              <div
                ref={topControlsRef}
                className="mt-6 flex flex-wrap items-center gap-3 scroll-mt-24"
              >
                <div className="inline-flex flex-wrap gap-1 rounded-2xl border border-[#181713]/10 bg-white p-1 shadow-[0_8px_24px_rgba(60,43,35,0.06)]">
                  <ModeButton
                    active={mode === "single"}
                    onClick={() => handleModeChange("single")}
                    label="Single purchase"
                  />
                  <ModeButton
                    active={mode === "compare"}
                    onClick={() => handleModeChange("compare")}
                    label="Compare options"
                  />
                  <ModeButton
                    active={mode === "buy_now_wait"}
                    onClick={() => handleModeChange("buy_now_wait")}
                    label="Buy now vs wait"
                  />
                  <ModeButton
                    active={mode === "stress"}
                    onClick={() => handleModeChange("stress")}
                    label="Financial stress test"
                  />
                  <ModeButton
                    active={mode === "what_if"}
                    onClick={() => handleModeChange("what_if")}
                    label="What-if simulator"
                  />
                  <ModeButton
                    active={mode === "multi_step"}
                    onClick={() => handleModeChange("multi_step")}
                    label="Multi-step plan"
                  />
                </div>

                <Link
                  href="/decisions/history"
                  className="discero-button-tertiary inline-flex items-center gap-1.5 rounded-full px-4 py-2.5 text-sm font-semibold transition"
                >
                  View saved decisions
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </div>
            </header>
          </Reveal>

          {mode === "what_if" ? (
            <WhatIfSimulator userId={userId} />
          ) : mode === "multi_step" ? (
            <MultiStepScenarioPlanner userId={userId} />
          ) : (
          <section className="mt-8 grid gap-8 xl:grid-cols-[0.76fr_1.24fr]">
            <Reveal>
              <form
                onSubmit={handleSubmit}
                className="border-y border-[#181713]/10 bg-[#FFFCF7] p-6 sm:p-8"
              >
                <div className="flex items-center gap-3">
                  <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#EDE5DE] text-[#6E4B63]">
                    {mode === "single" ? (
                      <BadgeDollarSign className="h-5 w-5" />
                    ) : mode === "compare" ? (
                      <GitCompareArrows className="h-5 w-5" />
                    ) : mode === "buy_now_wait" ? (
                      <Clock className="h-5 w-5" />
                    ) : (
                      <Activity className="h-5 w-5" />
                    )}
                  </span>

                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
                      Scenario inputs
                    </p>
                    <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em]">
                      {mode === "single"
                        ? "What are you planning to buy?"
                        : mode === "compare"
                          ? "Which options should Discero compare?"
                          : mode === "buy_now_wait"
                            ? "Should you buy now or wait?"
                            : "What financial shock do you want to test?"}
                    </h2>
                  </div>
                </div>

                <div className="mt-7 space-y-5">
                  {mode === "single" ? (
                    <>
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

                      <DateField
                        label="Purchase date"
                        value={purchaseDate}
                        min={toDateInputValue(today)}
                        onChange={setPurchaseDate}
                      />
                    </>
                  ) : mode === "compare" ? (
                    <>
                      <ComparisonOptionFields
                        title="Option A"
                        name={optionAName}
                        amount={optionAAmount}
                        date={optionADate}
                        minDate={toDateInputValue(today)}
                        onNameChange={setOptionAName}
                        onAmountChange={setOptionAAmount}
                        onDateChange={setOptionADate}
                      />

                      <ComparisonOptionFields
                        title="Option B"
                        name={optionBName}
                        amount={optionBAmount}
                        date={optionBDate}
                        minDate={toDateInputValue(today)}
                        onNameChange={setOptionBName}
                        onAmountChange={setOptionBAmount}
                        onDateChange={setOptionBDate}
                      />

                      <div className="rounded-2xl border border-[#181713]/8 bg-[#FFFCF7] px-4 py-3">
                        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
                          Shared assumptions
                        </p>
                        <p className="mt-1 text-xs leading-5 text-[#706961]">
                          Safety reserve, essential spending, and horizon apply
                          to both options.
                        </p>
                      </div>
                    </>
                  ) : mode === "buy_now_wait" ? (
                    <>
                      <Field
                        label="Purchase name"
                        value={waitPurchaseName}
                        onChange={setWaitPurchaseName}
                        placeholder="New laptop"
                        required
                      />

                      <Field
                        label="Purchase amount"
                        value={waitPurchaseAmount}
                        onChange={setWaitPurchaseAmount}
                        type="number"
                        min="0.01"
                        step="0.01"
                        prefix="$"
                        required
                      />

                      <DateField
                        label="Buy now date"
                        value={buyNowDate}
                        min={toDateInputValue(today)}
                        onChange={setBuyNowDate}
                      />

                      <DateField
                        label="Wait until date"
                        value={waitUntilDate}
                        min={toDateInputValue(addDays(today, 1))}
                        onChange={setWaitUntilDate}
                      />
                    </>
                  ) : (
                    <>
                      <label className="block">
                        <span className="text-sm font-semibold text-[#2F2930]">
                          Scenario type
                        </span>
                        <select
                          value={scenarioType}
                          onChange={(event) => {
                            const nextType = event.target
                              .value as FinancialStressScenarioType;

                            setScenarioType(nextType);

                            if (!DURATION_REQUIRED_SCENARIOS.has(nextType)) {
                              setDurationDays("");
                            }
                          }}
                          className="mt-2 h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
                        >
                          {SCENARIO_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>

                      <Field
                        label="Scenario name"
                        value={scenarioName}
                        onChange={setScenarioName}
                        placeholder="Emergency car repair"
                        required
                      />

                      {showStressAmount && (
                        <Field
                          label={
                            scenarioType === "one_time_expense" ||
                            scenarioType === "combined"
                              ? "One-time expense amount"
                              : "Stress amount"
                          }
                          value={stressAmount}
                          onChange={setStressAmount}
                          type="number"
                          min="0.01"
                          step="0.01"
                          prefix="$"
                          required={stressAmountRequired}
                        />
                      )}

                      {showIncomePercent && (
                        <Field
                          label="Income reduction (%)"
                          value={incomeReductionPercent}
                          onChange={setIncomeReductionPercent}
                          type="number"
                          min="0.1"
                          step="0.1"
                          required={scenarioType === "income_reduction"}
                        />
                      )}

                      {showRecurringPercent && (
                        <Field
                          label="Recurring expense increase (%)"
                          value={recurringIncreasePercent}
                          onChange={setRecurringIncreasePercent}
                          type="number"
                          min="0.1"
                          step="0.1"
                          required={
                            scenarioType === "recurring_expense_increase"
                          }
                        />
                      )}

                      {scenarioType === "recurring_bill_increase" && (
                        <p className="-mt-3 text-xs leading-5 text-[#706961]">
                          Enter the total added cost for this scenario.
                          Discero uses this amount as-is and does not
                          multiply it by month.
                        </p>
                      )}

                      {(scenarioType === "income_reduction" ||
                        scenarioType === "recurring_expense_increase" ||
                        scenarioType === "combined") && (
                        <p className="-mt-3 text-xs leading-5 text-[#706961]">
                          Percentages are applied to your recent income or
                          current recurring obligations from Discero data.
                        </p>
                      )}

                      <DateField
                        label="Event date"
                        value={eventDate}
                        min={toDateInputValue(today)}
                        onChange={setEventDate}
                      />

                      {durationRequired && (
                        <Field
                          label="Duration (days)"
                          value={durationDays}
                          onChange={setDurationDays}
                          type="number"
                          min="1"
                          step="1"
                          required
                        />
                      )}
                    </>
                  )}

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
                    <span className="text-sm font-semibold text-[#2F2930]">
                      Decision horizon
                    </span>
                    <select
                      value={horizonDays}
                      onChange={(event) =>
                        setHorizonDays(event.target.value)
                      }
                      className="mt-2 h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
                    >
                      <option value="14">Next 14 days</option>
                      <option value="30">Next 30 days</option>
                      <option value="60">Next 60 days</option>
                      <option value="90">Next 90 days</option>
                    </select>
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
                  disabled={initializing || simulating || userId === null}
                  className="discero-button-primary mt-7 inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold transition disabled:cursor-not-allowed"
                >
                  {simulating
                    ? mode === "single"
                      ? "Running simulation..."
                      : mode === "compare"
                        ? "Comparing options..."
                        : mode === "buy_now_wait"
                          ? "Comparing timing..."
                          : "Running stress test..."
                    : mode === "single"
                      ? "Simulate purchase"
                      : mode === "compare"
                        ? "Run comparison"
                        : mode === "buy_now_wait"
                          ? "Compare timing"
                          : "Run stress test"}
                  {!simulating && <ArrowRight className="h-4 w-4" />}
                </button>
              </form>
            </Reveal>

            <Reveal delay={0.06}>
              {mode === "single" ? (
                result ? (
                  <div className="space-y-3">
                    <SinglePurchaseResult
                      result={result}
                      statusContent={statusContent}
                      StatusIcon={StatusIcon}
                    />
                    {userId !== null && lastPurchaseInput && (
                      <SaveDecisionButton
                        userId={userId}
                        decisionType="major_purchase"
                        defaultTitle={result.purchase_name}
                        input={lastPurchaseInput}
                        onSaved={scrollToTopControls}
                      />
                    )}
                    {userId !== null && (
                      <>
                        <AdaptiveIntelligenceSection userId={userId} />
                        <DataFreshnessNote userId={userId} />
                      </>
                    )}
                  </div>
                ) : (
                  <EmptyState
                    title="See the impact before you spend"
                    description="Enter a purchase scenario to compare affordability, remaining safe-to-spend, shortfall risk, and safer alternatives."
                  />
                )
              ) : mode === "compare" ? (
                compareResult ? (
                  <div className="space-y-3">
                    <ComparisonResults result={compareResult} />
                    {userId !== null && lastComparisonInput && (
                      <SaveDecisionButton
                        userId={userId}
                        decisionType="scenario_comparison"
                        defaultTitle={`${compareResult.option_a.simulation.purchase_name} vs ${compareResult.option_b.simulation.purchase_name}`}
                        input={lastComparisonInput}
                        onSaved={scrollToTopControls}
                      />
                    )}
                    {userId !== null && (
                      <>
                        <AdaptiveIntelligenceSection userId={userId} />
                        <DataFreshnessNote userId={userId} />
                      </>
                    )}
                  </div>
                ) : (
                  <EmptyState
                    title="Compare two purchase paths"
                    description="Enter two options with shared assumptions to see which leaves you in a safer financial position."
                  />
                )
              ) : mode === "buy_now_wait" ? (
                buyNowVsWaitResult ? (
                  <div className="space-y-3">
                    <BuyNowVsWaitResults
                      result={buyNowVsWaitResult}
                      timingContent={timingContent}
                      TimingIcon={TimingIcon}
                    />
                    {userId !== null && lastBuyNowVsWaitInput && (
                      <SaveDecisionButton
                        userId={userId}
                        decisionType="buy_now_vs_wait"
                        defaultTitle={`${buyNowVsWaitResult.purchase_name}: now or wait?`}
                        input={lastBuyNowVsWaitInput}
                        onSaved={scrollToTopControls}
                      />
                    )}
                    {userId !== null && (
                      <>
                        <AdaptiveIntelligenceSection userId={userId} />
                        <DataFreshnessNote userId={userId} />
                      </>
                    )}
                  </div>
                ) : (
                  <EmptyState
                    title="Should you buy now or wait?"
                    description="Enter a purchase and a wait date to see affordability, buffer, and goal impact for both timings, plus a clear recommendation."
                  />
                )
              ) : stressResult ? (
                <div className="space-y-3">
                  <StressTestResult
                    result={stressResult}
                    riskContent={riskContent}
                    RiskIcon={RiskIcon}
                  />
                  {userId !== null && lastStressInput && (
                    <SaveDecisionButton
                      userId={userId}
                      decisionType="stress_test"
                      defaultTitle={stressResult.scenario_name}
                      input={lastStressInput}
                      onSaved={scrollToTopControls}
                    />
                  )}
                  {userId !== null && (
                    <>
                      <AdaptiveIntelligenceSection userId={userId} />
                      <DataFreshnessNote userId={userId} />
                    </>
                  )}
                </div>
              ) : (
                <EmptyState
                  title="See how a shock affects your safety net"
                  description="Enter a stress scenario to see your safe-to-spend before and after, risk level, recovery estimate, and recommendations."
                />
              )}
            </Reveal>
          </section>
          )}
        </PageReveal>
      </div>
    </main>
  );
}

function ModeButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-xl px-4 py-2.5 text-sm font-semibold transition ${
        active
          ? "discero-segment-selected"
          : "text-[#706961] hover:text-[#181713]"
      }`}
    >
      {label}
    </button>
  );
}

function SaveDecisionButton({
  userId,
  decisionType,
  defaultTitle,
  input,
  onSaved,
}: {
  userId: number;
  decisionType: DecisionType;
  defaultTitle: string;
  input: Record<string, unknown>;
  onSaved?: () => void;
}) {
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">(
    "idle"
  );

  async function handleSave() {
    setStatus("saving");
    try {
      await api.saveDecision(userId, {
        decision_type: decisionType,
        title: defaultTitle.trim() || "Saved decision",
        input,
      });
      setStatus("saved");
    } catch {
      setStatus("error");
      return;
    }

    // Scrolling is a UX nicety; it must never affect save status even
    // if it throws (e.g. an environment without scrollIntoView).
    onSaved?.();
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
        {status === "saving" ? "Saving..." : "Save this decision"}
      </button>

      {status === "error" && (
        <span className="text-xs font-medium text-[#a64b3d]">
          Couldn&apos;t save just now.
        </span>
      )}
    </div>
  );
}

function ComparisonOptionFields({
  title,
  name,
  amount,
  date,
  minDate,
  onNameChange,
  onAmountChange,
  onDateChange,
}: {
  title: string;
  name: string;
  amount: string;
  date: string;
  minDate: string;
  onNameChange: (value: string) => void;
  onAmountChange: (value: string) => void;
  onDateChange: (value: string) => void;
}) {
  return (
    <div className="border-l-2 border-[#6E4B63]/35 bg-[#F8F4EE] p-4 sm:p-5">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
        {title}
      </p>

      <div className="mt-4 space-y-4">
        <Field
          label="Name"
          value={name}
          onChange={onNameChange}
          placeholder={title}
          required
        />

        <Field
          label="Amount"
          value={amount}
          onChange={onAmountChange}
          type="number"
          min="0.01"
          step="0.01"
          prefix="$"
          required
        />

        <DateField
          label="Purchase date"
          value={date}
          min={minDate}
          onChange={onDateChange}
        />
      </div>
    </div>
  );
}

function DateField({
  label,
  value,
  min,
  onChange,
}: {
  label: string;
  value: string;
  min: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="text-sm font-semibold text-[#2F2930]">
        {label}
      </span>
      <div className="relative mt-2">
        <CalendarDays className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[#7f8c86]" />
        <input
          type="date"
          value={value}
          min={min}
          onChange={(event) => onChange(event.target.value)}
          required
          className="h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] pl-11 pr-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
        />
      </div>
    </label>
  );
}

function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <article className="flex min-h-[420px] flex-col items-center justify-center border-y border-[#181713]/10 bg-[#FFFCF7] p-8 text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-full bg-[#EDE5DE] text-[#6E4B63]">
        <Sparkles className="h-7 w-7" />
      </span>

      <h2 className="mt-6 text-2xl font-semibold tracking-[-0.035em]">
        {title}
      </h2>

      <p className="mt-3 max-w-md text-sm leading-6 text-[#6d7a74]">
        {description}
      </p>
    </article>
  );
}

function SinglePurchaseResult({
  result,
  statusContent,
  StatusIcon,
}: {
  result: MajorPurchaseSimulationResult;
  statusContent: (typeof STATUS_CONTENT)[keyof typeof STATUS_CONTENT];
  StatusIcon: typeof CheckCircle2;
}) {
  return (
    <article className="relative overflow-hidden rounded-[30px] bg-[#181713] p-7 text-white shadow-[0_24px_70px_rgba(60,43,35,0.2)] sm:p-9">
      <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-[#C89A78]/15 blur-3xl" />

      <div className="relative">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#D2B199]">
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
            {formatCents(result.safe_to_spend_after_purchase_cents)}
          </p>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-white/55">
            {statusContent.description}
          </p>
        </div>

        <div className="mt-9 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-2 xl:grid-cols-4">
          <ResultMetric
            label="Purchase"
            value={formatCents(-result.purchase_amount_cents)}
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
            value={`${Math.round(result.confidence_score)}%`}
          />
        </div>

        <div className="mt-7 rounded-2xl border border-white/10 bg-white/[0.045] p-5">
          <div className="flex items-start gap-3">
            <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-[#D2B199]" />
            <div>
              <p className="text-sm font-semibold">Discero explanation</p>
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
            value={formatCents(result.recommended_max_purchase_cents)}
          />
          <DecisionStat
            icon={Gauge}
            label="Shortfall after purchase"
            value={formatCents(-result.shortfall_after_purchase_cents)}
            warning={result.shortfall_after_purchase_cents > 0}
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
                  <p className="text-sm font-semibold text-[#D2B199]">
                    {alternative.label}
                  </p>
                  <p className="mt-2 text-2xl font-semibold tracking-[-0.035em]">
                    {formatCents(alternative.purchase_amount_cents)}
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

        <GoalImpactList
          goalImpacts={result.goal_impacts}
          conflictIntelligence={result.goal_conflict_intelligence}
        />
      </div>
    </article>
  );
}

function ComparisonResults({
  result,
}: {
  result: ScenarioComparisonResult;
}) {
  const isTie = result.recommended_option === "tie";

  return (
    <div className="space-y-6">
      <article
        className={`rounded-[30px] border p-6 shadow-[0_18px_50px_rgba(60,43,35,0.08)] sm:p-8 ${
          isTie
            ? "border-[#181713]/10 bg-white"
            : "border-[#6E4B63]/20 bg-[#181713] text-white"
        }`}
      >
        <div className="flex items-start gap-4">
          <span
            className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl ${
              isTie
                ? "bg-[#E3EBE1] text-[#48634B]"
                : "bg-[#D2B199]/15 text-[#D2B199]"
            }`}
          >
            {isTie ? (
              <Scale className="h-5 w-5" />
            ) : (
              <CheckCircle2 className="h-5 w-5" />
            )}
          </span>

          <div className="min-w-0">
            <p
              className={`text-xs font-semibold uppercase tracking-[0.16em] ${
                isTie ? "text-[#6E4B63]" : "text-[#D2B199]"
              }`}
            >
              {isTie ? "Comparison result" : "Recommended option"}
            </p>
            <h2
              className={`mt-2 break-words text-2xl font-semibold tracking-[-0.04em] sm:text-3xl ${
                isTie ? "text-[#181713]" : "text-white"
              }`}
            >
              {isTie
                ? "Both options are equally viable"
                : result.recommended_option === "option_a"
                  ? `Option A: ${result.option_a.simulation.purchase_name}`
                  : `Option B: ${result.option_b.simulation.purchase_name}`}
            </h2>
            <p
              className={`mt-3 max-w-3xl text-sm leading-6 ${
                isTie ? "text-[#706961]" : "text-white/60"
              }`}
            >
              {result.recommendation}
            </p>
          </div>
        </div>

        {result.reasons.length > 0 && (
          <div
            className={`mt-6 border-t pt-6 ${
              isTie ? "border-[#181713]/10" : "border-white/10"
            }`}
          >
            <p
              className={`text-xs font-semibold uppercase tracking-[0.16em] ${
                isTie ? "text-[#6E4B63]" : "text-[#D2B199]"
              }`}
            >
              {isTie ? "Why they tie" : "Why this wins"}
            </p>

            <ul
              className={`mt-3 space-y-2 text-sm leading-6 ${
                isTie ? "text-[#706961]" : "text-white/70"
              }`}
            >
              {result.reasons.map((reason) => (
                <li key={reason} className="flex gap-2">
                  <span aria-hidden="true">•</span>
                  <span>{reason}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </article>

      <div className="grid gap-6 lg:grid-cols-2">
        <ComparisonOptionCard
          title="Option A"
          option={result.option_a}
          recommended={result.recommended_option === "option_a"}
          isTie={isTie}
        />
        <ComparisonOptionCard
          title="Option B"
          option={result.option_b}
          recommended={result.recommended_option === "option_b"}
          isTie={isTie}
        />
      </div>

      <ComparisonScorecard scorecard={result.scorecard} />
    </div>
  );
}

function ComparisonOptionCard({
  title,
  option,
  recommended,
  isTie,
}: {
  title: string;
  option: ScenarioComparisonResult["option_a"];
  recommended: boolean;
  isTie: boolean;
}) {
  const simulation = option.simulation;
  const status =
    STATUS_CONTENT[simulation.affordability_status];
  const StatusIcon = status.icon;

  return (
    <article
      className={`relative overflow-hidden rounded-[30px] p-6 shadow-[0_18px_50px_rgba(60,43,35,0.08)] sm:p-7 ${
        recommended && !isTie
          ? "border-2 border-[#D2B199] bg-[#181713] text-white"
          : "border border-[#181713]/10 bg-white text-[#181713]"
      }`}
    >
      {recommended && !isTie && (
        <div className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-[#C89A78]/15 blur-3xl" />
      )}

      <div className="relative">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p
              className={`text-xs font-semibold uppercase tracking-[0.14em] ${
                recommended && !isTie
                  ? "text-[#D2B199]"
                  : "text-[#6E4B63]"
              }`}
            >
              {title}
            </p>
            <h3 className="mt-2 truncate text-2xl font-semibold tracking-[-0.04em]">
              {simulation.purchase_name}
            </h3>
          </div>

          <span
            className={`inline-flex shrink-0 items-center gap-1 rounded-full px-3 py-1 text-xs font-semibold ${
              recommended && !isTie
                ? "bg-[#D2B199]/15 text-[#D2B199]"
                : isTie
                  ? "bg-[#f1eee7] text-[#706961]"
                  : "bg-[#181713]/5 text-[#706961]"
            }`}
          >
            {recommended && !isTie && (
              <CheckCircle2 className="h-3.5 w-3.5" />
            )}
            {isTie
              ? "Equally viable"
              : recommended
                ? "Recommended"
                : "Alternative"}
          </span>
        </div>

        <span
          className={`mt-4 inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${status.className}`}
        >
          <StatusIcon className="h-4 w-4" />
          {status.label}
        </span>

        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          <ComparisonMetric
            label="Purchase amount"
            value={formatCents(simulation.purchase_amount_cents)}
            highlighted={recommended && !isTie}
          />
          <ComparisonMetric
            label="Safe to spend after"
            value={formatCents(
              simulation.safe_to_spend_after_purchase_cents
            )}
            highlighted={recommended && !isTie}
          />
          <ComparisonMetric
            label="Shortfall"
            value={formatCents(
              -simulation.shortfall_after_purchase_cents
            )}
            highlighted={recommended && !isTie}
            warning={simulation.shortfall_after_purchase_cents > 0}
          />
          <ComparisonMetric
            label="Impact"
            value={`${simulation.purchase_impact_percent}%`}
            highlighted={recommended && !isTie}
          />
          <ComparisonMetric
            label="Goal savings pace"
            value={formatGoalImpact(simulation.goal_impact_months)}
            highlighted={recommended && !isTie}
          />
          <ComparisonMetric
            label="Confidence"
            value={`${Math.round(simulation.confidence_score)}%`}
            highlighted={recommended && !isTie}
          />
        </div>
      </div>
    </article>
  );
}

function formatGoalImpact(months: number): string {
  if (months <= 0) {
    return "No active goals";
  }

  // This is a size comparison (purchase amount vs. required goal
  // savings pace), not a claim that the purchase actually delays or
  // consumes goal funding -- see the per-goal impact list for that.

  return `${months} mo of goal savings`;
}

function ComparisonMetric({
  label,
  value,
  highlighted = false,
  warning = false,
}: {
  label: string;
  value: string;
  highlighted?: boolean;
  warning?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl border p-4 ${
        highlighted
          ? "border-white/10 bg-white/[0.045]"
          : "border-[#181713]/8 bg-[#FFFCF7]"
      }`}
    >
      <p
        className={`text-[10px] font-semibold uppercase tracking-[0.14em] ${
          highlighted ? "text-white/35" : "text-[#7f8c86]"
        }`}
      >
        {label}
      </p>
      <p
        className={`mt-2 text-lg font-semibold ${
          warning
            ? highlighted
              ? "text-[#f4a594]"
              : "text-[#b65743]"
            : highlighted
              ? "text-white"
              : "text-[#181713]"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function ComparisonScorecard({
  scorecard,
}: {
  scorecard: ScenarioComparisonScorecard;
}) {
  const optionAPercent = Math.round(
    (scorecard.option_a_score / scorecard.max_score) * 100
  );
  const optionBPercent = Math.round(
    (scorecard.option_b_score / scorecard.max_score) * 100
  );

  return (
    <article className="rounded-[30px] border border-[#181713]/10 bg-white p-6 shadow-[0_18px_50px_rgba(60,43,35,0.08)] sm:p-8">
      <div className="flex items-center gap-2">
        <Scale className="h-4 w-4 text-[#6E4B63]" aria-hidden="true" />
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
          Comparison scorecard
        </p>
      </div>

      <p className="mt-2 max-w-2xl text-sm leading-6 text-[#706961]">
        Every factor below is scored directly from your financial
        data — a higher score always means a safer outcome for that
        option.
      </p>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <ScorecardTotal
          label="Option A score"
          score={scorecard.option_a_score}
          maxScore={scorecard.max_score}
          percent={optionAPercent}
        />
        <ScorecardTotal
          label="Option B score"
          score={scorecard.option_b_score}
          maxScore={scorecard.max_score}
          percent={optionBPercent}
        />
      </div>

      <div className="mt-5 divide-y divide-[#181713]/8 overflow-hidden rounded-2xl border border-[#181713]/8">
        {scorecard.criteria.map((criterion) => (
          <div
            key={criterion.key}
            className="flex items-center justify-between gap-3 px-4 py-3"
          >
            <span className="text-sm font-medium text-[#181713]">
              {criterion.label}
            </span>
            <span
              className={`text-xs font-semibold ${
                criterion.winner === "tie"
                  ? "text-[#706961]"
                  : "text-[#6E4B63]"
              }`}
            >
              {criterion.winner === "tie"
                ? "Tie"
                : criterion.winner === "option_a"
                  ? "Option A"
                  : "Option B"}
            </span>
          </div>
        ))}
      </div>
    </article>
  );
}

function ScorecardTotal({
  label,
  score,
  maxScore,
  percent,
}: {
  label: string;
  score: number;
  maxScore: number;
  percent: number;
}) {
  return (
    <div className="rounded-2xl border border-[#181713]/8 bg-[#FFFCF7] p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#7f8c86]">
        {label}
      </p>
      <p className="mt-2 text-lg font-semibold text-[#181713]">
        {score} / {maxScore}
      </p>
      <div
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label}: ${percent}% of maximum`}
        className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#181713]/8"
      >
        <div
          className="h-full rounded-full bg-[#6E4B63]"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

function formatDateLong(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

function BuyNowVsWaitResults({
  result,
  timingContent,
  TimingIcon,
}: {
  result: BuyNowVsWaitResult;
  timingContent: (typeof TIMING_CONTENT)[keyof typeof TIMING_CONTENT];
  TimingIcon: typeof CheckCircle2;
}) {
  return (
    <div className="space-y-6">
      <article className="relative overflow-hidden rounded-[30px] border border-[#6E4B63]/20 bg-[#181713] p-6 text-white shadow-[0_18px_50px_rgba(60,43,35,0.08)] sm:p-8">
        <div className="flex items-start gap-4">
          <span
            className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl ${timingContent.className}`}
          >
            <TimingIcon className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#D2B199]">
              Recommendation
            </p>
            <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] sm:text-3xl">
              {timingContent.label}
            </h2>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-white/60">
              {result.reason}
            </p>
          </div>
        </div>

        <div className="mt-6 grid gap-5 border-t border-white/10 pt-6 sm:grid-cols-2">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-white/35">
              Why
            </p>
            <p className="mt-2 text-sm leading-6 text-white/70">
              {formatCents(result.buffer_difference_cents)} difference in
              remaining buffer between the two timings.
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-white/35">
              What changes
            </p>
            <p className="mt-2 text-sm leading-6 text-white/70">
              {result.goal_impact_note ??
                "Your goal timeline is unaffected either way."}
            </p>
          </div>
        </div>

        <div className="mt-6 flex items-start gap-3 rounded-2xl border border-white/10 bg-white/[0.045] p-4">
          <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-[#D2B199]" />
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-white/40">
              How the wait estimate works
            </p>
            <p className="mt-1 text-xs leading-5 text-white/60">
              {result.assumption}
            </p>
          </div>
        </div>

        {result.caveat && (
          <div className="mt-4 flex items-start gap-3 rounded-2xl border border-white/10 bg-white/[0.045] p-4">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-[#f4a594]" />
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.12em] text-white/40">
                What this means
              </p>
              <p className="mt-1 text-xs leading-5 text-white/60">
                {result.caveat}
              </p>
            </div>
          </div>
        )}
      </article>

      <div className="grid gap-6 lg:grid-cols-2">
        <BuyNowVsWaitOptionCard
          title="Buy now"
          dateLabel={formatDateLong(result.now.evaluated_date)}
          option={result.now}
          highlighted={result.recommended_timing === "buy_now"}
        />
        <BuyNowVsWaitOptionCard
          title="Wait"
          dateLabel={formatDateLong(result.wait.evaluated_date)}
          option={result.wait}
          highlighted={result.recommended_timing === "wait"}
        />
      </div>
    </div>
  );
}

function BuyNowVsWaitOptionCard({
  title,
  dateLabel,
  option,
  highlighted,
}: {
  title: string;
  dateLabel: string;
  option: BuyNowVsWaitResult["now"];
  highlighted: boolean;
}) {
  const simulation = option.simulation;
  const status = STATUS_CONTENT[simulation.affordability_status];
  const StatusIcon = status.icon;

  return (
    <article
      className={`relative overflow-hidden rounded-[30px] p-6 shadow-[0_18px_50px_rgba(60,43,35,0.08)] sm:p-7 ${
        highlighted
          ? "border-2 border-[#D2B199] bg-[#181713] text-white"
          : "border border-[#181713]/10 bg-white text-[#181713]"
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p
            className={`text-xs font-semibold uppercase tracking-[0.14em] ${
              highlighted ? "text-[#D2B199]" : "text-[#6E4B63]"
            }`}
          >
            {title}
          </p>
          <h3 className="mt-2 text-2xl font-semibold tracking-[-0.04em]">
            {dateLabel}
          </h3>
        </div>

        {highlighted && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[#D2B199]/15 px-3 py-1 text-xs font-semibold text-[#D2B199]">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Recommended
          </span>
        )}
      </div>

      <span
        className={`mt-4 inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${status.className}`}
      >
        <StatusIcon className="h-4 w-4" />
        {status.label}
      </span>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <ComparisonMetric
          label="Safe to spend after"
          value={formatCents(
            simulation.safe_to_spend_after_purchase_cents
          )}
          highlighted={highlighted}
        />
        <ComparisonMetric
          label="Shortfall"
          value={formatCents(-simulation.shortfall_after_purchase_cents)}
          highlighted={highlighted}
          warning={simulation.shortfall_after_purchase_cents > 0}
        />
        <ComparisonMetric
          label="Impact"
          value={`${simulation.purchase_impact_percent}%`}
          highlighted={highlighted}
        />
        <ComparisonMetric
          label="Confidence"
          value={`${Math.round(simulation.confidence_score)}%`}
          highlighted={highlighted}
        />
      </div>
    </article>
  );
}

function StressTestResult({
  result,
  riskContent,
  RiskIcon,
}: {
  result: FinancialStressTestResult;
  riskContent: (typeof RISK_CONTENT)[keyof typeof RISK_CONTENT];
  RiskIcon: typeof ShieldCheck;
}) {
  return (
    <article className="relative overflow-hidden rounded-[30px] bg-[#181713] p-7 text-white shadow-[0_24px_70px_rgba(60,43,35,0.2)] sm:p-9">
      <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-[#C89A78]/15 blur-3xl" />

      <div className="relative">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#D2B199]">
              Stress test result
            </p>
            <h2 className="mt-3 text-3xl font-semibold tracking-[-0.045em]">
              {result.scenario_name}
            </h2>
            <p className="mt-2 text-sm text-white/50">
              {new Date(
                `${result.event_date}T00:00:00`
              ).toLocaleDateString("en-US", {
                month: "long",
                day: "numeric",
                year: "numeric",
              })}
            </p>
          </div>

          <div className="flex flex-col items-start gap-2 sm:items-end">
            <span
              className={`inline-flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${riskContent.className}`}
            >
              <RiskIcon className="h-4 w-4" />
              {riskContent.label}
            </span>
            <span
              className={`inline-flex w-fit items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${SEVERITY_CONTENT[result.severity].className}`}
            >
              {SEVERITY_CONTENT[result.severity].label} severity
            </span>
          </div>
        </div>

        <div className="mt-8">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-white/35">
            Safe to spend after stress
          </p>
          <p className="mt-3 text-5xl font-semibold tracking-[-0.06em] sm:text-6xl">
            {formatCents(result.safe_to_spend_after_stress_cents)}
          </p>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-white/55">
            {riskContent.description}
          </p>
        </div>

        <div className="mt-9 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-2 xl:grid-cols-4">
          <ResultMetric
            label="Before stress"
            value={formatCents(
              result.safe_to_spend_before_stress_cents
            )}
          />
          <ResultMetric
            label="Total impact"
            value={formatCents(-result.total_financial_impact_cents)}
          />
          <ResultMetric
            label="Shortfall"
            value={formatCents(-result.shortfall_cents)}
          />
          <ResultMetric
            label="Confidence"
            value={`${Math.round(result.confidence_score)}%`}
          />
        </div>

        <div className="mt-7 rounded-2xl border border-white/10 bg-white/[0.045] p-6">
          <div className="flex items-center justify-between gap-4">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-white/40">
              Resilience score
            </p>
            <p className="text-sm font-semibold">
              {Math.round(result.resilience_score)} / 100
            </p>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {result.resilience_factors.map((factor) => (
              <div key={factor.key} className="flex items-center justify-between gap-3">
                <span className="text-xs text-white/60">
                  {factor.label}
                </span>
                <span className="text-xs font-semibold text-white/85">
                  {Math.round(factor.score)}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-7 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-3">
          <ResultMetric
            label="Baseline projected balance"
            value={formatCents(result.baseline_projected_balance_cents)}
          />
          <ResultMetric
            label="Stressed projected balance"
            value={formatCents(result.stressed_projected_balance_cents)}
            warning={!result.cash_flow_positive}
          />
          <ResultMetric
            label="Change"
            value={`${result.balance_change_percent}%`}
            warning={result.balance_change_percent < 0}
          />
        </div>

        <p className="mt-4 text-xs font-semibold uppercase tracking-[0.12em] text-white/40">
          {result.cash_flow_positive
            ? "Remains cash-flow positive"
            : "Would go cash-flow negative"}
        </p>

        {result.affected_goals.length > 0 && (
          <div className="mt-7">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-white/40">
              Affected goals
            </p>
            <ul className="mt-4 space-y-3">
              {result.affected_goals.map((goal) => (
                <li
                  key={goal.goal_id}
                  className="rounded-2xl border border-white/10 bg-white/[0.045] p-4"
                >
                  <p className="text-sm font-semibold">{goal.name}</p>
                  <p className="mt-1 text-xs text-white/60">
                    {goal.status_before} → {goal.status_after}
                    {goal.estimated_delay_months !== null &&
                      goal.estimated_delay_months > 0 &&
                      ` · delayed by ~${goal.estimated_delay_months} month(s)`}
                    {goal.monthly_shortfall_after_cents > 0 &&
                      ` · ${formatCents(
                        -goal.monthly_shortfall_after_cents
                      )}/mo shortfall`}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )}

        <GoalImpactList
          goalImpacts={result.goal_impacts}
          conflictIntelligence={result.goal_conflict_intelligence}
        />

        <div className="mt-7 rounded-2xl border border-white/10 bg-white/[0.045] p-5">
          <div className="flex items-start gap-3">
            <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-[#D2B199]" />
            <div>
              <p className="text-sm font-semibold">Discero explanation</p>
              <p className="mt-2 text-sm leading-6 text-white/58">
                {result.explanation}
              </p>
              {result.explanations.length > 0 && (
                <ul className="mt-3 space-y-1.5">
                  {result.explanations.map((item) => (
                    <li
                      key={item}
                      className="text-sm leading-6 text-white/58"
                    >
                      · {item}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>

        <div className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <DecisionStat
            icon={CalendarClock}
            label="Estimated recovery"
            value={
              result.estimated_recovery_days === null
                ? "Not determinable"
                : `${result.estimated_recovery_days} days`
            }
            caption={
              DURATION_REQUIRED_SCENARIOS.has(result.scenario_type)
                ? "Reflects the scenario duration entered, not a guaranteed recovery timeline."
                : undefined
            }
          />
          <DecisionStat
            icon={Gauge}
            label="Shortfall after stress"
            value={formatCents(-result.shortfall_cents)}
            warning={result.shortfall_cents > 0}
          />
          <DecisionStat
            icon={Clock}
            label="Stressed runway"
            value={
              result.runway_days === null
                ? "Not exhausted"
                : `${result.runway_days} day(s)`
            }
            warning={result.runway_days !== null}
          />
          <DecisionStat
            icon={CalendarDays}
            label="First shortfall"
            value={
              result.first_shortfall_date === null
                ? "None projected"
                : new Date(
                    `${result.first_shortfall_date}T00:00:00`
                  ).toLocaleDateString("en-US", {
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                  })
            }
            warning={result.first_shortfall_date !== null}
          />
        </div>

        <div className="mt-7 grid gap-4 sm:grid-cols-2">
          <div className="rounded-2xl border border-white/10 bg-white/[0.045] p-5">
            <p className="text-xs text-white/40">Biggest pressure</p>
            <p className="mt-1 text-lg font-semibold text-white">
              {KEY_DRIVER_LABELS[result.key_driver]}
            </p>
          </div>

          {result.forecast_confidence && (
            <div className="rounded-2xl border border-white/10 bg-white/[0.045] p-5">
              <p className="text-xs text-white/40">Forecast confidence</p>
              <div className="mt-1 flex items-center gap-2">
                <span
                  className={`inline-flex w-fit items-center rounded-full px-2.5 py-1 text-xs font-semibold ${
                    CONFIDENCE_LEVEL_CONTENT[
                      result.forecast_confidence.level
                    ].className
                  }`}
                >
                  {
                    CONFIDENCE_LEVEL_CONTENT[
                      result.forecast_confidence.level
                    ].label
                  }
                </span>
                <span className="text-lg font-semibold text-white">
                  {Math.round(result.forecast_confidence.score)}%
                </span>
              </div>
            </div>
          )}
        </div>

        {result.recovery_recommendation && (
          <div className="mt-7 rounded-2xl border border-white/10 bg-white/[0.045] p-5">
            <div className="flex items-start gap-3">
              <Compass className="mt-0.5 h-5 w-5 shrink-0 text-[#D2B199]" />
              <div>
                <p className="text-sm font-semibold">Suggested recovery</p>
                <p className="mt-2 text-sm leading-6 text-white/58">
                  {result.recovery_recommendation.message}
                </p>
              </div>
            </div>
          </div>
        )}

        {result.recommendations.length > 0 && (
          <div className="mt-8 border-t border-white/10 pt-7">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-white/40">
              Recommendations
            </p>

            <ul className="mt-4 space-y-3">
              {result.recommendations.map((recommendation) => (
                <li
                  key={recommendation}
                  className="flex items-start gap-3 rounded-2xl border border-white/10 bg-white/[0.045] p-4"
                >
                  <ListChecks className="mt-0.5 h-4 w-4 shrink-0 text-[#D2B199]" />
                  <p className="text-sm leading-6 text-white/70">
                    {recommendation}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )}

        <p className="mt-7 text-xs leading-5 text-white/40">
          {result.data_disclaimer}
        </p>
      </div>
    </article>
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
      <span className="text-sm font-semibold text-[#2F2930]">
        {label}
      </span>

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
          step={step}
          required={required}
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

function ResultMetric({
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

function DecisionStat({
  icon: Icon,
  label,
  value,
  warning = false,
  caption,
}: {
  icon: typeof ShieldCheck;
  label: string;
  value: string;
  warning?: boolean;
  caption?: string;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.045] p-5">
      <div className="flex items-center gap-3">
        <span
          className={`flex h-10 w-10 items-center justify-center rounded-xl ${
            warning
              ? "bg-[#f0b8a8]/15 text-[#f4a594]"
              : "bg-[#D2B199]/10 text-[#D2B199]"
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
      {caption && (
        <p className="mt-3 text-xs leading-5 text-white/40">{caption}</p>
      )}
    </div>
  );
}
