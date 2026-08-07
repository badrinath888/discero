"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  Eye,
  EyeOff,
  FileDown,
  KeyRound,
  LogOut,
  Mail,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import Toast from "../components/Toast";
import { PageError, PageLoading } from "../components/PageFeedback";
import {
  api,
  session,
  type User,
} from "../lib/api";
import { downloadCsv, transactionsToCsv } from "../lib/csv";

type AccountStats = {
  connectedAccounts: number;
  transactions: number;
};

export default function SettingsPage() {
  const router = useRouter();

  const [user, setUser] = useState<User | null>(null);
  const [stats, setStats] = useState<AccountStats | null>(null);
  const [newEmail, setNewEmail] = useState("");
  const [emailPassword, setEmailPassword] = useState("");
  const [savingEmail, setSavingEmail] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingPassword, setSavingPassword] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadProfile = useCallback(async () => {
    const id = session.getUserId();
    const token = session.getToken();

    if (!id || !token) {
      session.clear();
      router.replace("/");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const currentUser = await api.getMe();

      if (currentUser.id !== id) {
        session.clear();
        router.replace("/");
        return;
      }

      setUser(currentUser);
      setNewEmail(currentUser.email);

      // Stats are a secondary, independent fetch: a failure here
      // shouldn't hide the profile info that already loaded fine.
      try {
        const [accounts, transactionPage] = await Promise.all([
          api.getAccounts(currentUser.id),
          api.searchTransactions(currentUser.id, {
            page: 1,
            page_size: 1,
          }),
        ]);

        setStats({
          connectedAccounts: accounts.length,
          transactions: transactionPage.total,
        });
      } catch {
        setStats(null);
      }
    } catch (err) {
      if (!session.getToken()) {
        router.replace("/");
        return;
      }

      setError(
        err instanceof Error
          ? err.message
          : "Unable to load profile"
      );
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void Promise.resolve().then(loadProfile);
  }, [loadProfile]);

  useEffect(() => {
    if (!message) return;

    const timeout = window.setTimeout(
      () => setMessage(""),
      5_000
    );

    return () => window.clearTimeout(timeout);
  }, [message]);

  async function changeEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!user) return;

    const email = newEmail.trim().toLowerCase();

    if (!email) {
      setError("Enter a valid email address.");
      setMessage("");
      return;
    }

    if (email === user.email.toLowerCase()) {
      setError("New email must be different.");
      setMessage("");
      return;
    }

    if (!emailPassword) {
      setError("Enter your current password to change your email.");
      setMessage("");
      return;
    }

    setSavingEmail(true);
    setError("");
    setMessage("");

    try {
      const updatedUser = await api.changeEmail(
        email,
        emailPassword
      );

      setUser(updatedUser);
      setNewEmail(updatedUser.email);
      setEmailPassword("");
      setMessage("Email updated. Signing you out...");

      window.setTimeout(() => {
        session.clear();
        router.replace("/");
      }, 1_500);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to update email address"
      );
    } finally {
      setSavingEmail(false);
    }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!currentPassword) {
      setError("Enter your current password.");
      setMessage("");
      return;
    }

    if (newPassword.length < 8) {
      setError("New password must contain at least 8 characters.");
      setMessage("");
      return;
    }

    if (newPassword !== confirmPassword) {
      setError("New password and confirmation do not match.");
      setMessage("");
      return;
    }

    if (currentPassword === newPassword) {
      setError("New password must be different.");
      setMessage("");
      return;
    }

    setSavingPassword(true);
    setError("");
    setMessage("");

    try {
      await api.changePassword(currentPassword, newPassword);

      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setMessage("Password updated. Signing you out...");

      window.setTimeout(() => {
        session.clear();
        router.replace("/");
      }, 1_500);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to update password"
      );
    } finally {
      setSavingPassword(false);
    }
  }

  async function exportTransactions() {
    if (!user) return;

    setError("");
    setMessage("");
    setExporting(true);

    try {
      const transactions = await api.getTransactions(user.id);
      const csv = transactionsToCsv(transactions);

      downloadCsv(
        `finsight-transactions-${
          new Date().toISOString().split("T")[0]
        }.csv`,
        csv
      );

      setMessage(
        transactions.length
          ? `Exported ${transactions.length.toLocaleString()} transactions.`
          : "Exported an empty transaction file."
      );
    } catch (exportError) {
      setError(
        exportError instanceof Error
          ? exportError.message
          : "Unable to export transactions."
      );
    } finally {
      setExporting(false);
    }
  }

  function signOut() {
    session.clear();
    router.replace("/");
  }

  return (
    <main className="min-h-screen bg-[#f4f1e8] text-[#17241f] lg:pl-64">
      <AppSidebar />

      <div className="mx-auto max-w-6xl px-5 py-20 sm:px-8 lg:px-10 lg:py-10">
        <header className="border-b border-[#183028]/10 pb-7">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
            Account
          </p>

          <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
            Profile & settings
          </h1>

          <p className="mt-3 max-w-2xl text-sm leading-6 text-[#65736c]">
            Review your FinSight profile, protect your account, and manage
            your active session.
          </p>
        </header>

        {loading ? (
          <div className="mt-8">
            <PageLoading message="Loading account settings..." />
          </div>
        ) : user ? (
          <div className="mt-8 grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
            <section className="rounded-[28px] border border-[#183028]/10 bg-white p-6 shadow-sm sm:p-7">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#167c5a]">
                    Profile
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em]">
                    Account overview
                  </h2>
                </div>

                <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#edf5ee] text-[#167c5a]">
                  <UserRound className="h-5 w-5" />
                </span>
              </div>

              <div className="mt-7 grid gap-4 sm:grid-cols-2">
                <StatCard
                  label="Email"
                  value={user.email}
                  className="sm:col-span-2"
                />
                <StatCard label="User ID" value={String(user.id)} />
                <StatCard
                  label="Connected accounts"
                  value={
                    stats ? String(stats.connectedAccounts) : "Unavailable"
                  }
                />
                <StatCard
                  label="Transactions"
                  value={
                    stats ? stats.transactions.toLocaleString() : "Unavailable"
                  }
                />
              </div>

              <div className="mt-6 rounded-2xl bg-[#14241e] p-5 text-white">
                <div className="flex items-start gap-3">
                  <ShieldCheck className="mt-0.5 h-5 w-5 text-[#83dcb9]" />

                  <div>
                    <p className="text-sm font-semibold">
                      Protected account
                    </p>
                    <p className="mt-1 text-sm leading-6 text-white/55">
                      Your password is securely hashed and your authenticated
                      requests use protected access tokens.
                    </p>
                  </div>
                </div>
              </div>
            </section>

            <section className="rounded-[28px] border border-[#183028]/10 bg-white p-6 shadow-sm sm:p-7">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#167c5a]">
                    Security
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em]">
                    Change password
                  </h2>
                  <p className="mt-2 text-sm leading-6 text-[#65736c]">
                    Use at least eight characters and choose a password you
                    have not used for this account.
                  </p>
                </div>

                <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#f7e8b5] text-[#8b6518]">
                  <KeyRound className="h-5 w-5" />
                </span>
              </div>

              <form onSubmit={changePassword} className="mt-7 space-y-4">
                <PasswordField
                  label="Current password"
                  value={currentPassword}
                  onChange={setCurrentPassword}
                  autoComplete="current-password"
                />

                <PasswordField
                  label="New password"
                  value={newPassword}
                  onChange={setNewPassword}
                  autoComplete="new-password"
                />

                <PasswordField
                  label="Confirm new password"
                  value={confirmPassword}
                  onChange={setConfirmPassword}
                  autoComplete="new-password"
                />

                <button
                  type="submit"
                  disabled={savingPassword}
                  className="min-h-11 w-full rounded-xl bg-[#14241e] px-5 text-sm font-semibold text-white transition hover:bg-[#20352d] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {savingPassword
                    ? "Updating password..."
                    : "Update password"}
                </button>
              </form>
            </section>

            <section className="rounded-[28px] border border-[#183028]/10 bg-white p-6 shadow-sm xl:col-span-2 sm:p-7">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#167c5a]">
                    Contact
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em]">
                    Change email address
                  </h2>
                  <p className="mt-2 text-sm leading-6 text-[#65736c]">
                    Your new email will be used the next time you sign in.
                    Confirm this change using your current password.
                  </p>
                </div>

                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#edf5ee] text-[#167c5a]">
                  <Mail className="h-5 w-5" />
                </span>
              </div>

              <form
                onSubmit={changeEmail}
                className="mt-7 grid gap-4 lg:grid-cols-[1fr_1fr_auto] lg:items-end"
              >
                <label className="block">
                  <span className="text-sm font-semibold text-[#30423a]">
                    New email
                  </span>

                  <input
                    type="email"
                    value={newEmail}
                    onChange={(event) => setNewEmail(event.target.value)}
                    autoComplete="email"
                    required
                    className="mt-2 h-11 w-full rounded-xl border border-[#183028]/12 bg-[#faf8f3] px-4 text-sm outline-none transition focus:border-[#167c5a]/50 focus:ring-4 focus:ring-[#167c5a]/10"
                  />
                </label>

                <PasswordField
                  label="Current password"
                  value={emailPassword}
                  onChange={setEmailPassword}
                  autoComplete="current-password"
                />

                <button
                  type="submit"
                  disabled={savingEmail}
                  className="min-h-11 rounded-xl bg-[#14241e] px-6 text-sm font-semibold text-white transition hover:bg-[#20352d] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {savingEmail ? "Updating..." : "Update email"}
                </button>
              </form>
            </section>

            <section className="rounded-[28px] border border-[#183028]/10 bg-white p-6 shadow-sm xl:col-span-2 sm:p-7">
              <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#167c5a]">
                    Your data
                  </p>
                  <h2 className="mt-2 text-xl font-semibold">
                    Export transactions
                  </h2>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-[#65736c]">
                    Download all of your FinSight transactions as a CSV file
                    for spreadsheets, reporting, or personal backup.
                  </p>
                </div>

                <button
                  type="button"
                  onClick={exportTransactions}
                  disabled={exporting}
                  className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-xl bg-[#14241e] px-5 text-sm font-semibold text-white transition hover:bg-[#20352d] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <FileDown className="h-4 w-4" />
                  {exporting ? "Preparing..." : "Download CSV"}
                </button>
              </div>
            </section>

            <section className="rounded-[28px] border border-[#183028]/10 bg-white p-6 shadow-sm xl:col-span-2 sm:p-7">
              <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#a64b3d]">
                    Session
                  </p>
                  <h2 className="mt-2 text-xl font-semibold">
                    Sign out of FinSight
                  </h2>
                  <p className="mt-2 text-sm text-[#65736c]">
                    This removes the current access token from this browser.
                  </p>
                </div>

                <button
                  type="button"
                  onClick={signOut}
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[#a64b3d] px-5 text-sm font-semibold text-white transition hover:bg-[#8f3f33]"
                >
                  <LogOut className="h-4 w-4" />
                  Sign out
                </button>
              </div>
            </section>
          </div>
        ) : (
          <div className="mt-8">
            <PageError
              message={error || "Unable to load your profile."}
              onRetry={() => void loadProfile()}
            />
          </div>
        )}
      </div>

      <Toast
        message={message}
        type="success"
        onClose={() => setMessage("")}
      />

      <Toast
        message={error}
        type="error"
        onClose={() => setError("")}
      />
    </main>
  );
}

