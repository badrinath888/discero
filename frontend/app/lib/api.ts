const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const TOKEN_KEY = "accessToken";
const USER_ID_KEY = "userId";

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

async function getErrorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => ({}));

  if (typeof body.detail === "string") {
    return body.detail;
  }

  if (Array.isArray(body.detail)) {
    return body.detail
      .map((item: { msg?: string }) => item.msg)
      .filter(Boolean)
      .join(", ");
  }

  return `Request failed (${res.status})`;
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    if (res.status === 401) {
      clearSession();
    }

    throw new Error(await getErrorMessage(res));
  }

  return res.json();
}

async function handleEmpty(res: Response): Promise<void> {
  if (!res.ok) {
    if (res.status === 401) {
      clearSession();
    }

    throw new Error(await getErrorMessage(res));
  }
}

export type User = {
  id: number;
  email: string;
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

export type RecurringPayment = {
  merchant: string;
  amount_cents: number;
  frequency: string;
  last_payment: string;
  occurrences: number;
};

export type PlaidLinkToken = {
  link_token: string;
};

export type FinancialAccount = {
  id: number;
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
  },

  clear: clearSession,

  getToken,

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
    fetch(`${API_URL}/users`, {
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
    fetch(`${API_URL}/users/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, password }),
    }).then((res) => handle<AuthResponse>(res)),

  getMe: (): Promise<User> =>
    fetch(`${API_URL}/users/me`, {
      headers: authHeaders(),
    }).then((res) => handle<User>(res)),

  getUser: (id: number): Promise<User> =>
    fetch(`${API_URL}/users/${id}`, {
      headers: authHeaders(),
    }).then((res) => handle<User>(res)),

  uploadTransactions: (
    userId: number,
    file: File
  ): Promise<UploadSummary> => {
    const form = new FormData();
    form.append("file", file);

    return fetch(
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
    fetch(`${API_URL}/users/${userId}/transactions`, {
      headers: authHeaders(),
    }).then((res) => handle<Transaction[]>(res)),

  updateTransaction: (
    userId: number,
    transactionId: number,
    category: string
  ): Promise<Transaction> =>
    fetch(
      `${API_URL}/users/${userId}/transactions/${transactionId}`,
      {
        method: "PATCH",
        headers: jsonHeaders(),
        body: JSON.stringify({ category }),
      }
    ).then((res) => handle<Transaction>(res)),

  deleteTransaction: (
    userId: number,
    transactionId: number
  ): Promise<void> =>
    fetch(
      `${API_URL}/users/${userId}/transactions/${transactionId}`,
      {
        method: "DELETE",
        headers: authHeaders(),
      }
    ).then(handleEmpty),

  overview: (userId: number): Promise<Overview> =>
    fetch(`${API_URL}/users/${userId}/summary/overview`, {
      headers: authHeaders(),
    }).then((res) => handle<Overview>(res)),

  byCategory: (
    userId: number
  ): Promise<CategoryTotal[]> =>
    fetch(`${API_URL}/users/${userId}/summary/by-category`, {
      headers: authHeaders(),
    }).then((res) => handle<CategoryTotal[]>(res)),

  byMonth: (userId: number): Promise<MonthTotal[]> =>
    fetch(`${API_URL}/users/${userId}/summary/by-month`, {
      headers: authHeaders(),
    }).then((res) => handle<MonthTotal[]>(res)),

  getRecurringPayments: (
    userId: number
  ): Promise<RecurringPayment[]> =>
    fetch(`${API_URL}/users/${userId}/summary/recurring`, {
      headers: authHeaders(),
    }).then((res) => handle<RecurringPayment[]>(res)),

  getBudgets: (
    userId: number,
    month: string
  ): Promise<Budget[]> =>
    fetch(
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
    fetch(`${API_URL}/users/${userId}/budgets`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify({
        category,
        month,
        limit_cents: limitCents,
      }),
    }).then((res) => handle<Budget>(res)),

  createPlaidLinkToken: (
    userId: number
  ): Promise<PlaidLinkToken> =>
    fetch(
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
    fetch(
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
    fetch(`${API_URL}/users/${userId}/accounts`, {
      headers: authHeaders(),
    }).then((res) => handle<FinancialAccount[]>(res)),


  syncPlaidTransactions: (
    userId: number
  ): Promise<PlaidSyncResult> =>
    fetch(`${API_URL}/users/${userId}/plaid/sync`, {
      method: "POST",
      headers: authHeaders(),
    }).then((res) => handle<PlaidSyncResult>(res)),
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