# Current work

Updated: 2026-08-03 after adding the focused Transactions-page frontend test foundation. Nothing is committed or pushed.

## Baseline and changed files

The work started from clean `main` at `f100a43052ab4196a23648255fda7a127195b144`, matching `origin/main`.

Frontend test and configuration changes:

- `frontend/app/transactions/page.test.tsx` (new)
- `frontend/test/setup.ts` (new)
- `frontend/vitest.config.mts` (new)
- `frontend/package.json`
- `frontend/package-lock.json`

Production-facing adjustment:

- `frontend/app/transactions/page.tsx` adds accessible labels to the existing bulk and row category controls; behavior is unchanged.

Documentation updates are limited to this file, `IMPLEMENTED_FEATURES.md`, and `TESTING_AND_DEPLOYMENT.md`.

## Test foundation

The frontend now uses Vitest, React Testing Library, `@testing-library/jest-dom`, and jsdom. Vitest resolves the existing `@/` alias, loads a shared DOM setup, and supports deterministic fake-timer tests. The suite mocks authentication/session state, frontend API calls, Next navigation, the sidebar, and Framer Motion; it never calls the backend.

Run the watch mode with `npm test` and the deterministic one-shot suite with `npm run test:run`.

## Transactions regression coverage

Ten rendered-page tests cover bulk category success, stale-selection rejection and refresh, exact mixed-category Undo, category Undo expiry and replacement, optimistic delete Undo, one atomic delete after expiry, full row restoration on delete failure, backend error-detail rendering, and Potential Duplicates compatibility with bulk actions.

## Validation

Run before review:

```bash
cd frontend
npm install
npm run test:run
npm run lint
npm run build

cd ../backend
source venv/bin/activate
pytest -q
alembic heads
alembic current

cd ..
git diff --check
git status --short
```

## Known limitations

- Coverage is intentionally focused on the highest-risk Transactions workflows; authentication redirects, CSV export, sync, filter combinations, pagination, responsive layout, and other pages remain without frontend automated coverage.
- The suite uses mocked API and animation boundaries, so it does not replace browser E2E, live-backend integration, accessibility auditing, or production smoke tests.
- No coverage threshold or coverage-reporting dependency was added.
- The final production dependency audit is clean. One high-severity `brace-expansion` advisory remains confined to ESLint/TypeScript development tooling; no force fix or unrelated framework upgrade was applied.

## Recommended next task

Add focused frontend authentication tests for invalidated-session redirects and the one-time login notice, using this test foundation without introducing a broad component rewrite.
