# Current work

Updated: 2026-08-03 after implementing atomic category Undo. Nothing is committed or pushed.

## Baseline and changed files

The work started from clean `main` at `8da0e6d2d84cdbae1afa16fb2aa19a3a498930bd`, matching `origin/main`. No migration or dependency change is required.

Current implementation files:

- `backend/app/schemas.py`
- `backend/app/routers/transactions.py`
- `backend/tests/test_transaction_bulk.py`
- `frontend/app/lib/api.ts`
- `frontend/app/transactions/page.tsx`

Documentation updates are limited to this file, `API_REFERENCE.md`, `IMPLEMENTED_FEATURES.md`, and `ARCHITECTURE.md`.

## Atomic category Undo

`PATCH /users/{user_id}/transactions/bulk/categories` accepts one to 100 unique transaction/category pairs. It requires positive IDs and trimmed, nonblank categories no longer than 64 characters. Duplicate IDs are rejected because repeated entries could specify conflicting values. The handler authenticates, enforces path ownership, loads the full owner-scoped set before mutation, sets every `category_locked` flag, commits once, and returns rows in request order. Missing or cross-user IDs reject the entire request with no partial update.

The Transactions page captures each previous category before a successful single or bulk change. The committed update is shown immediately with a six-second Undo action. Undo calls the mixed-category endpoint once and replaces the page rows with the atomic response. Failure leaves the newly applied categories visible and surfaces the backend error.

Only one Undo action is displayed. Starting another category change replaces the older category opportunity; starting a deletion clears it. Starting a category change hides an existing delete Undo without cancelling the already-scheduled delete, matching the existing close behavior. Category expiry and close only clear browser state and never call the backend. Both timers are cleared on unmount, and category timers use a generation check so stale callbacks cannot clear newer state.

## Atomic bulk endpoints

`PATCH /users/{user_id}/transactions/bulk/category` accepts transaction IDs and a category. `POST /users/{user_id}/transactions/bulk/delete` accepts transaction IDs and returns a deletion count. Both routes are declared before `/transactions/{transaction_id}`.

Shared Pydantic validation:

- requires at least one ID
- requires positive integer IDs
- deduplicates repeated IDs while preserving first occurrence
- allows at most 100 unique IDs

Both handlers authenticate the caller, enforce path-user ownership, and load the complete owner-scoped transaction set before mutation. If any requested ID is missing or belongs to another user, the request returns 404 and changes nothing. Category updates trim and validate the category using the existing single-update constraints, set every `category_locked` flag, commit once, and return transactions in requested order. Delete commits once and returns `{deleted}`. Cross-user and missing-ID errors use the same message to avoid record disclosure.

## Frontend behavior

The API client exposes `bulkUpdateTransactionCategory`, `bulkUpdateTransactionCategories`, and `bulkDeleteTransactions`. The Transactions page uses atomic requests for bulk mutations and category restoration:

- selected category changes use one PATCH request
- single and bulk category Undo use one mixed-category PATCH request
- both single and multi-row permanent deletion use one POST request
- confirmation, selection, optimistic totals, Potential duplicates, notifications, and error restoration are preserved
- Undo before six seconds cancels the timer and sends no backend delete
- after six seconds one atomic delete request is sent
- if it fails, every optimistically removed transaction and aggregate is restored

## Tests and verification

Focused backend tests cover successful single-category, mixed-category and delete operations; duplicate IDs; empty/zero/negative IDs; the 100-ID limit; blank categories; missing-ID and cross-user rollback; category locks; no partial updates/deletes; authentication; and deterministic response ordering.

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

Add a small frontend test harness and cover delayed bulk deletion, category Undo restoration, timer replacement, Undo cancellation, backend failure restoration, and overlapping user actions before changing the UX further.
