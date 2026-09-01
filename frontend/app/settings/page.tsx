"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  ChevronDown,
  Eye,
  EyeOff,
  FileDown,
  KeyRound,
  LogOut,
  ShieldCheck,
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
  const [emailFormOpen, setEmailFormOpen] = useState(false);
  const [passwordFormOpen, setPasswordFormOpen] = useState(false);

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
        `discero-transactions-${
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
    <main className="min-h-screen bg-[#F5F1EA] text-[#181713]">
      <AppSidebar />

      <div className="px-5 pb-14 pt-20 sm:px-8 lg:ml-56 lg:px-10 lg:pt-9">
        <div className="mx-auto w-full max-w-[1500px]">
        <header className="border-b border-[#181713]/10 pb-5">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
            Account control
          </p>

          <h1 className="mt-1 text-[32px] font-semibold tracking-[-0.03em]">
            Settings
          </h1>

          <p className="mt-1 text-sm text-[#706961]">
            Identity, security, and connected data.
          </p>
        </header>

        {loading ? (
          <div className="mt-8">
            <PageLoading message="Loading account settings..." />
          </div>
        ) : user ? (
          <div className="mt-8 space-y-5">
            <div className="grid gap-5 lg:grid-cols-2">
              <section className="rounded-2xl border border-[#181713]/10 bg-[#FFFCF7] p-5 sm:p-6">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
                  Profile
                </p>

                <div className="mt-3 flex items-center gap-3">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[#6E4B63]/12 text-sm font-semibold text-[#6E4B63]">
                    {emailInitials(user.email)}
                  </span>

                  <div className="min-w-0">
                    <p className="truncate text-base font-semibold">{user.email}</p>
                    <span className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-[#58715A]">
                      <ShieldCheck className="h-3.5 w-3.5" />
                      Protected
                    </span>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => setEmailFormOpen((value) => !value)}
                  aria-expanded={emailFormOpen}
                  className="focus-ring mt-5 inline-flex w-fit items-center gap-1.5 rounded-full px-3 py-2 text-sm font-semibold text-[#6E4B63] transition hover:bg-[#F0E9EE]"
                >
                  Change email
                  <ChevronDown className={`h-4 w-4 shrink-0 transition-transform ${emailFormOpen ? "rotate-180" : ""}`} />
                </button>

                {emailFormOpen && (
                  <form onSubmit={changeEmail} className="mt-4 space-y-4">
                    <label className="block">
                      <span className="text-sm font-semibold text-[#2F2930]">
                        New email
                      </span>

                      <input
                        type="email"
                        value={newEmail}
                        onChange={(event) => setNewEmail(event.target.value)}
                        autoComplete="email"
                        required
                        className="mt-2 h-11 w-full rounded-xl border border-[#181713]/12 bg-[#F8F4EE] px-4 text-sm outline-none transition focus:border-[#6E4B63]/50 focus:ring-4 focus:ring-[#6E4B63]/10"
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
                      className="discero-button-primary min-h-11 w-full rounded-xl px-5 text-sm font-semibold transition disabled:cursor-not-allowed"
                    >
                      {savingEmail ? "Updating..." : "Update email"}
                    </button>
                  </form>
                )}
              </section>

              <section className="rounded-2xl border border-[#181713]/10 bg-[#FFFCF7] p-5 sm:p-6">
                <div className="flex items-center gap-3">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[#f7e8b5] text-[#8b6518]">
                    <KeyRound className="h-5 w-5" />
                  </span>

                  <div>
                    <p className="text-base font-semibold">Security</p>
                    <p className="mt-1 text-xs text-[#706961]">
                      Password &amp; account access
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => setPasswordFormOpen((value) => !value)}
                  aria-expanded={passwordFormOpen}
                  className="focus-ring mt-5 inline-flex w-fit items-center gap-1.5 rounded-full px-3 py-2 text-sm font-semibold text-[#6E4B63] transition hover:bg-[#F0E9EE]"
                >
                  Change password
                  <ChevronDown className={`h-4 w-4 shrink-0 transition-transform ${passwordFormOpen ? "rotate-180" : ""}`} />
                </button>

                {passwordFormOpen && (
                  <form onSubmit={changePassword} className="mt-4 space-y-4">
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
                      className="discero-button-primary min-h-11 w-full rounded-xl px-5 text-sm font-semibold transition disabled:cursor-not-allowed"
                    >
                      {savingPassword
                        ? "Updating password..."
                        : "Update password"}
                    </button>
                  </form>
                )}
              </section>
            </div>

            <section className="rounded-2xl border border-[#181713]/10 bg-[#FFFCF7] p-5 sm:p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
                Financial data
              </p>

              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div>
                  <StatCard
                    label="Connected accounts"
                    value={
                      stats ? String(stats.connectedAccounts) : "Unavailable"
                    }
                  />
                  <button
                    type="button"
                    onClick={() => router.push("/accounts")}
                    className="focus-ring mt-2 inline-flex items-center gap-1 rounded text-sm font-semibold text-[#6E4B63] transition hover:text-[#583B50]"
                  >
                    Manage accounts <span aria-hidden="true">&rarr;</span>
                  </button>
                </div>
                <div>
                  <StatCard
                    label="Transactions"
                    value={
                      stats ? stats.transactions.toLocaleString() : "Unavailable"
                    }
                  />
                  <button
                    type="button"
                    onClick={() => router.push("/transactions")}
                    className="focus-ring mt-2 inline-flex items-center gap-1 rounded text-sm font-semibold text-[#6E4B63] transition hover:text-[#583B50]"
                  >
                    View transactions <span aria-hidden="true">&rarr;</span>
                  </button>
                </div>
              </div>

              <div className="mt-5 border-t border-[#181713]/8 pt-4">
                <button
                  type="button"
                  onClick={exportTransactions}
                  disabled={exporting}
                  className="discero-button-tertiary inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <FileDown className="h-4 w-4" />
                  {exporting ? "Preparing..." : "Download CSV"}
                </button>
              </div>
            </section>

            <section className="border-t border-[#181713]/10 px-1 py-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#8A8178]">
                Account details
              </p>
              <div className="mt-2 flex items-center justify-between gap-3 text-xs text-[#8A8178]">
                <span>User ID</span>
                <span className="tabular-nums text-[#181713]">{user.id}</span>
              </div>
            </section>

            <section className="border-y border-[#A25543]/20 bg-[#FFFCF7] p-5 sm:p-6">
              <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#a64b3d]">
                    Session
                  </p>
                  <h2 className="mt-2 text-xl font-semibold">
                    Sign out of Discero
                  </h2>
                  <p className="mt-2 text-sm text-[#706961]">
                    This removes the current access token from this browser.
                  </p>
                </div>

                <button
                  type="button"
                  onClick={signOut}
                  className="discero-button-destructive inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border px-5 text-sm font-semibold transition"
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
      </div>

     {message && !error && (
  <Toast
    message={message}
    type="success"
    onClose={() => setMessage("")}
  />
)}

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
      <span className="text-sm font-semibold text-[#2F2930]">
        {label}
      </span>

      <div className="relative mt-2">
        <input
          type={visible ? "text" : "password"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoComplete={autoComplete}
          required
          className="h-11 w-full rounded-xl border border-[#181713]/12 bg-[#F8F4EE] px-4 pr-12 text-sm outline-none transition placeholder:text-[#9ba59f] focus:border-[#6E4B63]/50 focus:ring-4 focus:ring-[#6E4B63]/10"
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

function emailInitials(email: string): string {
  const local = email.split("@")[0] ?? "";
  const parts = local.split(/[._-]+/).filter(Boolean);

  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }

  return local.slice(0, 2).toUpperCase() || "?";
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
      className={`border-t border-[#181713]/10 pt-4 ${className}`}
    >
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#7b8982]">
        {label}
      </p>

      <p className="mt-2 break-words text-base font-semibold text-[#181713]">
        {value}
      </p>
    </div>
  );
}