function PasswordField({
  label,
  value,
  onChange,
  autoComplete,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
}) {
  const [visible, setVisible] = useState(false);

  return (
    <label className="block">
      <span className="text-sm font-semibold text-[#30423a]">
        {label}
      </span>

      <div className="relative mt-2">
        <input
          type={visible ? "text" : "password"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoComplete={autoComplete}
          required
          className="h-11 w-full rounded-xl border border-[#183028]/12 bg-[#faf8f3] px-4 pr-12 text-sm outline-none transition placeholder:text-[#9ba59f] focus:border-[#167c5a]/50 focus:ring-4 focus:ring-[#167c5a]/10"
        />

        <button
          type="button"
          onClick={() => setVisible((current) => !current)}
          aria-label={visible ? `Hide ${label}` : `Show ${label}`}
          className="absolute inset-y-0 right-1 flex w-10 items-center justify-center rounded-lg text-[#65736c] transition hover:bg-[#183028]/5 hover:text-[#17241f]"
        >
          {visible ? (
            <EyeOff className="h-4 w-4" />
          ) : (
            <Eye className="h-4 w-4" />
          )}
        </button>
      </div>
    </label>
  );
}

function StatCard({
  label,
  value,
  className = "",
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div
      className={`rounded-2xl border border-[#183028]/10 bg-[#f8f6ef] p-5 ${className}`}
    >
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#7b8982]">
        {label}
      </p>

      <p className="mt-2 break-words text-base font-semibold text-[#17241f]">
        {value}
      </p>
    </div>
  );
}
