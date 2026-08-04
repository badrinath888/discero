# Current work

Updated: 2026-08-04.

## Integrated scope

FinSight now includes secure password recovery, advisory email verification, vendor-neutral SMTP delivery, and fully month-specific budgets.

## Authentication recovery

- Reset and verification tokens use 256-bit URL-safe values, while only SHA-256 hashes are stored.
- Reset tokens expire after 30 minutes and verification tokens after 24 hours by default.
- Password reset atomically consumes the token, replaces the Argon2 password hash, increments `token_version`, and invalidates all older JWTs.
- Forgot-password and resend-verification responses do not reveal whether an account exists or is already verified.
- Registration and email changes issue verification links; unverified users may continue to log in.
- Production console email delivery is prohibited. SMTP settings are supplied through environment variables.

## Monthly budgets

- Budgets are uniquely stored by user, category, and canonical `YYYY-MM` month.
- List, upsert, delete, copy, and progress operations are scoped to the selected month.
- Copy preserves existing target categories by default and supports explicit overwrite through the API.
- Progress uses negative transactions from the selected month and reports spent, signed remaining, percent used, overage, and overspent status.
- No budget migration was required because the original schema already supports monthly records.

## Validation baseline

- Backend: 192 tests expected after integrating account recovery and monthly-budget suites.
- Frontend: 17 tests expected: 10 Transactions, 5 authentication recovery, and 2 Budgets.
- Frontend lint and production build must pass.
- Alembic must report the single head `e7b1c9d4a2f6`.

## Known limitations

- Recovery and resend endpoints do not yet have shared datastore-backed rate limiting.
- Production SMTP requires environment-specific configuration and smoke testing.
- Email verification remains advisory rather than an authorization gate.
- Pending negative transactions count toward budget spending.
- Budget category matching is exact and case-sensitive.
- Arbitrary source-month copy and overwrite are API-only; the UI currently exposes copy-previous with preserve-existing behavior.
- There is no browser E2E suite, live PostgreSQL integration suite, or production email smoke test.
