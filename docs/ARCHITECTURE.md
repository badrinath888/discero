# Architecture

## System context

```text
Browser / Next.js 16 (Vercel)
  localStorage JWT + user id
  HTTPS JSON/multipart REST
FastAPI (Render)
  auth + domain routers
  SQLAlchemy 2 / Alembic
  SQLite local/test | configured PostgreSQL production
  ├─ Plaid Sandbox API
  └─ Anthropic API (optional; deterministic fallback)
```

The frontend is a client-rendered App Router application. Each authenticated page validates the local session through `/users/me` and redirects to `/` when missing/invalid. `app/lib/api.ts` centralizes the base URL, bearer header, JSON/error handling, and a 15-second abort timeout. The backend registers CORS and nine routers in `app/main.py`: `users`, `transactions`, `budgets`, `goals`, `major_purchase`, `recurring`, `safe_to_spend`, `plaid`, and `accounts`. `app/routers/auth.py` is not itself registered; it supplies the shared `get_current_user` dependency that every user-domain route uses to compare the JWT subject to the path `user_id`. Login is implemented directly in `app/routers/users.py`.

## Database model

- `User`: unique indexed email, Argon2 password hash, integer token version, email-verification state, nullable SHA-256 reset/verification token hashes and expirations, and creation time. Owns transactions, budgets, recurring items, goals, and Plaid items with delete-orphan cascades. Raw one-time tokens are never stored.
- `Transaction`: user; optional financial account (`SET NULL` on account removal); globally unique optional Plaid transaction id; date, description, optional merchant, signed integer cents, category, category lock, source, pending flag, timestamps. Positive is income; negative is expense.
- `Budget`: user/category/canonical `YYYY-MM` unique tuple, positive limit in cents. The API requires that same ISO month form for list, upsert, delete, copy, and progress operations.
- `RecurringItem`: user/normalized-merchant unique tuple; merchant, optional category, amount in cents, frequency, last/next payment dates, `suggested`/`active`/lifecycle status, confidence score, and price-change percent/warning. Feeds both the `/recurring` page and Safe-to-Spend's upcoming-obligations calculation.
- `SavingsGoal`: user, name, positive target, nonnegative saved amount (derived from its contributions), optional target date, timestamps. Owns `GoalContribution` rows with delete-orphan cascade.
- `GoalContribution`: goal, signed amount in cents, `deposit`/`withdrawal` type, contributed-on date, optional note, timestamps. A goal's `saved_cents` is the running sum of its contributions; creating a goal with an initial balance records an "Opening balance" deposit rather than setting the balance directly.
- `PlaidItem`: user, globally unique provider item id, institution metadata, encrypted access token, active/reconnect-required connection status, cursor, sync lifecycle status, safe error summary, and attempted/successful timestamps. Owns financial accounts.
- `FinancialAccount`: Plaid item, globally unique provider account id, names/type/subtype/mask, current/available balances, currency, timestamps. Relates to transactions.

Alembic is linear: `93dcf675c7ee` initial user/transaction/budget schema → `f77d39a9c4e0` Plaid items/accounts → `ac2645f928d0` transaction Plaid fields → `383774abbeb5` category lock → `568820dfb45d` savings goals → `c4a8d9e2f1b0` user token version → `e7b1c9d4a2f6` account recovery and email verification → `7d9c2a4e6b10` Plaid synchronization lifecycle → `8adb0528864c` recurring items → `146ccae6e522` goal contributions (head). Monthly-budget expansion required no migration.

## Authentication lifecycle

Registration normalizes email and rejects duplicates, hashes the password with pwdlib's recommended Argon2 hasher, and issues a 24-hour email-verification token. New users start unverified with token version zero. Unverified users may log in, intentionally preserving existing registration/login behavior. Login verifies the hash and issues an HS256 JWT containing string `sub` (user id), integer `ver` (the current user token version), and `exp`; default lifetime is 60 minutes. Authentication loads the user and requires the claim to equal the stored version. Validly signed tokens with a missing, non-integer, or mismatched `ver` receive the generic 401 `session expired; please sign in again`; legacy tokens without `ver` are intentionally rejected. Malformed, expired and unknown-user handling remains separate.

