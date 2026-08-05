# File map

## Root and operations

- `README.md`: public overview/setup; production status (deployment, monitoring) remains planned.
- `.gitignore`, `frontend/.gitignore`: secrets, databases, environments, dependencies and build/cache exclusions.
- `.github/workflows/ci.yml`: Python 3.12 pytest job and Node 24 lint/build job.
- `backend/.env.example`: safe backend variable names/default examples; real `.env` is ignored.
- `backend/requirements.txt`: pinned runtime/test dependencies.
- `backend/Dockerfile`: Python 3.12-slim/Uvicorn image; omits Alembic files and migration startup.
- `backend/start.sh`: production startup with migration then Uvicorn `$PORT`.
- `frontend/package.json` / lock: Next 16.2.12, React 19.2.4, Tailwind 4, Framer Motion, Lucide, Recharts, Plaid Link; dev/build/start/lint scripts.
- `frontend/next.config.ts`, `tsconfig.json`, `eslint.config.mjs`, `postcss.config.mjs`: framework/compiler/lint/Tailwind configuration.

## Backend application

- `app/main.py`: FastAPI app, CORS, router registration, `/health`.
- `app/config.py`: Pydantic settings and normalized CORS/Plaid helpers.
- `app/database.py`: engine/session/base and SQLite thread option.
- `app/models.py`: `User`, `Transaction`, `Budget`, `RecurringItem`, `SavingsGoal`, `GoalContribution`, `PlaidItem`, `FinancialAccount` and relationships.
- `app/schemas.py`: all Pydantic request/response models, including Safe-to-Spend, Major Purchase Simulation, Scenario Comparison, `RecurringItem`, and `GoalContribution` schemas. The formerly duplicated goal schema classes have been fixed; each goal schema is defined once.
- `app/security.py`: Argon2 hash/verify and HS256 JWT encode/decode.
- `app/auth.py`: `get_current_user` dependency (bearer parsing and current-user lookup) shared by every router; it is not itself registered as a router in `app/main.py`.
- `app/deps.py`: process-wide cached `LLMCategorizer` dependency.
- `app/money.py`: Decimal parsing/formatting for integer cents.
- `app/ingestion.py`: CSV aliases, date/money validation and row errors.
- `app/categorization.py`: deterministic keyword categories.
- `app/llm_categorization.py`: optional batched Anthropic classification/cache/fallback.
- `app/recurring.py`: algorithmic merchant normalization, cadence/confidence, next-date and price-change detection used by `summary/recurring`; distinct from the persisted `RecurringItem` model/router below.
- `app/token_encryption.py`: Fernet configuration, encrypt/decrypt and safe errors.
- `app/routers/users.py`: registration, login, forgot-password/reset-password/verify-email/resend-verification, self/get-user, credential changes.
- `app/routers/transactions.py`: upload/list/search/update/delete, bulk category/delete, and every summary/insight/forecast endpoint.
- `app/routers/budgets.py`: list/upsert/copy/progress.
- `app/routers/goals.py`: goal CRUD, derived status/progress, and `/goals/{goal_id}/contributions` deposit/withdrawal history CRUD.
- `app/routers/recurring.py`: `RecurringItem` CRUD at `/users/{user_id}/recurring-items`.
- `app/routers/safe_to_spend.py`: `POST /users/{user_id}/safe-to-spend`.
- `app/routers/major_purchase.py`: `POST /users/{user_id}/major-purchase/simulate` and `/major-purchase/compare`.
- `app/routers/accounts.py`: safe account listing.
- `app/routers/plaid.py`: link/exchange/disconnect/sync persistence orchestration.
- `app/services/plaid_service.py`: Plaid client calls and SDK-to-domain conversion.
- `app/services/email_service.py`: console/SMTP/Resend email delivery for password reset and email verification.
- `app/services/safe_to_spend_service.py`: liquid balance, upcoming `RecurringItem` obligations, and Safe-to-Spend status/confidence calculation.
- `app/services/major_purchase_service.py`: single-purchase affordability simulation built on Safe-to-Spend.
- `app/services/scenario_comparison_service.py`: ranks two major-purchase simulations and builds the recommendation text.

## Database and tests

