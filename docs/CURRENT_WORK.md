# Current work

Updated: 2026-08-03 after implementing per-user JWT invalidation. Nothing is committed or pushed.

## Baseline and changed files

The work started from clean `main` at `a650477e006160561f61ebe18e14f22f80194f0a`, matching `origin/main`.

Backend changes:

- `backend/app/models.py`
- `backend/app/security.py`
- `backend/app/auth.py`
- `backend/app/routers/auth.py`
- `backend/app/routers/users.py`
- `backend/alembic/versions/c4a8d9e2f1b0_add_user_token_version.py` (new)
- `backend/tests/test_token_version.py` (new)

Frontend changes:

- `frontend/app/lib/api.ts`
- `frontend/app/page.tsx`

Documentation updates are limited to this file, `API_REFERENCE.md`, `ARCHITECTURE.md`, `IMPLEMENTED_FEATURES.md`, and `TESTING_AND_DEPLOYMENT.md`.

## JWT invalidation behavior

`User.token_version` is a non-null integer with application and server default zero. Revision `c4a8d9e2f1b0` adds the column without requiring data backfill. Login embeds the current version in the JWT's integer `ver` claim. Authentication decodes the token, loads its subject user, and compares `ver` with the stored value.

Successful password and email changes increment the version exactly once in the same commit as the credential change. Every previously issued token then fails immediately with 401 `session expired; please sign in again`. Validation, password verification and email uniqueness failures return before mutation, leaving the version unchanged. New login uses the latest version and produces a working token. Path ownership checks remain unchanged.

Legacy tokens without `ver` are strictly rejected. This deliberately signs out all sessions issued before deployment rather than temporarily treating them as version zero. Missing/non-integer versions use the session-expired response; malformed, expired and unknown-user token handling remains unchanged.

## Frontend behavior

The API client still clears stored authentication on every 401. When the backend detail identifies a version-invalidated session, it additionally stores a one-time message in `sessionStorage`. Existing authenticated pages observe the removed token and redirect to `/`; the login page consumes and displays `Your session expired. Please sign in again.` once. Saving a successful login clears any stale notice. This does not introduce a global router or redirect loop.

Settings retains its existing successful credential-change flow: display the success message briefly, clear the current browser's token and user id, and redirect to login.

## Tests and verification

Focused tests cover version-zero registration/login, working pre-change tokens, exact version increments, old-token rejection after password/email changes, successful post-change login and token use, failed-change non-increment, incorrect and missing version claims, and cross-user authorization.

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

- Token version invalidates every session for a user; there is no per-device/session revocation.
- There are no refresh tokens, session inventory, remote logout UI, or token denylist.
- The one-time frontend notice uses browser `sessionStorage`; it does not persist across a fully closed browser session.
- The repository has no frontend automated test harness, so redirect/message behavior is lint/build verified rather than browser-test verified.

## Recommended next task

Add frontend authentication integration coverage for invalidated-session redirects and the one-time login notice before introducing refresh tokens or per-device session management.
