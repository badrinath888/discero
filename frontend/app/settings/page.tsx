"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import { api, session, type User } from "../lib/api";

export default function SettingsPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getMe()
      .then(setUser)
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Unable to load profile");
      });
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
          <p className="text-sm font-semibold text-[#167c5a]">Account</p>
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
          ) : !user ? (
            <p className="text-sm text-[#65736c]">Loading profile...</p>
          ) : (
            <div className="space-y-5">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#7b8982]">
                  Email
                </p>
                <p className="mt-2 text-base font-medium">{user.email}</p>
              </div>

              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#7b8982]">
                  User ID
                </p>
                <p className="mt-2 text-base font-medium">{user.id}</p>
              </div>

              <div className="border-t border-[#183028]/10 pt-5">
                <button
                  type="button"
                  onClick={signOut}
                  className="rounded-xl bg-[#183028] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#24463a]"
                >
                  Sign out
                </button>
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
