const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const TOKEN_KEY = "accessToken";
const REFRESH_TOKEN_KEY = "refreshToken";
const USER_ID_KEY = "userId";
const SESSION_NOTICE_KEY = "sessionNotice";
const INVALIDATED_SESSION_DETAIL =
  "session expired; please sign in again";
const REQUEST_TIMEOUT_MS = 15_000;
// The Copilot chat turn can run up to two sequential AI provider calls
// (DECIDE, then NARRATE), each with its own backend-side timeout budget
// (copilot_model_timeout_seconds) that alone exceeds REQUEST_TIMEOUT_MS.
// It can also be the first request to a scale-to-zero backend instance
// after it's been idle, which cold-starts (see
// docs/TESTING_AND_DEPLOYMENT.md) -- REQUEST_TIMEOUT_MS was aborting
// that combination client-side before the backend could ever respond,
// which is what a page refresh (a fresh, no-longer-cold backend) then
// appeared to "fix".
export const COPILOT_REQUEST_TIMEOUT_MS = 45_000;

async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  allowRefresh = true,
  timeoutMs = REQUEST_TIMEOUT_MS
): Promise<Response> {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    timeoutMs
  );

  try {
    const response = await fetch(input, {
      ...init,
      signal: controller.signal,
    });

    const requestHeaders = new Headers(init.headers);
    const wasAuthenticated = requestHeaders.has("Authorization");

    if (
      response.status === 401 &&
      allowRefresh &&
      wasAuthenticated &&
      (await refreshSession())
    ) {
      const token = getToken();
      const retryHeaders = new Headers(init.headers);

      if (token) {
        retryHeaders.set("Authorization", `Bearer ${token}`);
      }

      return fetchWithTimeout(
        input,
        {
          ...init,
          headers: retryHeaders,
        },
        false,
        timeoutMs
      );
    }

    return response;
  } catch (error) {
    if (
      error instanceof DOMException &&
      error.name === "AbortError"
    ) {
      throw new Error(
        "The server took too long to respond. Please try again."
      );
    }

    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;

  return localStorage.getItem(TOKEN_KEY);
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;

  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

async function refreshSession(): Promise<boolean> {
  const refreshToken = getRefreshToken();

  if (!refreshToken) return false;

  const response = await fetchWithTimeout(
    `${API_URL}/users/refresh`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        refresh_token: refreshToken,
      }),
    },
    false
  );

  if (!response.ok) return false;

  const auth = (await response.json()) as AuthResponse;
  session.save(auth);
  return true;
}


function authHeaders(): HeadersInit {
  const token = getToken();

  return token
    ? {
        Authorization: `Bearer ${token}`,
      }
    : {};
}

function jsonHeaders(): HeadersInit {
  return {
    "Content-Type": "application/json",
    ...authHeaders(),
  };
}

function clearSession(): void {
  if (typeof window === "undefined") return;

  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(USER_ID_KEY);
}

function handleUnauthorized(res: Response, message: string): void {
  if (res.status !== 401) return;

  clearSession();

  if (
    typeof window !== "undefined" &&
    message.startsWith(INVALIDATED_SESSION_DETAIL)
  ) {
    sessionStorage.setItem(
      SESSION_NOTICE_KEY,
      "Your session expired. Please sign in again."
    );
  }
}

async function getErrorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => ({}));
  const status = `${res.status}${
    res.statusText ? ` ${res.statusText}` : ""
  }`;

  if (typeof body.detail === "string") {
    return `${body.detail} (${status})`;
  }

  if (Array.isArray(body.detail)) {
    const detail = body.detail
      .map((item: { msg?: string }) => item.msg)
      .filter(Boolean)
      .join(", ");

    if (detail) {
      return `${detail} (${status})`;
    }
  }

  return `Request failed (${status})`;
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const message = await getErrorMessage(res);

    handleUnauthorized(res, message);
    throw new Error(message);
  }

  return res.json();
}

async function handleEmpty(res: Response): Promise<void> {
  if (!res.ok) {
    const message = await getErrorMessage(res);

    handleUnauthorized(res, message);
    throw new Error(message);
  }
}

export type User = {
  id: number;
  email: string;
  email_verified: boolean;
};

export type PublicMessage = {
  message: string;
};

export type AuthResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
};

export type Transaction = {
  id: number;
  posted_on: string;
  description: string;
  merchant_name: string | null;
  amount_cents: number;
  category: string;
  source: string;
  pending: boolean;
  financial_account_id: number | null;
  account_name: string | null;
  institution_name: string | null;
};


export type TransactionSearchParams = {
  search?: string;
  category?: string;
  source?: string;
  account_id?: number;
  start_date?: string;
  end_date?: string;
  pending?: boolean;
  duplicates_only?: boolean;
  transaction_type?: "income" | "spending";
  page?: number;
  page_size?: number;
};

