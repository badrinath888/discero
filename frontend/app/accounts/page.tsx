"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  ArrowUpRight,
  Building2,
  ChevronDown,
  CreditCard,
  Landmark,
  RefreshCw,
  WalletCards,
  X,
} from "lucide-react";
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
  AnimatedNumber,
  PageReveal,
  Reveal,
} from "../components/PremiumMotion";
import {
  api,
  FinancialAccount,
  formatCents,
  session,
  Transaction,
} from "../lib/api";

type AccountGroup = "asset" | "liability";

function getAccountGroup(account: FinancialAccount): AccountGroup {
  const value = `${account.account_type ?? ""} ${account.account_subtype ?? ""}`
    .toLowerCase();

  return ["credit", "loan", "mortgage", "debt"].some((keyword) =>
    value.includes(keyword)
  )
    ? "liability"
    : "asset";
}

function AccountTypeIcon({
  account,
  className = "h-5 w-5",
}: {
  account: FinancialAccount;
  className?: string;
}) {
  const value = `${account.account_type ?? ""} ${account.account_subtype ?? ""}`
    .toLowerCase();

  if (value.includes("credit")) {
    return <CreditCard className={className} />;
  }

  if (value.includes("loan") || value.includes("mortgage")) {
    return <Landmark className={className} />;
  }

  if (value.includes("investment")) {
    return <Building2 className={className} />;
  }

  return <WalletCards className={className} />;
}

