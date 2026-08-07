import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, session } from "./api";

const TOKEN_KEY = "accessToken";
const REFRESH_TOKEN_KEY = "refreshToken";
const USER_ID_KEY = "userId";
const SESSION_NOTICE_KEY = "sessionNotice";

function jsonResponse(
  status: number,
  body: unknown,
  ok = status >= 200 && status < 300
): Response {
  return {
    ok,
    status,
    statusText: "",
    json: async () => body,
  } as Response;
}

function brokenJsonResponse(status: number, ok = true): Response {
  return {
    ok,
    status,
    statusText: "",
    json: async () => {
      throw new SyntaxError("Unexpected end of JSON input");
    },
  } as Response;
}

function authHeaderOf(call: unknown[]): string | undefined {
  const init = call[1] as RequestInit | undefined;
  const headers = init?.headers as
    | Record<string, string>
    | Headers
    | undefined;

  if (!headers) return undefined;

  if (headers instanceof Headers) {
    return headers.get("Authorization") ?? undefined;
  }

  return headers.Authorization;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("authenticated requests", () => {
  it("uses the current access token for a successful request", async () => {
    localStorage.setItem(TOKEN_KEY, "access-current");
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { id: 1, email: "a@example.com", email_verified: true })
    );

    const result = await api.getMe();

    expect(result.id).toBe(1);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(authHeaderOf(fetchMock.mock.calls[0])).toBe(
      "Bearer access-current"
    );
  });
});

describe("401 handling and refresh", () => {
  it("triggers exactly one refresh request on a 401", async () => {
    localStorage.setItem(TOKEN_KEY, "access-old");
    localStorage.setItem(REFRESH_TOKEN_KEY, "refresh-old");

    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }, false))
      .mockResolvedValueOnce(
        jsonResponse(200, {
          access_token: "access-new",
          refresh_token: "refresh-new",
          token_type: "bearer",
          user: { id: 1, email: "a@example.com", email_verified: true },
        })
      )
      .mockResolvedValueOnce(
        jsonResponse(200, { id: 1, email: "a@example.com", email_verified: true })
      );

    const result = await api.getMe();

    expect(result.id).toBe(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);

    const refreshCalls = fetchMock.mock.calls.filter((call) =>
      String(call[0]).includes("/users/refresh")
    );
    expect(refreshCalls).toHaveLength(1);
  });

  it("stores new tokens, retries the request, and returns the retried response", async () => {
    localStorage.setItem(TOKEN_KEY, "access-old");
    localStorage.setItem(REFRESH_TOKEN_KEY, "refresh-old");

    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }, false))
      .mockResolvedValueOnce(
        jsonResponse(200, {
          access_token: "access-new",
          refresh_token: "refresh-new",
          token_type: "bearer",
          user: { id: 7, email: "b@example.com", email_verified: true },
        })
      )
      .mockResolvedValueOnce(
        jsonResponse(200, { id: 7, email: "b@example.com", email_verified: true })
      );

    const result = await api.getMe();

    expect(result.id).toBe(7);
    expect(localStorage.getItem(TOKEN_KEY)).toBe("access-new");
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBe("refresh-new");

    const retryCall = fetchMock.mock.calls[2];
    expect(authHeaderOf(retryCall)).toBe("Bearer access-new");
  });

  it("does not retry endlessly and clears session state when refresh fails", async () => {
    localStorage.setItem(TOKEN_KEY, "access-old");
    localStorage.setItem(REFRESH_TOKEN_KEY, "refresh-old");

    fetchMock
      .mockResolvedValueOnce(
        jsonResponse(
          401,
          { detail: "session expired; please sign in again" },
          false
        )
      )
      .mockResolvedValueOnce(
        jsonResponse(401, { detail: "refresh token invalid" }, false)
      );

    await expect(api.getMe()).rejects.toThrow(
      /session expired; please sign in again/
    );

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
    expect(sessionStorage.getItem(SESSION_NOTICE_KEY)).toBe(
      "Your session expired. Please sign in again."
    );
  });

  it("never lets the refresh endpoint itself trigger another refresh", async () => {
    localStorage.setItem(TOKEN_KEY, "access-old");
    localStorage.setItem(REFRESH_TOKEN_KEY, "refresh-old");

    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }, false))
      .mockResolvedValueOnce(
        jsonResponse(401, { detail: "refresh token invalid" }, false)
      );

    await expect(api.getMe()).rejects.toThrow();

    // Exactly two calls: the original request and one refresh attempt.
    // If the refresh endpoint's own 401 recursed into another refresh,
    // this would be 3+ calls.
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("uses the updated access token for subsequent sequential requests", async () => {
    localStorage.setItem(TOKEN_KEY, "access-old");
    localStorage.setItem(REFRESH_TOKEN_KEY, "refresh-old");

    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }, false))
      .mockResolvedValueOnce(
        jsonResponse(200, {
          access_token: "access-new",
          refresh_token: "refresh-new",
          token_type: "bearer",
          user: { id: 1, email: "a@example.com", email_verified: true },
        })
      )
      .mockResolvedValueOnce(
        jsonResponse(200, { id: 1, email: "a@example.com", email_verified: true })
      );

    await api.getMe();
    fetchMock.mockClear();

    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { id: 1, email: "a@example.com", email_verified: true })
    );

    await api.getMe();

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(authHeaderOf(fetchMock.mock.calls[0])).toBe("Bearer access-new");
  });

  it("does not attempt a refresh when there is no refresh token", async () => {
    localStorage.setItem(TOKEN_KEY, "access-old");

    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, { detail: "expired" }, false)
    );

    await expect(api.getMe()).rejects.toThrow();

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("handles a malformed refresh response safely without hanging or looping", async () => {
    localStorage.setItem(TOKEN_KEY, "access-old");
    localStorage.setItem(REFRESH_TOKEN_KEY, "refresh-old");

    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }, false))
      .mockResolvedValueOnce(brokenJsonResponse(200, true));

    await expect(api.getMe()).rejects.toThrow();

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not loop when the retried request also returns 401", async () => {
    localStorage.setItem(TOKEN_KEY, "access-old");
    localStorage.setItem(REFRESH_TOKEN_KEY, "refresh-old");

    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }, false))
      .mockResolvedValueOnce(
        jsonResponse(200, {
          access_token: "access-new",
          refresh_token: "refresh-new",
          token_type: "bearer",
          user: { id: 1, email: "a@example.com", email_verified: true },
        })
      )
      .mockResolvedValueOnce(
        jsonResponse(401, { detail: "still unauthorized" }, false)
      );

    await expect(api.getMe()).rejects.toThrow();

    // original + refresh + single retry = 3 calls, never more.
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});

