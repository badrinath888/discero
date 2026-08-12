"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import {
  CircleHelp,
  MessageCircle,
  Send,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import {
  HoverLift,
  PageReveal,
  Reveal,
  Stagger,
} from "../components/PremiumMotion";
import {
  api,
  CopilotMessage,
  CopilotMetric,
  CopilotResponse,
  SavingsGoal,
  session,
} from "../lib/api";

type ChatTurn =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "assistant"; response: CopilotResponse };

let turnCounter = 0;

function nextTurnId(): string {
  turnCounter += 1;
  return `turn-${turnCounter}`;
}

function buildSuggestedPrompts(goals: SavingsGoal[]): string[] {
  const prompts: string[] = ["What's my safe to spend right now?"];

  const activeGoal = goals.find(
    (goal) => goal.saved_cents < goal.target_cents
  );

  if (activeGoal) {
    prompts.push(`How's my ${activeGoal.name} goal tracking?`);
  }

  prompts.push("Can I afford a $2,000 purchase?");
  prompts.push("Run a stress test for a 20% income loss");

  if (prompts.length < 4) {
    prompts.push("How am I doing on cash flow this month?");
  }

  return prompts.slice(0, 4);
}

function assistantHistoryText(response: CopilotResponse): string {
  return (
    response.answer ||
    response.clarifying_question ||
    "(no response)"
  );
}

const NEAR_BOTTOM_THRESHOLD_PX = 120;

function isNearBottom(threadEl: HTMLDivElement | null): boolean {
  if (threadEl && threadEl.scrollHeight > threadEl.clientHeight + 1) {
    const distance =
      threadEl.scrollHeight - threadEl.scrollTop - threadEl.clientHeight;
    return distance < NEAR_BOTTOM_THRESHOLD_PX;
  }

  if (typeof window === "undefined") return true;

  const doc = document.documentElement;
  const distance = doc.scrollHeight - window.scrollY - window.innerHeight;
  return distance < NEAR_BOTTOM_THRESHOLD_PX;
}

