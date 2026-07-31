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
  api,
  FinancialAccount,
  formatCents,
  session,
} from "../lib/api";

export default function AccountsPage() {
  const router = useRouter();

  const [userId, setUserId] = useState<number | null>(null);
  const [accounts, setAccounts] = useState<
    FinancialAccount[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refreshAccounts = useCallback(
    async (id: number) => {
      setLoading(true);
      setError("");

      try {
        const data = await api.getAccounts(id);
        setAccounts(data);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Unable to load connected accounts"
        );
      } finally {
        setLoading(false);
      }
    },
    []
  );

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

        const data = await api.getAccounts(id);

        setUserId(id);
        setAccounts(data);
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

  const institutionCount = useMemo(
    () =>
      new Set(
        accounts.map(
          (account) =>
            account.institution_name ??
            "Connected institution"
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
      const result =
        await api.syncPlaidTransactions(userId);

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
    <main
      className="relative min-h-screen overflow-hidden bg-[#050d18] text-white"
      style={{
        backgroundImage: `
          radial-gradient(circle at 10% 5%, rgba(16,185,129,0.20), transparent 28%),
          radial-gradient(circle at 88% 15%, rgba(14,165,233,0.14), transparent 25%),
          radial-gradient(circle at 50% 100%, rgba(6,182,212,0.08), transparent 35%),
          linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)
        `,
        backgroundSize:
          "auto, auto, auto, 42px 42px, 42px 42px",
      }}
    >
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent via-[#050d18]/20 to-[#050d18]" />

      <AppSidebar />

      <div className="relative px-5 pb-10 pt-20 sm:px-8 lg:ml-72 lg:px-10 lg:pt-8">
        <div className="mx-auto max-w-6xl">
        <header className="flex flex-col gap-6 rounded-3xl border border-white/10 bg-white/[0.05] p-6 shadow-2xl shadow-black/30 backdrop-blur-xl sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-300">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              Secure bank connectivity
            </div>

            <h1 className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">
              Connected accounts
            </h1>

            <p className="mt-2 max-w-xl text-sm text-slate-400">
              Connect financial institutions securely and
              review balances across your accounts.
            </p>
          </div>

          <div className="flex flex-wrap items-start gap-3">
            {userId && accounts.length > 0 && (
              <button
                type="button"
                onClick={handleSync}
                disabled={syncing}
                className="rounded-xl border border-emerald-400/20 bg-emerald-400/10 px-5 py-3 text-sm font-medium text-emerald-300 transition hover:bg-emerald-400/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {syncing
                  ? "Syncing transactions..."
                  : "Sync transactions"}
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

        {message && (
          <div className="mt-5 rounded-2xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-300">
            {message}
          </div>
        )}

        {error && (
          <div className="mt-5 rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-300">
            {error}
          </div>
        )}

        <section className="mt-6 grid gap-4 sm:grid-cols-3">
          <SummaryCard
            label="Connected accounts"
            value={String(accounts.length)}
          />

          <SummaryCard
            label="Financial institutions"
            value={String(institutionCount)}
          />

          <SummaryCard
            label="Combined balance"
            value={formatCents(totalBalance)}
          />
        </section>

        {loading ? (
          <div className="mt-6 flex min-h-80 items-center justify-center rounded-3xl border border-white/10 bg-white/[0.05] backdrop-blur-xl">
            <div className="text-center">
              <div className="mx-auto h-9 w-9 animate-spin rounded-full border-2 border-emerald-400 border-t-transparent" />

              <p className="mt-4 text-sm text-slate-400">
                Loading connected accounts...
              </p>
            </div>
          </div>
        ) : accounts.length === 0 ? (
          <section className="mt-6 rounded-3xl border border-dashed border-white/10 bg-white/[0.04] px-6 py-16 text-center backdrop-blur-xl">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-emerald-400/10 text-2xl text-emerald-300">
              $
            </div>

            <h2 className="mt-5 text-xl font-semibold">
              No bank accounts connected
            </h2>

            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-400">
              Connect a Sandbox institution to securely import
              account details and balances into FinSight.
            </p>

            {userId && (
              <div className="mt-6 flex justify-center">
                <ConnectBankButton
                  userId={userId}
                  onConnected={handleConnected}
                />
              </div>
            )}
          </section>
        ) : (
          <section className="mt-6 grid gap-5 md:grid-cols-2">
            {accounts.map((account) => (
              <AccountCard
                key={account.id}
                account={account}
              />
            ))}
          </section>
        )}
        </div>
      </div>
    </main>
  );
}

function SummaryCard({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-3xl border border-white/10 bg-white/[0.06] p-5 shadow-xl shadow-black/20 backdrop-blur-xl">
      <p className="text-sm text-slate-400">{label}</p>

      <p className="mt-3 text-2xl font-bold text-emerald-300">
        {value}
      </p>
    </div>
  );
}

function AccountCard({
  account,
}: {
  account: FinancialAccount;
}) {
  const accountLabel = [
    account.account_type,
    account.account_subtype,
  ]
    .filter(Boolean)
    .join(" • ");

  return (
    <article className="rounded-3xl border border-white/10 bg-white/[0.06] p-6 shadow-xl shadow-black/20 backdrop-blur-xl transition hover:-translate-y-1 hover:border-emerald-400/20 hover:bg-white/[0.075]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-emerald-300">
            {account.institution_name ??
              "Connected institution"}
          </p>

          <h2 className="mt-2 text-xl font-semibold text-slate-100">
            {account.name}
          </h2>

          {account.official_name &&
            account.official_name !== account.name && (
              <p className="mt-1 text-sm text-slate-500">
                {account.official_name}
              </p>
            )}
        </div>

        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-400/10 text-lg font-bold text-emerald-300">
          {account.mask ? `••${account.mask.slice(-2)}` : "$"}
        </div>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <Balance
          label="Current balance"
          cents={account.current_balance_cents}
          currency={account.currency}
        />

        <Balance
          label="Available balance"
          cents={account.available_balance_cents}
          currency={account.currency}
        />
      </div>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-4 text-xs">
        <span className="capitalize text-slate-400">
          {accountLabel || "Financial account"}
        </span>

        <span className="text-slate-500">
          {account.mask
            ? `Account ending in ${account.mask}`
            : "Account number hidden"}
        </span>
      </div>
    </article>
  );
}

function Balance({
  label,
  cents,
  currency,
}: {
  label: string;
  cents: number | null;
  currency: string;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
      <p className="text-xs text-slate-500">{label}</p>

      <p className="mt-2 text-lg font-semibold text-slate-100">
        {cents === null
          ? "Unavailable"
          : formatCents(cents, currency)}
      </p>
    </div>
  );
}
