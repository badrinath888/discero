"use client";

import { useState } from "react";
import { usePathname, useRouter } from "next/navigation";
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
  {
    label: "Overview",
    href: "/dashboard",
    icon: "home",
  },
  {
    label: "Transactions",
    href: "/transactions",
    icon: "transactions",
  },
  {
    label: "Accounts",
    href: "/accounts",
    icon: "accounts",
  },
  {
    label: "Budgets",
    href: "/budgets",
    icon: "budgets",
  },
  {
    label: "Savings goals",
    href: "/goals",
    icon: "goals",
  },
];

const intelligenceNavigation: NavigationItem[] = [
  {
    label: "Insights",
    href: "/insights",
    icon: "insights",
  },
  {
    label: "Forecast",
    href: "/forecast",
    icon: "forecast",
  },
  {
    label: "Recurring bills",
    href: "/recurring",
    icon: "recurring",
  },
];

export default function AppSidebar() {
  const pathname = usePathname();
  const router = useRouter();
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
        className="focus-ring fixed left-4 top-4 z-50 flex h-10 w-10 items-center justify-center rounded-lg border border-white/10 bg-[#101720] text-slate-200 shadow-lg lg:hidden"
      >
        <Icon name="menu" />
      </button>

      {mobileOpen && (
        <button
          type="button"
          aria-label="Close navigation overlay"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-40 bg-black/65 lg:hidden"
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-white/[0.07] bg-[#0b1210] px-3 py-4 transition-transform duration-200 lg:translate-x-0 ${
          mobileOpen
            ? "translate-x-0"
            : "-translate-x-full"
        }`}
      >
        <div className="flex h-12 items-center justify-between px-2">
          <button
            type="button"
            onClick={() => navigate("/dashboard")}
            className="focus-ring flex items-center gap-3 rounded-lg text-left"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#167c5a] text-sm font-bold text-white">
              F
            </span>

            <span>
              <span className="block text-[15px] font-semibold tracking-tight text-slate-100">
                FinSight
              </span>

              <span className="block text-[11px] text-slate-500">
                Financial intelligence
              </span>
            </span>
          </button>

          <button
            type="button"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
            className="focus-ring rounded-lg p-2 text-slate-500 transition hover:bg-white/[0.05] hover:text-slate-200 lg:hidden"
          >
            <Icon name="close" />
          </button>
        </div>

        <nav className="mt-7 flex-1 overflow-y-auto">
          <NavigationGroup
            pathname={pathname}
            items={primaryNavigation}
            onNavigate={navigate}
          />

          <NavigationGroup
            label="Intelligence"
            pathname={pathname}
            items={intelligenceNavigation}
            onNavigate={navigate}
          />
        </nav>

        <div className="border-t border-white/[0.08] pt-3">
          <button
            type="button"
            onClick={signOut}
            className="focus-ring flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm text-slate-500 transition hover:bg-white/[0.045] hover:text-slate-200"
          >
            <Icon name="logout" />
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
    <div className={label ? "mt-7" : ""}>
      {label && (
        <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-600">
          {label}
        </p>
      )}

      <div className="space-y-1">
        {items.map((item) => {
          const active = pathname === item.href;

          return (
            <button
              key={item.href}
              type="button"
              onClick={() => onNavigate(item.href)}
              className={`focus-ring relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition ${
                active
                  ? "bg-white/[0.07] font-medium text-white"
                  : "text-slate-500 hover:bg-white/[0.035] hover:text-slate-200"
              }`}
            >
              {active && (
                <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-[#167c5a]" />
              )}

              <span
                className={
                  active
                    ? "text-[#76dfbd]"
                    : "text-slate-600"
                }
              >
                <Icon name={item.icon} />
              </span>

              {item.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Icon({
  name,
}: {
  name: IconName;
}) {
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
