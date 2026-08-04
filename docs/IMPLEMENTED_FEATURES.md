# Implemented features and history

Status vocabulary: **verified** means current automated validation covers it or the build compiled it; **implemented/unverified** means current code exists but this audit did not execute an end-to-end/provider/production flow; **partial** means incomplete and unsafe to present as working.

| Feature | Status/evidence | Primary files/history |
|---|---|---|
| FastAPI/SQLAlchemy base, cents-safe CSV import, rules, summaries, CI | Verified by tests | Initial `8e92069`; ingestion/money/API tests. |
| Optional batched/cached LLM categorization with fallback | Verified with mocked unit tests; live Anthropic unverified | `1da3562`; `llm_categorization.py`. |
| JWT auth, Argon2, user isolation | Verified route tests | `6d62b32`; auth/security/API tests. |
| Server-side JWT invalidation | Verified by credential, claim, legacy-token and ownership tests | Per-user token version is embedded as `ver`; successful email/password changes invalidate all older tokens. Legacy tokens without `ver` are rejected. |
| Plaid Sandbox link/exchange/sync/accounts and encrypted tokens | Verified with deterministic provider mocks; live Sandbox/production unverified | Manual sync lifecycle, 15-minute atomic stale-claim recovery, safe attempted/success timestamps and errors, reconnect-required state, atomic cursor/data commits, idempotent transaction updates/removals, and owner-scoped disconnect/status are covered by Plaid/account tests. |
| Alembic schema | Verified single linear head/current | `6d62b32`, goals `2d0c79b`, dependency/start fixes `eafc6ae`/`4a7c3a9`, boolean fix `7bb7d28`. |
| Search/filter/pagination/totals | Verified backend tests and frontend build | `bd5e74b`. |
| Category update/lock and transaction delete | Verified backend; UI compiled | Base/auth phases; confirmation `57215c0`, reusable modal `29220c5`. |
| Budgets, progress and copy-previous | Verified backend; UI compiled | `6d62b32`, `3b133de`; budget tests. |
| Savings goals CRUD/contributions/withdrawals/status | Verified backend; UI compiled | `2d0c79b`; confirmation `bf9082f`; goal tests. |
| Recurring detection | Verified algorithm tests | `2d0c79b`, improved `029da85`. |
| Insights and cash-flow forecast | Verified backend tests; UI compiled | `2d0c79b`, tests `b630613`. |
| Full frontend routes, shared feedback and product redesign | Production build verified | `9f4ad1a`, `fcaeed5`, `6a1c088`. |
| Settings/account statistics | Build verified | `bf2f0ae`, `c3abb26`. |
| Confirmations and success/error toasts | Build verified | `51ea95e` through `ffddc69`, shared modal/toast commits. |
| Password/email change and visibility; browser sign-out | Backend tests + build verified; server revocation absent | `fc4f4fe`–`b62c03b`. |
| Settings CSV export | Build verified; client-side export of all fetched transactions | `0d4896e`. |
| Atomic bulk category/delete | Verified by backend rollback/validation tests and focused frontend component tests | Bulk category locks every row and returns request-order results; bulk delete returns a count. The UI sends one request after selection/confirmation, with deletion delayed six seconds for Undo. |
| Atomic mixed-category update and category Undo | Verified by backend tests and focused frontend component tests | `PATCH /transactions/bulk/categories` applies up to 100 distinct per-transaction categories in one commit. Single and bulk category changes expose a six-second Undo that restores exact prior values with one atomic request. |
| Six-second optimistic Undo deletion | Verified by focused frontend component tests | `523514d` plus `faba3d2`, `9da720b`, `6633c2f`. Undo cancels a local timer before DELETE; expiry sends one atomic request and failure restores every removed row. |
| Potential Duplicates | Verified by focused backend tests and frontend lint/build | Correlated `EXISTS` over same user/date/amount and normalized merchant-or-description identity; transaction-page toggle reuses selection, bulk delete, confirmation and Undo. See [CURRENT_WORK.md](CURRENT_WORK.md). |

## Route UI behavior

Every authenticated route is responsive through Tailwind breakpoints and `AppSidebar` mobile navigation. Motion uses Framer Motion and shared helpers that respect `prefers-reduced-motion`. Transactions/accounts/goals use detail drawers; destructive account, goal and transaction actions use `ConfirmationModal`; mutation success/error uses `Toast` where implemented. Forecast/recurring/insights have page errors, empty CTAs and animated drawers. Budgets have loading/error/empty, copy confirmation state and success toast. Settings uses loading plus two toast channels but no confirmation for browser logout or CSV export. Dashboard has its own loading/error/empty blocks and upload result messaging.

The frontend has focused Vitest/React Testing Library coverage: 10 Transactions-page regression tests plus 6 Accounts-page Plaid lifecycle tests for Sync Now success/loading/failure, last-sync display, disconnect confirmation, and reconnect-required presentation. All provider/API boundaries are mocked.

Known UI limitations: frontend automated coverage is limited to the Transactions page; session logic is repeated per page; JWT is in localStorage; no global error boundary/auth provider; Undo state is client-memory-only; closing the delete Undo toast hides the action while the deletion timer continues; pagination can be stale after optimistic deletion; and the landing page displays stale “111 Backend tests.”

## Commit history summary

All 44 commits from `8e92069` through `6633c2f` were inventoried in chronological order, with per-commit files/stats and meaningful patches reviewed. Major architecture steps are the initial backend (`8e92069`), LLM (`1da3562`), auth/Plaid/frontend (`6d62b32`), analytics/routes (`2d0c79b`), redesigns (`fcaeed5`, `6a1c088`), search (`bd5e74b`), budgets/recurring (`3b133de`, `029da85`), settings/deployment hardening, confirmation/toast series, credentials, export, and Undo series. No merges or alternate reachable branch history were present; `main` and `origin/main` matched at audit time.
