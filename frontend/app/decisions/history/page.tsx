"use client";

import { useEffect, useState } from "react";
import {
  ArrowRight,
  Clock,
  RotateCcw,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AppSidebar from "../../components/AppSidebar";
import { PageReveal, Reveal, Stagger } from "../../components/PremiumMotion";
import {
  api,
  DecisionType,
  formatCents,
  SavedDecision,
  session,
} from "../../lib/api";

const TYPE_LABEL: Record<DecisionType, string> = {
  major_purchase: "Major Purchase",
  scenario_comparison: "Scenario Comparison",
  stress_test: "Stress Test",
  buy_now_vs_wait: "Buy Now vs Wait",
};

const STATUS_TONE: Record<string, string> = {
  affordable: "bg-[#dff6c7] text-[#315d31]",
  caution: "bg-[#f5d66f] text-[#66500f]",
  not_affordable: "bg-[#f0b8a8] text-[#7b3528]",
  resilient: "bg-[#dff6c7] text-[#315d31]",
  strained: "bg-[#f5d66f] text-[#66500f]",
  critical: "bg-[#f0b8a8] text-[#7b3528]",
  buy_now: "bg-[#dff6c7] text-[#315d31]",
  wait: "bg-[#dff6c7] text-[#315d31]",
  either: "bg-[#f5d66f] text-[#66500f]",
  neither: "bg-[#f0b8a8] text-[#7b3528]",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// result_snapshot is a free-form JSON blob (see SavedDecision) -- it
// should always match the decision type's real output schema, but a
// decision saved under a different/older shape must never crash the
// history page. Every chip is built from one of these guarded reads,
// and simply omitted (never a made-up placeholder) when its field is
// missing or the wrong type.
function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

function asNonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function humanize(value: string): string {
  return value.replace(/_/g, " ");
}

function summaryChips(
  decision: SavedDecision
): { label: string; value: string }[] {
  const r = decision.result_snapshot as Record<string, unknown>;
  const chips: { label: string; value: string }[] = [];

  if (decision.decision_type === "major_purchase") {
    const amount = asNumber(r.purchase_amount_cents);
    if (amount !== undefined) {
      chips.push({ label: "Amount", value: formatCents(amount) });
    }

    const safeAfter = asNumber(r.safe_to_spend_after_purchase_cents);
    if (safeAfter !== undefined) {
      chips.push({
        label: "Safe to spend after",
        value: formatCents(safeAfter),
      });
    }

    const confidence = asNumber(r.confidence_score);
    if (confidence !== undefined) {
      chips.push({
        label: "Confidence",
        value: `${Math.round(confidence)}%`,
      });
    }

    return chips;
  }

  if (decision.decision_type === "scenario_comparison") {
    const recommended = asNonEmptyString(r.recommended_option);
    const label =
      recommended === "option_a"
        ? "Option A"
        : recommended === "option_b"
          ? "Option B"
          : recommended === "tie"
            ? "Tie"
            : undefined;

    if (label !== undefined) {
      chips.push({ label: "Recommended", value: label });
    }

    return chips;
  }

  if (decision.decision_type === "buy_now_vs_wait") {
    const timing = asNonEmptyString(r.recommended_timing);
    if (timing !== undefined) {
      chips.push({ label: "Recommendation", value: humanize(timing) });
    }

    const buffer = asNumber(r.buffer_difference_cents);
    if (buffer !== undefined) {
      chips.push({
        label: "Buffer difference",
        value: formatCents(buffer),
      });
    }

    const confidenceDifference = asNumber(r.confidence_difference);
    if (confidenceDifference !== undefined) {
      chips.push({
        label: "Confidence difference",
        value: `${Math.round(confidenceDifference)} pts`,
      });
    }

    const assumption = asNonEmptyString(r.assumption);
    if (assumption !== undefined) {
      chips.push({ label: "Assumption", value: assumption });
    }

    return chips;
  }

  // stress_test (and any other/future decision type)
  const resilience = asNumber(r.resilience_score);
  if (resilience !== undefined) {
    chips.push({
      label: "Resilience score",
      value: `${Math.round(resilience)}`,
    });
  }

  const confidence = asNumber(r.confidence_score);
  if (confidence !== undefined) {
    chips.push({
      label: "Confidence",
      value: `${Math.round(confidence)}%`,
    });
  }

  return chips;
}

function statusLabel(decision: SavedDecision): string | null {
  const r = decision.result_snapshot as Record<string, unknown>;
  const status =
    asNonEmptyString(r.affordability_status) ??
    asNonEmptyString(r.risk_level) ??
    asNonEmptyString(r.recommended_timing);
  return status ? humanize(status) : null;
}

export default function DecisionHistoryPage() {
  const router = useRouter();
  const [initializing, setInitializing] = useState(true);
  const [userId, setUserId] = useState<number | null>(null);
  const [decisions, setDecisions] = useState<SavedDecision[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rerunResults, setRerunResults] = useState<
    Record<number, Record<string, unknown>>
  >({});
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    async function initialize() {
      const id = session.getUserId();
      const token = session.getToken();

      if (!id || !token) {
        session.clear();
        router.replace("/");
        return;
      }

      try {
        const user = await api.getMe();

        if (user.id !== id) {
          session.clear();
          router.replace("/");
          return;
        }

        setUserId(id);

        try {
          setDecisions(await api.getSavedDecisions(id));
        } catch {
          setError("Couldn't load your saved decisions just now.");
        }
      } catch {
        session.clear();
        router.replace("/");
      } finally {
        setInitializing(false);
      }
    }

    void initialize();
  }, [router]);

  async function handleDelete(decisionId: number) {
    if (userId === null) return;

    setBusyId(decisionId);
    try {
      await api.deleteSavedDecision(userId, decisionId);
      setDecisions(
        (prev) => prev?.filter((d) => d.id !== decisionId) ?? null
      );
    } catch {
      setError("Couldn't delete that decision just now.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleRerun(decisionId: number) {
    if (userId === null) return;

    setBusyId(decisionId);
    try {
      const outcome = await api.rerunSavedDecision(userId, decisionId);
      setRerunResults((prev) => ({
        ...prev,
        [decisionId]: outcome.result_snapshot,
      }));
    } catch {
      setError("Couldn't re-run that decision just now.");
    } finally {
      setBusyId(null);
    }
  }

  if (initializing) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#F5F1EA]">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#6E4B63] border-t-transparent" />
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#F5F1EA] text-[#181713]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-56 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[900px]">
          <Reveal>
            <header className="border-b border-[#181713]/10 pb-7">
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">
                <Clock className="h-3.5 w-3.5" />
                Decision history
              </p>

              <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
                Your decision record.
              </h1>

              <p className="mt-3 max-w-2xl text-sm leading-6 text-[#706961]">
                Purchases, comparisons, and stress tests you saved --
                with the exact deterministic result at the time.
              </p>

              <Link
                href="/decisions"
                className="focus-ring mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-[#6E4B63]"
              >
                Run a new analysis
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </header>
          </Reveal>

          <div className="mt-8">
            {error && (
              <p
                role="alert"
                className="mb-4 rounded-2xl border border-[#a64b3d]/20 bg-[#f8e6e1] px-4 py-3 text-sm font-medium text-[#a64b3d]"
              >
                {error}
              </p>
            )}

            {decisions !== null && decisions.length === 0 && (
              <Reveal>
                <div
                  data-testid="decisions-history-empty"
                  className="rounded-[26px] border border-[#181713]/10 bg-white px-6 py-10 text-center shadow-[0_14px_40px_rgba(60,43,35,0.06)]"
                >
                  <p className="text-lg font-semibold tracking-[-0.02em]">
                    No saved decisions yet
                  </p>
                  <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-[#706961]">
                    Save a major purchase, comparison, or stress test to
                    revisit it later.
                  </p>
                </div>
              </Reveal>
            )}

            {decisions !== null && decisions.length > 0 && (
              <Stagger className="divide-y divide-[#181713]/10 border-y border-[#181713]/10">
                {decisions.map((decision) => {
                  const status = statusLabel(decision);
                  const rerun = rerunResults[decision.id];

                  return (
                    <Reveal key={decision.id}>
                      <article
                        data-testid="decision-history-card"
                        className="py-6 sm:py-7"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="inline-flex items-center rounded-full bg-[#eef1ec] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-[#5F5751]">
                            {TYPE_LABEL[decision.decision_type]}
                          </span>

                          {status && (
                            <span
                              className={`inline-flex items-center rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.1em] ${
                                STATUS_TONE[status.replace(/ /g, "_")] ??
                                "bg-[#eef1ec] text-[#5F5751]"
                              }`}
                            >
                              {status}
                            </span>
                          )}

                          <span className="text-xs text-[#8a978f]">
                            Analyzed {formatDate(decision.created_at)}
                          </span>
                        </div>

                        <h2 className="mt-3 text-lg font-semibold tracking-[-0.02em] text-[#2F2930]">
                          {decision.title}
                        </h2>

                        <div className="mt-5 grid gap-px overflow-hidden bg-[#181713]/10 sm:grid-cols-3">
                          {summaryChips(decision).map((chip) => (
                            <div
                              key={chip.label}
                              className="bg-[#FFFCF7] px-4 py-3"
                            >
                              <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8a978f]">
                                {chip.label}
                              </p>
                              <p className="mt-0.5 text-base font-semibold tracking-[-0.02em] text-[#2F2930]">
                                {chip.value}
                              </p>
                            </div>
                          ))}
                        </div>

                        {rerun && (
                          <div
                            data-testid="decision-rerun-result"
                            className="mt-5 border-l-2 border-[#6E4B63] bg-[#F0E9EE]/55 px-5 py-4"
                          >
                            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
                              Now (re-run with current data)
                            </p>
                            <div className="mt-2 flex flex-wrap gap-2.5">
                              {summaryChips({
                                ...decision,
                                result_snapshot: rerun,
                              }).map((chip) => (
                                <div
                                  key={chip.label}
                                  className="rounded-xl bg-white px-3 py-2"
                                >
                                  <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8a978f]">
                                    {chip.label}
                                  </p>
                                  <p className="mt-0.5 text-sm font-semibold text-[#2F2930]">
                                    {chip.value}
                                  </p>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[#181713]/8 pt-4">
                          <button
                            type="button"
                            disabled={busyId === decision.id}
                            onClick={() => handleRerun(decision.id)}
                            className="focus-ring inline-flex items-center gap-1.5 rounded-full border border-[#6E4B63]/25 bg-[#F8F4EE] px-3.5 py-1.5 text-xs font-semibold text-[#6E4B63] transition hover:bg-[#dff6c7] disabled:opacity-50"
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                            Run again
                          </button>

                          <button
                            type="button"
                            disabled={busyId === decision.id}
                            onClick={() => handleDelete(decision.id)}
                            className="focus-ring inline-flex items-center gap-1.5 rounded-full border border-[#a64b3d]/25 bg-[#f8e6e1] px-3.5 py-1.5 text-xs font-semibold text-[#a64b3d] transition hover:bg-[#f0b8a8] disabled:opacity-50"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            Delete
                          </button>
                        </div>
                      </article>
                    </Reveal>
                  );
                })}
              </Stagger>
            )}
          </div>
        </PageReveal>
      </div>
    </main>
  );
}
