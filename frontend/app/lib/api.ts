const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const TOKEN_KEY = "accessToken";
const USER_ID_KEY = "userId";
const SESSION_NOTICE_KEY = "sessionNotice";
const INVALIDATED_SESSION_DETAIL =
  "session expired; please sign in again";
const REQUEST_TIMEOUT_MS = 15_000;

async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {}
): Promise<Response> {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    REQUEST_TIMEOUT_MS
  );

  try {
    return await fetch(input, {
      ...init,
      signal: controller.signal,
    });
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
  saved_cents?: number;
  target_date?: string | null;
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
  last_synced_at: string | null;
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

  updateTransaction: (
    userId: number,
    transactionId: number,
    category: string
  ): Promise<Transaction> =>
    fetchWithTimeout(
      `${API_URL}/users/${userId}/transactions/${transactionId}`,
      {
        method: "PATCH",
        headers: jsonHeaders(),
        body: JSON.stringify({ category }),
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
    fetchWithTimeout(`${API_URL}/users/${userId}/goals/${goalId}`, {
      method: "DELETE",
      headers: authHeaders(),
    }).then(handleEmpty),

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
