# Current work

Updated: 2026-08-04.

## Integrated scope

FinSight now includes:

- Secure password recovery and advisory email verification
- Vendor-neutral SMTP email delivery
- Fully month-specific budgets
- Hardened Plaid synchronization and connected-account lifecycle

## Authentication recovery

- Reset and verification tokens use 256-bit URL-safe values.
- Only SHA-256 token hashes are stored.
- Password reset atomically consumes the token, updates the Argon2 password hash, increments `token_version`, and invalidates all older JWTs.
- Forgot-password and resend-verification responses do not reveal account existence or verification state.
- Registration and email changes issue verification links.
- Unverified users may continue to log in.
- Production console delivery is prohibited; production email uses configured SMTP.

## Monthly budgets

- Budgets are uniquely stored by user, category, and canonical `YYYY-MM` month.
- List, upsert, delete, copy, and progress operations are selected-month scoped.
- Copy preserves existing target categories by default and supports explicit overwrite through the API.
- Progress uses negative transactions from the selected month and reports spent, signed remaining, percent used, overage, and overspent status.
- No budget migration was required because the original schema already supports monthly records.

## Plaid synchronization

- Manual synchronization tracks `idle`, `syncing`, `succeeded`, `failed`, and reconnect-required lifecycle states.
- Last attempted and last successful synchronization timestamps are persisted separately.
- One conditional database update atomically acquires synchronization ownership.
- Active claims remain protected with 409 responses.
- Claims at least 15 minutes old may be atomically reclaimed.
- Transaction mutations and final cursor updates commit atomically per institution.
- Failed synchronization preserves the previous valid cursor and successful-sync timestamp.
- Repeated provider responses remain idempotent.
- Removed provider transactions are handled safely.
- Disconnect remains provider-first and owner-scoped.
- The Accounts page exposes Sync Now, status, last-sync information, reconnect notices, and safe disconnect confirmation.

## Validation baseline

Expected after complete integration:

- Backend: 203 tests
- Frontend: 23 tests
  - 10 Transactions
  - 5 authentication recovery
  - 2 Budgets
  - 6 Accounts/Plaid
- Frontend lint and production build must pass.
- Alembic must report one head:
  `7d9c2a4e6b10`

## Known limitations

- Recovery and resend endpoints do not yet have shared datastore-backed rate limiting.
- Production SMTP requires environment-specific configuration and smoke testing.
- Email verification is advisory rather than an authorization gate.
- Pending negative transactions count toward budget spending.
- Budget category matching is exact and case-sensitive.
- Arbitrary budget source-month copy and overwrite are API-only.
- Plaid synchronization remains synchronous and covers all connected institutions for the user.
- A crashed Plaid request can delay another sync for up to 15 minutes.
- There is no live Plaid, PostgreSQL concurrency, browser E2E, or production smoke suite.
