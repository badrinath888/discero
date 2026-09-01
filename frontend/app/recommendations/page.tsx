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
    badge: "bg-[#F8E6E1] text-[#8F3F33]",
    label: "Critical",
    icon: TriangleAlert,
  },
  warning: {
    badge: "bg-[#FBF1DF] text-[#8A5A20]",
    label: "Warning",
    icon: CircleAlert,
  },
  opportunity: {
    badge: "bg-[#EDE5DE] text-[#6E4B63]",
    label: "Opportunity",
    icon: Lightbulb,
  },
  positive: {
    badge: "bg-[#E3EBE1] text-[#48634B]",
    label: "Positive",
    icon: CheckCircle2,
  },
  informational: {
    badge: "bg-[#EDE7E1] text-[#5F5751]",
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
      <main className="flex min-h-screen items-center justify-center bg-[#F5F1EA]">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#6E4B63] border-t-transparent" />
      </main>
    );
  }

  const attentionCount = recommendations?.filter((item) =>
    ["critical", "warning"].includes(item.severity)
  ).length ?? 0;
  const healthyCount = recommendations?.filter((item) =>
    ["positive", "informational"].includes(item.severity)
  ).length ?? 0;

  return (
    <main className="min-h-screen bg-[#F5F1EA] text-[#181713]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-56 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto w-full max-w-[1500px]">
          <Reveal>
            <header className="border-b border-[#181713]/10 pb-5">
              <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
                <Sparkles className="h-3.5 w-3.5" />
                Next moves
              </p>

              <h1 className="mt-1 text-[32px] font-semibold tracking-[-0.03em]">
                Recommendations
              </h1>

              <p className="mt-1 text-sm text-[#706961]">
                Actions worth considering now.
              </p>
            </header>
          </Reveal>

          {!error && recommendations && recommendations.length > 0 && (
            <Reveal delay={0.05}>
              <section aria-label="Recommendation summary" className="mt-6 flex flex-col gap-5 border-y border-[#181713]/10 bg-[#FFFCF7] px-5 py-5 sm:flex-row sm:items-center sm:gap-0 sm:px-6">
                <div className="sm:w-40 sm:border-r sm:border-[#181713]/10 sm:pr-6">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8A8178]">Needs attention</p>
                  <p className="mt-1 text-xl font-semibold tabular-nums text-[#A25543]">{attentionCount}</p>
                </div>
                <div className="sm:w-44 sm:border-r sm:border-[#181713]/10 sm:px-6">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8A8178]">Healthy signals</p>
                  <p className="mt-1 text-xl font-semibold tabular-nums text-[#58715A]">{healthyCount}</p>
                </div>
                <div className="sm:min-w-0 sm:flex-1 sm:pl-6">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8A8178]">Highest priority</p>
                  <p className="mt-1 text-sm font-semibold capitalize leading-6 text-[#2F2930]">{SEVERITY_STYLES[recommendations[0].severity].label} · {recommendations[0].category}</p>
                </div>
              </section>
            </Reveal>
          )}

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
                  className="rounded-[26px] border border-[#181713]/10 bg-white px-6 py-10 text-center shadow-[0_14px_40px_rgba(60,43,35,0.06)]"
                >
                  <CheckCircle2 className="mx-auto h-8 w-8 text-[#6E4B63]" />
                  <p className="mt-3 text-lg font-semibold tracking-[-0.02em]">
                    You&rsquo;re all caught up
                  </p>
                  <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-[#706961]">
                    Nothing needs your attention right now. Check back as
                    your accounts, goals, and spending change.
                  </p>
                </div>
              </Reveal>
            )}

            {!error && recommendations !== null && recommendations.length > 0 && (
              <Stagger className="space-y-3">
                {recommendations.map((recommendation, index) => (
                  <RecommendationCard
                    key={recommendation.id}
                    recommendation={recommendation}
                    featured={index === 0}
                    rank={index + 1}
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
  featured,
  rank,
  onAction,
}: {
  recommendation: Recommendation;
  featured: boolean;
  rank: number;
  onAction: () => void;
}) {
  const style = SEVERITY_STYLES[recommendation.severity];
  const Icon = style.icon;

  return (
    <Reveal>
      <article
        data-testid="recommendation-card"
        className={
          featured
            ? "border-l-2 border-[#C89A78] bg-[#FFFCF7] px-5 py-7 sm:px-7 sm:py-8"
            : "bg-[#FFFCF7]/55 px-5 py-5 sm:px-7"
        }
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="text-lg font-semibold tabular-nums text-[#2F2930]">
            {String(rank).padStart(2, "0")}
          </span>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.1em] ${style.badge}`}
          >
            <Icon className="h-3.5 w-3.5" />
            {style.label}
          </span>

          {recommendation.confidence !== null && (
            <span className="text-[11px] font-semibold text-[#706961]">
              {Math.round(recommendation.confidence)}% confidence
            </span>
          )}
        </div>

        <h2 className={`${featured ? "text-2xl sm:text-3xl" : "text-lg"} mt-3 font-semibold tracking-[-0.02em] text-[#2F2930]`}>
          {recommendation.title}
        </h2>

        {recommendation.impact && (
          <p className={`${featured ? "text-xl" : "text-base"} mt-2 font-semibold tracking-[-0.02em] text-[#6E4B63]`}>
            {recommendation.impact}
          </p>
        )}

        <div className={`${featured ? "mt-5" : "mt-4"} flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between`}>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#8A8178]">
              Recommended action
            </p>
            <p className="mt-1 text-sm font-medium leading-6 text-[#2F2930]">
              {recommendation.recommended_action}
            </p>
          </div>

          {recommendation.deep_link && (
            <button
              type="button"
              onClick={onAction}
              className="discero-button-tertiary inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-lg px-2 text-xs font-semibold transition"
            >
              Review
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        <p className="mt-4 max-w-2xl text-sm leading-6 text-[#514B46]">
          {recommendation.summary}
        </p>

        {recommendation.why.trim() !== recommendation.summary.trim() && (
          <details className="mt-3 text-sm text-[#706961]">
            <summary className="cursor-pointer text-xs font-semibold text-[#706961]">
              Supporting detail
            </summary>
            <p className="mt-2 max-w-2xl leading-6">{recommendation.why}</p>
          </details>
        )}

        {recommendation.source_signals.length > 0 && (
          <dl className="mt-4 flex flex-wrap gap-y-3 text-sm">
            {recommendation.source_signals.map((signal, index) => (
              <div
                key={signal.label}
                className={`${index > 0 ? "ml-4 border-l border-[#181713]/10 pl-4" : ""}`}
              >
                <dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8A8178]">
                  {signal.label}
                </dt>
                <dd className="mt-0.5 font-semibold tracking-[-0.01em] text-[#2F2930]">
                  {signal.value_display}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </article>
    </Reveal>
  );
}
