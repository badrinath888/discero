type Accent = "emerald" | "cyan" | "violet";

export function PageLoading({
  message = "Loading...",
  accent = "emerald",
}: {
  message?: string;
  accent?: Accent;
}) {
  const spinner = {
    emerald: "border-emerald-400",
    cyan: "border-cyan-400",
    violet: "border-violet-400",
  };

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-72 items-center justify-center rounded-3xl border border-white/10 bg-white/[0.05] shadow-xl shadow-black/20 backdrop-blur-xl"
    >
      <div className="text-center">
        <div
          className={`mx-auto h-9 w-9 animate-spin rounded-full border-2 border-t-transparent ${spinner[accent]}`}
        />

        <p className="mt-4 text-sm text-slate-400">
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
      className="rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-4 text-sm text-rose-200"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="font-semibold text-rose-300">
            Something went wrong
          </p>

          <p className="mt-1 text-rose-200/80">
            {message}
          </p>
        </div>

        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="shrink-0 rounded-xl border border-rose-300/20 bg-rose-300/10 px-4 py-2 text-sm font-medium text-rose-200 transition hover:bg-rose-300/20"
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
      className="rounded-2xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-300"
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
    <div className="rounded-3xl border border-dashed border-white/10 bg-white/[0.03] px-6 py-14 text-center backdrop-blur-xl">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-white/[0.05] text-xl text-slate-400">
        ◇
      </div>

      <h2 className="mt-5 text-lg font-semibold text-slate-200">
        {title}
      </h2>

      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
        {description}
      </p>

      {actionLabel && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="mt-6 rounded-xl bg-emerald-500 px-5 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-emerald-400"
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
    <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }).map((_, index) => (
        <div
          key={index}
          className="h-32 animate-pulse rounded-3xl border border-white/5 bg-white/[0.05]"
        />
      ))}
    </div>
  );
}
