# FinSight — AI-Powered Personal Finance Platform

Upload your bank transactions, see where your money goes, and ask an AI
assistant questions about your spending in plain English.

> **Status:** Phase 2 complete — backend spine + LLM-powered categorization
> (batched, cached, with a deterministic fallback) and richer spending
> summaries. 51 tests, green CI.

## Why this project

A finance product forces real engineering: correct money math, secure
per-user data isolation, a validated ingestion pipeline, and tested business
logic. This repo is built to production practices, not tutorial shortcuts.

## Tech stack

| Layer      | Choice                                             |
|------------|----------------------------------------------------|
| Backend    | FastAPI (async Python)                             |
| Database   | PostgreSQL + pgvector (SQLite for local/tests)     |
| ORM        | SQLAlchemy 2.0                                     |
| Validation | Pydantic v2                                        |
| Tests      | pytest (51 tests)                                  |
| CI         | GitHub Actions                                     |
| Container  | Docker                                            |
| Frontend   | Next.js + TypeScript + Tailwind *(Phase 3)*        |
| AI         | LangChain + Claude/OpenAI, RAG over pgvector *(Phase 4)* |

## Design decisions worth calling out

- **Money is integer cents, never floats.** All parsing goes through
  `app/money.py` using `Decimal` at the boundary, then integer arithmetic
  everywhere. Floats silently lose cents; this doesn't.
- **Uploads never crash on bad data.** `app/ingestion.py` validates every row,
  imports the good ones, and reports the bad ones with row numbers — no silent
  drops.
- **LLM categorization is cost-aware.** `app/llm_categorization.py` categorizes
  with an LLM when `ANTHROPIC_API_KEY` is set, but sends all uncategorized
  descriptions in **one batched request** and **caches** results, so the same
  merchant is never billed twice. With no key it falls back to deterministic
  rules — so tests and CI need no secret and stay fast and free.
- **Per-user ownership from day one.** Every transaction belongs to a user;
  the schema is the isolation boundary auth will enforce in Phase 3.

## Run it locally

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for the interactive API.

Try it end to end:

```bash
# create a user
curl -X POST localhost:8000/users -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com"}'

# upload the sample transactions (user id 1)
curl -X POST localhost:8000/users/1/transactions/upload \
  -F "file=@sample_transactions.csv"

# see spending by category
curl localhost:8000/users/1/summary/by-category
```

## Run the tests

```bash
cd backend
pytest
# 43 passed
```

## API (Phase 1)

| Method | Path                                     | Purpose                        |
|--------|------------------------------------------|--------------------------------|
| POST   | `/users`                                 | Create a user                  |
| GET    | `/users/{id}`                            | Fetch a user                   |
| POST   | `/users/{id}/transactions/upload`        | Upload a CSV of transactions   |
| GET    | `/users/{id}/transactions`               | List a user's transactions     |
| GET    | `/users/{id}/summary/by-category`        | Spending totals by category    |
| GET    | `/users/{id}/summary/overview`           | Income, spending, net totals   |
| GET    | `/users/{id}/summary/by-month`           | Income/spending/net per month  |
| GET    | `/health`                                | Health check                   |

## Roadmap

- [x] **Phase 1** — Backend spine: ingestion, categorization, summaries, tests, CI
- [x] **Phase 2** — LLM categorization (batched + cached, rule fallback) + overview/by-month summaries
- [ ] **Phase 3** — Next.js/TypeScript frontend: auth, upload, dashboard
- [ ] **Phase 4** — AI assistant (RAG over transactions with pgvector)
- [ ] **Phase 5** — Dispute-letter agent + evaluation harness
- [ ] **Phase 6** — Docker deploy (Vercel + Render), architecture docs
