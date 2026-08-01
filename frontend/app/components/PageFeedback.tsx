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
      className="flex min-h-56 items-center justify-center rounded-xl border border-white/[0.08] bg-[#101916]"
    >
      <div className="text-center">
        <div className="mx-auto h-7 w-7 animate-spin rounded-full border-2 border-[#55d6a7] border-t-transparent" />

        <p className="mt-4 text-sm text-slate-500">
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
      className="rounded-lg border border-rose-400/20 bg-rose-400/[0.07] px-4 py-3.5"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium text-rose-300">
            Something went wrong
          </p>

          <p className="mt-1 text-sm text-rose-200/70">
            {message}
          </p>
        </div>

        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="focus-ring shrink-0 rounded-lg border border-rose-300/20 px-3.5 py-2 text-sm font-medium text-rose-200 transition hover:bg-rose-300/[0.08]"
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
      className="rounded-lg border border-emerald-400/20 bg-emerald-400/[0.07] px-4 py-3 text-sm text-[#55d6a7]"
    >
      {message}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  actionLabel,
  onAction,
}: {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="rounded-xl border border-dashed border-white/[0.1] bg-[#101916] px-6 py-12 text-center">
      <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-lg border border-white/[0.08] text-slate-600">
        ◎
      </div>

      <h2 className="mt-4 text-sm font-medium text-slate-300">
        {title}
      </h2>

      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-600">
        {description}
      </p>

      {actionLabel && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="focus-ring mt-5 rounded-lg bg-[#55d6a7] px-4 py-2.5 text-sm font-semibold text-[#07110e] transition hover:bg-[#6ee0b5]"
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
          className="h-28 animate-pulse rounded-xl border border-white/[0.06] bg-[#101916]"
        />
      ))}
    </div>
  );
}
