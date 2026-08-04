# Current work

Updated: 2026-08-03 for Plaid synchronization and connected-account lifecycle hardening. Nothing is committed or pushed.

## Baseline and scope

This isolated worktree started clean at `eb9e2082577de39519450b006ade25276c9a335c`. Authentication recovery work, budgets, Next.js, and React were not changed. One migration was added; no environment variables or real Plaid credentials were introduced.

## Implementation

- Manual `POST /users/{user_id}/plaid/sync` now persists per-item `syncing`, `succeeded`, or `failed` lifecycle state and attempted/successful timestamps. Recent claims return 409; claims at least 15 minutes old can be reclaimed by one atomic UTC-guarded update.
- `GET /users/{user_id}/plaid/sync/status` returns safe owner-scoped item status; account responses carry the same lifecycle metadata.
- Each item's added/modified/removed transaction changes and final cursor commit atomically. Provider transaction ids are upserted, duplicate/repeated input is idempotent, locked categories remain intact, and account mappings are item-scoped.
- Failed provider, encryption, mapping, or persistence work retains the prior cursor and successful timestamp, then stores a bounded safe error summary. `ITEM_LOGIN_REQUIRED` marks the item `reconnect_required`; a successful token exchange restores it to active/idle.
- Disconnect remains provider-first and owner-scoped. Provider failure retains local state; success removes the item/accounts while keeping transactions with null account links.
- The Accounts page provides Sync Now loading/success/failure feedback, last successful sync, persisted failure/reconnect notices, safe confirmation, and refreshes both accounts and transactions after sync.

## Tests and validation

- Backend: 11 new tests; 186 total passing. Deterministic mocks cover repeated sync, recent-claim rejection, stale-claim recovery/success/failure safety, competing reclaim requests, final cursor progression, failed-cursor preservation, timestamps/status/error, successful retry, reconnect requirement, safe status ownership/authentication, and disconnect authentication in addition to existing success/removal/disconnect coverage.
- Frontend: 6 new Accounts tests; 16 total passing. No real Plaid API or backend calls.
- Frontend lint and production build pass.
- Migration/head/current and final repository checks are run before handoff and reported in the final response.

## Known limitations

- Sync is a synchronous request; there is no background job or webhook scheduler. A process crash can delay the next manual sync for up to the documented 15-minute claim timeout.
- Manual sync covers all connected items for the user rather than one selected institution.
- Live Plaid Sandbox/production, PostgreSQL concurrency, browser E2E, and production deployment are not exercised by the deterministic local suites.