Email and password changes require the current password. Email is normalized, must differ, and must be unique; a successful email change marks the new address unverified and sends a new verification link. New password must differ and meet the schema's 8-character minimum. Each successful credential change increments the token version exactly once in the same commit, invalidating every older token immediately; rejected changes do not increment it. The Settings UI clears local storage and redirects to login. Shared frontend 401 handling also clears authentication and carries a one-time sign-in-again notice to the login page for version-invalidated sessions.

Forgot-password and resend-verification accept an email but always return the same public response for unknown, already-verified, and applicable accounts. Tokens use `secrets.token_urlsafe(32)`; only SHA-256 hashes and expirations are persisted. Reset links expire after 30 minutes and verification links after 24 hours by default. Reset and verification consume their hash with one conditional database update, making reuse and concurrent double-submit fail safely. A successful reset replaces the Argon2 hash, increments `token_version`, clears the token, and invalidates every JWT. There are no refresh tokens, per-device sessions, denylist, endpoint rate limits, or account deletion.

Email delivery is isolated in `app/services/email_service.py`. The development environment template enables token-safe console delivery metadata; the application itself defaults to production mode, where console delivery is prohibited. Deployments may use authenticated SMTP with optional TLS or Resend's HTTPS API, selected by `EMAIL_BACKEND`; Resend requires `RESEND_API_KEY`, and both providers use `EMAIL_FROM`. Provider failures become generic internal delivery errors and are logged without exception details, message bodies, links, tokens, API keys, or SMTP passwords, while public endpoints retain enumeration-safe responses.

## Data flows

### CSV import

`POST /transactions/upload` accepts only a filename ending `.csv`. UTF-8 BOM is tolerated. Case-insensitive aliases are: date (`date`, `posted_on`, `transaction date`, `posted date`), description (`description`, `name`, `memo`, `details`), and amount (`amount`, `amount_cents`, `value`). Dates accept ISO, US long/short, or `DD-MM-YYYY`; money is parsed with decimal half-up to cents. Bad rows are reported without aborting valid rows.

Duplicates are prevented per user by exact date + trimmed/lowercased description + amount, against stored transactions and earlier rows in the same upload. This does not normalize punctuation/internal whitespace or use merchant, account, or source. Accepted descriptions are categorized in one batch and stored as CSV-source transactions.

### Categorization

Deterministic keyword rules cover nine categories with `Uncategorized` fallback. With `ANTHROPIC_API_KEY`, `LLMCategorizer` batches distinct uncached descriptions, asks for one allowed category per item, caches in process memory, and falls back to rules for errors, invalid categories, or wrong-length output. The broad exception handler preserves imports but hides provider error detail; cache is not persistent or user-correction-aware.

### Plaid

The browser requests a link token, Plaid Link supplies a public token, and the API exchanges it, encrypts the access token with Fernet, upserts the item/accounts, and returns safe account fields. Manual sync works per owner-scoped item: one conditional update atomically claims non-syncing items or UTC claims at least 15 minutes old, refreshes the attempt timestamp, and rejects recent/competing claims. It requests every Plaid cursor page from the last committed cursor, then applies added/modified/removed transactions and the final cursor in one database commit. Provider transaction ids are upserted, repeated pages remain idempotent, account mappings must belong to the item, and manually locked categories are preserved. A failure rolls back data/cursor changes and separately records `failed` with a bounded safe summary; `ITEM_LOGIN_REQUIRED` also marks the connection `reconnect_required`. A retry or stale-claim recovery starts from the last valid cursor.