describe("requests that do not require authentication", () => {
  it("does not attempt a refresh on a 401 from an unauthenticated request", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, { detail: "invalid credentials" }, false)
    );

    await expect(api.login("a@example.com", "wrong-password")).rejects.toThrow();

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(authHeaderOf(fetchMock.mock.calls[0])).toBeUndefined();
  });

  it("resolves normally for a successful unauthenticated request", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        access_token: "access-1",
        refresh_token: "refresh-1",
        token_type: "bearer",
        user: { id: 1, email: "a@example.com", email_verified: true },
      })
    );

    const result = await api.login("a@example.com", "correct-password");

    expect(result.access_token).toBe("access-1");
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});

describe("session storage", () => {
  it("stores access and refresh tokens on login", () => {
    session.save({
      access_token: "access-1",
      refresh_token: "refresh-1",
      token_type: "bearer",
      user: { id: 9, email: "a@example.com", email_verified: true },
    });

    expect(localStorage.getItem(TOKEN_KEY)).toBe("access-1");
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBe("refresh-1");
    expect(localStorage.getItem(USER_ID_KEY)).toBe("9");
  });

  it("clears both tokens on logout", () => {
    localStorage.setItem(TOKEN_KEY, "access-1");
    localStorage.setItem(REFRESH_TOKEN_KEY, "refresh-1");
    localStorage.setItem(USER_ID_KEY, "9");

    session.clear();

    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(USER_ID_KEY)).toBeNull();
  });
});
