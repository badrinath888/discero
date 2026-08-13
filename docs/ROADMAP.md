# Roadmap

Priority reflects MVP impact, risk and dependencies; it is guidance, not a commitment.

## Known limitations

- Recovery and resend endpoints do not yet have shared datastore-backed rate limiting.
- Pending negative transactions count toward budget spending.
- Budget category matching is exact and case-sensitive.
- Arbitrary budget source-month copy and overwrite are API-only.
- Plaid synchronization remains synchronous and covers all connected institutions for the user; a crashed request can delay another sync for up to 15 minutes.
- Safe-to-Spend obligations come only from `RecurringItem` rows; budgets and one-off manual obligations are not yet included even though `SafeToSpendObligationOut.source` already allows `budget`/`manual` values.
- Recurring items are created manually or promoted from a detected suggestion; there is no automatic promotion job.
- There is no live Plaid, PostgreSQL concurrency, browser E2E, or production smoke suite.

## Immediate cleanup

Potential Duplicates, the duplicated goal-schema declarations, atomic bulk category/delete, the stale landing-page test count, and Undo edge-case coverage (items formerly listed here) are complete: Potential Duplicates has seven backend tests plus a frontend compatibility test, the goal schema classes are defined once, bulk category/delete use dedicated atomic backend endpoints rather than `Promise.all`, the landing page reports the current verified backend test count, and the Transactions page has regression tests for overlapping-delete merging, Undo-after-overlap restoration, and deletion continuing after the Undo toast is closed (which also fixed a real data-loss bug: an overlapping delete used to silently drop the first batch instead of committing or restoring it). See [IMPLEMENTED_FEATURES.md](IMPLEMENTED_FEATURES.md).

1. **P1, small:** reconcile Docker deployment with migrations (copy Alembic assets/use startup script) and document actual Render/Vercel dashboard settings.

## MVP completion

Manual transaction creation, full transaction editing (date/description/merchant/amount/category), and filter-aware CSV export (items formerly listed here) are complete. See [IMPLEMENTED_FEATURES.md](IMPLEMENTED_FEATURES.md).

- Import preview and confirmation before commit; then CSV column mapping.
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
