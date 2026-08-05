# FinSight

FinSight is a full-stack personal finance intelligence platform for securely importing transactions, connecting bank accounts, tracking budgets and savings goals, detecting recurring expenses, analyzing spending patterns, and forecasting cash flow.

## Features

- JWT authentication with Argon2 password hashing, server-side session invalidation, password reset, and email verification (console/SMTP/Resend delivery)
- Per-user data isolation and protected API routes
- CSV upload with validation, duplicate handling, potential-duplicate detection, and categorization
- Plaid Sandbox account connection and transaction synchronization
- Search, filters, pagination, category editing, category locking, and deletion
- Month-specific budgets with progress, over-budget tracking, and copy-from-previous-month support
- Savings goals with editing, deadlines, status, and a full contribution/withdrawal history
- Persisted recurring items (bills/subscriptions) with weekly/biweekly/monthly cadence, pending-transaction filtering, and price-change alerts
- Safe-to-Spend calculation combining liquid balances, upcoming recurring obligations, essential spending, and a safety reserve
- Major Purchase Simulator with affordability status, recommended ceiling, and alternative amounts
- Scenario Comparison that evaluates two purchase options side by side with a recommendation
- Financial Stress Testing that models an emergency expense, temporary income loss, delayed paycheck, or recurring bill increase against Safe-to-Spend, returning risk level, shortfall, confidence, and recovery estimate
- Financial insights with spending trends and savings-rate analysis
- Cash-flow forecasting with projected month-end balance and low-balance risk
- Responsive sidebar, mobile navigation, charts, and reusable feedback states

## Application routes

| Route | Purpose |
|---|---|
| `/` | Registration and login |
| `/dashboard` | Financial overview |
| `/transactions` | Transaction management |
| `/accounts` | Connected financial accounts |
| `/budgets` | Monthly budget management |
| `/goals` | Savings-goal management |
| `/insights` | Detailed financial insights |
| `/decisions` | Safe-to-Spend, Major Purchase Simulator, Scenario Comparison, and Financial Stress Testing |
| `/forecast` | Cash-flow forecasting |
| `/recurring` | Recurring bills and subscriptions |
| `/settings` | Profile, credentials, and CSV export |
| `/forgot-password` | Password reset request |
| `/reset-password` | Token-based password reset |
| `/verify-email` | Email verification |

## Technology stack

**Backend:** Python, FastAPI, SQLAlchemy 2, Pydantic 2, Alembic, SQLite/PostgreSQL, PyJWT, Argon2, Plaid SDK, Anthropic SDK, Fernet, pytest

**Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS 4, Recharts, React Plaid Link, ESLint

## Architecture

```text
Browser
  |
Next.js frontend
  |
  | JWT-authenticated REST requests
  v
FastAPI backend
  |
  +-- SQLAlchemy / Alembic
  +-- SQLite locally or PostgreSQL in production
  +-- Plaid Sandbox API
  +-- Optional Anthropic categorization
```

## Local development

### Requirements

- Python 3.11+
- Node.js 20+
- npm
- Plaid Sandbox credentials for bank connectivity

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Generate secrets:

```bash
python3 - <<'PY'
import secrets
from cryptography.fernet import Fernet

print("JWT_SECRET=" + secrets.token_urlsafe(48))
print("TOKEN_ENCRYPTION_KEY=" + Fernet.generate_key().decode())
PY
```

Add the generated values to `backend/.env`, then run:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

API: `http://localhost:8000`  
Swagger documentation: `http://localhost:8000/docs`

### Frontend

```bash
cd frontend
npm install
printf 'NEXT_PUBLIC_API_URL=http://localhost:8000\n' > .env.local
npm run dev
```

Frontend: `http://localhost:3000`

