# API reference

Base URL is configured by deployment; local default is `http://localhost:8000`. Except registration, login, health and framework docs, send `Authorization: Bearer <JWT>`. Every `/users/{user_id}/...` handler rejects a JWT/path mismatch with 403; record lookups also scope by owner. FastAPI/Pydantic validation returns 422 unless a handler documents another status.

## Meta and users

| Method/path | Input | Output and behavior |
|---|---|---|
| `GET /health` | None; public | `{"status":"ok"}`. |
| `POST /users` | JSON `email`, password 8–128 | 201 `UserOut`; normalized lowercase email; 409 duplicate. |
| `POST /users/login` | JSON email/password | `TokenOut`; 401 invalid credentials. JWT has `sub`, `iat`, `exp`. |
| `GET /users/me` | Bearer | Current `UserOut`. |
| `PATCH /users/me/email` | `new_email`, `current_password` | Updated `UserOut`; 400 wrong password/same email, 409 duplicate. Existing JWTs remain valid. |
| `PATCH /users/me/password` | `current_password`, `new_password` | 204; 400 wrong/same password. Existing JWTs remain valid. |
| `GET /users/{user_id}` | Bearer | `UserOut`; 403 cross-user. |

## Transactions and import

| Method/path | Input | Output and behavior |
|---|---|---|
| `POST /users/{user_id}/transactions/upload` | multipart `file`; `.csv` filename | `UploadSummary {imported,rejected,duplicates,errors}`. 400 non-CSV. Per-user exact date + trimmed/lower description + amount dedupe. Partial-row success. |
| `GET /users/{user_id}/transactions` | None | All `TransactionOut`, date/id descending, with account/institution. No pagination. |
| `GET /users/{user_id}/transactions/search` | optional `search` ≤120, `category` ≤64, `source` ≤16, positive `account_id`, dates, `pending`, `duplicates_only`, `transaction_type=income|spending`, page ≥1, page_size 1–100 | `TransactionPage` with current filtered items, count/pages and filtered income/spending/net. With `duplicates_only=true`, a row is included when another transaction in the same user's complete corpus has a different id and the same date, amount, and case-insensitive trimmed merchant-or-description identity. Other filters control displayed rows, not the duplicate counterpart search. Search covers description, merchant, category, account and institution. 422 reversed dates. |
| `PATCH /users/{user_id}/transactions/bulk/category` | JSON `transaction_ids` and nonblank category ≤64 | Atomically updates and locks the category for every requested transaction; returns updated transactions in first-requested-ID order. IDs are positive, deduplicated in first-occurrence order, and limited to 100 unique values. Returns 404 without updates if any ID is missing or not owned. |
| `PATCH /users/{user_id}/transactions/bulk/categories` | JSON `updates`, each containing a positive `transaction_id` and nonblank category ≤64 | Atomically applies different category values to as many as 100 transactions, locks every category, and returns updated transactions in request order. Requires at least one update and rejects repeated IDs. Returns 404 without updates if any ID is missing or not owned. Used by category Undo to restore exact prior values in one request. |
| `POST /users/{user_id}/transactions/bulk/delete` | JSON `transaction_ids` | Atomically deletes all requested transactions and returns `{deleted}`. Uses the same positive, deduplicated, 100-ID validation. Returns 404 without deletion if any ID is missing or not owned. |
| `PATCH /users/{user_id}/transactions/{transaction_id}` | JSON nonblank category ≤64 | Updated transaction; sets `category_locked=true`; 404 missing/not owned. |
| `DELETE /users/{user_id}/transactions/{transaction_id}` | None | 204 permanent delete; 404 missing/not owned. No restore endpoint. |

`TransactionOut` contains id, date, description, nullable merchant, signed cents, category, source, pending, nullable account id/name/institution. Search joins account/item only to filter/display; all filters apply to totals as well as items.

## Summaries and analytics

| Method/path | Input | Output and limitations |
|---|---|---|
| `GET /users/{user_id}/summary/by-category` | None | Category totals/counts over all transactions; signed totals. |
| `GET /users/{user_id}/summary/overview` | None | Lifetime income, absolute spending, net and count. |
| `GET /users/{user_id}/summary/by-month` | None | Monthly income/spending/net, chronological. |
| `GET /users/{user_id}/summary/recurring` | None | Detected recurring patterns; algorithmic estimate, requires ≥3 completed occurrences. |
| `GET /users/{user_id}/summary/insights` | required `month=YYYY-MM` | Selected/previous month metrics and generated info/positive/warning insights; 422 invalid month. |
| `GET /users/{user_id}/summary/cash-flow-forecast` | optional `as_of` date | Liquid balance, received/expected income, upcoming bills, projected end balance/risk/flows. Estimate; invalid dates receive validation error. |

## Budgets

| Method/path | Input | Output and behavior |
|---|---|---|
| `GET /users/{user_id}/budgets?month=YYYY-MM` | required month | Month budgets ordered by category. |
| `PUT /users/{user_id}/budgets` | category, month, positive `limit_cents` | Upserts by user/category/month and returns `BudgetOut`. |
| `POST /users/{user_id}/budgets/copy-previous?month=YYYY-MM&overwrite=false` | target month; overwrite boolean | Copy result counts and target budgets; skips existing unless overwrite; 404 when previous month has none. |
| `GET /users/{user_id}/budgets/progress?month=YYYY-MM` | month | Limit, spending, remaining, percent, overage by budget category. Spending uses negative transactions in month. |

## Goals

| Method/path | Input | Output and behavior |
|---|---|---|
| `GET /users/{user_id}/goals` | None | Goals with remaining/progress and active/completed/overdue derived status. |
| `POST /users/{user_id}/goals` | name, positive target, nonnegative saved, optional target date | 201 goal; rejects saved above target. |
| `PATCH /users/{user_id}/goals/{goal_id}` | partial name/target/saved/date | Updated goal; validates combined state; 404 missing/not owned. |
| `DELETE /users/{user_id}/goals/{goal_id}` | None | 204 permanent delete. |

## Plaid and accounts

| Method/path | Input | Output and security/error behavior |
|---|---|---|
| `POST /users/{user_id}/plaid/link-token` | None | Link token; 503 missing config, 502 provider error. |
| `POST /users/{user_id}/plaid/exchange-token` | public token, optional institution id/name | 201 item/status/safe accounts. Encrypts access token before persistence; upserts item/accounts. 409 item belongs to another user; 502/503/500 mapped failures. |
| `POST /users/{user_id}/plaid/sync` | None | Added/modified/removed/items/sync time. Syncs all active user items, applies cursor, preserves locked categories. Empty connections return zero counts. |
| `DELETE /users/{user_id}/plaid/items/{item_id}` | None | 204 after provider removal; preserves transactions but nulls account link. 404 missing/not owned. Local data is retained if provider removal fails. |
| `GET /users/{user_id}/accounts` | None | Safe connected-account metadata/balances and last sync; no access tokens/provider ids. |

Common failures are 401 missing/invalid/expired bearer, 403 path ownership mismatch, 404 owner-scoped resource missing, 409 conflicts, 422 validation, 502 Plaid upstream, 503 missing integration/encryption configuration, and 500 persistence/encryption failures. There is no standardized error envelope beyond FastAPI's `detail`.
