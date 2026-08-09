const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const TOKEN_KEY = "accessToken";
const REFRESH_TOKEN_KEY = "refreshToken";
const USER_ID_KEY = "userId";
const SESSION_NOTICE_KEY = "sessionNotice";
const INVALIDATED_SESSION_DETAIL =
  "session expired; please sign in again";
const REQUEST_TIMEOUT_MS = 15_000;

async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  allowRefresh = true
): Promise<Response> {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    REQUEST_TIMEOUT_MS
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
        false
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

export type ForecastConfidence = {
  score: number;
  level: "high" | "medium" | "low";
  factors: ForecastConfidenceFactor[];
  recommendations: string[];
  monthly_confidence: MonthlyForecastConfidence[];
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
};

export type SafeToSpendRequest = {
  safety_reserve_cents: number;
  essential_spending_cents: number;
  horizon_days: number;
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
  upcoming_obligations_cents: number;
  essential_spending_cents: number;
  safety_reserve_cents: number;
};

export type SafeToSpendResult = {
  as_of: string;
  through_date: string;
  horizon_days: number;
  safe_to_spend_cents: number;
  shortfall_cents: number;
  status: "safe" | "limited" | "negative";
  confidence_score: number;
  breakdown: SafeToSpendBreakdown;
  obligations: SafeToSpendObligation[];
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

export type GoalConflictDetection = {
  as_of: string;
  conflict_status: "no_conflict" | "strained" | "conflict";
  monthly_savings_capacity_cents: number;
  total_required_monthly_cents: number;
  monthly_shortfall_cents: number;
  confidence_score: number;
  goals: GoalConflictGoal[];
  explanation: string;
  recommendations: string[];
  warnings: string[];
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
    fetchWithTimeout(`${API_URL}/users/${userId}/copilot/chat`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ messages }),
    }).then((res) => handle<CopilotResponse>(res)),

  getRecommendations: (
    userId: number
  ): Promise<RecommendationsResult> =>
    fetchWithTimeout(`${API_URL}/users/${userId}/recommendations`, {
      headers: authHeaders(),
    }).then((res) => handle<RecommendationsResult>(res)),

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