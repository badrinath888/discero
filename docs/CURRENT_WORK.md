# Current work

Updated: 2026-08-03 after completing Potential Duplicates. Nothing is committed or pushed.

## Git state

The branch remains `main` at `6633c2f3ef541fe73a030df91eb5086c0994ff4b`, matching the last audited `origin/main`. Application changes are limited to:

- `backend/app/routers/transactions.py`
- `backend/tests/test_transaction_search.py`
- `frontend/app/lib/api.ts`
- `frontend/app/transactions/page.tsx`

Documentation changes for this feature are limited to this file, `IMPLEMENTED_FEATURES.md`, and `API_REFERENCE.md`. The audit documentation remains untracked. No migration was added.

## Potential Duplicates: implemented behavior

`GET /users/{user_id}/transactions/search?duplicates_only=true` now uses a correlated `EXISTS` query with an aliased `Transaction`. A displayed transaction is a candidate when another row has:

- the same `user_id`
- a different transaction id
- the same `posted_on`
- the same `amount_cents`
- the same normalized identity

The identity expression is the conservative, SQLite/PostgreSQL-compatible MVP expression:

```text
lower(trim(coalesce(nullif(trim(merchant_name), ''), description)))
```

A non-empty trimmed merchant takes precedence; null/blank merchant falls back to description. Only case and edge whitespace are normalized. The correlated lookup searches the user's complete transaction corpus, while search/category/source/account/date/pending/type filters control displayed group members. `EXISTS` returns each matching transaction once, so counts, aggregates and pagination are not multiplied. Omitted or false `duplicates_only` preserves the previous search behavior. No deletion is automatic.

The Transactions page has an accessible `role="switch"` Potential duplicates control beside Filters. Enabling it sends `duplicates_only=true`, resets to page 1, increments the active filter count, and shows duplicate-specific empty copy. Clear filters disables it. Existing checkbox selection, category update, confirmation, bulk deletion and six-second Undo behavior are reused without redesign.

## Verification

Focused transaction-search suite:

```text
11 passed
```

Full validation:

```text
143 passed, 2 pytest cache-write warnings
frontend lint: passed
frontend production build: passed
git diff --check: passed
```

The two pytest warnings are audit-sandbox cache permissions, not test failures. Added coverage verifies omitted/false behavior, all members, distinct ids, amount/date mismatch exclusion, user isolation, merchant case/edge trimming, blank/null fallback, merchant precedence, CSV/Plaid and same-source groups, three-member uniqueness, totals, pagination, and composition with search/category/source/account/date/pending/type filters.

## Known limitations and follow-up

- Conservative normalization does not collapse punctuation, reference numbers, accents, or internal whitespace.
- Same-source and cross-source matches are intentionally both shown; pending and posted rows may therefore be candidates when date/amount/identity match.
- The feature identifies candidates for human review and never decides which row is authoritative.
- Frontend behavior is lint/build verified; the repository still has no frontend automated test harness.
- Bulk operations remain multiple non-atomic requests, and Undo remains a client-side delayed delete rather than server restoration.
- `CODEX_HANDOFF.md` and `TESTING_AND_DEPLOYMENT.md` retain the earlier 136-test audit baseline because this task permitted documentation updates only to three named files; the current verified count is 143.

## Recommended next task

Add browser-level coverage for the Potential duplicates toggle, selection, deletion confirmation and Undo once a frontend test harness is approved. Do not broaden normalization until real false-positive/false-negative examples justify it.
