# Current work

Updated: 2026-08-03 after implementing atomic transaction bulk operations. Nothing is committed or pushed.

## Baseline and changed files

The work started from clean `main` at `dcca7ef98c5e199c0b83df07c0b068f8b1ea8cfd`, matching `origin/main`. No migration or dependency change is required.

Current implementation files:

- `backend/app/schemas.py`
- `backend/app/routers/transactions.py`
- `backend/tests/test_transaction_bulk.py` (new)
- `frontend/app/lib/api.ts`
- `frontend/app/transactions/page.tsx`

Documentation updates are limited to this file, `API_REFERENCE.md`, `IMPLEMENTED_FEATURES.md`, and `ARCHITECTURE.md`.

## Atomic bulk endpoints

`PATCH /users/{user_id}/transactions/bulk/category` accepts transaction IDs and a category. `POST /users/{user_id}/transactions/bulk/delete` accepts transaction IDs and returns a deletion count. Both routes are declared before `/transactions/{transaction_id}`.

Shared Pydantic validation:

- requires at least one ID
- requires positive integer IDs
- deduplicates repeated IDs while preserving first occurrence
- allows at most 100 unique IDs

Both handlers authenticate the caller, enforce path-user ownership, and load the complete owner-scoped transaction set before mutation. If any requested ID is missing or belongs to another user, the request returns 404 and changes nothing. Category updates trim and validate the category using the existing single-update constraints, set every `category_locked` flag, commit once, and return transactions in requested order. Delete commits once and returns `{deleted}`. Cross-user and missing-ID errors use the same message to avoid record disclosure.

## Frontend behavior

The API client exposes `bulkUpdateTransactionCategory` and `bulkDeleteTransactions`. The Transactions page no longer uses `Promise.all` for bulk mutations:

- selected category changes use one PATCH request
- both single and multi-row permanent deletion use one POST request
- confirmation, selection, optimistic totals, Potential duplicates, notifications, and error restoration are preserved
- Undo before six seconds cancels the timer and sends no backend delete
- after six seconds one atomic delete request is sent
- if it fails, every optimistically removed transaction and aggregate is restored

## Tests and verification

Focused backend tests cover successful category/delete, duplicate IDs, empty/zero/negative IDs, the 100-ID limit, blank category, missing-ID rollback, cross-user rollback, category locks, no partial updates/deletes, authentication, and deterministic response ordering.

Run before review:

```bash
cd backend
source venv/bin/activate
pytest -q
alembic heads
alembic current

cd ../frontend
npm run lint
npm run build

cd ..
git diff --check
git status --short
```

## Known limitations

- Bulk size is capped at 100 unique IDs.
- Undo remains in browser memory; navigation/reload before the timer fires can cancel the pending timer through component cleanup while leaving optimistic UI state irrelevant after navigation.
- The backend has no restore endpoint after a successful delete.
- The repository still has no frontend automated test harness, so the delayed request behavior is lint/build verified rather than browser-test verified.

## Recommended next task

Add a small frontend test harness and cover delayed bulk deletion, Undo cancellation, backend failure restoration, and overlapping user actions before changing the UX further.
