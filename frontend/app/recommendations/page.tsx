"use client";

import { useEffect, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  Info,
  Lightbulb,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import { PageReveal, Reveal, Stagger } from "../components/PremiumMotion";
import {
  api,
  Recommendation,
  RecommendationSeverity,
  session,
} from "../lib/api";

const SEVERITY_STYLES: Record<
  RecommendationSeverity,
  { badge: string; label: string; icon: typeof TriangleAlert }
> = {
  critical: {
    badge: "bg-[#f0b8a8] text-[#7b3528]",
    label: "Critical",
    icon: TriangleAlert,
  },
  warning: {
    badge: "bg-[#f5d66f] text-[#66500f]",
    label: "Warning",
    icon: CircleAlert,
  },
  opportunity: {
    badge: "bg-[#c9e7ff] text-[#1c4f73]",
    label: "Opportunity",
    icon: Lightbulb,
  },
  positive: {
    badge: "bg-[#dff6c7] text-[#315d31]",
    label: "Positive",
    icon: CheckCircle2,
  },
  informational: {
    badge: "bg-[#eef1ec] text-[#4d5a53]",
    label: "Info",
    icon: Info,
  },
};

export default function RecommendationsPage() {
  const router = useRouter();
  const [initializing, setInitializing] = useState(true);
  const [recommendations, setRecommendations] = useState<
    Recommendation[] | null
  >(null);
  const [error, setError] = useState<string | null>(null);

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

        try {
          const result = await api.getRecommendations(id);
          setRecommendations(result.recommendations);
        } catch {
          setError(
            "Couldn't load your recommendations just now. Please try again."
          );
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

  if (initializing) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f5f1e8]">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#167c5a] border-t-transparent" />
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#f5f1e8] text-[#14241e]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[900px]">
          <Reveal>
            <header className="border-b border-[#14241e]/10 pb-6">
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
                <Sparkles className="h-3.5 w-3.5" />
                For you
              </p>

              <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
                What should I do next?
              </h1>

              <p className="mt-3 max-w-2xl text-sm leading-6 text-[#66746e]">
                Deterministic priorities from your real accounts, goals,
                budgets, and forecasts -- ranked by how much they matter.
              </p>
            </header>
          </Reveal>

          <div className="mt-8">
            {error && (
              <p
                role="alert"
                className="rounded-2xl border border-[#a64b3d]/20 bg-[#f8e6e1] px-4 py-3 text-sm font-medium text-[#a64b3d]"
              >
                {error}
              </p>
            )}

            {!error && recommendations !== null && recommendations.length === 0 && (
              <Reveal>
                <div
                  data-testid="recommendations-empty"
                  className="rounded-[26px] border border-[#14241e]/10 bg-white px-6 py-10 text-center shadow-[0_14px_40px_rgba(20,36,30,0.06)]"
                >
                  <CheckCircle2 className="mx-auto h-8 w-8 text-[#167c5a]" />
                  <p className="mt-3 text-lg font-semibold tracking-[-0.02em]">
                    You&rsquo;re all caught up
                  </p>
                  <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-[#66746e]">
                    Nothing needs your attention right now. Check back as
                    your accounts, goals, and spending change.
                  </p>
                </div>
              </Reveal>
            )}

            {!error && recommendations !== null && recommendations.length > 0 && (
              <Stagger className="space-y-4">
                {recommendations.map((recommendation) => (
                  <RecommendationCard
                    key={recommendation.id}
                    recommendation={recommendation}
                    onAction={() => {
                      if (recommendation.deep_link) {
                        router.push(recommendation.deep_link);
                      }
                    }}
                  />
                ))}
              </Stagger>
            )}
          </div>
        </PageReveal>
      </div>
    </main>
  );
}

function RecommendationCard({
  recommendation,
  onAction,
}: {
  recommendation: Recommendation;
  onAction: () => void;
}) {
  const style = SEVERITY_STYLES[recommendation.severity];
  const Icon = style.icon;

  return (
    <Reveal>
      <article
        data-testid="recommendation-card"
        className="rounded-[26px] border border-[#14241e]/10 bg-white p-5 shadow-[0_14px_40px_rgba(20,36,30,0.07)] sm:p-6"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.1em] ${style.badge}`}
          >
            <Icon className="h-3.5 w-3.5" />
            {style.label}
          </span>

          {recommendation.impact && (
            <span className="inline-flex items-center rounded-full bg-[#eef1ec] px-3 py-1 text-[11px] font-semibold text-[#4d5a53]">
              {recommendation.impact}
            </span>
          )}

          {recommendation.confidence !== null && (
            <span className="inline-flex items-center rounded-full bg-[#eef1ec] px-3 py-1 text-[11px] font-semibold text-[#4d5a53]">
              {Math.round(recommendation.confidence)}% confidence
            </span>
          )}
        </div>

        <h2 className="mt-3 text-lg font-semibold tracking-[-0.02em] text-[#182b23]">
          {recommendation.title}
        </h2>

        <p className="mt-1.5 text-sm leading-6 text-[#3d4a44]">
          {recommendation.summary}
        </p>

        <div className="mt-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8a978f]">
            Why
          </p>
          <p className="mt-1 text-sm leading-6 text-[#3d4a44]">
            {recommendation.why}
          </p>
        </div>

        {recommendation.source_signals.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2.5">
            {recommendation.source_signals.map((signal) => (
              <div
                key={signal.label}
                className="rounded-2xl bg-[#f7fbf5] px-3.5 py-2.5"
              >
                <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8a978f]">
                  {signal.label}
                </p>
                <p className="mt-0.5 text-base font-semibold tracking-[-0.02em] text-[#182b23]">
                  {signal.value_display}
                </p>
              </div>
            ))}
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-[#14241e]/8 pt-4">
          <p className="text-sm leading-6 text-[#3d4a44]">
            {recommendation.recommended_action}
          </p>

          {recommendation.deep_link && (
            <button
              type="button"
              onClick={onAction}
              className="focus-ring inline-flex shrink-0 items-center gap-1.5 rounded-full border border-[#167c5a]/25 bg-[#f7fbf5] px-3.5 py-1.5 text-xs font-semibold text-[#167c5a] transition hover:bg-[#dff6c7]"
            >
              Review
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </article>
    </Reveal>
  );
}
