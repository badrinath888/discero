# Security

Discero handles real personal financial data. This document covers how to
report a vulnerability, the security invariants the codebase is built to
hold, and what's required to keep a production deployment safe.

## Reporting a vulnerability

If you believe you've found a security issue in Discero, please report it
privately rather than opening a public GitHub issue. Include enough detail
to reproduce the issue (affected endpoint/component, request shape, and
impact). Do not include real user data in a report.

## Production security invariants

These properties are enforced in code and covered by the `test_security_*`
backend test modules -- treat a change that breaks one of these tests as a
regression, not an inconvenience to work around:

- **Financial truth is deterministic.** The LLM/Copilot layer only
  explains results computed by deterministic backend services; it never
  computes, invents, or overrides a financial figure. Narration is checked
  against the real payload before being shown (`_narration_is_grounded` in
  `backend/app/services/copilot_service.py`).
- **Every user-owned resource is scoped by the authenticated user**, both
  at the route level (`_authorize_user`) and at the query level
  (`WHERE ... user_id = :authenticated_user`). No object is ever fetched
  by id alone.
- **The LLM can never choose whose data a tool touches.** No tool schema
  exposes a `user_id` field; execution always uses the user_id from the
  authenticated request, never anything from a model's tool-call
  arguments.
- **No request schema accepts a server-owned field** (`user_id`,
  ownership, password hashes, verification/lifecycle state, a
  client-supplied "result" standing in for a real calculation).
- **The refresh token lives only in an HttpOnly, `Secure`-in-production
  cookie**, scoped to `/users`, never in JS-readable storage and never in
  a JSON response body. The access token is short-lived and used as a
  Bearer header on every other request (immune to CSRF, since nothing
  ambient attaches it).
- **Rate limiting is backend-agnostic** (`backend/app/rate_limit.py`): an
  in-memory sliding window for local dev/test, or a Redis-backed atomic
  sliding window (set `REDIS_URL`) for a horizontally-scaled production
  deployment. Do not add a new abuse control that only works
  single-process. A Redis outage never becomes unlimited traffic: on a
  Redis error, `_ResilientLimiter` falls back to the same in-process
  limiter for a short cooldown, then automatically retries Redis.
- **Expensive authenticated endpoints are limited by IP AND by user**
  (`authenticated_rate_limiter` in `backend/app/rate_limit.py`; used by
  Copilot chat, CSV upload, and Plaid link/exchange/sync) -- either
  bucket being exceeded rejects the request, and the user identity always
  comes from the already-authenticated `User` object, never a
  client-supplied `user_id`. Purely public/anonymous auth endpoints
  (login, register, password reset) remain IP-only.
- **Client IP is read from `request.client.host`, never an
  `X-Forwarded-For` header directly** (`_client_ip` in
  `backend/app/rate_limit.py`). This is safe only because Render is the
  sole public ingress for this deployment (`backend/start.sh` runs
  uvicorn with `--proxy-headers`, and Render's edge is the only peer that
  can ever connect) -- this is a deployment invariant, not a code
  guarantee, and would need revisiting under any other proxy topology.
- **Production configuration fails closed at startup** (see
  `Settings.validate_production_*` in `backend/app/config.py`): a default
  JWT secret, a wildcard/localhost CORS origin, or a missing encryption
  key (when Plaid is configured) all refuse to start when
  `APP_ENV=production`.

## Secret rotation

If a real credential is ever suspected of leaking (committed, logged, or
exposed via an error message):

1. Rotate/revoke it at the provider immediately (Plaid, Anthropic/Groq,
   Resend/SMTP, the database) -- deleting the file it appeared in does not
   invalidate an already-issued credential.
2. Rotate `JWT_SECRET` if a JWT signing key is suspected -- this
   immediately invalidates every outstanding access/refresh token.
3. Rotate `TOKEN_ENCRYPTION_KEY` only with a migration plan: existing
   Plaid access tokens are encrypted with the current key and become
   unreadable if it's replaced outright. This repository does not yet
   implement dual-key (current + previous, decrypt-only) rotation --
   treat a `TOKEN_ENCRYPTION_KEY` rotation as requiring re-linking
   affected Plaid connections, or implement dual-key support first if
   that's not acceptable.
4. Never commit a rotated value -- set it via the hosting platform's
   environment/secrets configuration (Render, Vercel, GitHub Actions
   secrets).

## Known residual risks / operational assumptions

- Refresh tokens are stateless JWTs (rotated on every `/users/refresh`
  call) rather than a server-side session table -- there is no reuse-
  detection for a stolen-and-replayed refresh cookie beyond its own
  expiry or a blanket `token_version` bump (password reset/change/
  logout). A per-session refresh-token-family table with replay
  detection would close this gap but requires a new table/migration.
- The global request-body-size limit
  (`backend/app/body_size_limit.py`) checks the `Content-Length` header;
  a request using chunked transfer-encoding without a declared
  Content-Length is not bounded by it.
- No first-party MFA/passkey support. Account takeover risk is bounded by
  password strength + rate limiting + full session revocation on password
  change, but a second factor is not implemented.
- The Redis-backed rate limiter degrades to the in-process limiter (not
  unconditional allow) on a Redis outage, so each affected instance still
  enforces its own limit even though instances briefly stop coordinating
  with each other -- a deliberate trade-off (bounded per-instance abuse
  window during a brief backend blip) rather than either failing fully
  open or failing the whole API closed.

## External configuration checklist (cannot be verified from source)

See the security-audit report for the full list with severities. At
minimum, before/at production deployment:

- Render: `APP_ENV=production`, `JWT_SECRET`, `TOKEN_ENCRYPTION_KEY`,
  `CORS_ORIGINS` (exact frontend origin, no wildcard/localhost), database
  TLS enabled, `REDIS_URL` set if running more than one instance.
- Vercel: `NEXT_PUBLIC_API_URL` pointed at the production backend only;
  no non-`NEXT_PUBLIC_` secret ever added with that prefix.
- GitHub: branch protection on `main`, secret scanning + push protection
  enabled, Dependabot alerts enabled.
- Plaid: production (not sandbox) credentials configured only in Render's
  environment, never in source.
