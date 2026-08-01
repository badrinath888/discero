"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import ConnectBankButton from "../components/ConnectBankButton";
import {
  EmptyState,
  PageError,
  PageLoading,
  PageSuccess,
} from "../components/PageFeedback";
import {
  api,
  FinancialAccount,
  formatCents,
  session,
} from "../lib/api";

export default function AccountsPage() {
  const router = useRouter();

  const [userId, setUserId] = useState<number | null>(null);
  const [accounts, setAccounts] = useState<FinancialAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refreshAccounts = useCallback(async (id: number) => {
    setLoading(true);
    setError("");

    try {
      setAccounts(await api.getAccounts(id));
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to load connected accounts"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    async function initializeAccounts() {
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
        setAccounts(await api.getAccounts(id));
      } catch {
        session.clear();
        router.replace("/");
      } finally {
        setLoading(false);
      }
    }

    void initializeAccounts();
  }, [router]);

  const totalBalance = useMemo(
    () =>
      accounts.reduce(
        (total, account) =>
          total + (account.current_balance_cents ?? 0),
        0
      ),
    [accounts]
  );

  const availableBalance = useMemo(
    () =>
      accounts.reduce(
        (total, account) =>
          total + (account.available_balance_cents ?? 0),
        0
      ),
    [accounts]
  );

  const institutionCount = useMemo(
    () =>
      new Set(
        accounts.map(
          (account) =>
            account.institution_name ?? "Connected institution"
        )
      ).size,
    [accounts]
  );

  async function handleConnected() {
    if (!userId) return;

    setMessage(
      "Bank connected successfully. Your accounts are now available."
    );

    await refreshAccounts(userId);
  }

  async function handleSync() {
    if (!userId) return;

    setSyncing(true);
    setError("");
    setMessage("");

    try {
      const result = await api.syncPlaidTransactions(userId);

      setMessage(
        `Sync complete: ${result.added} added, ` +
          `${result.modified} updated, ` +
          `${result.removed} removed.`
      );

      await refreshAccounts(userId);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to synchronize transactions"
      );
    } finally {
      setSyncing(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#f5f1e8] text-[#14241e]">
      <AppSidebar />

      <div className="px-5 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-10">
        <div className="mx-auto max-w-7xl">
          <header className="grid gap-6 xl:grid-cols-[1fr_auto] xl:items-end">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
                Connected money
              </p>

              <h1 className="mt-3 max-w-3xl text-4xl font-semibold leading-tight tracking-[-0.05em] sm:text-5xl">
                All your accounts,
                <span className="block text-[#167c5a]">
                  in one calm view.
                </span>
              </h1>

              <p className="mt-4 max-w-2xl text-sm leading-6 text-[#66746e] sm:text-base">
                Review balances across institutions, connect new accounts,
                and keep transaction data synchronized.
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              {userId && accounts.length > 0 && (
                <button
                  type="button"
                  onClick={handleSync}
                  disabled={syncing}
                  className="rounded-full border border-[#14241e]/10 bg-white px-5 py-3 text-sm font-semibold transition hover:bg-[#f7f4ed] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {syncing ? "Syncing..." : "Sync transactions"}
                </button>
              )}

              {userId && (
                <ConnectBankButton
                  userId={userId}
                  onConnected={handleConnected}
                />
              )}
            </div>
          </header>

          {(message || error) && (
            <div className="mt-6 space-y-3">
              {message && <PageSuccess message={message} />}
              {error && (
                <PageError
                  message={error}
                  onRetry={
                    userId
                      ? () => void refreshAccounts(userId)
                      : undefined
                  }
                />
              )}
            </div>
          )}

          <section className="mt-8 grid gap-4 md:grid-cols-3">
            <MetricCard
              label="Combined balance"
              value={formatCents(totalBalance)}
              tone="green"
            />
            <MetricCard
              label="Available to use"
              value={formatCents(availableBalance)}
              tone="yellow"
            />
            <MetricCard
              label="Connected institutions"
              value={String(institutionCount)}
              tone="blue"
            />
          </section>

          {loading ? (
            <div className="mt-6">
              <PageLoading message="Loading connected accounts..." />
            </div>
          ) : accounts.length === 0 ? (
            <div className="mt-6">
              <EmptyState
                title="No bank accounts connected"
                description="Connect a Sandbox institution to securely import balances and transaction activity into FinSight."
              />

              {userId && (
                <div className="-mt-20 flex justify-center pb-12">
                  <ConnectBankButton
                    userId={userId}
                    onConnected={handleConnected}
                  />
                </div>
              )}
            </div>
          ) : (
            <section className="mt-6 grid gap-5 lg:grid-cols-2">
              {accounts.map((account, index) => (
                <AccountCard
                  key={account.id}
                  account={account}
                  index={index}
                />
              ))}
            </section>
          )}
        </div>
      </div>
    </main>
  );
}

function MetricCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "green" | "yellow" | "blue";
}) {
  const styles = {
    green: "bg-[#dff6c7]",
    yellow: "bg-[#f7e8b5]",
    blue: "bg-[#dceeea]",
  };

  return (
    <article className={`rounded-[26px] p-5 ${styles[tone]}`}>
      <p className="text-sm text-[#52635b]">{label}</p>
      <p className="mt-3 text-3xl font-semibold tracking-[-0.04em]">
        {value}
      </p>
    </article>
  );
}

function AccountCard({
  account,
  index,
}: {
  account: FinancialAccount;
  index: number;
}) {
  const accountLabel = [
    account.account_type,
    account.account_subtype,
  ]
    .filter(Boolean)
    .join(" • ");

  const tones = [
    "bg-[#14241e] text-white",
    "bg-[#dff6c7] text-[#14241e]",
    "bg-[#f7e8b5] text-[#14241e]",
    "bg-[#dceeea] text-[#14241e]",
  ];

  const muted =
    index % tones.length === 0
      ? "text-white/65"
      : "text-[#66746e]";

  const divider =
    index % tones.length === 0
      ? "border-white/15"
      : "border-[#14241e]/10";

  return (
    <article
      className={`rounded-[30px] p-6 shadow-sm shadow-[#14241e]/5 ${
        tones[index % tones.length]
      }`}
    >
      <div className="flex items-start justify-between gap-5">
        <div className="min-w-0">
          <p className={`text-xs font-semibold uppercase tracking-[0.16em] ${muted}`}>
            {account.institution_name ?? "Connected institution"}
          </p>

          <h2 className="mt-3 truncate text-2xl font-semibold tracking-[-0.03em]">
            {account.name}
          </h2>

          {account.official_name &&
            account.official_name !== account.name && (
              <p className={`mt-1 truncate text-sm ${muted}`}>
                {account.official_name}
              </p>
            )}
        </div>

        <div
          className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border text-sm font-bold ${
            index % tones.length === 0
              ? "border-white/15 bg-white/10 text-white"
              : "border-[#14241e]/10 bg-white/45"
          }`}
        >
          {account.mask ? `••${account.mask.slice(-2)}` : "$"}
        </div>
      </div>

      <div className="mt-8">
        <p className={`text-sm ${muted}`}>Current balance</p>
        <p className="mt-2 text-4xl font-semibold tracking-[-0.05em]">
          {account.current_balance_cents === null
            ? "Unavailable"
            : formatCents(
                account.current_balance_cents,
                account.currency
              )}
        </p>
      </div>

      <div className={`mt-8 grid gap-4 border-t pt-5 sm:grid-cols-2 ${divider}`}>
        <Balance
          label="Available balance"
          cents={account.available_balance_cents}
          currency={account.currency}
          muted={muted}
        />

        <div>
          <p className={`text-xs ${muted}`}>Account type</p>
          <p className="mt-2 text-sm font-semibold capitalize">
            {accountLabel || "Financial account"}
          </p>
        </div>
      </div>

      <p className={`mt-5 text-xs ${muted}`}>
        {account.mask
          ? `Account ending in ${account.mask}`
          : "Account number hidden"}
      </p>
    </article>
  );
}

function Balance({
  label,
  cents,
  currency,
  muted,
}: {
  label: string;
  cents: number | null;
  currency: string;
  muted: string;
}) {
  return (
    <div>
      <p className={`text-xs ${muted}`}>{label}</p>
      <p className="mt-2 text-sm font-semibold">
        {cents === null
          ? "Unavailable"
          : formatCents(cents, currency)}
      </p>
    </div>
  );
}
