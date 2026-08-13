import type { ReactNode } from "react";

type Accent = "emerald" | "cyan" | "violet";

export function PageLoading({
  message = "Loading...",
}: {
  message?: string;
  accent?: Accent;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-56 items-center justify-center rounded-xl border border-[#181713]/10 bg-[#FFFCF7]"
    >
      <div className="text-center">
        <div className="mx-auto h-7 w-7 animate-spin rounded-full border-2 border-[#6E4B63] border-t-transparent" />

        <p className="mt-4 text-sm text-[#777168]">
          {message}
        </p>
      </div>
    </div>
  );
}

export function PageError({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-[#B75C50]/25 bg-[#F6E5E0] px-4 py-4 shadow-sm"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-[#96493F]">
            Something went wrong
          </p>

          <p className="mt-1 text-sm font-medium text-[#96493F]">
            {message}
          </p>
        </div>

        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="focus-ring shrink-0 rounded-lg border border-[#B75C50]/25 bg-[#FFFCF7] px-3.5 py-2 text-sm font-semibold text-[#96493F] transition hover:bg-white"
          >
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

export function PageSuccess({
  message,
}: {
  message: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-3 rounded-xl border border-[#58715A]/30 bg-[#E3EBE1] px-4 py-3.5 text-sm font-semibold text-[#48634B] shadow-sm"
    >
      <span
        aria-hidden="true"
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#58715A] text-xs text-white"
      >
        ✓
      </span>

      {message}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  actionLabel,
  onAction,
  children,
}: {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-[#DED8CF] bg-[#FFFCF7] px-6 py-8 text-center">
      <div
        aria-hidden="true"
        className="mx-auto flex h-9 w-9 items-center justify-center rounded-lg bg-[#EDE5DE] text-[#6E4B63]"
      >
        ◎
      </div>

      <h2 className="mt-3 text-sm font-semibold text-[#181713]">
        {title}
      </h2>

      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[#706961]">
        {description}
      </p>

      {children && <div className="mt-5">{children}</div>}

      {actionLabel && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="discero-button-primary mt-5 rounded-lg px-4 py-2.5 text-sm font-semibold transition"
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}

export function CardSkeleton({
  count = 3,
}: {
  count?: number;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }).map((_, index) => (
        <div
          key={index}
          className="h-28 animate-pulse rounded-xl border border-[#181713]/10 bg-[#181713]/[0.04]"
        />
      ))}
    </div>
  );
}
