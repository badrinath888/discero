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

  useEffect(() => {
    threadRef.current?.scrollTo?.({
      top: threadRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [turns, sending]);

  async function sendMessage(rawText: string) {
    const text = rawText.trim();

    if (!text || sending || userId === null) return;

    const nextHistory: CopilotMessage[] = [
      ...history,
      { role: "user", content: text },
    ];

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
        "The Copilot couldn't respond just now. Please try again."
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
      <main className="flex min-h-screen items-center justify-center bg-[#f5f1e8]">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#167c5a] border-t-transparent" />
      </main>
    );
  }

  const suggestedPrompts = buildSuggestedPrompts(goals);

  return (
    <main className="min-h-screen bg-[#f5f1e8] text-[#14241e]">
      <AppSidebar />

      <div className="flex min-h-screen flex-col px-4 pb-6 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto flex w-full max-w-[880px] flex-1 flex-col">
          <Reveal>
            <header className="border-b border-[#14241e]/10 pb-6">
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
                <MessageCircle className="h-3.5 w-3.5" />
                Copilot
              </p>

              <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
                Ask FinSight anything
              </h1>

              <p className="mt-3 max-w-2xl text-sm leading-6 text-[#66746e]">
                Answers are grounded in your real accounts, goals, and
                forecasts -- never guessed.
              </p>
            </header>
          </Reveal>

          <div
            ref={threadRef}
            data-testid="copilot-thread"
            className="mt-6 flex-1 space-y-5 overflow-y-auto pb-4"
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
            className="sticky bottom-4 flex items-end gap-3 rounded-[26px] border border-[#14241e]/10 bg-white p-3 shadow-[0_18px_50px_rgba(20,36,30,0.1)]"
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
              className="focus-ring flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-[#167c5a] text-white transition hover:bg-[#0f6448] disabled:opacity-40"
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
    <Stagger className="grid gap-3 sm:grid-cols-2">
      {prompts.map((prompt) => (
        <Reveal key={prompt}>
          <HoverLift>
            <button
              type="button"
              onClick={() => onSelect(prompt)}
              className="focus-ring flex w-full items-start gap-3 rounded-2xl border border-[#14241e]/10 bg-white px-4 py-3.5 text-left text-sm font-medium text-[#26382f] shadow-[0_10px_30px_rgba(20,36,30,0.05)] transition hover:border-[#167c5a]/30 hover:bg-[#f7fbf5]"
            >
              <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-[#167c5a]" />
              {prompt}
            </button>
          </HoverLift>
        </Reveal>
      ))}
    </Stagger>
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
      aria-label="Copilot is thinking"
      className="flex w-fit items-center gap-2 rounded-[22px] border border-[#14241e]/8 bg-white px-5 py-4 shadow-[0_10px_30px_rgba(20,36,30,0.05)]"
    >
      <span className="h-2 w-2 animate-bounce rounded-full bg-[#167c5a] [animation-delay:-0.3s]" />
      <span className="h-2 w-2 animate-bounce rounded-full bg-[#167c5a] [animation-delay:-0.15s]" />
      <span className="h-2 w-2 animate-bounce rounded-full bg-[#167c5a]" />
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
        <div className="rounded-[22px] border border-[#14241e]/10 bg-white px-5 py-4 text-sm leading-6 text-[#4d5a53] shadow-[0_10px_30px_rgba(20,36,30,0.05)]">
          {response.answer}
        </div>
      </Reveal>
    );
  }

  if (response.kind === "clarifying_question") {
    return (
      <Reveal>
        <div className="rounded-[22px] border border-[#167c5a]/30 bg-[#f2f9f0] px-5 py-4 shadow-[0_10px_30px_rgba(20,36,30,0.06)]">
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-[#167c5a]">
            <CircleHelp className="h-3.5 w-3.5" />
            Quick question
          </p>

          <p className="mt-2 text-sm font-medium leading-6 text-[#1c2e26]">
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
                    className="focus-ring rounded-full border border-[#167c5a]/30 bg-white px-3.5 py-1.5 text-xs font-semibold text-[#167c5a] transition hover:bg-[#dff6c7]"
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
      <article className="rounded-[26px] border border-[#14241e]/10 bg-white p-5 shadow-[0_14px_40px_rgba(20,36,30,0.07)] sm:p-6">
        {response.tool_used && (
          <p className="inline-flex items-center gap-1.5 rounded-full bg-[#dff6c7] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-[#167c5a]">
            {response.tool_used}
          </p>
        )}

        <p className="mt-3 text-[15px] font-medium leading-7 text-[#182b23]">
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
          <div className="mt-4 flex flex-wrap gap-2 border-t border-[#14241e]/8 pt-4">
            {response.suggested_actions.map((action) => (
              <button
                key={action}
                type="button"
                onClick={() => onSuggestedAction(action)}
                className="focus-ring rounded-full border border-[#167c5a]/25 bg-[#f7fbf5] px-3.5 py-1.5 text-xs font-semibold text-[#167c5a] transition hover:bg-[#dff6c7]"
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

function Section({ label, text }: { label: string; text: string }) {
  return (
    <div className="mt-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8a978f]">
        {label}
      </p>
      <p className="mt-1.5 text-sm leading-6 text-[#3d4a44]">{text}</p>
    </div>
  );
}

const TONE_STYLES: Record<CopilotMetric["tone"], string> = {
  positive: "bg-[#dff6c7] text-[#315d31]",
  warning: "bg-[#f5d66f] text-[#66500f]",
  danger: "bg-[#f0b8a8] text-[#7b3528]",
  neutral: "bg-[#eef1ec] text-[#4d5a53]",
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