Disconnect loads the item by both local id and user, calls Plaid before local deletion, and retains local data when the provider call fails. After provider success, deleting the item cascades its accounts while the account foreign key on historical transactions becomes null, preserving transaction history. Provider/config/encryption failures map to 502/503/500 responses. Safe status/account responses exclude access tokens, provider identifiers, and cursors. Provider item/account/transaction uniqueness remains global rather than `(user, provider id)`.

### Analytics

Summary endpoints compute overview, category/month totals, recurring patterns, insights, and cash-flow forecasts from stored transactions/accounts. Algorithmic recurring detection (`app/recurring.py`, `detect_recurring`) ignores pending activity, normalizes merchant/reference noise, requires three completed occurrences, recognizes weekly/biweekly/monthly cadence with tolerance, and emits confidence/price-change signals. Forecasts combine liquid balances, income pace, and detected recurring payments; these are estimates, not guarantees.

### Recurring items

`RecurringItem` rows (`app/routers/recurring.py`, prefix `/users/{user_id}/recurring-items`) are a user-owned, persisted list distinct from the algorithmic detection above: the `/recurring` page surfaces both the detected suggestions from `summary/recurring` and the persisted items, and a suggestion can be saved as a tracked item. Create validates that merchant/normalized-merchant are non-empty and relies on the user/normalized-merchant unique constraint to reject duplicates (409). Update accepts partial changes to category, amount, frequency, next payment, and status. Only `active`-status items with a `next_payment` inside the requested horizon count as upcoming obligations for Safe-to-Spend.

### Goal contributions

Each `SavingsGoal` no longer stores a balance directly; `GoalContribution` rows (`app/routers/goals.py`, `/users/{user_id}/goals/{goal_id}/contributions`) record dated deposits/withdrawals, and `saved_cents` is maintained as their running signed sum. Creating, updating, or deleting a contribution recomputes the goal's projected balance and rejects the change with a 422 if it would go negative; update recalculates the balance excluding the contribution being edited. Creating a goal with a nonzero opening `saved_cents` writes a synthetic "Opening balance" deposit rather than setting the column directly, so the contribution history stays authoritative.

### Safe-to-Spend, Major Purchase Simulator, and Scenario Comparison

`app/services/safe_to_spend_service.py` (`POST /users/{user_id}/safe-to-spend`) computes a liquid balance from active Plaid accounts of type `depository`/`cash` (preferring available balance, falling back to current balance with a warning), subtracts upcoming `RecurringItem` obligations due within `horizon_days` (default 30, 1–90), an essential-spending amount, and a safety reserve, and reports `safe`, `limited`, or `negative` status with a confidence score blended from obligation confidence and whether a liquid balance exists.

`app/services/major_purchase_service.py` (`POST /users/{user_id}/major-purchase/simulate`) runs a Safe-to-Spend calculation as of the purchase inputs, then evaluates one purchase against it: `affordable`, `caution` (exceeds a 75%-of-safe-to-spend recommended ceiling), or `not_affordable` (exceeds the safe-to-spend amount). It returns a plain-language explanation and up to two alternative amounts (a conservative 50% option and the recommended ceiling), each only included if it is cheaper than the requested purchase. The purchase date must fall between the calculation date and the Safe-to-Spend horizon's `through_date`, or the endpoint returns 422.

`app/services/scenario_comparison_service.py` (`POST /users/{user_id}/major-purchase/compare`) runs two independent major-purchase simulations (`option_a`, `option_b`) and ranks them by affordability status, then shortfall, then remaining safe-to-spend, then impact percent, then cost, returning the recommended option (or `tie`) with a generated reason and the cent/percent differences between options.

The `/decisions` page exposes both single-purchase simulation and side-by-side comparison modes against these endpoints.

### Transaction bulk mutations and Undo

