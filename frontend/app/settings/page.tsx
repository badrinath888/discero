"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import {
  api,
  session,
  type User,
} from "../lib/api";

type AccountStats = {
  connectedAccounts: number;
  transactions: number;
};

export default function SettingsPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [stats, setStats] = useState<AccountStats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadProfile() {
      try {
        const currentUser = await api.getMe();

        const [accounts, transactionPage] = await Promise.all([
          api.getAccounts(currentUser.id),
          api.searchTransactions(currentUser.id, {
            page: 1,
            page_size: 1,
          }),
        ]);

        setUser(currentUser);
        setStats({
          connectedAccounts: accounts.length,
          transactions: transactionPage.total,
        });
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Unable to load profile"
        );
      }
    }

    void loadProfile();
  }, []);

  function signOut() {
    session.clear();
    router.replace("/");
  }

  return (
    <main className="min-h-screen bg-[#f4f1e8] text-[#17241f] lg:pl-64">
      <AppSidebar />

      <div className="mx-auto max-w-5xl px-5 py-20 sm:px-8 lg:px-10 lg:py-10">
        <header>
          <p className="text-sm font-semibold text-[#167c5a]">
            Account
          </p>

          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.04em]">
            Profile & settings
          </h1>

          <p className="mt-3 text-sm text-[#65736c]">
            Review your FinSight account and manage your session.
          </p>
        </header>

        <section className="mt-8 rounded-3xl border border-[#183028]/10 bg-white p-6 shadow-sm">
          {error ? (
            <p className="text-sm text-rose-600">{error}</p>
          ) : !user || !stats ? (
            <p className="text-sm text-[#65736c]">
              Loading profile...
            </p>
          ) : (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <StatCard label="Email" value={user.email} />
                <StatCard label="User ID" value={String(user.id)} />
                <StatCard
                  label="Connected accounts"
                  value={String(stats.connectedAccounts)}
                />
                <StatCard
                  label="Transactions"
                  value={stats.transactions.toLocaleString()}
                />
              </div>

              <div className="mt-6 border-t border-[#183028]/10 pt-5">
                <button
                  type="button"
                  onClick={signOut}
                  className="rounded-xl bg-[#183028] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#24463a]"
                >
                  Sign out
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}

function StatCard({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl border border-[#183028]/10 bg-[#f8f6ef] p-5">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#7b8982]">
        {label}
      </p>

      <p className="mt-2 break-words text-base font-semibold text-[#17241f]">
        {value}
      </p>
    </div>
  );
}
