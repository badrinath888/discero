"use client";

import { useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { session } from "../lib/api";

type NavigationItem = {
  label: string;
  href: string;
  icon: string;
  disabled?: boolean;
};

const navigation: NavigationItem[] = [
  {
    label: "Overview",
    href: "/dashboard",
    icon: "⌂",
  },
  {
    label: "Transactions",
    href: "/transactions",
    icon: "↕",
  },
  {
    label: "Accounts",
    href: "/accounts",
    icon: "▣",
  },
  {
    label: "Budgets",
    href: "/budgets",
    icon: "◎",
  },
  {
    label: "Savings Goals",
    href: "/goals",
    icon: "◇",
  },
  {
    label: "Insights",
    href: "/insights",
    icon: "✦",
  },
  {
    label: "Forecast",
    href: "/forecast",
    icon: "↗",
  },
  {
    label: "Recurring Bills",
    href: "/recurring",
    icon: "⟳",
  },
];

export default function AppSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = useState(false);

  function navigate(href: string, disabled?: boolean) {
    if (disabled) return;

    setMobileOpen(false);
    router.push(href);
  }

  function signOut() {
    session.clear();
    router.replace("/");
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setMobileOpen(true)}
        aria-label="Open navigation"
        className="fixed left-4 top-4 z-50 flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-[#0b1728]/95 text-xl text-white shadow-xl backdrop-blur-xl lg:hidden"
      >
        ☰
      </button>

      {mobileOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-white/10 bg-[#081422]/95 p-5 shadow-2xl shadow-black/30 backdrop-blur-2xl transition-transform duration-300 lg:translate-x-0 ${
          mobileOpen
            ? "translate-x-0"
            : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={() => navigate("/dashboard")}
            className="flex items-center gap-3 text-left"
          >
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400 to-cyan-400 text-lg font-black text-slate-950 shadow-lg shadow-emerald-500/20">
              F
            </span>

            <span>
              <span className="block text-lg font-bold tracking-tight text-white">
                FinSight
              </span>

              <span className="block text-xs text-slate-500">
                Financial intelligence
              </span>
            </span>
          </button>

          <button
            type="button"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
            className="rounded-lg p-2 text-slate-400 hover:bg-white/5 hover:text-white lg:hidden"
          >
            ✕
          </button>
        </div>

        <div className="mt-8 rounded-2xl border border-emerald-400/15 bg-emerald-400/[0.06] p-4">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-300">
            Financial workspace
          </p>

          <p className="mt-2 text-xs leading-5 text-slate-400">
            Track spending, budgets, goals, and future cash flow.
          </p>
        </div>

        <nav className="mt-7 flex-1 space-y-1.5">
          {navigation.map((item) => {
            const active = pathname === item.href;

            return (
              <button
                key={item.href}
                type="button"
                disabled={item.disabled}
                onClick={() =>
                  navigate(item.href, item.disabled)
                }
                className={`group flex w-full items-center gap-3 rounded-xl px-3.5 py-3 text-left text-sm font-medium transition ${
                  active
                    ? "bg-emerald-400/12 text-emerald-300"
                    : item.disabled
                    ? "cursor-not-allowed text-slate-600"
                    : "text-slate-400 hover:bg-white/[0.06] hover:text-white"
                }`}
              >
                <span
                  className={`flex h-8 w-8 items-center justify-center rounded-lg text-base ${
                    active
                      ? "bg-emerald-400/15"
                      : "bg-white/[0.04]"
                  }`}
                >
                  {item.icon}
                </span>

                <span className="flex-1">
                  {item.label}
                </span>

                {item.disabled && (
                  <span className="rounded-full bg-white/[0.05] px-2 py-0.5 text-[10px] font-medium text-slate-600">
                    Soon
                  </span>
                )}

                {active && (
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                )}
              </button>
            );
          })}
        </nav>

        <div className="border-t border-white/10 pt-5">
          <button
            type="button"
            onClick={signOut}
            className="flex w-full items-center gap-3 rounded-xl px-3.5 py-3 text-left text-sm font-medium text-slate-400 transition hover:bg-rose-400/10 hover:text-rose-300"
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/[0.04]">
              ↪
            </span>

            Sign out
          </button>
        </div>
      </aside>
    </>
  );
}
