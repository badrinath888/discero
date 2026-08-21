import logging

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.body_size_limit import MaxBodySizeMiddleware
from app.config import settings
from app.database import get_db
from app.routers import (
    accounts,
    budgets,
    copilot,
    decisions,
    financial_resilience,
    financial_stress_test,
    goal_conflict_detection,
    goals,
    major_purchase,
    plaid,
    recommendations,
    recurring,
    recurring_intelligence,
    safe_to_spend,
    spending_anomalies,
    transactions,
    users,
    what_if,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Interactive API docs describe the entire endpoint surface -- useful
# in development, unnecessary attack-surface reconnaissance for an
# anonymous Internet caller once this is a real production deployment.
_docs_enabled = settings.app_env != "production"

app = FastAPI(
    title=settings.app_name,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # Required so the browser sends/receives the refresh-token cookie
    # (see routers/users.py) on cross-site requests to this API. Safe
    # only because allow_origins is always an explicit list, never "*"
    # -- Starlette itself refuses allow_credentials=True combined with
    # a wildcard origin.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(
    request: Request, call_next
) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = (
        "strict-origin-when-cross-origin"
    )
    response.headers["X-Frame-Options"] = "DENY"
    # Defensive only -- this API returns JSON, never HTML, so CSP has
    # no real content to restrict here. Set anyway in case any response
    # (an error page from an intermediary, a future misconfiguration)
    # ever comes back as HTML: it must never be framable or able to run
    # a script. Excludes the dev/test-only docs UI, which legitimately
    # loads its own script/style assets and would otherwise break under
    # this policy.
    if request.url.path not in ("/docs", "/redoc"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'"
        )
    # Every response from this API is either an auth flow or a specific
    # user's financial data -- there is no cacheable public content, so
    # this is unconditional rather than an allowlist of sensitive
    # routes.
    response.headers["Cache-Control"] = "no-store"

    is_https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
    )
    if is_https:
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains"
        )

    return response


# Added last so it wraps outermost (Starlette middleware added later
# runs first on the way in) -- an oversized body is rejected before
# CORS, routing, or any of the above ever run.
app.add_middleware(
    MaxBodySizeMiddleware,
    max_bytes=settings.max_request_body_bytes,
)


app.include_router(users.router)
app.include_router(transactions.router)
app.include_router(budgets.router)
app.include_router(goals.router)    
app.include_router(major_purchase.router)
app.include_router(recurring.router)
app.include_router(safe_to_spend.router)
app.include_router(financial_stress_test.router)
app.include_router(goal_conflict_detection.router)
app.include_router(plaid.router)
app.include_router(accounts.router)
app.include_router(copilot.router)
app.include_router(recommendations.router)
app.include_router(decisions.router)
app.include_router(financial_resilience.router)
app.include_router(recurring_intelligence.router)
app.include_router(spending_anomalies.router)
app.include_router(what_if.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Basic process liveness check. Does not touch the database."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["meta"])
def readiness(db: Session = Depends(get_db)) -> dict[str, str]:
    """Readiness check: confirms the app can reach the database."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Readiness check failed: database unreachable")
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok"}


logger.info("Discero API configured (app_env=%s)", settings.app_env)