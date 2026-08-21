import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { proxy } from "./proxy";

describe("proxy (CSP)", () => {
  it("sets a Content-Security-Policy header with a nonce", () => {
    const response = proxy(new NextRequest("http://localhost:3000/"));
    const csp = response.headers.get("Content-Security-Policy");

    expect(csp).toBeTruthy();
    expect(csp).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
  });

  it("never allows unsafe-inline or unsafe-eval in script-src", () => {
    const response = proxy(new NextRequest("http://localhost:3000/"));
    const csp = response.headers.get("Content-Security-Policy") ?? "";
    const scriptSrc = csp
      .split(";")
      .find((d) => d.trim().startsWith("script-src"));

    expect(scriptSrc).toBeDefined();
    expect(scriptSrc).not.toContain("unsafe-inline");
    expect(scriptSrc).not.toContain("unsafe-eval");
    expect(scriptSrc).not.toContain("*");
  });

  it("never allows a wildcard origin anywhere in the policy", () => {
    const response = proxy(new NextRequest("http://localhost:3000/"));
    const csp = response.headers.get("Content-Security-Policy") ?? "";

    // "*" alone (a bare wildcard source) would defeat the policy --
    // this is distinct from "https://*.plaid.com", a scoped subdomain
    // wildcard, which is fine.
    expect(csp).not.toMatch(/(^|\s)\*(\s|$|;)/);
  });

  it("allowlists Plaid's CDN for script and frame sources", () => {
    const response = proxy(new NextRequest("http://localhost:3000/"));
    const csp = response.headers.get("Content-Security-Policy") ?? "";

    expect(csp).toContain("https://cdn.plaid.com");
    expect(csp).toContain("frame-src https://cdn.plaid.com");
  });

  it("generates a different nonce on every request", () => {
    const first = proxy(new NextRequest("http://localhost:3000/"));
    const second = proxy(new NextRequest("http://localhost:3000/"));

    const nonceOf = (res: typeof first) => {
      const csp = res.headers.get("Content-Security-Policy") ?? "";
      return /nonce-([A-Za-z0-9+/=]+)/.exec(csp)?.[1];
    };

    expect(nonceOf(first)).toBeTruthy();
    expect(nonceOf(first)).not.toBe(nonceOf(second));
  });

  it("propagates the nonce to the request so Server Components can read it", () => {
    const response = proxy(new NextRequest("http://localhost:3000/"));
    const csp = response.headers.get("Content-Security-Policy") ?? "";
    const nonce = /nonce-([A-Za-z0-9+/=]+)/.exec(csp)?.[1];

    // NextResponse.next({ request }) forwards the modified request
    // headers downstream; the nonce set there must match the one in
    // the response's own CSP header, or Server Components reading
    // x-nonce would apply a nonce that doesn't match the policy.
    expect(response.headers.get("x-middleware-request-x-nonce")).toBe(
      nonce
    );
  });

  it("does not upgrade insecure requests against the local-dev http backend", () => {
    // NEXT_PUBLIC_API_URL is read once at module load; the test
    // environment leaves it unset, so this exercises the "http://
    // localhost:8000" fallback -- the same one local dev actually
    // uses. Upgrading it would break every API call, since nothing
    // listens for https on localhost in dev.
    const response = proxy(new NextRequest("http://localhost:3000/"));
    const csp = response.headers.get("Content-Security-Policy") ?? "";

    expect(csp).toContain("connect-src 'self' http://localhost:8000");
    expect(csp).not.toContain("upgrade-insecure-requests");
  });
});