export default function AccountsPage() {
  const router = useRouter();

  const [userId, setUserId] = useState<number | null>(null);
  const [accounts, setAccounts] = useState<FinancialAccount[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [activeAccountId, setActiveAccountId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadAccounts = useCallback(async (id: number) => {
    setLoading(true);
    setError("");

    try {
      const [accountData, transactionData] = await Promise.all([
        api.getAccounts(id),
        api.getTransactions(id),
      ]);

      setAccounts(accountData);
      setTransactions(transactionData);
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
        await loadAccounts(id);
      } catch {
        session.clear();
        router.replace("/");
      }
    }

    void initializeAccounts();
  }, [router, loadAccounts]);

  const assets = useMemo(
    () => accounts.filter((account) => getAccountGroup(account) === "asset"),
    [accounts]
  );

  const liabilities = useMemo(
    () =>
      accounts.filter(
        (account) => getAccountGroup(account) === "liability"
      ),
    [accounts]
  );

  const assetTotal = useMemo(
    () =>
      assets.reduce(
        (total, account) =>
          total + Math.abs(account.current_balance_cents ?? 0),
        0
      ),
    [assets]
  );

  const liabilityTotal = useMemo(
    () =>
      liabilities.reduce(
        (total, account) =>
          total + Math.abs(account.current_balance_cents ?? 0),
        0
      ),
    [liabilities]
  );

  const netPosition = assetTotal - liabilityTotal;

  const availableBalance = useMemo(
    () =>
      assets.reduce(
        (total, account) =>
          total + Math.max(account.available_balance_cents ?? 0, 0),
        0
      ),
    [assets]
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

  const activeAccount =
    accounts.find((account) => account.id === activeAccountId) ?? null;

  async function handleConnected() {
    if (!userId) return;

    setMessage(
      "Bank connected successfully. Your accounts are now available."
    );
    await loadAccounts(userId);
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

      await loadAccounts(userId);
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

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[1500px]">
          <Reveal>
            <header className="flex flex-col gap-6 border-b border-[#14241e]/10 pb-7 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
                  Connected money
                </p>

                <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
                  Accounts
                </h1>

                <p className="mt-3 max-w-2xl text-sm leading-6 text-[#66746e]">
                  See your full financial position, inspect every account,
                  and keep connected balances up to date.
                </p>
              </div>

              <div className="flex flex-wrap gap-3">
                {userId && accounts.length > 0 && (
                  <button
                    type="button"
                    onClick={handleSync}
                    disabled={syncing}
                    className="inline-flex min-h-11 items-center gap-2 rounded-full border border-[#14241e]/10 bg-white px-5 text-sm font-semibold transition hover:-translate-y-0.5 hover:bg-[#f9f7f1] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <RefreshCw
                      className={`h-4 w-4 ${syncing ? "animate-spin" : ""}`}
                    />
                    {syncing ? "Syncing..." : "Sync accounts"}
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
          </Reveal>

          {(message || error) && (
            <div className="mt-5 space-y-3">
              {message && <PageSuccess message={message} />}
              {error && (
                <PageError
                  message={error}
                  onRetry={
                    userId ? () => void loadAccounts(userId) : undefined
                  }
                />
              )}
            </div>
          )}

          <Reveal delay={0.06}>
            <section className="mt-6 grid gap-4 xl:grid-cols-[1.4fr_0.6fr]">
              <article className="premium-hover relative overflow-hidden rounded-[30px] bg-[#14241e] p-7 text-white shadow-[0_24px_70px_rgba(20,36,30,0.18)] sm:p-9">
                <div className="pointer-events-none absolute -right-16 -top-16 h-52 w-52 rounded-full bg-[#76dfbd]/15 blur-3xl" />

                <div className="relative">
                  <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#83dcb9]">
                        Net financial position
                      </p>

                      {loading ? (
                        <div className="mt-5 h-14 w-60 animate-pulse rounded-xl bg-white/10" />
                      ) : (
                        <AnimatedNumber
                          value={netPosition}
                          format={formatCents}
                          className="mt-4 block text-5xl font-semibold tracking-[-0.06em] sm:text-6xl"
                        />
                      )}
                    </div>

                    <span
                      className={`inline-flex w-fit rounded-full px-3 py-1.5 text-xs font-semibold ${
                        netPosition >= 0
                          ? "bg-[#dff6c7] text-[#315d31]"
                          : "bg-[#f0b8a8] text-[#7b3528]"
                      }`}
                    >
                      {netPosition >= 0 ? "Positive position" : "Net debt"}
                    </span>
                  </div>

                  <div className="mt-10 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-3">
                    <PortfolioMetric
                      label="Assets"
                      value={formatCents(assetTotal)}
                      tone="positive"
                    />
                    <PortfolioMetric
                      label="Liabilities"
                      value={formatCents(-liabilityTotal)}
                      tone="negative"
                    />
                    <PortfolioMetric
                      label="Available cash"
                      value={formatCents(availableBalance)}
                      tone="neutral"
                    />
                  </div>
                </div>
              </article>

              <article className="premium-hover rounded-[30px] bg-[#dff6c7] p-7 sm:p-8">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#4c7e53]">
                  Connected network
                </p>

                <AnimatedNumber
                  value={accounts.length}
                  format={(value) => String(value)}
                  className="mt-4 block text-5xl font-semibold tracking-[-0.05em]"
                />

                <p className="mt-2 text-sm text-[#56705d]">
                  Financial accounts across {institutionCount} institution
                  {institutionCount === 1 ? "" : "s"}.
                </p>

                <div className="mt-8 border-t border-[#14241e]/10 pt-5">
                  <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[#5c7663]">
                    Portfolio mix
                  </p>
                  <p className="mt-2 text-sm text-[#52635b]">
                    {assets.length} asset account
                    {assets.length === 1 ? "" : "s"} · {liabilities.length}{" "}
                    liability account
                    {liabilities.length === 1 ? "" : "s"}
                  </p>
                </div>
              </article>
            </section>
          </Reveal>

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
                <div className="mt-6 flex justify-center pb-12">
                  <ConnectBankButton
                    userId={userId}
                    onConnected={handleConnected}
                  />
                </div>
              )}
            </div>
          ) : (
            <div className="mt-8 space-y-8">
              <AccountSection
                title="Assets"
                description="Cash, savings, and other accounts that contribute to your financial position."
                total={assetTotal}
                accounts={assets}
                transactions={transactions}
                expandedId={expandedId}
                onToggle={(id) =>
                  setExpandedId((current) => (current === id ? null : id))
                }
                onOpenDetails={setActiveAccountId}
              />

              <AccountSection
                title="Liabilities"
                description="Credit cards, loans, and other balances you owe."
                total={liabilityTotal}
                accounts={liabilities}
                transactions={transactions}
                expandedId={expandedId}
                onToggle={(id) =>
                  setExpandedId((current) => (current === id ? null : id))
                }
                onOpenDetails={setActiveAccountId}
                liability
              />
            </div>
          )}
        </PageReveal>
      </div>

      <AnimatePresence>
        {activeAccount && (
          <AccountDrawer
            account={activeAccount}
            transactions={transactions.filter(
              (transaction) =>
                transaction.financial_account_id === activeAccount.id
            )}
            onClose={() => setActiveAccountId(null)}
          />
        )}
      </AnimatePresence>
    </main>
  );
}

function PortfolioMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "positive" | "negative" | "neutral";
}) {
  const toneClass = {
    positive: "text-[#83dcb9]",
    negative: "text-[#f4a594]",
    neutral: "text-white",
  };

  return (
    <div className="bg-white/[0.045] p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/35">
        {label}
      </p>
      <p className={`mt-2 text-lg font-semibold ${toneClass[tone]}`}>
        {value}
      </p>
    </div>
  );
}