export default function CopilotPage() {
  const router = useRouter();
  const [userId, setUserId] = useState<number | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [goals, setGoals] = useState<SavingsGoal[]>([]);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [history, setHistory] = useState<CopilotMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Passive tracking: is the user currently near the bottom (used only
  // when no request is actively being followed).
  const shouldAutoScrollRef = useRef(true);
  // Active tracking: "follow this request until its terminal response
  // has rendered." Set on submit, released once the response (or
  // error) for that request has been scrolled into view. While true,
  // scrolling is unconditional -- this is what stops the passive
  // near-bottom tracker (which is itself perturbed by scrollIntoView's
  // own scroll events) from ever cancelling a request already in
  // flight.
  const forceFollowRef = useRef(false);

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
          setGoals(await api.getSavingsGoals(id));
        } catch {
          // Suggested prompts just fall back to generic ones.
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

  // The thread may or may not be the actual scrolling element -- it
  // depends on viewport height vs. content height. Rather than assume
  // one or the other, track "near bottom" against whichever container
  // is actually scrollable, and always scroll a sentinel at the end of
  // the thread into view (works correctly regardless of which ancestor
  // ends up owning the scroll).
  useEffect(() => {
    // threadRef isn't attached to the real thread element until the
    // auth-guard's `initializing` spinner clears and the chat layout
    // mounts, so this must re-run once that happens rather than only
    // on initial mount (when threadRef.current would still be null).
    if (initializing) return;

    function updateAutoScrollIntent() {
      shouldAutoScrollRef.current = isNearBottom(threadRef.current);
    }

    const el = threadRef.current;
    el?.addEventListener("scroll", updateAutoScrollIntent, {
      passive: true,
    });
    window.addEventListener("scroll", updateAutoScrollIntent, {
      passive: true,
    });

    return () => {
      el?.removeEventListener("scroll", updateAutoScrollIntent);
      window.removeEventListener("scroll", updateAutoScrollIntent);
    };
  }, [initializing]);

  useEffect(() => {
    if (forceFollowRef.current || shouldAutoScrollRef.current) {
      bottomRef.current?.scrollIntoView?.({
        behavior: "smooth",
        block: "end",
      });
    }

    // `sending` only transitions back to false once the request's
    // terminal turn (success or error) has already been appended in
    // this same batched update, so this is exactly the render where
    // that turn's scroll (above) has just been issued -- safe to
    // release force-follow so a manual scroll afterward is respected.
    if (!sending) {
      forceFollowRef.current = false;
    }
  }, [turns, sending, error]);

  async function sendMessage(rawText: string) {
    const text = rawText.trim();

    if (!text || sending || userId === null) return;

    const nextHistory: CopilotMessage[] = [
      ...history,
      { role: "user", content: text },
    ];

    // Sending a message always brings the conversation back to the
    // newest content and follows it through the whole request
    // lifecycle, even if the user had scrolled up to read earlier
    // turns or scrolls during the request.
    forceFollowRef.current = true;

    setTurns((prev) => [
      ...prev,
      { id: nextTurnId(), role: "user", content: text },
    ]);
    setHistory(nextHistory);
    setInput("");
    setSending(true);
    setError(null);

    try {
      const response = await api.sendCopilotChat(userId, nextHistory);

      setTurns((prev) => [
        ...prev,
        { id: nextTurnId(), role: "assistant", response },
      ]);
      setHistory((prev) => [
        ...prev,
        { role: "assistant", content: assistantHistoryText(response) },
      ]);
    } catch {
      setError(
        "Ask Discero couldn't respond just now. Please try again."
      );
    } finally {
      setSending(false);
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void sendMessage(input);
  }

  if (initializing) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#F5F1EA]">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#6E4B63] border-t-transparent" />
      </main>
    );
  }

  const suggestedPrompts = buildSuggestedPrompts(goals);

  return (
    <main className="min-h-screen bg-[#F5F1EA] text-[#181713]">
      <AppSidebar />

      <div className="flex min-h-screen flex-col px-4 pb-6 pt-20 sm:px-8 lg:ml-56 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto flex w-full max-w-[880px] flex-1 flex-col">
          <Reveal>
            <header className="border-b border-[#181713]/10 pb-7">
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">
                <MessageCircle className="h-3.5 w-3.5" />
                Ask Discero
              </p>

              <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
                Ask a financial question.
              </h1>

              <p className="mt-3 max-w-2xl text-sm leading-6 text-[#706961]">
                See what it means for your cash, goals, obligations, and resilience.
              </p>
            </header>
          </Reveal>

          <div
            ref={threadRef}
            data-testid="copilot-thread"
            className="mt-6 flex-1 space-y-5 overflow-y-auto pb-24"
          >
            {turns.length === 0 && (
              <EmptyPrompts
                prompts={suggestedPrompts}
                onSelect={sendMessage}
              />
            )}

            {turns.map((turn) =>
              turn.role === "user" ? (
                <UserBubble key={turn.id} content={turn.content} />
              ) : (
                <AssistantCard
                  key={turn.id}
                  response={turn.response}
                  onSuggestedAction={sendMessage}
                />
              )
            )}

            {sending && <ThinkingIndicator />}

            {/* scroll-mb reserves clearance above the floating sticky
                composer so the last card and its action buttons land
                fully visible when scrolled into view. */}
            <div
              ref={bottomRef}
              data-testid="copilot-thread-bottom"
              className="h-px scroll-mb-24"
              aria-hidden="true"
            />
          </div>

          {error && (
            <p
              role="alert"
              className="mb-3 text-sm font-medium text-[#a64b3d]"
            >
              {error}
            </p>
          )}

          <form
            onSubmit={handleSubmit}
            className="sticky bottom-4 flex items-end gap-3 rounded-[26px] border border-[#181713]/10 bg-white p-3 shadow-[0_18px_50px_rgba(60,43,35,0.1)]"
          >
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendMessage(input);
                }
              }}
              placeholder="Ask about your safe-to-spend, a purchase, or a goal..."
              rows={1}
              disabled={sending}
              aria-label="Message"
              className="max-h-32 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-[#9aa79f]"
            />

            <button
              type="submit"
              disabled={sending || !input.trim()}
              aria-label="Send message"
              className="discero-button-primary flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl transition"
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </PageReveal>
      </div>
    </main>
  );
}

