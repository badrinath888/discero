from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

# check_same_thread is a SQLite-only flag; skip it for Postgres.
connect_args = {"check_same_thread": False} if _is_sqlite else {}

# pool_size/max_overflow/pool_timeout are QueuePool-specific -- SQLite
# uses its own default pool class, which rejects these kwargs outright,
# so they're only ever passed for a real (Postgres) database_url. 10,000
# users does NOT mean 10,000 DB connections: this bounds each backend
# process to a fixed, configurable ceiling (see app/config.py) rather
# than growing connections unboundedly under load.
_pool_kwargs = (
    {}
    if _is_sqlite
    else {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_recycle": settings.db_pool_recycle_seconds,
    }
)

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    # Detects and discards stale connections (e.g. dropped by a hosted
    # Postgres provider's idle timeout) instead of surfacing them as errors.
    pool_pre_ping=True,
    **_pool_kwargs,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
