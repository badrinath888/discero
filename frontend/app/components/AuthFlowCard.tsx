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
    <main className="flex min-h-screen items-center justify-center bg-[#f5f1e8] px-5 py-16 text-[#14241e]">
      <section className="w-full max-w-lg rounded-[28px] bg-white p-6 shadow-[0_30px_90px_rgba(20,36,30,0.14)] sm:p-9">
        <Link
          href="/"
          className="inline-flex items-center gap-3 font-semibold"
        >
          <span className="flex h-10 w-10 items-center justify-center rounded-[14px] bg-[#167c5a] text-white">
            F
          </span>
          FinSight
        </Link>

        <p className="mt-9 text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
          {eyebrow}
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-[-0.04em]">
          {title}
        </h1>
        <p className="mt-3 text-sm leading-6 text-[#66746e]">
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
          : "border-[#167c5a]/20 bg-[#d5f7a7]/35 text-[#315c29]"
      }`}
    >
      {children}
    </div>
  );
}

export const inputClass =
  "mt-2 w-full rounded-xl border border-[#14241e]/12 bg-[#f7f4ed] px-4 py-3 text-sm outline-none transition placeholder:text-[#9aa39f] focus:border-[#167c5a]";

export const buttonClass =
  "w-full rounded-full bg-[#167c5a] px-5 py-3.5 text-sm font-semibold text-white transition hover:bg-[#116847] disabled:cursor-not-allowed disabled:opacity-50";
