# Discero

*Discern before you decide.*

Discero is a financial decision-intelligence platform. It combines account, budget, and obligation data with a deterministic simulation engine to evaluate how a proposed decision would affect liquidity, obligations, goals, and financial resilience — before the decision is made. Outcomes are computed by backend services in integer cents, not inferred by a language model.

**[Live application](https://discero-app.vercel.app)** · [Architecture](docs/ARCHITECTURE.md) · [Security](SECURITY.md)

## What Discero Does

Discero builds a forward-looking financial model from account and transaction data, budgets, savings goals, and recurring obligations. Proposed decisions — a major purchase, a temporary income loss, a multi-step plan — are evaluated against that model before they're acted on.

Every simulation is computed by a deterministic backend service in integer cents, not estimated by a language model. A Safe-to-Spend calculation, a stress test, or a scenario comparison will return the same result every time for the same inputs, and the reasoning behind it is inspectable rather than generated.

Decisions are also persisted and revisited: outcomes are tracked against what was originally simulated, and a calibration layer reads back how past predictions actually played out, so the system's own confidence is grounded in its track record rather than asserted.

## Decision Intelligence

| Capability | What it does |
|---|---|
| **Safe-to-Spend** | Liquid balance minus upcoming recurring obligations, essential spending, and a safety reserve — the deterministic base every other decision tool builds on |
| **Major Purchase / Buy Now vs Wait** | Classifies a purchase against Safe-to-Spend and compares buying now vs. waiting under the same assumptions |
| **Scenario Comparison** | Ranks two purchase options by affordability, shortfall, and cost, with a deterministic recommendation |
| **Financial Stress Testing** | Models an emergency expense, income loss, delayed paycheck, or bill increase and returns a risk level, shortfall, and recovery estimate |
| **Multi-Step Scenario Planning** | Evaluates 2–5 dated financial events in chronological order against one running balance |
| **Time-Aware Simulation** | Shared temporal engine underlying every scenario and forecast, so events are evaluated in the order and timeframe they'd actually occur |
| **Decision Outcome Tracking & Calibration** | Re-runs an acted-on decision's original saved inputs later and compares predicted vs. actual, feeding a deterministic calibration read-model |
| **Decision Portfolio Intelligence** | Evaluates several compatible saved decisions together as one combined position instead of in isolation |
| **Financial Resilience** | Emergency-runway modeling: how many months of survival a loss of income would leave |

Each capability is implemented as a dedicated backend service with targeted regression coverage, not a variation of one generic calculator.

## AI Architecture and Grounding

Discero's Copilot answers financial questions in plain language, but the model never computes a balance, a percentage, or a recommendation itself.

```
User request
  -> intent / tool selection
  -> deterministic backend computation (Safe-to-Spend, stress test, etc.)
  -> structured, trusted result
  -> optional LLM narration in plain language
  -> grounding validation against the result payload
  -> deterministic fallback narration if validation fails
```

The principle: LLMs interpret and explain; deterministic services calculate financial results. The tool schema exposed to the model excludes user identity — execution always scopes to the authenticated request's user, never to anything the model supplies. When no provider is configured, Copilot runs entirely on its deterministic router and template narration, so the financial answer is unchanged by whether an LLM is in the loop. Grounding behavior is covered by dedicated regression and evaluation tests, alongside observability for token usage, estimated cost, and provider latency.

## Architecture

```
Browser
  |
Next.js 16 / React 19 (Vercel)
  |  Bearer access token + HttpOnly refresh cookie
  v
FastAPI backend (Render)
  |
  +-- Authentication / per-user authorization
  +-- Decision engines (Safe-to-Spend, stress test, scenarios, portfolio, calibration...)
  +-- Forecasting / recurring-obligation detection
  +-- Copilot orchestration
  |      +-- deterministic tool router
  |      +-- Groq LLM narration (optional, falls back to deterministic templates)
  |      +-- grounding validator
  |      +-- evals / observability
  |
  +-- SQLAlchemy 2 / Alembic -> PostgreSQL
  +-- Redis / Valkey (distributed rate limiting)
  +-- Plaid (account/transaction sync, encrypted tokens)
```

Discero currently uses a modular-monolith backend: FastAPI hosts domain-specific routers and services — auth, decisions, forecasting, Copilot — in a single deployable application backed by PostgreSQL. Deployment topology is Vercel (frontend) → Render (backend) → PostgreSQL / Redis-Valkey / Plaid.

## Engineering Highlights

- Deterministic financial simulation engines with a shared time-aware core, all operating in integer cents
- Persisted decision lifecycle: saved decisions, tracked outcomes, and a calibration layer that reads back prediction accuracy
- LLM narration architecturally separated from calculation, with automated grounding validation, evals, and observability
- Session design with short-lived Bearer access tokens and an HttpOnly, origin-validated refresh cookie
- Backend-agnostic rate limiting — Redis/Valkey-backed sliding window in production, in-memory fallback on a Redis outage, applied by IP and by authenticated user on expensive endpoints
- Protected resource access is scoped to the authenticated user at both route and query layers
- Plaid account/transaction sync with encrypted access tokens, idempotent cursor-based updates, and reconnect handling
- PostgreSQL persistence via SQLAlchemy 2 with a linear Alembic migration history
- Production configuration that fails closed at startup (default secrets, wildcard CORS, or missing encryption keys refuse to boot when `APP_ENV=production`)
- CI on every push/PR (backend pytest suite, frontend lint/build/test), plus Dependabot dependency updates

## Technology

| | |
|---|---|
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind CSS 4, Recharts, React Plaid Link |
| **Backend** | Python, FastAPI, SQLAlchemy 2, Pydantic 2, Alembic |
| **Data** | PostgreSQL, Redis / Valkey |
| **AI** | Groq (OpenAI-compatible), deterministic tool routing, grounding validation |
| **Integrations** | Plaid |
| **Infrastructure** | Vercel, Render, Docker |
| **Security / Quality** | Argon2 (pwdlib), PyJWT, Fernet encryption, GitHub Actions CI, Dependabot |

## Reliability and Testing

- **Backend:** 1,347 tests (pytest). Coverage includes authentication, authorization, decision engines, Copilot grounding/evaluations, rate limiting, and Plaid synchronization, with external provider boundaries mocked where appropriate
- **Frontend:** 325 tests (Vitest + React Testing Library) across the route surface
- GitHub Actions runs the backend suite, frontend lint, frontend tests, and a production frontend build on every push to `main` and every pull request
- Dependabot tracks pip, npm, and GitHub Actions dependencies weekly

## Security

- Passwords hashed with Argon2; short-lived Bearer access tokens paired with an origin-validated refresh cookie. Refresh tokens are stored in HttpOnly cookies rather than client-accessible storage
- Server-side session invalidation via a per-user token version, bumped on password/email change and logout
- Protected resource queries are scoped to the authenticated user, and the LLM tool layer has no path to select whose data it touches
- Plaid access tokens encrypted at rest (Fernet); safe account/status responses never expose provider identifiers or tokens
- Redis/Valkey-backed distributed rate limiting with an in-process fallback on a Redis outage, applied by IP and by user on expensive endpoints
- Nonce-based Content-Security-Policy on the frontend, plus standard security headers (HSTS, X-Frame-Options, X-Content-Type-Options) on the backend
- Production configuration validation that refuses to start on an unsafe secret, wildcard/localhost CORS, or a missing encryption key

See [SECURITY.md](SECURITY.md) for the full threat model, invariants, and residual risks.

## Running Locally

**Requirements:** Python 3.12+, Node.js 20+, npm

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in JWT_SECRET / TOKEN_ENCRYPTION_KEY, see comments in the file
alembic upgrade head
uvicorn app.main:app --reload
```

```bash
# Frontend
cd frontend
npm install
printf 'NEXT_PUBLIC_API_URL=http://localhost:8000\n' > .env.local
npm run dev
```

Backend: `http://localhost:8000` (Swagger at `/docs`) · Frontend: `http://localhost:3000`

Never commit `.env`, `.env.local`, database files, or real credentials.

## Project Structure

```
backend/     FastAPI app: routers, services, models, Alembic migrations, tests
frontend/    Next.js App Router application
docs/        Architecture, feature, and testing/deployment documentation
.github/     CI workflow, Dependabot config
SECURITY.md  Threat model and security invariants
```

## Deployment

Discero is deployed with:

- **Frontend** — Vercel
- **Backend** — Render
- **Database** — PostgreSQL
- **Distributed rate limiting** — Redis/Valkey
- **Financial account integration** — Plaid

The backend applies pending Alembic migrations before starting the ASGI server on every deploy, and exposes `/health` (liveness) and `/health/ready` (database connectivity) endpoints for the host's health checks.

## Future Engineering Work

Additional hardening and architectural evolution planned beyond the current baseline:

- Server-side refresh-token replay/family detection, building on the existing stateless-JWT token-version invalidation
- Encryption-key rotation for Plaid tokens
- First-party MFA/passkey support

## Disclaimer

Discero is an educational/personal engineering project. Financial simulations and recommendations are informational estimates based on supplied data and are not professional financial advice.

## Author

**Badrinath T**
Software Engineer focused on backend systems, cloud platforms, distributed systems, and AI-enabled applications.
