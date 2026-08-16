import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, COPILOT_REQUEST_TIMEOUT_MS } from "./api";

const TOKEN_KEY = "accessToken";

function jsonResponse(
  status: number,
  body: unknown,
  ok = status >= 200 && status < 300,
  headers: Record<string, string> = {}
): Response {
  return {
    ok,
    status,
    statusText: "",
    headers: new Headers(headers),
    json: async () => body,
  } as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem(TOKEN_KEY, "test-token");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("copilot chat request timeout", () => {
  it("does not abort a copilot request that is still pending past the default 15s window", async () => {
    vi.useFakeTimers();

    let capturedSignal: AbortSignal | undefined;
    fetchMock.mockImplementation(
      (_input: RequestInfo, init?: RequestInit) => {
        capturedSignal = init?.signal ?? undefined;
        return new Promise<Response>(() => {
          // Never resolves -- only the abort (or lack of it) matters here.
        });
      }
    );

    void api.sendCopilotChat(1, [{ role: "user", content: "hi" }]);
    await vi.advanceTimersByTimeAsync(0);

    // Past the generic 15s REQUEST_TIMEOUT_MS other endpoints use.
    await vi.advanceTimersByTimeAsync(20_000);

    expect(capturedSignal?.aborted).toBe(false);
  });

  it("still aborts a copilot request once the copilot-specific window elapses", async () => {
    vi.useFakeTimers();

    let capturedSignal: AbortSignal | undefined;
    fetchMock.mockImplementation(
      (_input: RequestInfo, init?: RequestInit) => {
        capturedSignal = init?.signal ?? undefined;
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("aborted", "AbortError"));
          });
        });
      }
    );

    const promise = api.sendCopilotChat(1, [
      { role: "user", content: "hi" },
    ]);
    await vi.advanceTimersByTimeAsync(0);

    // Attach the rejection assertion before the promise actually
    // settles so it isn't briefly "unhandled" once the timer fires.
    const assertion = expect(promise).rejects.toThrow(/took too long/);

    await vi.advanceTimersByTimeAsync(COPILOT_REQUEST_TIMEOUT_MS + 1_000);

    expect(capturedSignal?.aborted).toBe(true);
    await assertion;
  });
});

describe("copilot chat failure correlation", () => {
  it("logs only bounded status + request id metadata, never prompt content", async () => {
    const consoleSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        500,
        { detail: "boom" },
        false,
        { "X-Request-Id": "req-abc123" }
      )
    );

    await expect(
      api.sendCopilotChat(1, [
        { role: "user", content: "a very private financial question" },
      ])
    ).rejects.toThrow();

    expect(consoleSpy).toHaveBeenCalledWith("copilot_chat_failed", {
      status: 500,
      requestId: "req-abc123",
    });

    const loggedText = JSON.stringify(consoleSpy.mock.calls);
    expect(loggedText).not.toContain("private financial question");

    consoleSpy.mockRestore();
  });

  it("does not log anything for a successful copilot chat", async () => {
    const consoleSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        kind: "answer",
        answer: "ok",
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
      })
    );

    await api.sendCopilotChat(1, [{ role: "user", content: "hi" }]);

    expect(consoleSpy).not.toHaveBeenCalled();

    consoleSpy.mockRestore();
  });
});
