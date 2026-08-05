# Roadmap

Priority reflects MVP impact, risk and dependencies; it is guidance, not a commitment.

## Immediate cleanup

Potential Duplicates, the duplicated goal-schema declarations, and atomic bulk category/delete (items formerly listed here) are complete: Potential Duplicates has seven backend tests plus a frontend compatibility test, the goal schema classes are defined once, and bulk category/delete use dedicated atomic backend endpoints rather than `Promise.all`. See [IMPLEMENTED_FEATURES.md](IMPLEMENTED_FEATURES.md).

1. **P0, small:** update the landing-page "111 Backend tests" stat (`frontend/app/page.tsx`) to the current verified count of 254.
2. **P1, medium:** test Undo edge cases: toast close semantics, navigation/unmount, overlapping deletes, request failure restoration, selection/pagination after optimistic removal.
3. **P1, small:** reconcile Docker deployment with migrations (copy Alembic assets/use startup script) and document actual Render/Vercel dashboard settings.

## MVP completion

- Import preview and confirmation before commit; then CSV column mapping.
- Manual transaction creation and broader transaction editing.
- Filter-aware export rather than settings-only full export.
- Account rename/hide controls and account deletion policy.

## Security

- P0: server-side invalidation for credential changes (token version/session table); design refresh/rotation only if product needs persistent sessions.
- P0: production secret rotation runbook and strict CORS/security headers.
- P1: rate limits for auth/import/Plaid; audit logging without sensitive payloads.
- P1: account deletion with re-authentication, provider disconnect and retention policy.
- Later: move browser auth away from localStorage to an appropriate HttpOnly session design.

## Reliability

- PostgreSQL migration/integration CI and restore-tested backups.
- Idempotent sync/import, concurrency tests, transaction boundaries and uniqueness review.
- Plaid re-auth/item-error UX, retry policy and cursor recovery.
- Structured logs, request correlation, error monitoring, health/readiness and alerts.
- Frontend component/E2E tests for auth, destructive flows, export, bulk and Undo.

## UX/product

- Dedicated duplicate review workspace after detection precision is proven.
- Budget alerts, recurring allow/ignore controls, notifications.
- Accessibility audit (keyboard, focus, dialogs/drawers, charts, contrast).
- Mobile refinements; dark mode only if product direction calls for it.

## Plaid/data

- Validate cross-source duplicate semantics and provider pending→posted behavior.
- Production Plaid readiness review, webhooks and scheduled/background sync.
- Stronger account/provider uniqueness constraints and data-retention policy.
- Multi-currency only after currency-aware aggregation rules exist.

## AI/analytics

- Confidence/explanations and observable fallback for categorization.
- Persist user corrections and safe learning rules.
- Richer spending insights, anomaly detection and calibrated forecasts.
- AI assistant/RAG only after authorization, privacy, grounding and audit controls are mature.

## Deployment/observability

- Capture infrastructure-as-code or authoritative dashboard runbook.
- Production smoke checks tied to exact Git SHA; uptime/error/latency monitoring.
- Review 15-second client timeout against Render cold-start behavior.
- Document database backup, recovery objectives and incident rollback drills.

## Advanced future phase

- Household/shared accounts with explicit authorization model.
- Net worth/investment tracking, multi-currency and robust forecasting.
- Webhook-driven automatic sync, anomaly alerts and an explainable financial assistant.
