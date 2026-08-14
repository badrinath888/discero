import logging

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

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

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
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

    is_https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
    )
    if is_https:
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains"
        )

    return response


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