- `backend/alembic.ini`, `alembic/env.py`, `script.py.mako`: Alembic configuration; env overrides the ini URL with application settings.
- `alembic/versions/*.py`: ten linear revisions described in [ARCHITECTURE.md](ARCHITECTURE.md); current head is `146ccae6e522`.
- `tests/conftest.py`: isolated SQLite test engine, dependency override, TestClient, registered-user/auth fixtures.
- `test_api.py`: health, users, credential changes, upload/auth/isolation.
- `test_transaction_search.py`, `test_transaction_bulk.py`: pagination, totals, text/source/type/account/date/category/duplicate filters, invalid range, and bulk category/delete atomicity.
- `test_budgets.py`, `test_goals.py`: domain CRUD/calculation/auth/isolation, including `test_goals.py` coverage of contribution/withdrawal history.
- `test_recurring_items.py`: persisted `RecurringItem` CRUD, duplicate rejection, and cross-user isolation.
- `test_safe_to_spend.py`, `test_major_purchase.py`, `test_scenario_comparison.py`: Safe-to-Spend, Major Purchase Simulator, and Scenario Comparison calculation and endpoint tests.
- `test_accounts.py`: safe account response/auth/isolation.
- `test_account_recovery.py`, `test_token_version.py`, `test_email_service.py`: password reset, email verification, token-version invalidation, and email delivery backends.
- `test_plaid_routes.py`, `test_plaid_sync.py`, `test_plaid_config.py`: provider mocks, exchange/disconnect/sync/error/config behavior.
- `test_summaries.py`, `test_recurring.py`: overview/month/insight/forecast and algorithmic recurrence detection.
- `test_ingestion.py`, `test_money.py`, `test_categorization.py`, `test_llm_categorization.py`, `test_token_encryption.py`, `test_health.py`: unit/regression coverage.
- `sample_transactions.csv`: example input.

## Frontend routes and shared code

- `app/layout.tsx`, `globals.css`: root metadata/fonts and global Tailwind theme/accessibility/reduced-motion styling.
- `app/page.tsx`: public marketing and authentication page.
- `app/{dashboard,transactions,accounts,budgets,recurring,forecast,goals,insights,settings,forgot-password,reset-password,verify-email}/page.tsx`: route implementations (14 pages plus root); see [ARCHITECTURE.md](ARCHITECTURE.md).
- `app/decisions/page.tsx`: Safe-to-Spend, Major Purchase Simulator, and Scenario Comparison; covered by `app/decisions/page.test.tsx`.
- `app/lib/api.ts`: API/result types, 15-second fetch wrapper, localStorage session, all endpoint methods (including `duplicates_only`, recurring items, goal contributions, Safe-to-Spend, and major-purchase simulate/compare), money formatter.
- `components/AppSidebar.tsx`: grouped desktop/mobile navigation and browser logout.
- `components/AuthFlowCard.tsx`: shared layout for the forgot-password/reset-password/verify-email pages.
- `ConfirmationModal.tsx`: accessible reusable destructive confirmation dialog.
- `Toast.tsx`: animated success/error notification with optional action.
- `PageFeedback.tsx`: `PageLoading`, `PageError`, `PageSuccess`, `EmptyState`, `CardSkeleton`.
- `PremiumMotion.tsx`: page/reveal/stagger/hover/count animation helpers honoring reduced motion.
- `MerchantAvatar.tsx`: merchant initials/logo/category icon treatment.
- `ConnectBankButton.tsx`: Plaid Link token/exchange UI.
- `BudgetProgress.tsx`, `MonthlyTrend.tsx`, `RecurringPayments.tsx`: dashboard visualization panels.
- `SafeToSpendCard.tsx`: dashboard Safe-to-Spend summary card.
- `public/*.svg`, `favicon.ico`: static starter/brand assets.

## Do not edit

Ignored/generated local state includes `backend/.env`, `frontend/.env.local`, `backend/finance.db`, `backend/venv/`, `frontend/node_modules/`, `frontend/.next/`, `next-env.d.ts`, `__pycache__/`, `.pytest_cache/`, and `*.pyc`. They are not source of truth and may contain secrets or machine-specific state. `package-lock.json` is generated but tracked and should change only with intentional dependency changes. `docs/screenshots/` existed locally as an ignored/untracked directory at audit time and was not changed.
