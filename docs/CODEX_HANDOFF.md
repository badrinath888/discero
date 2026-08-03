# FinSight Codex handoff

Last audited: 2026-08-03. Repository: `~/Desktop/finance-platform`; remote: `https://github.com/badrinath888/finsigh.git`; primary branch: `main`. Production URLs supplied by the owner are `https://finsigh.vercel.app` and `https://finsigh.onrender.com` (not live-probed in this repository-only audit).

## Start here

FinSight is a personal-finance web app. A Next.js 16/React 19 browser client calls a FastAPI/SQLAlchemy API with bearer JWTs. SQLite is the local/test default; configuration and `psycopg2-binary` support PostgreSQL. Plaid Sandbox connection/sync and optional Anthropic categorization are server integrations.

At audit time, `HEAD == origin/main == 6633c2f` and the checked-out branch is `main`. The application baseline validates: **136 backend tests pass**, frontend lint passes, frontend production build passes, and Alembic reports the database at its single head `568820dfb45d`. Two pre-existing modified files contain an incomplete Potential Duplicates experiment; see [CURRENT_WORK.md](CURRENT_WORK.md). The eight files in `docs/` are audit-only additions.

## Safety rules for future sessions

- Read `git status`, `git diff`, and [CURRENT_WORK.md](CURRENT_WORK.md) before editing.
- Preserve the two existing duplicate-feature edits unless explicitly completing or reverting them.
- Never print `.env` or `.env.local`; use `.env.example` and document variable names only.
- Do not edit generated/ignored `venv/`, `node_modules/`, `.next/`, caches, `finance.db`, or `next-env.d.ts`.
- Use Alembic for schema changes; never run destructive database commands without explicit approval.
- Do not call behavior “working” without current tests/build/runtime evidence. Repository code can establish implementation, not production availability.
- Keep user ownership checks, integer-cent money, token encryption, category locks, and existing UI patterns intact.

## Documentation map

- [ARCHITECTURE.md](ARCHITECTURE.md): components, models, auth, CSV/Plaid/categorization data flows, deployment.
- [FILE_MAP.md](FILE_MAP.md): tracked source/config map and generated-file exclusions.
- [API_REFERENCE.md](API_REFERENCE.md): complete application endpoint reference.
- [IMPLEMENTED_FEATURES.md](IMPLEMENTED_FEATURES.md): implemented features, evidence, history, limitations.
- [TESTING_AND_DEPLOYMENT.md](TESTING_AND_DEPLOYMENT.md): setup, validation, migrations, deploy/rollback.
- [ROADMAP.md](ROADMAP.md): ranked future work.
- [CURRENT_WORK.md](CURRENT_WORK.md): exact dirty state and Potential Duplicates plan.

## Validation commands

```bash
cd ~/Desktop/finance-platform
git status --short
git diff
git diff --cached
git rev-parse HEAD
git rev-parse origin/main

cd backend
source venv/bin/activate
pytest -q
alembic heads
alembic current
alembic history

cd ../frontend
npm run lint
npm run build
```

Local servers: `cd backend && source venv/bin/activate && alembic upgrade head && uvicorn app.main:app --reload` on port 8000; `cd frontend && npm run dev` on port 3000.
