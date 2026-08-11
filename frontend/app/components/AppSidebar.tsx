"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import Link from "next/link";
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
  | "decisions"
  | "forecast"
  | "recurring"
  | "copilot"
  | "recommendations"
  | "settings"
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
  { label: "Settings", href: "/settings", icon: "settings" },
];

const intelligenceNavigation: NavigationItem[] = [
  { label: "Copilot", href: "/copilot", icon: "copilot" },
  {
    label: "For You",
    href: "/recommendations",
    icon: "recommendations",
  },
  { label: "Insights", href: "/insights", icon: "insights" },
  { label: "Decisions", href: "/decisions", icon: "decisions" },
  { label: "Forecast", href: "/forecast", icon: "forecast" },
  { label: "Recurring bills", href: "/recurring", icon: "recurring" },
];

export default function AppSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const reduceMotion = useReducedMotion();
  const [mobileOpen, setMobileOpen] = useState(false);

  function closeMobileMenu() {
    setMobileOpen(false);
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
          <Link
            href="/dashboard"
            onClick={closeMobileMenu}
            className="focus-ring flex min-w-0 items-center gap-3 rounded-xl text-left"
          >
            <span className="min-w-0">
              <span className="block truncate text-[15px] font-semibold tracking-[-0.02em] text-white">
                Discero
              </span>
              <span className="block truncate text-[11px] text-[#a9b8b0]">
                Financial decision intelligence
              </span>
            </span>
          </Link>

          <button
            type="button"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
            className="focus-ring rounded-xl p-2 text-[#d7e2dd] transition hover:bg-white/[0.07] hover:text-white lg:hidden"
          >
            <Icon name="close" />
          </button>
        </div>

        <nav
          aria-label="Main navigation"
          className="mt-5 flex-1 overflow-y-auto pr-1"
        >
          <NavigationGroup
            pathname={pathname}
            items={primaryNavigation}
            onNavigate={closeMobileMenu}
          />

          <div className="my-5 border-t border-white/8" />

          <NavigationGroup
            label="Intelligence"
            pathname={pathname}
            items={intelligenceNavigation}
            onNavigate={closeMobileMenu}
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
  onNavigate: () => void;
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
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
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
            </Link>
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
    decisions: (
  <>
    <path d="M12 3v18" />
    <path d="M5 7h14" />
    <path d="m5 7-3 5h6L5 7Z" />
    <path d="m19 7-3 5h6l-3-5Z" />
    <path d="M8 21h8" />
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
    copilot: (
      <>
        <path d="M12 3a8 8 0 0 0-8 8c0 2.4 1.05 4.55 2.72 6.03L6 21l4.3-1.7A8 8 0 1 0 12 3Z" />
        <path d="M9 11h.01" />
        <path d="M12 11h.01" />
        <path d="M15 11h.01" />
      </>
    ),
    recommendations: (
      <>
        <path d="M12 2v3" />
        <path d="m4.9 4.9 2.1 2.1" />
        <path d="M2 12h3" />
        <path d="m4.9 19.1 2.1-2.1" />
        <circle cx="12" cy="12" r="4" />
      </>
    ),
    settings: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21h-4v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H3v-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V3h4v.1a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1H21v4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
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