## Environment variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | SQLAlchemy database connection |
| `CORS_ORIGINS` | Comma-separated frontend origins |
| `JWT_SECRET` | JWT signing secret |
| `JWT_ALGORITHM` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access-token lifetime |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for Plaid tokens |
| `APP_ENV` | `development`, `test`, or `production`; gates console email delivery |
| `FRONTEND_URL` | Base URL used to build reset/verification links |
| `EMAIL_BACKEND` | `console`, `smtp`, or `resend` |
| `EMAIL_FROM` | From address for reset/verification email |
| `RESEND_API_KEY` | Required when `EMAIL_BACKEND=resend` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_USE_TLS` | Required when `EMAIL_BACKEND=smtp` |
| `PASSWORD_RESET_EXPIRE_MINUTES` | Password reset token lifetime (default 30) |
| `EMAIL_VERIFICATION_EXPIRE_HOURS` | Email verification token lifetime (default 24) |
| `ANTHROPIC_API_KEY` | Optional Anthropic API key |
| `LLM_MODEL` | Optional categorization model |
| `PLAID_CLIENT_ID` | Plaid client ID |
| `PLAID_SECRET` | Plaid secret |
| `PLAID_ENV` | `sandbox` or `production` |
| `PLAID_PRODUCTS` | Plaid products |
| `PLAID_COUNTRY_CODES` | Supported country codes |
| `PLAID_REDIRECT_URI` | Optional OAuth redirect URI |
| `NEXT_PUBLIC_API_URL` | Frontend API base URL |

Never commit `.env`, `.env.local`, database files, credentials, or encryption keys.

## Plaid Sandbox

1. Create a Plaid developer account.
2. Add the Sandbox client ID and secret to `backend/.env`.
3. Set `PLAID_ENV=sandbox`.
4. Start the backend and frontend.
5. Open `/accounts` and select **Connect bank**.
6. Use a Plaid Sandbox institution and test credentials.

Plaid access tokens are encrypted before storage.

## CSV format

```csv
date,description,amount,category
2026-01-05,ACME Payroll,3000.00,Income
2026-01-08,Whole Foods,-125.50,Groceries
2026-01-10,Apartment Rent,-1450.00,Housing
```

Positive amounts represent income; negative amounts represent expenses.

## Database migrations

```bash
cd backend
alembic revision --autogenerate -m "describe change"
alembic upgrade head
alembic current
```

Always review generated migrations before applying them.

## Testing

Backend:

```bash
cd backend
pytest -q
```

Current verified result:

```text
275 passed
```

Frontend:

```bash
cd frontend
npm run lint
npm run build
npm run test:run
```

Current verified result: 32 tests across 5 files (`auth-recovery.test.tsx`, `decisions/page.test.tsx`, `transactions/page.test.tsx`, `accounts/page.test.tsx`, `budgets/page.test.tsx`).

## API overview

```text
/users
/users/login
/users/me
/users/forgot-password
/users/reset-password
/users/verify-email
/users/resend-verification
/users/{user_id}/transactions
/users/{user_id}/transactions/search
/users/{user_id}/transactions/upload
/users/{user_id}/summary/overview
/users/{user_id}/summary/by-category
/users/{user_id}/summary/by-month
/users/{user_id}/summary/recurring
/users/{user_id}/summary/insights
/users/{user_id}/summary/cash-flow-forecast
/users/{user_id}/budgets
/users/{user_id}/budgets/progress
/users/{user_id}/budgets/copy-previous
/users/{user_id}/goals
/users/{user_id}/goals/{goal_id}/contributions
/users/{user_id}/recurring-items
/users/{user_id}/safe-to-spend
/users/{user_id}/major-purchase/simulate
/users/{user_id}/major-purchase/compare
/users/{user_id}/financial-stress-test
/users/{user_id}/accounts
/users/{user_id}/plaid/link-token
/users/{user_id}/plaid/exchange-token
/users/{user_id}/plaid/sync
```

Use `/docs` for complete request and response schemas.

## Security decisions

- Passwords are hashed with Argon2.
- User ownership is validated on protected resources.
- Plaid access tokens are encrypted at rest.
- Financial values are stored as integer cents.
- Schema changes are managed through Alembic.
- CORS origins are explicitly configurable.
- Request and response payloads are validated with Pydantic.
- Sensitive provider identifiers are not exposed by account endpoints.

## Deployment

Recommended architecture:

- Frontend: Vercel
- Backend: Render, Railway, Fly.io, or AWS
- Database: Managed PostgreSQL

Production setup requires secure secrets, production CORS, `NEXT_PUBLIC_API_URL`, Alembic migrations, and end-to-end testing of authentication and Plaid.

## Roadmap

### Completed

- [x] Authentication, password reset, and email verification
- [x] CSV ingestion with potential-duplicate detection
- [x] Plaid Sandbox integration
- [x] Transaction management with server-side filtering and pagination
- [x] Monthly budgets with copy-from-previous-month workflow
- [x] Savings goals with contribution/withdrawal history
- [x] Persisted recurring items with weekly/biweekly/monthly detection
- [x] Safe-to-Spend calculation
- [x] Major Purchase Simulator and Scenario Comparison
- [x] Financial Stress Testing
- [x] Financial insights
- [x] Cash-flow forecasting
- [x] Responsive navigation
- [x] Shared feedback states
- [x] Backend regression tests

### Planned

- [ ] Production deployment
- [ ] PostgreSQL production migration
- [ ] Screenshots and demo video
- [ ] Refresh-token flow
- [ ] Rate limiting and monitoring
- [ ] Scheduled Plaid synchronization
- [ ] AI financial assistant
- [ ] Anomaly detection and alerts
- [ ] Net-worth and investment tracking

## Disclaimer

FinSight is a portfolio and educational project. Forecasts, insights, recurring-payment predictions, and categorizations are estimates and are not professional financial advice.

## Author

**Badrinath T**  
Software Engineer focused on backend systems, cloud platforms, distributed systems, and AI-enabled applications.