function AccountSection({
  title,
  description,
  total,
  accounts,
  transactions,
  expandedId,
  onToggle,
  onOpenDetails,
  liability = false,
}: {
  title: string;
  description: string;
  total: number;
  accounts: FinancialAccount[];
  transactions: Transaction[];
  expandedId: number | null;
  onToggle: (id: number) => void;
  onOpenDetails: (id: number) => void;
  liability?: boolean;
}) {
  return (
    <Reveal>
      <section className="overflow-hidden rounded-[24px] border border-[#14241e]/10 bg-white">
        <header className="flex flex-col gap-3 border-b border-[#14241e]/10 bg-[#faf8f3] px-5 py-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#167c5a]">
              {title}
            </p>
            <p className="mt-2 max-w-2xl text-sm text-[#728078]">
              {description}
            </p>
          </div>

          <p
            className={`text-2xl font-semibold tracking-[-0.04em] ${
              liability ? "text-[#a64b3d]" : "text-[#167c5a]"
            }`}
          >
            {formatCents(liability ? -total : total)}
          </p>
        </header>

        {accounts.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-[#728078]">
            No {title.toLowerCase()} connected.
          </div>
        ) : (
          <div className="divide-y divide-[#14241e]/8">
            {accounts.map((account) => (
              <AccountRow
                key={account.id}
                account={account}
                expanded={expandedId === account.id}
                recentTransactions={transactions
                  .filter(
                    (transaction) =>
                      transaction.financial_account_id === account.id
                  )
                  .slice(0, 4)}
                onToggle={() => onToggle(account.id)}
                onOpenDetails={() => onOpenDetails(account.id)}
                liability={liability}
              />
            ))}
          </div>
        )}
      </section>
    </Reveal>
  );
}

