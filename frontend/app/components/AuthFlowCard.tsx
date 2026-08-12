import Link from "next/link";
import type { ReactNode } from "react";


export default function AuthFlowCard({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[#F5F1EA] px-5 py-12 text-[#181713]">
      <section className="w-full max-w-lg border-y border-[#181713]/10 bg-[#FFFCF7] p-6 shadow-[0_20px_60px_rgba(60,43,35,0.08)] sm:p-9">
        <Link
          href="/"
          className="inline-flex items-center gap-3 font-semibold"
        >
          Discero
        </Link>

        <p className="mt-8 text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">
          {eyebrow}
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-[-0.04em]">
          {title}
        </h1>
        <p className="mt-3 text-sm leading-6 text-[#706961]">
          {description}
        </p>

        <div className="mt-7">{children}</div>
      </section>
    </main>
  );
}

export function FlowMessage({
  children,
  error = false,
}: {
  children: ReactNode;
  error?: boolean;
}) {
  return (
    <div
      role={error ? "alert" : "status"}
      className={`rounded-xl border px-4 py-3 text-sm ${
        error
          ? "border-[#bc5b47]/20 bg-[#f0b8a8]/30 text-[#873d2f]"
          : "border-[#58715A]/20 bg-[#E3EBE1] text-[#48634B]"
      }`}
    >
      {children}
    </div>
  );
}

export const inputClass =
  "mt-2 w-full rounded-xl border border-[#181713]/12 bg-[#F8F4EE] px-4 py-3 text-sm outline-none transition placeholder:text-[#9B938B] focus:border-[#6E4B63] focus:ring-4 focus:ring-[#6E4B63]/10";

export const buttonClass =
  "discero-button-primary w-full rounded-xl px-5 py-3.5 text-sm font-semibold transition disabled:cursor-not-allowed";
