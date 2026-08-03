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

alembic heads      # 568820dfb45d (head)
alembic current    # 568820dfb45d (head), local SQLite
alembic history    # one five-revision chain

cd ../frontend
npm run lint       # pass, no findings
npm run build      # pass; 11 static routes including /_not-found
```

Tests use a dependency-overridden isolated SQLite engine and TestClient; Plaid/LLM are mocked. Coverage is strong for backend domain/auth/error paths but there is no coverage measurement threshold, frontend unit/component/E2E suite, live PostgreSQL migration test, live Plaid test, browser export/Undo test, concurrency test, or production smoke suite. Parameterization makes pytest collect 136 cases although there are 113 `test_` functions.

## Environment variable names

Backend: `APP_NAME`, `DATABASE_URL`, `CORS_ORIGINS`, `JWT_SECRET`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `TOKEN_ENCRYPTION_KEY`, `ANTHROPIC_API_KEY`, `LLM_MODEL`, `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV`, `PLAID_PRODUCTS`, `PLAID_COUNTRY_CODES`, `PLAID_REDIRECT_URI`, and platform-provided `PORT`. Frontend: `NEXT_PUBLIC_API_URL`. Values are intentionally omitted.

## Migrations

Run `alembic upgrade head` from `backend/`. `alembic/env.py` uses `settings.database_url`, not merely the ini default. Review generated revisions and test both upgrade and downgrade on disposable data; do not downgrade production casually. Current chain is documented in [ARCHITECTURE.md](ARCHITECTURE.md).

## CI and production

GitHub Actions runs pytest and npm lint/build on PRs and pushes to `main`. The intended deployment flow is merge/push main → GitHub CI plus external Vercel/Render main-branch deployments. That linkage is configured in vendor dashboards, not repository files.

Render should use `backend/start.sh`; it migrates then starts Uvicorn on `$PORT`. A direct Dockerfile deployment starts Uvicorn but currently cannot migrate because Alembic files are not copied. Expect free/scale-to-zero Render instances to cold-start; the frontend's 15-second request timeout can surface this as “server took too long.” Do not claim an exact cold-start duration.

Vercel should use `frontend` as root, `npm run build`, and production `NEXT_PUBLIC_API_URL`. To verify a commit is Ready: open the Vercel project Deployments view, match the Git SHA/branch, require status **Ready**, inspect build logs, open the deployment, and smoke-test login plus an authenticated API call. Also check backend `/health` and CORS from the production origin. The audit did not have vendor-dashboard evidence and did not live-probe production.

## Troubleshooting

- 401: expired/invalid bearer; browser API clears local session. Credential changes do not revoke older server tokens.
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
