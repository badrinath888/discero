"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { session } from "../lib/api";

type IconName =
  | "home"
  | "transactions"
  | "accounts"
  | "budgets"
  | "goals"
  | "insights"
  | "forecast"
  | "recurring"
  | "logout"
  | "menu"
  | "close";

type NavigationItem = {
  label: string;
  href: string;
  icon: IconName;
};

const primaryNavigation: NavigationItem[] = [
  { label: "Overview", href: "/dashboard", icon: "home" },
  { label: "Transactions", href: "/transactions", icon: "transactions" },
  { label: "Accounts", href: "/accounts", icon: "accounts" },
  { label: "Budgets", href: "/budgets", icon: "budgets" },
  { label: "Savings goals", href: "/goals", icon: "goals" },
];

const intelligenceNavigation: NavigationItem[] = [
  { label: "Insights", href: "/insights", icon: "insights" },
  { label: "Forecast", href: "/forecast", icon: "forecast" },
  { label: "Recurring bills", href: "/recurring", icon: "recurring" },
];

export default function AppSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const reduceMotion = useReducedMotion();
  const [mobileOpen, setMobileOpen] = useState(false);

  function navigate(href: string) {
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
        className="focus-ring fixed left-4 top-4 z-50 flex h-11 w-11 items-center justify-center rounded-2xl border border-[#14241e]/10 bg-[#24463a] text-[#f4f0e7] shadow-[0_10px_30px_rgba(20,36,30,0.12)] lg:hidden"
      >
        <Icon name="menu" />
      </button>

      <AnimatePresence>
        {mobileOpen && (
          <motion.button
            type="button"
            aria-label="Close navigation overlay"
            onClick={() => setMobileOpen(false)}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduceMotion ? 0 : 0.18 }}
            className="fixed inset-0 z-40 bg-[#0f211b]/45 backdrop-blur-[2px] lg:hidden"
          />
        )}
      </AnimatePresence>

      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-white/8 bg-[#183028] px-3 py-4 text-[#f4f0e7] shadow-[8px_0_30px_rgba(15,33,27,0.16)] transition-transform duration-200 lg:translate-x-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-14 items-center justify-between px-2">
          <button
            type="button"
            onClick={() => navigate("/dashboard")}
            className="focus-ring flex min-w-0 items-center gap-3 rounded-xl text-left"
          >
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-[#1b9a70] text-sm font-bold text-white shadow-sm">
              F
            </span>

            <span className="min-w-0">
              <span className="block truncate text-[15px] font-semibold tracking-[-0.02em] text-white">
                FinSight
              </span>
              <span className="block truncate text-[11px] text-[#a9b8b0]">
                Financial intelligence
              </span>
            </span>
          </button>

          <button
            type="button"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
            className="focus-ring rounded-xl p-2 text-[#d7e2dd] transition hover:bg-white/[0.07] hover:text-white lg:hidden"
          >
            <Icon name="close" />
          </button>
        </div>

        <nav className="mt-5 flex-1 overflow-y-auto pr-1">
          <NavigationGroup
            pathname={pathname}
            items={primaryNavigation}
            onNavigate={navigate}
          />

          <div className="my-5 border-t border-white/8" />

          <NavigationGroup
            label="Intelligence"
            pathname={pathname}
            items={intelligenceNavigation}
            onNavigate={navigate}
          />
        </nav>

        <div className="border-t border-white/8 pt-3">
          <button
            type="button"
            onClick={signOut}
            className="focus-ring flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium text-[#dce7e1] transition hover:bg-white/[0.07] hover:text-white"
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-white/[0.06] text-[#9fb0a8]">
              <Icon name="logout" />
            </span>
            Sign out
          </button>
        </div>
      </aside>
    </>
  );
}

function NavigationGroup({
  label,
  pathname,
  items,
  onNavigate,
}: {
  label?: string;
  pathname: string;
  items: NavigationItem[];
  onNavigate: (href: string) => void;
}) {
  return (
    <div>
      {label && (
        <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#aebfb7]">
          {label}
        </p>
      )}

      <div className="space-y-1.5">
        {items.map((item) => {
          const active = pathname === item.href;

          return (
            <button
              key={item.href}
              type="button"
              onClick={() => onNavigate(item.href)}
              className={`focus-ring group relative flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-left text-sm transition ${
                active
                  ? "bg-[#d5e7da] font-semibold text-[#173c30] shadow-[0_6px_18px_rgba(20,36,30,0.10)]"
                  : "font-medium text-[#d7e2dd] hover:bg-white/[0.07] hover:text-white"
              }`}
            >
              <span
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl transition ${
                  active
                    ? "bg-white text-[#167c5a]"
                    : "bg-white/[0.08] text-[#c8d5cf] group-hover:bg-white/[0.12] group-hover:text-[#7ce0bd]"
                }`}
              >
                <Icon name={item.icon} />
              </span>

              <span className="truncate">{item.label}</span>

              {active && (
                <span className="absolute inset-y-3 left-0 w-1 rounded-r-full bg-[#22a879]" />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, React.ReactNode> = {
    home: (
      <>
        <path d="m3 11 9-8 9 8" />
        <path d="M5 10v10h14V10" />
        <path d="M9 20v-6h6v6" />
      </>
    ),
    transactions: (
      <>
        <path d="M7 3v18" />
        <path d="m3 7 4-4 4 4" />
        <path d="M17 21V3" />
        <path d="m13 17 4 4 4-4" />
      </>
    ),
    accounts: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <path d="M3 10h18" />
        <path d="M7 15h3" />
      </>
    ),
    budgets: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v10" />
        <path d="M15 9.5c0-1.4-1.3-2.5-3-2.5s-3 1-3 2.5 1.3 2.5 3 2.5 3 1.1 3 2.5-1.3 2.5-3 2.5-3-1.1-3-2.5" />
      </>
    ),
    goals: (
      <>
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="5" />
        <circle cx="12" cy="12" r="1" />
      </>
    ),
    insights: (
      <>
        <path d="M4 19V9" />
        <path d="M10 19V5" />
        <path d="M16 19v-7" />
        <path d="M22 19H2" />
      </>
    ),
    forecast: (
      <>
        <path d="M4 17 10 11l4 4 6-8" />
        <path d="M15 7h5v5" />
      </>
    ),
    recurring: (
      <>
        <path d="M20 7h-5V2" />
        <path d="M4 17h5v5" />
        <path d="M5.5 9a8 8 0 0 1 13-3L20 7" />
        <path d="M18.5 15a8 8 0 0 1-13 3L4 17" />
      </>
    ),
    logout: (
      <>
        <path d="M10 17l5-5-5-5" />
        <path d="M15 12H3" />
        <path d="M21 19V5a2 2 0 0 0-2-2h-6" />
      </>
    ),
    menu: (
      <>
        <path d="M4 7h16" />
        <path d="M4 12h16" />
        <path d="M4 17h16" />
      </>
    ),
    close: (
      <>
        <path d="m6 6 12 12" />
        <path d="m18 6-12 12" />
      </>
    ),
  };

  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-[18px] w-[18px]"
    >
      {paths[name]}
    </svg>
  );
}
