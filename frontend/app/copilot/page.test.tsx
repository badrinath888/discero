import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CopilotResponse, SavingsGoal } from "../lib/api";
import CopilotPage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  getMe: vi.fn(),
  getSavingsGoals: vi.fn(),
  sendCopilotChat: vi.fn(),
  getUserId: vi.fn(),
  getToken: vi.fn(),
  clearSession: vi.fn(),
}));

const routerMock = { replace: mocks.replace, push: vi.fn() };

vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
}));

vi.mock("framer-motion", async () => {
  const { createElement } = await import("react");
  const ignored = new Set([
    "animate",
    "exit",
    "initial",
    "layout",
    "transition",
    "whileHover",
    "whileInView",
    "viewport",
    "variants",
  ]);
  const motion = new Proxy(
    {},
    {
      get: (_target, tag: string) =>
        ({ children, ...props }: Record<string, unknown>) =>
          createElement(
            tag,
            Object.fromEntries(
              Object.entries(props).filter(([name]) => !ignored.has(name))
            ),
            children as ReactNode
          ),
    }
  );

  return {
    AnimatePresence: ({ children }: { children: ReactNode }) => children,
    motion,
    useInView: () => true,
    useMotionValue: (value: number) => ({ set: vi.fn(), get: () => value }),
    useTransform: (value: unknown, fn: (v: number) => string) => fn(0),
    animate: () => ({ stop: vi.fn() }),
    useReducedMotion: () => true,
  };
});

vi.mock("../components/AppSidebar", () => ({
  default: () => null,
}));

