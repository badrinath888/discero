# Current work

Updated: 2026-08-03. Nothing is committed or pushed.

## Baseline and scope

This isolated worktree started clean at requested main baseline `eb9e2082577de39519450b006ade25276c9a335c`. The active change implements secure password recovery, email verification, vendor-neutral email delivery, focused backend/frontend tests, one coordinated Alembic migration, and the required documentation updates.

## Design decisions

- Raw reset and verification tokens are generated with `secrets.token_urlsafe(32)`, delivered once, and represented in the database only by SHA-256 hashes.
- Reset tokens expire after 30 minutes; verification tokens expire after 24 hours. Both durations are configurable.
- Conditional database updates atomically validate expiration and consume token hashes, preventing sequential reuse and concurrent double-submit.
- Successful password reset replaces the Argon2 hash, increments `token_version`, invalidates all JWTs, and clears the reset fields in the same transaction.
- Forgot-password and resend-verification responses do not reveal account existence or verification state.
- Unverified users may continue to log in and use FinSight. This preserves existing registration/login behavior. Email changes mark the new address unverified.
- The development environment template uses console email delivery. Runtime defaults are fail-closed production mode, where console delivery is blocked; the vendor-neutral SMTP backend uses TLS by default and does not log raw links or tokens.

## Files and validation

Backend changes touch the user model/config/security/router/schemas, one email service, one migration, `.env.example`, and focused recovery tests. Frontend changes add three recovery routes, a shared recovery card, API methods, a login link, and five mocked component tests.

Current results: 186 backend tests pass; all 15 frontend tests pass; frontend lint and production build pass; Alembic reports the single head `e7b1c9d4a2f6`. The default worktree database is fresh/unversioned, so `alembic current` is blank; the full SQLite upgrade, downgrade of this revision, and re-upgrade were verified against a disposable database at head.

Run before review:

```bash
cd backend
source venv/bin/activate
pytest -q
alembic heads
alembic current

cd ../frontend
npm run test:run
npm run lint
npm run build

cd ..
git diff --check
git status --short
```

## Known limitations

- The existing stack has no shared rate limiter. Production should add datastore-backed throttling for forgot-password and resend-verification.
- SMTP delivery needs environment-specific integration/smoke testing; automated tests replace delivery with a capture function.
- Verification is advisory, not an authorization gate.
- The application has no browser E2E suite, live PostgreSQL migration test, or production email smoke test.