function EmptyPrompts({
  prompts,
  onSelect,
}: {
  prompts: string[];
  onSelect: (text: string) => void;
}) {
  return (
    <section>
      <p className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-[#8A8178]">Suggested questions</p>
      <Stagger className="grid gap-px overflow-hidden border-y border-[#181713]/10 bg-[#181713]/10 sm:grid-cols-2">
        {prompts.map((prompt) => (
          <Reveal key={prompt}>
            <HoverLift>
              <button
                type="button"
                onClick={() => onSelect(prompt)}
                className="focus-ring flex w-full items-start gap-3 bg-[#FFFCF7] px-5 py-4 text-left text-sm font-medium text-[#2F2930] transition hover:bg-[#F8F4EE]"
              >
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-[#B86D4B]" />
                {prompt}
              </button>
            </HoverLift>
          </Reveal>
        ))}
      </Stagger>
    </section>
  );
}

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[75%] rounded-2xl bg-[#183028] px-4 py-2.5 text-sm leading-6 text-white">
        {content}
      </p>
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Discero analysis is in progress"
      className="w-full border-y border-[#181713]/10 bg-[#FFFCF7] px-5 py-5"
    >
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">Analyzing your question</p>
      <div className="mt-4 grid gap-3 text-sm text-[#706961] sm:grid-cols-3">
        <span>01 · Reading your position</span>
        <span>02 · Checking obligations</span>
        <span>03 · Preparing the consequence</span>
      </div>
    </div>
  );
}

function AssistantCard({
  response,
  onSuggestedAction,
}: {
  response: CopilotResponse;
  onSuggestedAction: (text: string) => void;
}) {
  if (response.kind === "unavailable" || response.kind === "out_of_scope") {
    return (
      <Reveal>
        <div className="rounded-[22px] border border-[#181713]/10 bg-white px-5 py-4 text-sm leading-6 text-[#5F5751] shadow-[0_10px_30px_rgba(60,43,35,0.05)]">
          {response.answer}
        </div>
      </Reveal>
    );
  }

  if (response.kind === "clarifying_question") {
    return (
      <Reveal>
        <div className="rounded-[22px] border border-[#6E4B63]/30 bg-[#f2f9f0] px-5 py-4 shadow-[0_10px_30px_rgba(60,43,35,0.06)]">
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-[#6E4B63]">
            <CircleHelp className="h-3.5 w-3.5" />
            Quick question
          </p>

          <p className="mt-2 text-sm font-medium leading-6 text-[#2F2930]">
            {response.clarifying_question}
          </p>

          {response.clarifying_options &&
            response.clarifying_options.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {response.clarifying_options.map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => onSuggestedAction(option)}
                    className="focus-ring rounded-full border border-[#6E4B63]/30 bg-white px-3.5 py-1.5 text-xs font-semibold text-[#6E4B63] transition hover:bg-[#EDE5DE]"
                  >
                    {option}
                  </button>
                ))}
              </div>
            )}
        </div>
      </Reveal>
    );
  }

  return (
    <Reveal>
      <article className="border-y border-[#181713]/10 bg-[#FFFCF7] p-5 sm:p-7">
        <div className="flex flex-wrap items-center gap-2">
          {response.tool_used && (
            <p className="inline-flex items-center gap-1.5 border-l-2 border-[#B86D4B] pl-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">
              {response.tool_used}
            </p>
          )}
          <ProvenanceBadge provenance={response.provenance} />
        </div>

        <p className="mt-3 text-[15px] font-medium leading-7 text-[#2F2930]">
          {response.answer}
        </p>

        {response.low_data_warning && (
          <p className="mt-2 flex items-start gap-1.5 text-xs leading-5 text-[#8a6a1f]">
            <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {response.low_data_warning}
          </p>
        )}

        {response.key_numbers.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2.5">
            {response.key_numbers.map((metric) => (
              <MetricChip key={metric.label} metric={metric} />
            ))}
          </div>
        )}

        {response.why && <Section label="Why" text={response.why} />}

        {response.what_this_means && (
          <Section
            label="What this means"
            text={response.what_this_means}
          />
        )}

        {response.suggested_actions.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2 border-t border-[#181713]/8 pt-4">
            {response.suggested_actions.map((action) => (
              <button
                key={action}
                type="button"
                onClick={() => onSuggestedAction(action)}
                className="focus-ring rounded-full border border-[#6E4B63]/25 bg-[#F8F4EE] px-3.5 py-1.5 text-xs font-semibold text-[#6E4B63] transition hover:bg-[#EDE5DE]"
              >
                {action}
              </button>
            ))}
          </div>
        )}
      </article>
    </Reveal>
  );
}

function ProvenanceBadge({
  provenance,
}: {
  provenance: CopilotResponse["provenance"];
}) {
  const label =
    provenance === "ai_enhanced"
      ? "AI-enhanced Discero analysis"
      : "Discero analysis";

  return (
    <p className="inline-flex items-center gap-1.5 text-[11px] font-medium text-[#8a978f]">
      <span className="h-1.5 w-1.5 rounded-full bg-[#a9b8b0]" />
      {label}
    </p>
  );
}

function Section({ label, text }: { label: string; text: string }) {
  return (
    <div className="mt-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8a978f]">
        {label}
      </p>
      <p className="mt-1.5 text-sm leading-6 text-[#514B46]">{text}</p>
    </div>
  );
}

const TONE_STYLES: Record<CopilotMetric["tone"], string> = {
  positive: "bg-[#E3EBE1] text-[#48634B]",
  warning: "bg-[#FBF1DF] text-[#8A5A20]",
  danger: "bg-[#F8E6E1] text-[#8F3F33]",
  neutral: "bg-[#eef1ec] text-[#5F5751]",
};

function MetricChip({ metric }: { metric: CopilotMetric }) {
  return (
    <div
      className={`rounded-2xl px-3.5 py-2.5 ${TONE_STYLES[metric.tone]}`}
    >
      <p className="text-[10px] font-semibold uppercase tracking-[0.1em] opacity-70">
        {metric.label}
      </p>
      <p className="mt-0.5 text-base font-semibold tracking-[-0.02em]">
        {metric.value_display}
      </p>
    </div>
  );
}