vi.mock("../components/PremiumMotion", () => ({
  PageReveal: ({ children }: { children: ReactNode }) => children,
  Reveal: ({ children }: { children: ReactNode }) => children,
  Stagger: ({ children }: { children: ReactNode }) => children,
  HoverLift: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();

  return {
    ...actual,
    api: {
      ...actual.api,
      getMe: mocks.getMe,
      getSavingsGoals: mocks.getSavingsGoals,
      sendCopilotChat: mocks.sendCopilotChat,
    },
    session: {
      ...actual.session,
      getUserId: mocks.getUserId,
      getToken: mocks.getToken,
      clear: mocks.clearSession,
    },
  };
});

const activeGoal: SavingsGoal = {
  id: 1,
  name: "Emergency Fund",
  target_cents: 500_000,
  saved_cents: 100_000,
  remaining_cents: 400_000,
  progress_percent: 20,
  target_date: "2026-12-31",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const answerResponse: CopilotResponse = {
  kind: "answer",
  answer: "You have $5,000.00 safe to spend.",
  why: "Your liquid balance comfortably covers upcoming obligations.",
  what_this_means: "You can spend freely this month.",
  key_numbers: [
    {
      label: "Safe to spend",
      value_display: "$5,000.00",
      kind: "currency",
      tone: "positive",
    },
  ],
  suggested_actions: ["Run a stress test"],
  clarifying_question: null,
  clarifying_options: null,
  tool_used: "Safe-to-Spend",
  confidence: { score: 88, level: "high" },
  low_data_warning: null,
  provenance: "ai_enhanced",
};

const freeModeAnswerResponse: CopilotResponse = {
  ...answerResponse,
  provenance: "deterministic",
};

const clarifyingResponse: CopilotResponse = {
  kind: "clarifying_question",
  answer: null,
  why: null,
  what_this_means: null,
  key_numbers: [],
  suggested_actions: [],
  clarifying_question: "What amount are you considering?",
  clarifying_options: ["$1,000", "$2,000"],
  tool_used: null,
  confidence: null,
  low_data_warning: null,
  provenance: "deterministic",
};

const outOfScopeResponse: CopilotResponse = {
  kind: "out_of_scope",
  answer: "I can only help with your Discero finances.",
  why: null,
  what_this_means: null,
  key_numbers: [],
  suggested_actions: [],
  clarifying_question: null,
  clarifying_options: null,
  tool_used: null,
  confidence: null,
  low_data_warning: null,
  provenance: "deterministic",
};

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** Simulates the thread container being scrolled away from the bottom. */
function scrollThreadAwayFromBottom() {
  const thread = screen.getByTestId("copilot-thread");
  Object.defineProperty(thread, "scrollHeight", { value: 2000, configurable: true });
  Object.defineProperty(thread, "clientHeight", { value: 400, configurable: true });
  Object.defineProperty(thread, "scrollTop", { value: 0, configurable: true });
  fireEvent.scroll(thread);
}

beforeEach(() => {
  mocks.getUserId.mockReturnValue(1);
  mocks.getToken.mockReturnValue("test-token");
  mocks.getMe.mockResolvedValue({
    id: 1,
    email: "user@example.com",
    email_verified: true,
  });
  mocks.getSavingsGoals.mockResolvedValue([activeGoal]);
  mocks.sendCopilotChat.mockReset();
  HTMLElement.prototype.scrollIntoView = vi.fn();
});

describe("Copilot page", () => {
  it("shows contextual suggested prompts including a real goal name", async () => {
    render(<CopilotPage />);

    expect(
      await screen.findByText("What's my safe to spend right now?")
    ).toBeInTheDocument();
    expect(
      screen.getByText("How's my Emergency Fund goal tracking?")
    ).toBeInTheDocument();
  });

  it("sends a message, shows a thinking state, then renders an answer card with chips", async () => {
    mocks.sendCopilotChat.mockResolvedValue(answerResponse);

    render(<CopilotPage />);

    const prompt = await screen.findByText(
      "What's my safe to spend right now?"
    );
    fireEvent.click(prompt);

    expect(
      screen.getByText("What's my safe to spend right now?")
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Discero analysis is in progress")).toBeInTheDocument();

    await waitFor(() =>
      expect(
        screen.getByText("You have $5,000.00 safe to spend.")
      ).toBeInTheDocument()
    );

    expect(screen.getByText("Safe-to-Spend")).toBeInTheDocument();
    expect(screen.getByText("$5,000.00")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Your liquid balance comfortably covers upcoming obligations."
      )
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Run a stress test" })
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Discero analysis is in progress")
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("AI-enhanced Discero analysis")
    ).toBeInTheDocument();
  });

  it("renders free-mode (deterministic) responses normally, without a degraded look", async () => {
    mocks.sendCopilotChat.mockResolvedValue(freeModeAnswerResponse);

    render(<CopilotPage />);

    const prompt = await screen.findByText(
      "What's my safe to spend right now?"
    );
    fireEvent.click(prompt);

    await waitFor(() =>
      expect(
        screen.getByText("You have $5,000.00 safe to spend.")
      ).toBeInTheDocument()
    );

    expect(screen.getByText("Discero analysis")).toBeInTheDocument();
    expect(
      screen.queryByText("AI-enhanced Discero analysis")
    ).not.toBeInTheDocument();
    expect(screen.getByText("$5,000.00")).toBeInTheDocument();
    expect(screen.queryByText(/provider key/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/API key/i)).not.toBeInTheDocument();
  });

  it("renders clarifying questions with working quick-reply buttons", async () => {
    mocks.sendCopilotChat
      .mockResolvedValueOnce(clarifyingResponse)
      .mockResolvedValueOnce(answerResponse);

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");
    fireEvent.change(input, { target: { value: "Can I afford it?" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() =>
      expect(
        screen.getByText("What amount are you considering?")
      ).toBeInTheDocument()
    );

    const quickReply = screen.getByRole("button", { name: "$2,000" });
    fireEvent.click(quickReply);

    await waitFor(() =>
      expect(mocks.sendCopilotChat).toHaveBeenLastCalledWith(
        1,
        expect.arrayContaining([
          expect.objectContaining({ role: "user", content: "$2,000" }),
        ])
      )
    );
  });

  it("gracefully renders out-of-scope responses", async () => {
    mocks.sendCopilotChat.mockResolvedValue(outOfScopeResponse);

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");
    fireEvent.change(input, {
      target: { value: "What's the weather today?" },
    });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() =>
      expect(
        screen.getByText("I can only help with your Discero finances.")
      ).toBeInTheDocument()
    );
  });

  it("renders an auto-derived capacity source chip and transparency note", async () => {
    mocks.sendCopilotChat.mockResolvedValue({
      ...answerResponse,
      answer: "Emergency Fund is your most urgent goal.",
      tool_used: "Goal Intelligence",
      key_numbers: [
        {
          label: "Capacity source",
          value_display: "Estimated",
          kind: "text",
          tone: "neutral",
        },
      ],
      low_data_warning:
        "Monthly capacity ($675.11) was estimated from your recent financial data. Tell me a specific monthly amount and I'll use that instead.",
    });

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");
    fireEvent.change(input, {
      target: { value: "Which goal is most urgent?" },
    });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() =>
      expect(
        screen.getByText("Emergency Fund is your most urgent goal.")
      ).toBeInTheDocument()
    );

    expect(screen.getByText("Capacity source")).toBeInTheDocument();
    expect(screen.getByText("Estimated")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Monthly capacity ($675.11) was estimated from your recent financial data. Tell me a specific monthly amount and I'll use that instead."
      )
    ).toBeInTheDocument();
  });

  it("keeps prior turns visible across multiple exchanges", async () => {
    mocks.sendCopilotChat.mockResolvedValue(answerResponse);

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");

    fireEvent.change(input, { target: { value: "First question" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    await waitFor(() =>
      expect(
        screen.getByText("You have $5,000.00 safe to spend.")
      ).toBeInTheDocument()
    );

    fireEvent.change(input, { target: { value: "Second question" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    await waitFor(() =>
      expect(mocks.sendCopilotChat).toHaveBeenCalledTimes(2)
    );

    expect(screen.getByText("First question")).toBeInTheDocument();
    expect(screen.getByText("Second question")).toBeInTheDocument();
  });
});

describe("Copilot auto-scroll", () => {
  it("scrolls to the newest content when a message is submitted", async () => {
    const deferred = createDeferred<CopilotResponse>();
    mocks.sendCopilotChat.mockReturnValue(deferred.promise);

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");
    fireEvent.change(input, { target: { value: "Hello" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    // Submitting appends the user turn and the thinking indicator --
    // both should trigger a scroll immediately, before the response
    // arrives.
    await waitFor(() =>
      expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled()
    );

    deferred.resolve(answerResponse);
    await waitFor(() =>
      expect(
        screen.getByText("You have $5,000.00 safe to spend.")
      ).toBeInTheDocument()
    );
  });

  it("scrolls again when the assistant response arrives while near the bottom", async () => {
    const deferred = createDeferred<CopilotResponse>();
    mocks.sendCopilotChat.mockReturnValue(deferred.promise);

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");
    fireEvent.change(input, { target: { value: "Hello" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() =>
      expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled()
    );
    const callsBeforeResponse = (
      HTMLElement.prototype.scrollIntoView as ReturnType<typeof vi.fn>
    ).mock.calls.length;

    deferred.resolve(answerResponse);

    await waitFor(() =>
      expect(
        screen.getByText("You have $5,000.00 safe to spend.")
      ).toBeInTheDocument()
    );
    await waitFor(() =>
      expect(
        (HTMLElement.prototype.scrollIntoView as ReturnType<typeof vi.fn>)
          .mock.calls.length
      ).toBeGreaterThan(callsBeforeResponse)
    );
  });

  it("scrolls when a clarification card is appended", async () => {
    mocks.sendCopilotChat.mockResolvedValue(clarifyingResponse);

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");
    fireEvent.change(input, { target: { value: "Can I afford it?" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() =>
      expect(
        screen.getByText("What amount are you considering?")
      ).toBeInTheDocument()
    );
    expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("scrolls when an error response is appended", async () => {
    mocks.sendCopilotChat.mockRejectedValue(new Error("network error"));

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");
    fireEvent.change(input, { target: { value: "Hello" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() =>
      expect(
        screen.getByText(
          "I couldn't complete that just now. Your financial data wasn't changed. Please try again."
        )
      ).toBeInTheDocument()
    );
    expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("shows a distinct message when the request is rate-limited", async () => {
    mocks.sendCopilotChat.mockRejectedValue(
      new Error("too many attempts, please try again later (429 Too Many Requests)")
    );

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");
    fireEvent.change(input, { target: { value: "Hello" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() =>
      expect(
        screen.getByText(
          "You've sent a lot of questions in a short time. Please wait a moment before asking again."
        )
      ).toBeInTheDocument()
    );
  });

  it("shows a distinct message when the request times out (e.g. a cold-started backend)", async () => {
    mocks.sendCopilotChat.mockRejectedValue(
      new Error("The server took too long to respond. Please try again.")
    );

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");
    fireEvent.change(input, { target: { value: "Hello" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() =>
      expect(
        screen.getByText(
          "Discero is taking longer than usual to respond -- this can happen right after being idle. Please try again in a moment."
        )
      ).toBeInTheDocument()
    );
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it("redirects to sign-in instead of showing a generic error when the session was not recoverable", async () => {
    // api.ts's centralized 401 handling already attempted a refresh and,
    // on failure, cleared the stored token before this rejection reached
    // the page -- a cleared token is how the page recognizes this case.
    mocks.sendCopilotChat.mockImplementation(async () => {
      mocks.getToken.mockReturnValue(null);
      throw new Error("session expired; please sign in again (401)");
    });

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");
    fireEvent.change(input, { target: { value: "Hello" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/"));
    expect(
      screen.queryByText(
        "I couldn't complete that just now. Your financial data wasn't changed. Please try again."
      )
    ).not.toBeInTheDocument();
  });

  it("does not redirect for a generic network error while the session is still valid", async () => {
    mocks.sendCopilotChat.mockRejectedValue(new Error("network error"));

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");
    fireEvent.change(input, { target: { value: "Hello" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() =>
      expect(
        screen.getByText(
          "I couldn't complete that just now. Your financial data wasn't changed. Please try again."
        )
      ).toBeInTheDocument()
    );
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it("a programmatic/scroll event mid-flight does not cancel follow for the active request", async () => {
    // This is the actual production bug: scrollIntoView's own smooth
    // scroll fires "scroll" events, which previously flipped the
    // near-bottom flag to false mid-animation and silently cancelled
    // the pending response's scroll. Force-follow must be immune to
    // this for the whole lifecycle of a request the user just sent.
    const deferred = createDeferred<CopilotResponse>();
    mocks.sendCopilotChat.mockReturnValue(deferred.promise);

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");
    fireEvent.change(input, { target: { value: "Hello" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() =>
      expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled()
    );

    // Simulate a scroll event firing away-from-bottom while the
    // request is still in flight (e.g. from the smooth-scroll
    // animation itself, or the user nudging the trackpad).
    scrollThreadAwayFromBottom();
    (
      HTMLElement.prototype.scrollIntoView as ReturnType<typeof vi.fn>
    ).mockClear();

    deferred.resolve(answerResponse);

    await waitFor(() =>
      expect(
        screen.getByText("You have $5,000.00 safe to spend.")
      ).toBeInTheDocument()
    );
    // scrollIntoView is triggered from a React effect after the response
  // render, so wait for the effect rather than assuming it has already run.
    await waitFor(() =>
      expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled()
    );
  });

  it("reproduces the repeated-message bug: the second response scrolls into view", async () => {
    // Exact production reproduction: send the same message twice in a
    // row and confirm the SECOND response also triggers a scroll, not
    // just the first.
    const first = createDeferred<CopilotResponse>();
    const second = createDeferred<CopilotResponse>();
    mocks.sendCopilotChat
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");
    const prompt = "Can I afford a $2,000 laptop?";

    fireEvent.change(input, { target: { value: prompt } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    await waitFor(() =>
      expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled()
    );

    first.resolve(answerResponse);
    await waitFor(() =>
      expect(mocks.sendCopilotChat).toHaveBeenCalledTimes(1)
    );
    await screen.findAllByText("You have $5,000.00 safe to spend.");

    (
      HTMLElement.prototype.scrollIntoView as ReturnType<typeof vi.fn>
    ).mockClear();

    fireEvent.change(input, { target: { value: prompt } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    await waitFor(() =>
      expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled()
    );

    (
      HTMLElement.prototype.scrollIntoView as ReturnType<typeof vi.fn>
    ).mockClear();

    second.resolve(answerResponse);
    await waitFor(() =>
      expect(mocks.sendCopilotChat).toHaveBeenCalledTimes(2)
    );
    await waitFor(() =>
      expect(
        screen.getAllByText("You have $5,000.00 safe to spend.")
      ).toHaveLength(2)
    );

    // The SECOND response must also have triggered a scroll.
    expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("brings the view back to the newest content on the next submitted message even after scrolling up", async () => {
    mocks.sendCopilotChat.mockResolvedValue(answerResponse);

    render(<CopilotPage />);

    const input = await screen.findByLabelText("Message");
    fireEvent.change(input, { target: { value: "First question" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    await waitFor(() =>
      expect(
        screen.getByText("You have $5,000.00 safe to spend.")
      ).toBeInTheDocument()
    );

    scrollThreadAwayFromBottom();
    (
      HTMLElement.prototype.scrollIntoView as ReturnType<typeof vi.fn>
    ).mockClear();

    fireEvent.change(input, { target: { value: "Second question" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() =>
      expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled()
    );
  });

  it("reserves scroll clearance so the last card isn't hidden behind the composer", async () => {
    render(<CopilotPage />);

    const thread = await screen.findByTestId("copilot-thread");
    const sentinel = screen.getByTestId("copilot-thread-bottom");

    // Trailing padding gives the last card room to scroll above the
    // sticky composer; scroll-margin on the sentinel itself is what
    // scrollIntoView uses to land above the composer's footprint.
    expect(thread.className).toMatch(/pb-\d+/);
    expect(sentinel.className).toMatch(/scroll-mb-\d+/);
  });
});
