import { NextRequest, NextResponse } from "next/server";

// Same variable the API client reads (see app/lib/api.ts) -- kept in
// sync so connect-src always matches the backend origin actually
// being called, in every environment.
const BACKEND_ORIGIN =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Plaid Link (see app/components/ConnectBankButton.tsx, backed by
// react-plaid-link) loads its own script and opens an iframe hosted on
// Plaid's CDN/API domains. Allowlisted by domain rather than folded
// into 'strict-dynamic' alone, since Link's iframe navigation is a
// separate load Plaid's own CSP guidance calls out explicitly.
const PLAID_SCRIPT_SRC = "https://cdn.plaid.com";
const PLAID_FRAME_SRC = "https://cdn.plaid.com https://*.plaid.com";
const PLAID_CONNECT_SRC = "https://*.plaid.com";

export function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const isHttpsBackend = BACKEND_ORIGIN.startsWith("https://");

  const directives = [
    "default-src 'self'",
    // 'strict-dynamic' lets Next.js's own nonced scripts load further
    // same-bundle chunks without listing every hashed filename; the
    // explicit Plaid origin covers the one legitimate non-bundled
    // script this app loads.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic' ${PLAID_SCRIPT_SRC}`,
    // React/Tailwind-adjacent libraries this app actually uses
    // (framer-motion, recharts) set inline `style="..."` attributes
    // at runtime -- CSP has no nonce mechanism for style ATTRIBUTES
    // (only <style> elements), so 'unsafe-inline' here is a deliberate,
    // narrowly-scoped exception, never extended to script-src.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    `connect-src 'self' ${BACKEND_ORIGIN} ${PLAID_CONNECT_SRC}`,
    `frame-src ${PLAID_FRAME_SRC}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ];

  // Upgrading insecure requests would break plain-http local dev
  // (there is no TLS listener on localhost to upgrade to) -- only
  // meaningful, and only added, once the backend itself is https.
  if (isHttpsBackend) {
    directives.push("upgrade-insecure-requests");
  }

  const csp = directives.join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set("Content-Security-Policy", csp);

  return response;
}

export const config = {
  matcher: [
    // Skip static assets and image optimization output -- the CSP
    // (and its per-request nonce) only matters for actual page/API
    // responses.
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