export type TransactionPage = {
  items: Transaction[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  total_income_cents: number;
  total_spending_cents: number;
  net_cents: number;
};

export type BulkTransactionDeleteResult = {
  deleted: number;
};

export type TransactionCategoryUpdateInput = {
  transaction_id: number;
  category: string;
};

export type TransactionCreateInput = {
  posted_on: string;
  description: string;
  merchant_name?: string | null;
  amount_cents: number;
  category?: string;
};

export type TransactionUpdateInput = {
  posted_on?: string;
  description?: string;
  merchant_name?: string | null;
  amount_cents?: number;
  category?: string;
};

export type CategoryTotal = {
  category: string;
  total_cents: number;
  count: number;
};

export type Overview = {
  total_income_cents: number;
  total_spending_cents: number;
  net_cents: number;
  transaction_count: number;
};

export type MonthTotal = {
  month: string;
  income_cents: number;
  spending_cents: number;
  net_cents: number;
};

export type FinancialInsight = {
  kind: string;
  title: string;
  description: string;
  severity: "info" | "positive" | "warning";
  category: string | null;
  amount_cents: number | null;
  percentage: number | null;
};

export type MonthlyInsights = {
  month: string;
  previous_month: string;
  income_cents: number;
  spending_cents: number;
  net_cents: number;
  savings_rate_percent: number;
  spending_change_cents: number;
  spending_change_percent: number | null;
  insights: FinancialInsight[];
};

export type UpcomingCashFlow = {
  merchant: string;
  amount_cents: number;
  expected_date: string;
  kind: "expense" | "income";
  confidence_score: number;
};

export type ForecastConfidenceFactor = {
  key: string;
  label: string;
  weight: number;
  score: number;
  impact: "positive" | "neutral" | "negative";
  detail: string;
};

export type MonthlyForecastConfidence = {
  month: string;
  score: number;
  transaction_count: number;
};

export type ForecastConfidenceDriver = {
  code: string;
  direction: "positive" | "negative";
  message: string;
};

export type ForecastDataQuality = {
  history_days: number;
  transaction_count: number;
  recognized_recurring_items: number;
  uncategorized_share: number;
};

export type ForecastConfidence = {
  score: number;
  level: "high" | "medium" | "low";
  factors: ForecastConfidenceFactor[];
  recommendations: string[];
  monthly_confidence: MonthlyForecastConfidence[];
  drivers: ForecastConfidenceDriver[];
  data_quality: ForecastDataQuality;
};

export type CashFlowHorizon = {
  horizon_days: number;
  through_date: string;
  expected_income_cents: number;
  known_obligations_cents: number;
  projected_balance_cents: number;
  shortfall_cents: number;
  confidence_score: number;
};

export type CashFlowForecast = {
  as_of: string;
  month_end: string;
  days_remaining: number;
  liquid_balance_cents: number;
  income_received_cents: number;
  expected_income_cents: number;
  upcoming_bills_cents: number;
  projected_end_balance_cents: number;
  low_balance_risk: boolean;
  upcoming_cash_flows: UpcomingCashFlow[];
  confidence: ForecastConfidence;
  horizon_outlook: CashFlowHorizon[];
};

export type ResilienceHorizon = {
  horizon_days: number;
  required_essential_cents: number;
  remaining_liquid_cents: number;
  shortfall_cents: number;
  coverage_percent: number;
};

export type ResilienceStatus =
  | "critical"
  | "weak"
  | "fair"
  | "strong"
  | "very_strong";

export type FinancialResilience = {
  as_of: string;
  liquid_balance_cents: number;
  liquid_account_count: number;
  monthly_essential_cents: number;
  essential_spending_source: "user_provided" | "derived";
  spending_basis_label: string;
  months_of_spending_data: number;
  runway_months: number | null;
  runway_days: number | null;
  resilience_status: ResilienceStatus;
  horizons: ResilienceHorizon[];
  confidence_score: number;
  data_quality_note: string | null;
  headline: string;
  why: string;
  what_this_means: string;
  suggested_actions: string[];
  warnings: string[];
};

export type SafeToSpendRequest = {
  safety_reserve_cents: number;
  essential_spending_cents: number;
  horizon_days: number;
  include_projected_income?: boolean;
  include_goal_reserve?: boolean;
};

export type SafeToSpendObligation = {
  name: string;
  amount_cents: number;
  expected_date: string;
  category: string | null;
  confidence_score: number;
  source: "recurring" | "budget" | "manual";
};

export type SafeToSpendBreakdown = {
  liquid_balance_cents: number;
  projected_income_cents: number;
  upcoming_obligations_cents: number;
  essential_spending_cents: number;
  goal_reserve_cents: number;
  safety_reserve_cents: number;
};

export type SafeToSpendConfidenceDriver = {
  code: string;
  direction: "positive" | "negative";
  message: string;
};

export type SafeToSpendExplanationItem = {
  code: string;
  amount_cents: number | null;
  message: string;
};

export type SafeToSpendResult = {
  as_of: string;
  through_date: string;
  horizon_days: number;
  safe_to_spend_cents: number;
  shortfall_cents: number;
  status: "safe" | "limited" | "negative";
  confidence_score: number;
  confidence_level: "high" | "medium" | "low";
  confidence_drivers: SafeToSpendConfidenceDriver[];
  breakdown: SafeToSpendBreakdown;
  obligations: SafeToSpendObligation[];
  explanation: SafeToSpendExplanationItem[];
  warnings: string[];
};

export type GoalImpactStatus =
  | "unaffected"
  | "reduced"
  | "delayed"
  | "at_risk"
  | "impossible";

export type GoalImpact = {
  goal_id: number;
  goal_name: string;
  target_date: string | null;
  target_amount_cents: number;
  saved_amount_cents: number;
  remaining_amount_cents: number;
  current_required_monthly_contribution_cents: number;
  baseline_monthly_allocation_cents: number;
  adjusted_monthly_allocation_cents: number;
  monthly_allocation_change_cents: number;
  baseline_estimated_completion_date: string | null;
  adjusted_estimated_completion_date: string | null;
  delay_months: number;
  funding_shortfall_cents: number;
  status: GoalImpactStatus;
  explanation: string;
};

export type MajorPurchaseSimulationRequest = {
  purchase_name: string;
  purchase_amount_cents: number;
  purchase_date: string;
  safety_reserve_cents: number;
  essential_spending_cents: number;
  horizon_days: number;
};

export type MajorPurchaseAlternative = {
  label: string;
  purchase_amount_cents: number;
  remaining_safe_to_spend_cents: number;
  description: string;
};

export type MajorPurchaseSimulationResult = {
  purchase_name: string;
  purchase_amount_cents: number;
  purchase_date: string;
  as_of: string;
  through_date: string;
  affordability_status:
    | "affordable"
    | "caution"
    | "not_affordable";
  safe_to_spend_before_purchase_cents: number;
  safe_to_spend_after_purchase_cents: number;
  shortfall_after_purchase_cents: number;
  recommended_max_purchase_cents: number;
  purchase_impact_percent: number;
  goal_monthly_savings_required_cents: number;
  goal_impact_months: number;
  confidence_score: number;
  explanation: string;
  alternatives: MajorPurchaseAlternative[];
  safe_to_spend: SafeToSpendResult;
  goal_impacts: GoalImpact[];
};

export type BuyNowVsWaitRequest = {
  purchase_name: string;
  purchase_amount_cents: number;
  buy_now_date: string;
  wait_until_date: string;
  safety_reserve_cents: number;
  essential_spending_cents: number;
  horizon_days: number;
};

export type BuyNowVsWaitOption = {
  label: "now" | "wait";
  evaluated_date: string;
  simulation: MajorPurchaseSimulationResult;
};

export type BuyNowVsWaitResult = {
  purchase_name: string;
  purchase_amount_cents: number;
  buy_now_date: string;
  wait_until_date: string;
  now: BuyNowVsWaitOption;
  wait: BuyNowVsWaitOption;
  recommended_timing: "buy_now" | "wait" | "either" | "neither";
  reason: string;
  key_driver:
    | "affordability"
    | "buffer"
    | "goal_impact"
    | "confidence"
    | "equivalent";
  buffer_difference_cents: number;
  goal_impact_note: string | null;
  confidence_difference: number;
  assumption: string;
  caveat: string | null;
};

export type ScenarioComparisonRequest = {
  option_a: MajorPurchaseSimulationRequest;
  option_b: MajorPurchaseSimulationRequest;
};

export type ScenarioComparisonOption = {
  option_key: "option_a" | "option_b";
  simulation: MajorPurchaseSimulationResult;
  affordability_rank: number;
};

export type ScenarioComparisonScoreCriterion = {
  key: string;
  label: string;
  weight: number;
  winner: "option_a" | "option_b" | "tie";
};

export type ScenarioComparisonScorecard = {
  option_a_score: number;
  option_b_score: number;
  max_score: number;
  criteria: ScenarioComparisonScoreCriterion[];
};

export type ScenarioComparisonResult = {
  recommended_option: "option_a" | "option_b" | "tie";
  recommendation: string;
  reasons: string[];
  scorecard: ScenarioComparisonScorecard;
  safe_to_spend_difference_cents: number;
  purchase_cost_difference_cents: number;
  impact_difference_percent: number;
  option_a: ScenarioComparisonOption;
  option_b: ScenarioComparisonOption;
};

export type FinancialStressScenarioType =
  | "emergency_expense"
  | "temporary_income_loss"
  | "delayed_paycheck"
  | "recurring_bill_increase"
  | "income_reduction"
  | "one_time_expense"
  | "recurring_expense_increase"
  | "combined";

export type FinancialStressTestRequest = {
  scenario_type: FinancialStressScenarioType;
  scenario_name: string;
  stress_amount_cents?: number | null;
  income_reduction_percent?: number | null;
  recurring_expense_increase_percent?: number | null;
  event_date: string;
  duration_days?: number | null;
  safety_reserve_cents: number;
  essential_spending_cents: number;
  horizon_days: number;
};

export type StressResilienceFactor = {
  key: string;
  label: string;
  weight: number;
  score: number;
};

export type StressAffectedGoal = {
  goal_id: number;
  name: string;
  status_before: string;
  status_after: string;
  monthly_shortfall_before_cents: number;
  monthly_shortfall_after_cents: number;
  estimated_delay_months: number | null;
};

export type StressKeyDriver =
  | "income_loss"
  | "recurring_expense_increase"
  | "emergency_expense"
  | "baseline_shortfall";

export type StressRecoveryRecommendation = {
  type:
    | "replace_lost_income"
    | "reduce_stress_expense"
    | "preserve_cash_buffer"
    | "no_action_required";
  message: string;
  adjustment_cents: number | null;
  verified: boolean;
};

export type FinancialStressTestResult = {
  scenario_type: FinancialStressScenarioType;
  scenario_name: string;
  event_date: string;
  duration_days: number | null;
  as_of: string;
  through_date: string;
  risk_level: "resilient" | "strained" | "critical";
  severity: "low" | "moderate" | "high" | "critical";
  safe_to_spend_before_stress_cents: number;
  safe_to_spend_after_stress_cents: number;
  total_financial_impact_cents: number;
  shortfall_cents: number;
  baseline_projected_balance_cents: number;
  stressed_projected_balance_cents: number;
  balance_change_cents: number;
  balance_change_percent: number;
  cash_flow_positive: boolean;
  resilience_score: number;
  resilience_factors: StressResilienceFactor[];
  affected_goals: StressAffectedGoal[];
  confidence_score: number;
  estimated_recovery_days: number | null;
  explanation: string;
  recommendations: string[];
  data_disclaimer: string;
  safe_to_spend: SafeToSpendResult;
  goal_impacts: GoalImpact[];
  runway_days: number | null;
  first_shortfall_date: string | null;
  key_driver: StressKeyDriver;
  forecast_confidence: ForecastConfidence | null;
  recovery_recommendation: StressRecoveryRecommendation | null;
  explanations: string[];
};

export type WhatIfScenarioType =
  | "one_time_expense"
  | "monthly_expense_change"
  | "monthly_income_change"
  | "monthly_savings_change"
  | "temporary_income_loss";

export type WhatIfSimulationRequest = {
  scenario_type: WhatIfScenarioType;
  scenario_name: string;
  amount_cents?: number | null;
  effective_date?: string | null;
  monthly_amount_change_cents?: number | null;
  monthly_income_loss_cents?: number | null;
  duration_months?: number | null;
  safety_reserve_cents: number;
  essential_spending_cents: number;
  horizon_days: number;
};

export type WhatIfOutcome = {
  safe_to_spend_cents: number;
  shortfall_cents: number;
  confidence_score: number;
  confidence_level: "high" | "medium" | "low";
};

export type WhatIfImpact = {
  safe_to_spend_delta_cents: number;
  shortfall_delta_cents: number;
  confidence_delta: number;
  level: "positive" | "neutral" | "caution" | "negative";
};

export type WhatIfSimulationResult = {
  scenario_type: WhatIfScenarioType;
  scenario_name: string;
  as_of: string;
  through_date: string;
  horizon_days: number;
  baseline: WhatIfOutcome;
  scenario: WhatIfOutcome;
  impact: WhatIfImpact;
  explanation: SafeToSpendExplanationItem[];
  goal_impacts: GoalImpact[];
  safe_to_spend: SafeToSpendResult;
};

export type WhatIfComparisonScenarioRequest = {
  label: string;
  scenario_type: WhatIfScenarioType;
  amount_cents?: number | null;
  effective_date?: string | null;
  monthly_amount_change_cents?: number | null;
  monthly_income_loss_cents?: number | null;
  duration_months?: number | null;
};

export type WhatIfComparisonRequest = {
  horizon_days: number;
  safety_reserve_cents: number;
  essential_spending_cents: number;
  scenarios: WhatIfComparisonScenarioRequest[];
};

export type WhatIfComparisonScenarioResult = {
  label: string;
  scenario_type: WhatIfScenarioType;
  safe_to_spend_cents: number;
  shortfall_cents: number;
  safe_to_spend_delta_cents: number;
  shortfall_delta_cents: number;
  confidence_score: number;
  confidence_level: "high" | "medium" | "low";
  impact_level: "positive" | "neutral" | "caution" | "negative";
  goal_impacts: GoalImpact[];
  explanation: SafeToSpendExplanationItem[];
};

export type WhatIfComparisonResult = {
  as_of: string;
  through_date: string;
  horizon_days: number;
  baseline: WhatIfOutcome;
  scenarios: WhatIfComparisonScenarioResult[];
  recommended_label: string | null;
  recommendation_reason: string;
  key_driver: "shortfall" | "safe_to_spend" | "goal_impact" | "tie";
  key_tradeoff: string | null;
  ranking: string[];
  is_tie: boolean;
};

export type UploadSummary = {
  imported: number;
  rejected: number;
  duplicates: number;
  errors: string[];
};

export type Budget = {
  id: number;
  category: string;
  month: string;
  limit_cents: number;
};

export type BudgetProgress = {
  category: string;
  month: string;
  limit_cents: number;
  spent_cents: number;
  remaining_cents: number;
  percent_used: number;
  over_budget_cents: number;
  overspent: boolean;
};


export type BudgetCopyResult = {
  source_month: string;
  target_month: string;
  copied: number;
  updated: number;
  skipped: number;
  budgets: Budget[];
};

export type SavingsGoal = {
  id: number;
  name: string;
  target_cents: number;
  saved_cents: number;
  remaining_cents: number;
  progress_percent: number;
  target_date: string | null;
  status: "active" | "completed" | "overdue";
  created_at: string;
  updated_at: string;
};

export type SavingsGoalCreate = {
  name: string;
  target_cents: number;
  saved_cents?: number;
  target_date?: string | null;
};

export type SavingsGoalUpdate = {
  name?: string;
  target_cents?: number;
  target_date?: string | null;
};

export type GoalContributionType =
  | "deposit"
  | "withdrawal";

export type GoalContribution = {
  id: number;
  goal_id: number;
  amount_cents: number;
  contribution_type: GoalContributionType;
  contributed_on: string;
  note: string | null;
  created_at: string;
  updated_at: string;
};

export type GoalContributionCreate = {
  amount_cents: number;
  contribution_type?: GoalContributionType;
  contributed_on?: string;
  note?: string | null;
};

export type GoalContributionUpdate = {
  amount_cents?: number;
  contribution_type?: GoalContributionType;
  contributed_on?: string;
  note?: string | null;
};


export type GoalConflictDetectionRequest = {
  monthly_savings_capacity_cents?: number | null;
};

export type GoalConflictGoal = {
  goal_id: number;
  name: string;
  target_cents: number;
  saved_cents: number;
  remaining_cents: number;
  target_date: string | null;
  months_remaining: number | null;
  required_monthly_cents: number;
  allocated_monthly_cents: number;
  monthly_shortfall_cents: number;
  status:
    | "on_track"
    | "at_risk"
    | "unfunded"
    | "no_deadline"
    | "completed";
};

export type GoalConflictKeyDriver =
  | "no_goals"
  | "no_conflict"
  | "insufficient_capacity"
  | "largest_required_goal";

export type GoalConflictRecommendation = {
  type:
    | "increase_monthly_capacity"
    | "increase_goal_allocation"
    | "reduce_goal_contribution"
    | "extend_target_date"
    | "reprioritize_goal"
    | "no_change_needed";
  message: string;
  goal_id: number | null;
  amount_cents: number | null;
  extension_months: number | null;
  resulting_monthly_gap_cents: number;
};

export type GoalConflictDetection = {
  as_of: string;
  conflict_status: "no_conflict" | "strained" | "conflict";
  monthly_savings_capacity_cents: number;
  total_required_monthly_cents: number;
  monthly_shortfall_cents: number;
  monthly_headroom_cents: number;
  key_driver: GoalConflictKeyDriver;
  confidence_score: number;
  goals: GoalConflictGoal[];
  explanation: string;
  recommendations: string[];
  recommendation: GoalConflictRecommendation;
  recommendation_alternatives: GoalConflictRecommendation[];
  warnings: string[];
};

export type GoalIntelligenceStatus =
  | "on_track"
  | "ahead"
  | "at_risk"
  | "conflict"
  | "not_feasible"
  | "completed"
  | "no_deadline";

export type GoalIntelligenceKeyDriver =
  | "goal_already_completed"
  | "no_target_date_set"
  | "ahead_of_schedule"
  | "on_track"
  | "target_date_passed"
  | "competing_goal_priority"
  | "insufficient_monthly_capacity";

export type GoalIntelligenceGoal = {
  goal_id: number;
  name: string;
  target_amount_cents: number;
  saved_amount_cents: number;
  remaining_amount_cents: number;
  target_date: string | null;
  months_remaining: number | null;
  required_monthly_cents: number;
  allocated_monthly_cents: number;
  monthly_gap_cents: number;
  status: GoalIntelligenceStatus;
  projected_completion_date: string | null;
  suggested_feasible_target_date: string | null;
  projected_delay_months: number | null;
  urgency_rank: number | null;
  confidence_score: number;
  explanation: string;
  key_driver: GoalIntelligenceKeyDriver;
  recommended_action: GoalConflictRecommendation;
  alternative_actions: GoalConflictRecommendation[];
};

export type GoalIntelligence = {
  as_of: string;
  conflict_status: "no_conflict" | "strained" | "conflict";
  total_capacity_cents: number;
  total_required_cents: number;
  total_shortfall_cents: number;
  monthly_headroom_cents: number;
  key_driver: GoalConflictKeyDriver;
  largest_pressure_goal_id: number | null;
  confidence_score: number;
  explanation: string;
  suggestions: string[];
  recommendation: GoalConflictRecommendation;
  recommendation_alternatives: GoalConflictRecommendation[];
  warnings: string[];
  goals: GoalIntelligenceGoal[];
};

export type CopilotMessage = {
  role: "user" | "assistant";
  content: string;
};

export type CopilotMetric = {
  label: string;
  value_display: string;
  kind: "currency" | "percent" | "score" | "text";
  tone: "positive" | "neutral" | "warning" | "danger";
};

export type CopilotConfidence = {
  score: number;
  level: "high" | "medium" | "low";
};

export type CopilotResponse = {
  kind: "answer" | "clarifying_question" | "out_of_scope" | "unavailable";
  answer: string | null;
  why: string | null;
  what_this_means: string | null;
  key_numbers: CopilotMetric[];
  suggested_actions: string[];
  clarifying_question: string | null;
  clarifying_options: string[] | null;
  tool_used: string | null;
  confidence: CopilotConfidence | null;
  low_data_warning: string | null;
  provenance: "deterministic" | "ai_enhanced";
};

export type RecommendationCategory =
  | "liquidity"
  | "budget"
  | "goals"
  | "spending"
  | "recurring"
  | "forecast"
  | "savings"
  | "data_quality"
  | "positive_progress";

export type RecommendationSeverity =
  | "critical"
  | "warning"
  | "opportunity"
  | "positive"
  | "informational";

export type RecommendationSourceSignal = {
  label: string;
  value_display: string;
};

export type Recommendation = {
  id: string;
  category: RecommendationCategory;
  severity: RecommendationSeverity;
  priority: number;
  title: string;
  summary: string;
  why: string;
  recommended_action: string;
  impact: string | null;
  confidence: number | null;
  source_signals: RecommendationSourceSignal[];
  deep_link: string | null;
  evaluated_at: string;
};

export type RecommendationsResult = {
  as_of: string;
  recommendations: Recommendation[];
};

export type DecisionType =
  | "major_purchase"
  | "scenario_comparison"
  | "stress_test"
  | "buy_now_vs_wait"
  | "what_if"
  | "what_if_comparison";

export type SaveDecisionRequest = {
  decision_type: DecisionType;
  title: string;
  input: Record<string, unknown>;
};

export type DecisionLifecycleStatus = "saved" | "acted_on" | "dismissed";

export type SavedDecision = {
  id: number;
  decision_type: DecisionType;
  title: string;
  input_snapshot: Record<string, unknown>;
  result_snapshot: Record<string, unknown>;
  status: DecisionLifecycleStatus;
  acted_on_at: string | null;
  created_at: string;
  outcome_count: number;
  latest_outcome_at: string | null;
};

export type DecisionRerunResult = {
  decision_id: number;
  decision_type: DecisionType;
  evaluated_at: string;
  result_snapshot: Record<string, unknown>;
};

export type DecisionOutcomeComparisonMetric = {
  path: string;
  before: number | boolean | string;
  current: number | boolean | string;
  delta: number | null;
  change_type: "numeric" | "boolean" | "text" | "date";
};

export type DecisionOutcomeComparison = {
  changed: boolean;
  metrics: DecisionOutcomeComparisonMetric[];
  summary: {
    metrics_compared: number;
    metrics_changed: number;
  };
};

export type DecisionOutcome = {
  id: number;
  decision_id: number;
  evaluated_at: string;
  current_result_snapshot: Record<string, unknown>;
  comparison_snapshot: DecisionOutcomeComparison;
  created_at: string;
};

export type CalibrationMetricUnit =
  | "currency"
  | "score"
  | "percentage"
  | "days"
  | "numeric";

export type CalibrationMetricDirection =
  | "higher_is_better"
  | "lower_is_better"
  | "unknown";

export type CalibrationLabel =
  | "insufficient_data"
  | "mostly_conservative"
  | "mostly_optimistic"
  | "balanced";

export type DecisionCalibrationMetricGroup = {
  path: string;
  unit: CalibrationMetricUnit;
  direction: CalibrationMetricDirection;
  observations: number;
  mean_signed_delta: number;
  mean_absolute_delta: number;
  latest_delta: number | null;
  favorable_count: number;
  unfavorable_count: number;
  unchanged_count: number;
};

export type DecisionCalibrationTypeBreakdown = {
  decision_type: DecisionType;
  tracked_decisions: number;
  outcome_checks: number;
  directional_observations: number;
  favorable_count: number;
  unfavorable_count: number;
  unchanged_count: number;
  favorable_rate: number | null;
  calibration_label: CalibrationLabel;
};

export type DecisionCalibration = {
  tracked_decisions: number;
  outcome_checks: number;
  numeric_metrics_compared: number;
  changed_numeric_metrics: number;
  directional_metrics_compared: number;
  favorable_count: number;
  unfavorable_count: number;
  unchanged_count: number;
  favorable_rate: number | null;
  unfavorable_rate: number | null;
  calibration_label: CalibrationLabel;
  metric_groups: DecisionCalibrationMetricGroup[];
  decision_types: DecisionCalibrationTypeBreakdown[];
};

// v1 supports major_purchase and what_if only -- other decision types
// are shown as disabled/unavailable for portfolio analysis rather
// than silently reinterpreted.
export type DecisionPortfolioRequest = {
  decision_ids: number[];
};

export type DecisionPortfolioDecision = {
  decision_id: number;
  decision_type: DecisionType;
  title: string;
};

export type DecisionPortfolioBaseline = {
  safe_to_spend_cents: number;
  confidence_score: number;
};

export type DecisionPortfolioCombined = {
  safe_to_spend_cents: number;
  safe_to_spend_delta_cents: number;
  confidence_score: number;
  confidence_delta: number;
};

export type DecisionPortfolioContributionLevel = "low" | "medium" | "high";

export type DecisionPortfolioImpact = {
  decision_id: number;
  title: string;
  decision_type: DecisionType;
  incremental_safe_to_spend_impact_cents: number;
  risk_rank: number;
  contribution_level: DecisionPortfolioContributionLevel;
};

export type DecisionPortfolioStatus = "comfortable" | "tight" | "high_risk";

export type DecisionPortfolioResult = {
  as_of: string;
  selected_decisions: DecisionPortfolioDecision[];
  baseline: DecisionPortfolioBaseline;
  combined: DecisionPortfolioCombined;
  portfolio_status: DecisionPortfolioStatus;
  decision_impacts: DecisionPortfolioImpact[];
  goal_impacts: GoalImpact[];
  conflicts: GoalConflictDetection;
  warnings: string[];
  assumptions: string[];
};

export type RecurringPayment = {
  merchant: string;
  amount_cents: number;
  frequency: string;
  last_payment: string;
  next_payment: string;
  days_until_due: number;
  occurrences: number;
  confidence_score: number;
  price_change_percent: number;
  price_change_warning: boolean;
};

export type RecurringItemStatus =
  | "suggested"
  | "active"
  | "paused"
  | "cancelled"
  | "dismissed";

export type RecurringItem = {
  id: number;
  merchant: string;
  normalized_merchant: string;
  category: string | null;
  amount_cents: number;
  frequency: "Weekly" | "Biweekly" | "Monthly";
  last_payment: string;
  next_payment: string;
  status: RecurringItemStatus;
  confidence_score: number;
  price_change_percent: number;
  price_change_warning: boolean;
  created_at: string;
  updated_at: string;
};

export type RecurringItemCreate = {
  merchant: string;
  normalized_merchant: string;
  category?: string | null;
  amount_cents: number;
  frequency: "Weekly" | "Biweekly" | "Monthly";
  last_payment: string;
  next_payment: string;
  status?: "suggested" | "active" | "dismissed";
  confidence_score: number;
  price_change_percent?: number;
  price_change_warning?: boolean;
};

export type RecurringItemUpdate = {
  category?: string | null;
  amount_cents?: number;
  frequency?: "Weekly" | "Biweekly" | "Monthly";
  next_payment?: string;
  status?: RecurringItemStatus;
};

export type RecurringUpcomingObligation = {
  recurring_item_id: number;
  merchant: string;
  category: string | null;
  amount_cents: number;
  frequency: string;
  next_payment: string;
  days_until_due: number;
};

export type RecurringAmountChange = {
  recurring_item_id: number;
  merchant: string;
  category: string | null;
  status: "increased" | "decreased";
  current_amount_cents: number;
  baseline_amount_cents: number;
  change_cents: number;
  change_percent: number;
  occurrences_considered: number;
  last_payment: string;
};

export type NewRecurringPayment = {
  recurring_item_id: number;
  merchant: string;
  category: string | null;
  amount_cents: number;
  frequency: string;
  occurrences_seen: number;
  last_payment: string;
};

export type MissingRecurringPayment = {
  recurring_item_id: number;
  merchant: string;
  category: string | null;
  amount_cents: number;
  frequency: string;
  expected_date: string;
  days_overdue: number;
  message: string;
};

export type DuplicateRecurringPair = {
  recurring_item_id_a: number;
  recurring_item_id_b: number;
  merchant_a: string;
  merchant_b: string;
  amount_a_cents: number;
  amount_b_cents: number;
  frequency: string;
  reason: string;
};

export type RecurringBurden = {
  monthly_recurring_cents: number;
  active_recurring_count: number;
  percent_of_income: number | null;
  percent_of_spending: number | null;
  next_30_days_cents: number;
  next_60_days_cents: number;
  next_90_days_cents: number;
};

export type RecurringIntelligence = {
  as_of: string;
  burden: RecurringBurden;
  upcoming: RecurringUpcomingObligation[];
  amount_changes: RecurringAmountChange[];
  new_recurring: NewRecurringPayment[];
  possibly_missing: MissingRecurringPayment[];
  possible_duplicates: DuplicateRecurringPair[];
  data_quality_note: string | null;
};

export type SpendingAnomalyType =
  | "merchant_unusual_spend"
  | "category_spike"
  | "large_transaction"
  | "repeated_charge";

export type SpendingAnomaly = {
  id: string;
  type: SpendingAnomalyType;
  severity: "info" | "warning" | "high";
  title: string;
  merchant: string | null;
  category: string | null;
  transaction_id: number | null;
  transaction_ids?: number[] | null;
  occurrence_count?: number | null;
  date: string;
  current_amount_cents: number;
  baseline_amount_cents: number | null;
  difference_cents: number | null;
  percent_difference: number | null;
  reason: string;
  confidence: "low" | "medium" | "high";
};

export type SpendingAnomalies = {
  as_of: string;
  lookback_months: number;
  anomalies: SpendingAnomaly[];
  data_quality_note: string | null;
};

export type PlaidLinkToken = {
  link_token: string;
};

export type FinancialAccount = {
  id: number;
  plaid_item_id: number;
  institution_name: string | null;
  name: string;
  official_name: string | null;
  account_type: string;
  account_subtype: string | null;
  mask: string | null;
  current_balance_cents: number | null;
  available_balance_cents: number | null;
  currency: string;
  connection_status: string;
  sync_status: "idle" | "syncing" | "succeeded" | "failed";
  sync_error: string | null;
  last_sync_attempted_at: string | null;
  last_synced_at: string | null;
};

export type PlaidSyncStatus = {
  items: Array<{
    id: number;
    institution_name: string | null;
    status: string;
    sync_status: "idle" | "syncing" | "succeeded" | "failed";
    sync_error: string | null;
    last_sync_attempted_at: string | null;
    last_synced_at: string | null;
  }>;
};

export type PlaidSyncResult = {
  added: number;
  modified: number;
  removed: number;
  items_synced: number;
  synced_at: string;
};

export type PlaidConnection = {
  item_id: number;
  institution_name: string | null;
  status: string;
  accounts: Array<{
    id: number;
    name: string;
    official_name: string | null;
    account_type: string;
    account_subtype: string | null;
    mask: string | null;
    current_balance_cents: number | null;
    available_balance_cents: number | null;
    currency: string;
  }>;
};

export const session = {
  save(auth: AuthResponse): void {
    localStorage.setItem(TOKEN_KEY, auth.access_token);
    localStorage.setItem(
      REFRESH_TOKEN_KEY,
      auth.refresh_token
    );
    localStorage.setItem(USER_ID_KEY, String(auth.user.id));
    sessionStorage.removeItem(SESSION_NOTICE_KEY);
  },

  clear: clearSession,

  getToken,

  consumeNotice(): string {
    if (typeof window === "undefined") return "";

    const notice = sessionStorage.getItem(SESSION_NOTICE_KEY) ?? "";
    sessionStorage.removeItem(SESSION_NOTICE_KEY);
    return notice;
  },

  getUserId(): number | null {
    if (typeof window === "undefined") return null;

    const value = Number(localStorage.getItem(USER_ID_KEY));

    return Number.isInteger(value) && value > 0 ? value : null;
  },
};

export const api = {
  createUser: (
    email: string,
    password: string
  ): Promise<User> =>
    fetchWithTimeout(`${API_URL}/users`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, password }),
    }).then((res) => handle<User>(res)),

  login: (
    email: string,
    password: string
  ): Promise<AuthResponse> =>
    fetchWithTimeout(`${API_URL}/users/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, password }),
    }).then((res) => handle<AuthResponse>(res)),

  forgotPassword: (email: string): Promise<PublicMessage> =>
    fetchWithTimeout(`${API_URL}/users/forgot-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    }).then((res) => handle<PublicMessage>(res)),

  resetPassword: (
    token: string,
    newPassword: string
  ): Promise<PublicMessage> =>
    fetchWithTimeout(`${API_URL}/users/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, new_password: newPassword }),
    }).then((res) => handle<PublicMessage>(res)),

  verifyEmail: (token: string): Promise<PublicMessage> =>
    fetchWithTimeout(`${API_URL}/users/verify-email`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    }).then((res) => handle<PublicMessage>(res)),

  resendVerification: (email: string): Promise<PublicMessage> =>
    fetchWithTimeout(`${API_URL}/users/resend-verification`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    }).then((res) => handle<PublicMessage>(res)),

  getMe: (): Promise<User> =>
    fetchWithTimeout(`${API_URL}/users/me`, {
      headers: authHeaders(),
    }).then((res) => handle<User>(res)),

  changePassword: (
    currentPassword: string,
    newPassword: string
  ): Promise<void> =>
    fetchWithTimeout(`${API_URL}/users/me/password`, {
      method: "PATCH",
      headers: jsonHeaders(),
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    }).then(handleEmpty),

  changeEmail: (
    newEmail: string,
    currentPassword: string
  ): Promise<User> =>
    fetchWithTimeout(`${API_URL}/users/me/email`, {
      method: "PATCH",
      headers: jsonHeaders(),
      body: JSON.stringify({
        new_email: newEmail,
        current_password: currentPassword,
      }),
    }).then((res) => handle<User>(res)),

  getUser: (id: number): Promise<User> =>
    fetchWithTimeout(`${API_URL}/users/${id}`, {
      headers: authHeaders(),
    }).then((res) => handle<User>(res)),

  uploadTransactions: (
    userId: number,
    file: File
  ): Promise<UploadSummary> => {
    const form = new FormData();
    form.append("file", file);

    return fetchWithTimeout(
      `${API_URL}/users/${userId}/transactions/upload`,
      {
        method: "POST",
        headers: authHeaders(),
        body: form,
      }
    ).then((res) => handle<UploadSummary>(res));
  },

  getTransactions: (
    userId: number
  ): Promise<Transaction[]> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/transactions`, {
      headers: authHeaders(),
    }).then((res) => handle<Transaction[]>(res)),


  searchTransactions: (
    userId: number,
    params: TransactionSearchParams = {}
  ): Promise<TransactionPage> => {
    const query = new URLSearchParams();

    for (const [key, value] of Object.entries(params)) {
      if (
        value !== undefined &&
        value !== null &&
        value !== ""
      ) {
        query.set(key, String(value));
      }
    }

    const suffix = query.toString()
      ? `?${query.toString()}`
      : "";

    return fetchWithTimeout(
      `${API_URL}/users/${userId}/transactions/search${suffix}`,
      {
        headers: authHeaders(),
      }
    ).then((res) => handle<TransactionPage>(res));
  },

  createTransaction: (
    userId: number,
    payload: TransactionCreateInput
  ): Promise<Transaction> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/transactions`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    }).then((res) => handle<Transaction>(res)),

  updateTransaction: (
    userId: number,
    transactionId: number,
    payload: TransactionUpdateInput
  ): Promise<Transaction> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/transactions/${transactionId}`,
      {
        method: "PATCH",
        headers: jsonHeaders(),
        body: JSON.stringify(payload),
      }
    ).then((res) => handle<Transaction>(res)),

  bulkUpdateTransactionCategory: (
    userId: number,
    transactionIds: number[],
    category: string
  ): Promise<Transaction[]> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/transactions/bulk/category`,
      {
        method: "PATCH",
        headers: jsonHeaders(),
        body: JSON.stringify({
          transaction_ids: transactionIds,
          category,
        }),
      }
    ).then((res) => handle<Transaction[]>(res)),

  bulkUpdateTransactionCategories: (
    userId: number,
    updates: TransactionCategoryUpdateInput[]
  ): Promise<Transaction[]> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/transactions/bulk/categories`,
      {
        method: "PATCH",
        headers: jsonHeaders(),
        body: JSON.stringify({ updates }),
      }
    ).then((res) => handle<Transaction[]>(res)),

  bulkDeleteTransactions: (
    userId: number,
    transactionIds: number[]
  ): Promise<BulkTransactionDeleteResult> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/transactions/bulk/delete`,
      {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({ transaction_ids: transactionIds }),
      }
    ).then((res) => handle<BulkTransactionDeleteResult>(res)),

  overview: (userId: number): Promise<Overview> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/summary/overview`, {
      headers: authHeaders(),
    }).then((res) => handle<Overview>(res)),

  byCategory: (
    userId: number
  ): Promise<CategoryTotal[]> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/summary/by-category`, {
      headers: authHeaders(),
    }).then((res) => handle<CategoryTotal[]>(res)),

  byMonth: (userId: number): Promise<MonthTotal[]> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/summary/by-month`, {
      headers: authHeaders(),
    }).then((res) => handle<MonthTotal[]>(res)),

  getRecurringPayments: (
    userId: number
  ): Promise<RecurringPayment[]> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/summary/recurring`, {
      headers: authHeaders(),
    }).then((res) => handle<RecurringPayment[]>(res)),

  getRecurringItems: (
    userId: number
  ): Promise<RecurringItem[]> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/recurring-items`,
      {
        headers: authHeaders(),
      }
    ).then((res) => handle<RecurringItem[]>(res)),

  createRecurringItem: (
    userId: number,
    payload: RecurringItemCreate
  ): Promise<RecurringItem> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/recurring-items`,
      {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(payload),
      }
    ).then((res) => handle<RecurringItem>(res)),

  updateRecurringItem: (
    userId: number,
    itemId: number,
    payload: RecurringItemUpdate
  ): Promise<RecurringItem> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/recurring-items/${itemId}`,
      {
        method: "PATCH",
        headers: jsonHeaders(),
        body: JSON.stringify(payload),
      }
    ).then((res) => handle<RecurringItem>(res)),

  deleteRecurringItem: (
    userId: number,
    itemId: number
  ): Promise<void> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/recurring-items/${itemId}`,
      {
        method: "DELETE",
        headers: authHeaders(),
      }
    ).then(handleEmpty),

  getRecurringIntelligence: (
    userId: number
  ): Promise<RecurringIntelligence> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/recurring-intelligence`,
      {
        headers: authHeaders(),
      }
    ).then((res) => handle<RecurringIntelligence>(res)),

  getSpendingAnomalies: (
    userId: number,
    params?: { lookback_months?: number; limit?: number }
  ): Promise<SpendingAnomalies> => {
    const query = new URLSearchParams();

    if (params?.lookback_months) {
      query.set("lookback_months", String(params.lookback_months));
    }
    if (params?.limit) {
      query.set("limit", String(params.limit));
    }

    const queryString = query.toString();

    return fetchWithTimeout(
      `${API_URL}/users/${userId}/spending-anomalies${
        queryString ? `?${queryString}` : ""
      }`,
      {
        headers: authHeaders(),
      }
    ).then((res) => handle<SpendingAnomalies>(res));
  },

  getMonthlyInsights: (
    userId: number,
    month: string
  ): Promise<MonthlyInsights> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/summary/insights?month=${encodeURIComponent(
        month
      )}`,
      {
        headers: authHeaders(),
      }
    ).then((res) => handle<MonthlyInsights>(res)),

  getCashFlowForecast: (
    userId: number,
    asOf?: string
  ): Promise<CashFlowForecast> => {
    const query = asOf
      ? `?as_of=${encodeURIComponent(asOf)}`
      : "";

    return fetchWithTimeout(
      `${API_URL}/users/${userId}/summary/cash-flow-forecast${query}`,
      {
        headers: authHeaders(),
      }
    ).then((res) => handle<CashFlowForecast>(res));
  },

  getFinancialResilience: (
    userId: number,
    essentialSpendingCents?: number
  ): Promise<FinancialResilience> => {
    const query =
      essentialSpendingCents != null
        ? `?essential_spending_cents=${essentialSpendingCents}`
        : "";

    return fetchWithTimeout(
      `${API_URL}/users/${userId}/financial-resilience${query}`,
      {
        headers: authHeaders(),
      }
    ).then((res) => handle<FinancialResilience>(res));
  },

  getSafeToSpend: (
  userId: number,
  payload: SafeToSpendRequest
): Promise<SafeToSpendResult> =>
  fetchWithTimeout(
    `${API_URL}/users/${userId}/safe-to-spend`,
    {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    }
  ).then((res) => handle<SafeToSpendResult>(res)),

simulateMajorPurchase: (
  userId: number,
  payload: MajorPurchaseSimulationRequest
): Promise<MajorPurchaseSimulationResult> =>
  fetchWithTimeout(
    `${API_URL}/users/${userId}/major-purchase/simulate`,
    {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    }
  ).then((res) =>
    handle<MajorPurchaseSimulationResult>(res)
  ),

compareMajorPurchaseScenarios: (
  userId: number,
  payload: ScenarioComparisonRequest
): Promise<ScenarioComparisonResult> =>
  fetchWithTimeout(
    `${API_URL}/users/${userId}/major-purchase/compare`,
    {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    }
  ).then((res) => handle<ScenarioComparisonResult>(res)),

evaluateBuyNowVsWait: (
  userId: number,
  payload: BuyNowVsWaitRequest
): Promise<BuyNowVsWaitResult> =>
  fetchWithTimeout(
    `${API_URL}/users/${userId}/major-purchase/buy-now-vs-wait`,
    {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    }
  ).then((res) => handle<BuyNowVsWaitResult>(res)),

runFinancialStressTest: (
  userId: number,
  payload: FinancialStressTestRequest
): Promise<FinancialStressTestResult> =>
  fetchWithTimeout(
    `${API_URL}/users/${userId}/financial-stress-test`,
    {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    }
  ).then((res) =>
    handle<FinancialStressTestResult>(res)
  ),

simulateWhatIf: (
  userId: number,
  payload: WhatIfSimulationRequest
): Promise<WhatIfSimulationResult> =>
  fetchWithTimeout(
    `${API_URL}/users/${userId}/what-if`,
    {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    }
  ).then((res) => handle<WhatIfSimulationResult>(res)),

compareWhatIfScenarios: (
  userId: number,
  payload: WhatIfComparisonRequest
): Promise<WhatIfComparisonResult> =>
  fetchWithTimeout(
    `${API_URL}/users/${userId}/what-if/compare`,
    {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    }
  ).then((res) => handle<WhatIfComparisonResult>(res)),

  getBudgets: (
    userId: number,
    month: string
  ): Promise<Budget[]> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/budgets?month=${encodeURIComponent(
        month
      )}`,
      {
        headers: authHeaders(),
      }
    ).then((res) => handle<Budget[]>(res)),

  saveBudget: (
    userId: number,
    category: string,
    month: string,
    limitCents: number
  ): Promise<Budget> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/budgets`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify({
        category,
        month,
        limit_cents: limitCents,
      }),
    }).then((res) => handle<Budget>(res)),

  getBudgetProgress: (
    userId: number,
    month: string
  ): Promise<BudgetProgress[]> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/budgets/progress?month=${encodeURIComponent(
        month
      )}`,
      {
        headers: authHeaders(),
      }
    ).then((res) => handle<BudgetProgress[]>(res)),

  deleteBudget: (
    userId: number,
    category: string,
    month: string
  ): Promise<void> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/budgets/${encodeURIComponent(
        category
      )}?month=${encodeURIComponent(month)}`,
      {
        method: "DELETE",
        headers: authHeaders(),
      }
    ).then(handleEmpty),

  copyBudgets: (
    userId: number,
    sourceMonth: string,
    targetMonth: string,
    overwrite = false
  ): Promise<BudgetCopyResult> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/budgets/copy`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        source_month: sourceMonth,
        target_month: targetMonth,
        overwrite,
      }),
    }).then((res) => handle<BudgetCopyResult>(res)),

  getSavingsGoals: (
    userId: number
  ): Promise<SavingsGoal[]> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/goals`, {
      headers: authHeaders(),
    }).then((res) => handle<SavingsGoal[]>(res)),

  getGoalIntelligence: (
    userId: number,
    monthlyCapacityCents?: number
  ): Promise<GoalIntelligence> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/goals/intelligence${
        monthlyCapacityCents != null
          ? `?monthly_capacity_cents=${monthlyCapacityCents}`
          : ""
      }`,
      {
        headers: authHeaders(),
      }
    ).then((res) => handle<GoalIntelligence>(res)),

  detectGoalConflicts: (
    userId: number,
    payload: GoalConflictDetectionRequest
  ): Promise<GoalConflictDetection> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/goal-conflicts`,
      {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(payload),
      }
    ).then((res) => handle<GoalConflictDetection>(res)),

  sendCopilotChat: (
    userId: number,
    messages: CopilotMessage[]
  ): Promise<CopilotResponse> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/copilot/chat`,
      {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({ messages }),
      },
      true,
      COPILOT_REQUEST_TIMEOUT_MS
    ).then((res) => {
      if (!res.ok) {
        // Bounded metadata only (status + backend request id) so a
        // first-after-idle failure can be correlated against backend
        // logs -- never the prompt or any financial value.
        console.error("copilot_chat_failed", {
          status: res.status,
          requestId: res.headers.get("X-Request-Id"),
        });
      }

      return handle<CopilotResponse>(res);
    }),

  getRecommendations: (
    userId: number
  ): Promise<RecommendationsResult> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/recommendations`, {
      headers: authHeaders(),
    }).then((res) => handle<RecommendationsResult>(res)),

  saveDecision: (
    userId: number,
    payload: SaveDecisionRequest
  ): Promise<SavedDecision> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/decisions`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    }).then((res) => handle<SavedDecision>(res)),

  getSavedDecisions: (userId: number): Promise<SavedDecision[]> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/decisions`, {
      headers: authHeaders(),
    }).then((res) => handle<SavedDecision[]>(res)),

  getSavedDecision: (
    userId: number,
    decisionId: number
  ): Promise<SavedDecision> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/decisions/${decisionId}`,
      { headers: authHeaders() }
    ).then((res) => handle<SavedDecision>(res)),

  deleteSavedDecision: (
    userId: number,
    decisionId: number
  ): Promise<void> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/decisions/${decisionId}`,
      { method: "DELETE", headers: authHeaders() }
    ).then(handleEmpty),

  rerunSavedDecision: (
    userId: number,
    decisionId: number
  ): Promise<DecisionRerunResult> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/decisions/${decisionId}/rerun`,
      { method: "POST", headers: authHeaders() }
    ).then((res) => handle<DecisionRerunResult>(res)),

  updateDecisionStatus: (
    userId: number,
    decisionId: number,
    status: DecisionLifecycleStatus
  ): Promise<SavedDecision> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/decisions/${decisionId}/status`,
      {
        method: "PATCH",
        headers: jsonHeaders(),
        body: JSON.stringify({ status }),
      }
    ).then((res) => handle<SavedDecision>(res)),

  evaluateDecisionOutcome: (
    userId: number,
    decisionId: number
  ): Promise<DecisionOutcome> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/decisions/${decisionId}/outcomes`,
      { method: "POST", headers: authHeaders() }
    ).then((res) => handle<DecisionOutcome>(res)),

  getDecisionOutcomes: (
    userId: number,
    decisionId: number
  ): Promise<DecisionOutcome[]> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/decisions/${decisionId}/outcomes`,
      { headers: authHeaders() }
    ).then((res) => handle<DecisionOutcome[]>(res)),

  getDecisionCalibration: (
    userId: number
  ): Promise<DecisionCalibration> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/decisions/calibration`, {
      headers: authHeaders(),
    }).then((res) => handle<DecisionCalibration>(res)),

  evaluateDecisionPortfolio: (
    userId: number,
    decisionIds: number[]
  ): Promise<DecisionPortfolioResult> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/decisions/portfolio`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ decision_ids: decisionIds }),
    }).then((res) => handle<DecisionPortfolioResult>(res)),

  createSavingsGoal: (
    userId: number,
    payload: SavingsGoalCreate
  ): Promise<SavingsGoal> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/goals`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    }).then((res) => handle<SavingsGoal>(res)),

  updateSavingsGoal: (
    userId: number,
    goalId: number,
    payload: SavingsGoalUpdate
  ): Promise<SavingsGoal> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/goals/${goalId}`, {
      method: "PATCH",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    }).then((res) => handle<SavingsGoal>(res)),

  deleteSavingsGoal: (
    userId: number,
    goalId: number
  ): Promise<void> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/goals/${goalId}`,
      {
        method: "DELETE",
        headers: authHeaders(),
      }
    ).then(handleEmpty),

  getGoalContributions: (
    userId: number,
    goalId: number
  ): Promise<GoalContribution[]> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/goals/${goalId}/contributions`,
      {
        headers: authHeaders(),
      }
    ).then((res) => handle<GoalContribution[]>(res)),

  createGoalContribution: (
    userId: number,
    goalId: number,
    payload: GoalContributionCreate
  ): Promise<GoalContribution> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/goals/${goalId}/contributions`,
      {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(payload),
      }
    ).then((res) => handle<GoalContribution>(res)),

  updateGoalContribution: (
    userId: number,
    goalId: number,
    contributionId: number,
    payload: GoalContributionUpdate
  ): Promise<GoalContribution> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/goals/${goalId}/contributions/${contributionId}`,
      {
        method: "PATCH",
        headers: jsonHeaders(),
        body: JSON.stringify(payload),
      }
    ).then((res) => handle<GoalContribution>(res)),

  deleteGoalContribution: (
    userId: number,
    goalId: number,
    contributionId: number
  ): Promise<void> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/goals/${goalId}/contributions/${contributionId}`,
      {
        method: "DELETE",
        headers: authHeaders(),
      }
    ).then(handleEmpty),

  createPlaidLinkToken: (
    userId: number
  ): Promise<PlaidLinkToken> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/plaid/link-token`,
      {
        method: "POST",
        headers: authHeaders(),
      }
    ).then((res) => handle<PlaidLinkToken>(res)),

  exchangePlaidToken: (
    userId: number,
    publicToken: string,
    institutionId?: string | null,
    institutionName?: string | null
  ): Promise<PlaidConnection> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/plaid/exchange-token`,
      {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({
          public_token: publicToken,
          institution_id: institutionId || null,
          institution_name: institutionName || null,
        }),
      }
    ).then((res) => handle<PlaidConnection>(res)),

  getAccounts: (
    userId: number
  ): Promise<FinancialAccount[]> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/accounts`, {
      headers: authHeaders(),
    }).then((res) => handle<FinancialAccount[]>(res)),


  syncPlaidTransactions: (
    userId: number
  ): Promise<PlaidSyncResult> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/plaid/sync`, {
      method: "POST",
      headers: authHeaders(),
    }).then((res) => handle<PlaidSyncResult>(res)),

  getPlaidSyncStatus: (
    userId: number
  ): Promise<PlaidSyncStatus> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/plaid/sync/status`, {
      headers: authHeaders(),
    }).then((res) => handle<PlaidSyncStatus>(res)),

  disconnectPlaidItem: (
    userId: number,
    itemId: number
  ): Promise<void> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/plaid/items/${itemId}`, {
      method: "DELETE",
      headers: authHeaders(),
    }).then(handleEmpty),
};

export function formatCents(
  cents: number,
  currency = "USD"
): string {
  const value = (
    Math.abs(cents) / 100
  ).toLocaleString("en-US", {
    style: "currency",
    currency,
  });

  return cents < 0 ? `-${value}` : value;
}