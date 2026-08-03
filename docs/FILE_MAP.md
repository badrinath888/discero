# File map

## Root and operations

- `README.md`: public overview/setup; currently stale on test count and production status.
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
- `app/models.py`: `User`, `Transaction`, `Budget`, `SavingsGoal`, `PlaidItem`, `FinancialAccount` and relationships.
- `app/schemas.py`: all Pydantic request/response models. Note: goal schema classes are accidentally duplicated verbatim; the second definitions shadow the first.
- `app/security.py`: Argon2 hash/verify and HS256 JWT encode/decode.
- `app/auth.py`: optional bearer parsing and current-user lookup.
- `app/deps.py`: process-wide cached `LLMCategorizer` dependency.
- `app/money.py`: Decimal parsing/formatting for integer cents.
- `app/ingestion.py`: CSV aliases, date/money validation and row errors.
- `app/categorization.py`: deterministic keyword categories.
- `app/llm_categorization.py`: optional batched Anthropic classification/cache/fallback.
- `app/recurring.py`: merchant normalization, cadence/confidence, next-date and price-change detection.
- `app/token_encryption.py`: Fernet configuration, encrypt/decrypt and safe errors.
- `app/routers/users.py`: registration/login, self/get-user, credential changes. It imports and includes the separate `routers/auth.py` login router.
- `app/routers/auth.py`: `/users/login` implementation.
- `app/routers/transactions.py`: upload/list/search/update/delete and every summary/insight/forecast endpoint.
- `app/routers/budgets.py`: list/upsert/copy/progress.
- `app/routers/goals.py`: goal CRUD and derived status/progress.
- `app/routers/accounts.py`: safe account listing.
- `app/routers/plaid.py`: link/exchange/disconnect/sync persistence orchestration.
- `app/services/plaid_service.py`: Plaid client calls and SDK-to-domain conversion.

## Database and tests

- `backend/alembic.ini`, `alembic/env.py`, `script.py.mako`: Alembic configuration; env overrides the ini URL with application settings.
- `alembic/versions/*.py`: five linear revisions described in [ARCHITECTURE.md](ARCHITECTURE.md).
- `tests/conftest.py`: isolated SQLite test engine, dependency override, TestClient, registered-user/auth fixtures.
- `test_api.py`: health, users, credential changes, upload/auth/isolation.
- `test_transaction_search.py`: pagination, totals, text/source/type/account/date/category filters and invalid range.
- `test_budgets.py`, `test_goals.py`: domain CRUD/calculation/auth/isolation.
- `test_accounts.py`: safe account response/auth/isolation.
- `test_plaid_routes.py`, `test_plaid_sync.py`, `test_plaid_config.py`: provider mocks, exchange/disconnect/sync/error/config behavior.
- `test_summaries.py`, `test_recurring.py`: overview/month/insight/forecast and recurrence algorithms.
- `test_ingestion.py`, `test_money.py`, `test_categorization.py`, `test_llm_categorization.py`, `test_token_encryption.py`, `test_health.py`: unit/regression coverage.
- `sample_transactions.csv`: example input.

## Frontend routes and shared code

- `app/layout.tsx`, `globals.css`: root metadata/fonts and global Tailwind theme/accessibility/reduced-motion styling.
- `app/page.tsx`: public marketing and authentication page.
- `app/{dashboard,transactions,accounts,budgets,recurring,forecast,goals,insights,settings}/page.tsx`: route implementations; see [ARCHITECTURE.md](ARCHITECTURE.md).
- `app/lib/api.ts`: API/result types, 15-second fetch wrapper, localStorage session, all endpoint methods, money formatter. It contains the partial `duplicates_only` type addition.
- `components/AppSidebar.tsx`: grouped desktop/mobile navigation and browser logout.
- `ConfirmationModal.tsx`: accessible reusable destructive confirmation dialog.
- `Toast.tsx`: animated success/error notification with optional action.
- `PageFeedback.tsx`: `PageLoading`, `PageError`, `PageSuccess`, `EmptyState`, `CardSkeleton`.
- `PremiumMotion.tsx`: page/reveal/stagger/hover/count animation helpers honoring reduced motion.
- `MerchantAvatar.tsx`: merchant initials/logo/category icon treatment.
- `ConnectBankButton.tsx`: Plaid Link token/exchange UI.
- `BudgetProgress.tsx`, `MonthlyTrend.tsx`, `RecurringPayments.tsx`: dashboard visualization panels.
- `public/*.svg`, `favicon.ico`: static starter/brand assets.

## Do not edit

Ignored/generated local state includes `backend/.env`, `frontend/.env.local`, `backend/finance.db`, `backend/venv/`, `frontend/node_modules/`, `frontend/.next/`, `next-env.d.ts`, `__pycache__/`, `.pytest_cache/`, and `*.pyc`. They are not source of truth and may contain secrets or machine-specific state. `package-lock.json` is generated but tracked and should change only with intentional dependency changes. `docs/screenshots/` existed locally as an ignored/untracked directory at audit time and was not changed.