Bulk category and delete requests validate up to 100 positive transaction IDs, then load the complete owner-scoped set before changing any row. A missing or cross-user ID produces a 404 before mutation, preventing partial writes and avoiding disclosure of another user's records. The single-category endpoint deduplicates IDs in first-occurrence order. The mixed-category endpoint rejects repeated IDs, applies one validated category per transaction, locks every category, and returns rows in request order. Deletes return the number removed. Each endpoint commits once.

The Transactions page optimistically removes selected rows but waits six seconds before calling the atomic bulk-delete endpoint. Delete Undo clears that timer and restores local state without making a delete request. Once the timer expires, one request deletes the entire set; a request failure restores every optimistically removed row. Single-row deletion uses the same bulk endpoint with one ID.

Single and bulk category changes commit immediately, capture the exact previous values in browser memory, and expose Undo for six seconds. Category Undo sends one mixed-category request so restoration is atomic even when prior categories differ. Expiry or toast dismissal only clears the local opportunity; it sends no request. Generation-guarded timers prevent an older callback from clearing a newer operation. A new category or delete operation replaces the prior category Undo, and one shared action toast prevents category and delete Undo from appearing together.

## Frontend architecture and routes

All authenticated pages use `AppSidebar`, responsive desktop/mobile navigation, reusable motion respecting reduced-motion preferences, and page-specific loading/error/empty states.

- `/`: marketing plus login/register; validates existing token; form validation and inline auth errors.
- `/dashboard`: loads overview, categories, budgets, all transactions, goals, forecast, and Safe-to-Spend; charts/KPIs, CSV upload, links to detail pages; bespoke loading/error/empty presentation.
- `/transactions`: server search/filter/pagination, accounts, category edit, Plaid sync, bulk selection/category/delete, confirmation, success/error and six-second Undo toasts, detail drawer.
- `/accounts`: accounts plus transactions; portfolio totals/grouping/detail drawer, Plaid connect/sync/disconnect with confirmation and toast.
- `/budgets`: monthly budgets/progress; save/edit drawer, copy previous month, overwrite choice, progress visuals and toast.
- `/recurring`: combines detected recurring payments with persisted recurring items (create/update/delete); totals, due timing, warnings, rows/detail drawer; transaction CTA when empty.
- `/forecast`: forecast API; balance scenario, upcoming flows, risk/empty state and detail drawer.
- `/goals`: goal CRUD, contribution/withdrawal history per goal, status/progress, form/detail drawers, deletion confirmation/toast.
- `/insights`: selected-month insights, metrics/severity filtering, rows/detail drawer and empty CTA.
- `/decisions`: Safe-to-Spend summary card plus single-purchase simulation and side-by-side scenario comparison modes; status badges, explanation text, and alternative-amount suggestions.
- `/settings`: profile, account/transaction counts, password/email changes, logout, client-side CSV export; password visibility and toast errors/success.
- `/forgot-password`: public email submission with enumeration-safe success and error/loading states.
- `/reset-password`: token-based password replacement, invalid/expired state, and local session clearing on success.
- `/verify-email`: automatic token verification plus a public resend action.
- `/_not-found`: Next.js generated not-found route; there is no repository-authored page.

Next.js's app-router route manifest reports 17 routes: the 14 application pages above (including `/`) plus the generated `/_not-found`, `/_global-error`, and `/favicon.ico` entries.

See [FILE_MAP.md](FILE_MAP.md) for component responsibilities and [API_REFERENCE.md](API_REFERENCE.md) for calls.

## Deployment

GitHub Actions validates backend on Python 3.12 and frontend on Node 24 for pushes to `main` and pull requests. `backend/start.sh` applies `alembic upgrade head` and starts Uvicorn on `$PORT` (default 8000), matching Render-style deployment. The Dockerfile starts Uvicorn but does **not** run migrations. Vercel builds the Next app using `NEXT_PUBLIC_API_URL`; the repository has no `vercel.json` or checked-in Render blueprint, so dashboard configuration is external. Production health/readiness and the supplied URLs were not network-verified during this audit.
