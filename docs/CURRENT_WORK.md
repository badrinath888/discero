# Current work

Updated: 2026-08-03 for the month-specific budgets implementation. Nothing is committed or pushed.

## Baseline and scope

This isolated worktree started clean at `eb9e2082577de39519450b006ade25276c9a335c`, matching `main` and `origin/main`. The main checkout was not modified.

The existing initial schema already stores each budget with a canonical `YYYY-MM` month and enforces one row per user/category/month. No Alembic revision or data backfill was necessary.

Changed application files:

- `backend/app/routers/budgets.py`
- `backend/app/schemas.py`
- `backend/tests/test_budgets.py`
- `frontend/app/budgets/page.tsx`
- `frontend/app/budgets/page.test.tsx` (new)
- `frontend/app/lib/api.ts`

Budget documentation was updated in `API_REFERENCE.md`, `ARCHITECTURE.md`, `IMPLEMENTED_FEATURES.md`, and `TESTING_AND_DEPLOYMENT.md`.

## Monthly budget behavior

- List and upsert require an explicit ISO `YYYY-MM` month.
- Delete is scoped to the authenticated user, category, and selected month.
- Copy accepts distinct source and target months, preserves existing target categories by default, and supports explicit overwrite. The copy-previous endpoint remains compatible.
- Progress uses negative transactions from the selected calendar month only and returns spent, signed remaining, percent used, overage, and explicit overspent status.
- The Budgets page selects and displays one month at a time, distinguishes at-limit from overspent budgets, copies the prior plan through the general month-to-month API, and confirms selected-month deletion.

## Validation

- Backend: `181 passed` with Python 3.12.
- Focused budget backend suite: `16 passed`.
- Frontend: `12 passed` across the Transactions and Budgets page suites.
- Frontend lint: pass.
- Frontend production build: pass, including TypeScript and all static routes.
- Alembic: one head, `c4a8d9e2f1b0`; a disposable SQLite database upgraded from base to head and reported current at head.
- `git diff --check`: pass.

## Known limitations

- Frontend component tests mock the API, session, navigation, and animation boundaries; they are not browser E2E or live-backend tests.
- Copy overwrite is supported by the API, while the current page action intentionally preserves any already-configured target categories.
- There is no live PostgreSQL migration or production smoke test in this worktree.