function AccountRow({
  account,
  expanded,
  recentTransactions,
  onToggle,
  onOpenDetails,
  liability,
}: {
  account: FinancialAccount;
  expanded: boolean;
  recentTransactions: Transaction[];
  onToggle: () => void;
  onOpenDetails: () => void;
  liability: boolean;
}) {
  const reduceMotion = useReducedMotion();
  const accountLabel = [account.account_type, account.account_subtype]
    .filter(Boolean)
    .join(" • ");

  return (
    <motion.article layout>
      <button
        type="button"
        onClick={onToggle}
        className="grid w-full gap-4 px-5 py-4 text-left transition hover:bg-[#fbfaf6] md:grid-cols-[52px_minmax(220px,1.4fr)_minmax(160px,1fr)_150px_36px] md:items-center"
      >
        <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#edf5ee] text-[#167c5a]">
          <AccountTypeIcon account={account} />
        </span>

        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold">
            {account.name}
          </span>
          <span className="mt-1 block truncate text-xs text-[#87928d]">
            {account.institution_name ?? "Connected institution"}
            {account.mask ? ` · •••• ${account.mask}` : ""}
          </span>
        </span>

        <span className="text-sm capitalize text-[#52635b]">
          {accountLabel || "Financial account"}
        </span>

        <span
          className={`text-base font-semibold md:text-right ${
            liability ? "text-[#a64b3d]" : "text-[#14241e]"
          }`}
        >
          {account.current_balance_cents === null
            ? "Unavailable"
            : formatCents(
                liability
                  ? -Math.abs(account.current_balance_cents)
                  : account.current_balance_cents,
                account.currency
              )}
        </span>

        <motion.span
          animate={{ rotate: expanded ? 180 : 0 }}
          transition={{ duration: reduceMotion ? 0 : 0.2 }}
          className="flex h-9 w-9 items-center justify-center rounded-xl text-[#66746e]"
        >
          <ChevronDown className="h-4 w-4" />
        </motion.span>
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={reduceMotion ? false : { opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{
              duration: reduceMotion ? 0 : 0.26,
              ease: [0.22, 1, 0.36, 1],
            }}
            className="overflow-hidden bg-[#faf8f3]"
          >
            <div className="grid gap-6 border-t border-[#14241e]/8 px-5 py-5 lg:grid-cols-[0.65fr_1.35fr]">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
                <AccountDetail
                  label="Available balance"
                  value={
                    account.available_balance_cents === null
                      ? "Unavailable"
                      : formatCents(
                          account.available_balance_cents,
                          account.currency
                        )
                  }
                />
                <AccountDetail
                  label="Official name"
                  value={account.official_name || account.name}
                />
                <AccountDetail
                  label="Currency"
                  value={account.currency.toUpperCase()}
                />

                <button
                  type="button"
                  onClick={onOpenDetails}
                  className="inline-flex items-center gap-2 text-sm font-semibold text-[#167c5a]"
                >
                  Open account details
                  <ArrowUpRight className="h-4 w-4" />
                </button>
              </div>

              <div>
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold uppercase tracking-[0.13em] text-[#728078]">
                    Recent activity
                  </p>
                  <span className="text-xs text-[#98a19d]">
                    {recentTransactions.length} shown
                  </span>
                </div>

                <div className="mt-3 divide-y divide-[#14241e]/8">
                  {recentTransactions.length > 0 ? (
                    recentTransactions.map((transaction) => (
                      <div
                        key={transaction.id}
                        className="grid gap-2 py-3 sm:grid-cols-[1fr_110px] sm:items-center"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">
                            {transaction.merchant_name ||
                              transaction.description}
                          </p>
                          <p className="mt-1 text-xs text-[#87928d]">
                            {transaction.category} ·{" "}
                            {new Date(
                              `${transaction.posted_on}T00:00:00`
                            ).toLocaleDateString("en-US", {
                              month: "short",
                              day: "numeric",
                            })}
                          </p>
                        </div>

                        <p
                          className={`text-sm font-semibold sm:text-right ${
                            transaction.amount_cents >= 0
                              ? "text-[#167c5a]"
                              : "text-[#a64b3d]"
                          }`}
                        >
                          {formatCents(transaction.amount_cents)}
                        </p>
                      </div>
                    ))
                  ) : (
                    <p className="py-6 text-sm text-[#87928d]">
                      No recent activity for this account.
                    </p>
                  )}
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.article>
  );
}

function AccountDetail({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div>
      <p className="text-xs uppercase tracking-[0.1em] text-[#87928d]">
        {label}
      </p>
      <p className="mt-2 text-sm font-semibold">{value}</p>
    </div>
  );
}

function AccountDrawer({
  account,
  transactions,
  onClose,
}: {
  account: FinancialAccount;
  transactions: Transaction[];
  onClose: () => void;
}) {
  const reduceMotion = useReducedMotion();
  const liability = getAccountGroup(account) === "liability";

  return (
    <motion.div
      className="fixed inset-0 z-50"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduceMotion ? 0 : 0.2 }}
    >
      <motion.button
        type="button"
        aria-label="Close account details"
        onClick={onClose}
        className="absolute inset-0 bg-[#14241e]/35 backdrop-blur-[2px]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      />

      <motion.aside
        initial={reduceMotion ? false : { x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{
          duration: reduceMotion ? 0 : 0.32,
          ease: [0.22, 1, 0.36, 1],
        }}
        className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col bg-[#fdfcf8] shadow-2xl"
      >
        <header className="flex items-start justify-between border-b border-[#14241e]/10 px-6 py-5">
          <div className="flex min-w-0 items-center gap-3 pr-4">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#edf5ee] text-[#167c5a]">
              <AccountTypeIcon account={account} />
            </span>

            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#167c5a]">
                Account details
              </p>
              <h2 className="mt-1 truncate text-xl font-semibold">
                {account.name}
              </h2>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[#14241e]/10 bg-white"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          <p className="text-sm text-[#728078]">
            {account.institution_name ?? "Connected institution"}
          </p>

          <p
            className={`mt-3 text-4xl font-semibold tracking-[-0.05em] ${
              liability ? "text-[#a64b3d]" : "text-[#14241e]"
            }`}
          >
            {account.current_balance_cents === null
              ? "Unavailable"
              : formatCents(
                  liability
                    ? -Math.abs(account.current_balance_cents)
                    : account.current_balance_cents,
                  account.currency
                )}
          </p>

          <dl className="mt-7 divide-y divide-[#14241e]/10 border-y border-[#14241e]/10">
            <DrawerDetail
              label="Available"
              value={
                account.available_balance_cents === null
                  ? "Unavailable"
                  : formatCents(
                      account.available_balance_cents,
                      account.currency
                    )
              }
            />
            <DrawerDetail
              label="Type"
              value={
                [account.account_type, account.account_subtype]
                  .filter(Boolean)
                  .join(" · ") || "Financial account"
              }
            />
            <DrawerDetail
              label="Account number"
              value={account.mask ? `•••• ${account.mask}` : "Hidden"}
            />
            <DrawerDetail
              label="Currency"
              value={account.currency.toUpperCase()}
            />
          </dl>

          <div className="mt-7">
            <p className="text-xs font-semibold uppercase tracking-[0.13em] text-[#728078]">
              Recent transactions
            </p>

            <div className="mt-3 divide-y divide-[#14241e]/8">
              {transactions.slice(0, 8).map((transaction) => (
                <div
                  key={transaction.id}
                  className="flex items-center justify-between gap-4 py-3"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {transaction.merchant_name || transaction.description}
                    </p>
                    <p className="mt-1 text-xs text-[#87928d]">
                      {transaction.category}
                    </p>
                  </div>

                  <p
                    className={`shrink-0 text-sm font-semibold ${
                      transaction.amount_cents >= 0
                        ? "text-[#167c5a]"
                        : "text-[#a64b3d]"
                    }`}
                  >
                    {formatCents(transaction.amount_cents)}
                  </p>
                </div>
              ))}

              {transactions.length === 0 && (
                <p className="py-6 text-sm text-[#87928d]">
                  No recent transactions are available.
                </p>
              )}
            </div>
          </div>
        </div>
      </motion.aside>
    </motion.div>
  );
}

function DrawerDetail({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="grid gap-1 py-4 sm:grid-cols-[120px_1fr]">
      <dt className="text-xs font-semibold uppercase tracking-[0.1em] text-[#87928d]">
        {label}
      </dt>
      <dd className="text-sm font-medium sm:text-right">{value}</dd>
    </div>
  );
}
