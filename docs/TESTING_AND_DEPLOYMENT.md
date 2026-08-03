# Testing and deployment

## Local setup and commands

Backend requires Python 3.12 to match Docker/CI (README's “3.11+” is broader than verified). Copy `.env.example` to ignored `.env`, generate distinct strong JWT/Fernet secrets, install, migrate and run:

```bash
cd backend
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

API is port 8000; Swagger `/docs`. Frontend uses Node 24 in CI:

```bash
cd frontend
npm ci
# create ignored .env.local with NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Frontend is port 3000. Never print or commit either real env file.

## Validation baseline (2026-08-03)

```bash
cd backend && source venv/bin/activate && pytest -q
# 136 passed in 7.42s; two cache-write warnings caused by audit sandbox permissions

alembic heads      # c4a8d9e2f1b0 (head)
alembic current    # c4a8d9e2f1b0 (head), local SQLite
alembic history    # one six-revision chain

cd ../frontend
npm run test:run  # 10 Transactions-page regression tests
npm run lint       # pass, no findings
npm run build      # pass; 11 static routes including /_not-found
```

Backend tests use a dependency-overridden isolated SQLite engine and TestClient; Plaid/LLM are mocked. Frontend component tests use Vitest, React Testing Library, jest-dom and jsdom with API/session/navigation/animation boundaries mocked, so they do not call the backend. The focused Transactions suite covers category and delete bulk workflows, six-second Undo timers, stale selections, backend error details, and Potential Duplicates compatibility.

Run frontend tests in watch mode with `npm test` or once with `npm run test:run`. There is no coverage measurement threshold, browser E2E suite, live PostgreSQL migration test, live Plaid test, CSV-export browser test, concurrency test, or production smoke suite.

The dependency audit reviewed on 2026-08-03 uses narrow overrides for patched PostCSS `8.5.25` and Sharp `0.35.3` without changing Next.js or React. `npm audit --omit=dev` reports zero vulnerabilities. The full `npm audit` retains one high-severity `brace-expansion` advisory confined to ESLint/TypeScript development tooling; no force fix was used.

## Environment variable names

Backend: `APP_NAME`, `DATABASE_URL`, `CORS_ORIGINS`, `JWT_SECRET`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `TOKEN_ENCRYPTION_KEY`, `ANTHROPIC_API_KEY`, `LLM_MODEL`, `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV`, `PLAID_PRODUCTS`, `PLAID_COUNTRY_CODES`, `PLAID_REDIRECT_URI`, and platform-provided `PORT`. Frontend: `NEXT_PUBLIC_API_URL`. Values are intentionally omitted.

## Migrations

Run `alembic upgrade head` from `backend/`. `alembic/env.py` uses `settings.database_url`, not merely the ini default. Review generated revisions and test both upgrade and downgrade on disposable data; do not downgrade production casually. Current chain is documented in [ARCHITECTURE.md](ARCHITECTURE.md).

Revision `c4a8d9e2f1b0` adds `users.token_version` as a non-null integer with server default zero. Deploy through `backend/start.sh` so the migration completes before the new authentication code serves requests. The release intentionally signs out every browser holding a legacy token without `ver`; users must log in once to receive a versioned token.

## CI and production

GitHub Actions runs pytest and npm lint/build on PRs and pushes to `main`. The intended deployment flow is merge/push main → GitHub CI plus external Vercel/Render main-branch deployments. That linkage is configured in vendor dashboards, not repository files.

Render should use `backend/start.sh`; it runs `alembic upgrade head` and only then executes `uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"`. The Dockerfile copies the Alembic configuration/revisions and uses the same script as its `CMD`, so both documented native and container starts migrate before serving. The repository has no `render.yaml` or Procfile; confirm the external Render dashboard command points to `./start.sh` when using the native runtime. Expect free/scale-to-zero Render instances to cold-start; the frontend's 15-second request timeout can surface this as “server took too long.” Do not claim an exact cold-start duration.

Vercel should use `frontend` as root, `npm run build`, and production `NEXT_PUBLIC_API_URL`. To verify a commit is Ready: open the Vercel project Deployments view, match the Git SHA/branch, require status **Ready**, inspect build logs, open the deployment, and smoke-test login plus an authenticated API call. Also check backend `/health` and CORS from the production origin. The audit did not have vendor-dashboard evidence and did not live-probe production.

## Troubleshooting

- 401: expired/invalid bearer or version-invalidated session; browser API clears local authentication. Version mismatches and legacy tokens return `session expired; please sign in again`, which the login page displays once.
- 403: URL `user_id` differs from JWT subject.
- Plaid 503: credentials or Fernet key absent/invalid; 502: provider failure.
- CORS: ensure exact frontend origin (without trailing slash after normalization) appears in `CORS_ORIGINS`.
- Build API URL: `NEXT_PUBLIC_*` is embedded at build time; redeploy after changes.
- Database: confirm `DATABASE_URL`, `alembic current`, and one head before starting.
- Cold start: retry after backend health is responsive; consider an appropriate hosting plan/health strategy.

## Rollback

1. Identify the last known-good Git SHA and preserve database backups/logs.
2. Prefer vendor rollback/redeploy of that immutable frontend/backend artifact; do not force-reset shared `main`.
3. If a code revert is needed, create a normal revert commit and let CI/deploy run.
4. Treat schema rollback separately: determine backward compatibility; restore backup or run a specifically reviewed downgrade only when safe. A code rollback after a forward-compatible migration often leaves schema in place.
5. Verify Vercel status/commit, backend `/health`, migrations, auth, one data read, CORS, and logs. Rotate exposed secrets independently of code rollback.
