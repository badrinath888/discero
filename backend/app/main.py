from fastapi import FastAPI

from app.config import settings
from app.database import Base, engine
from app.routers import transactions, users

# For Phase 1 we create tables on startup. When the schema stabilizes, swap
# this for Alembic migrations (a good "production maturity" upgrade later).
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name)

app.include_router(users.router)
app.include_router(transactions.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
