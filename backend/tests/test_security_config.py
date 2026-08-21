"""Database pool configuration and other production-config surfaces
not already covered by test_production_secrets.py / test_cors.py.
"""

import os
import subprocess
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run(script: str, database_url: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=_BACKEND_DIR,
        env={
            "PATH": os.environ.get("PATH", ""),
            "APP_ENV": "test",
            "DATABASE_URL": database_url,
        },
        capture_output=True,
        text=True,
    )


def test_sqlite_engine_never_receives_queuepool_kwargs() -> None:
    # create_engine raises TypeError outright if pool_size/max_overflow
    # are passed for a pool class that doesn't accept them (SQLite's
    # default) -- this just has to import cleanly.
    script = (
        "from app.database import engine\n"
        "print('OK', engine.pool.__class__.__name__)\n"
    )
    result = _run(script, "sqlite:///./_security_config_check.db")

    db_path = _BACKEND_DIR / "_security_config_check.db"
    if db_path.exists():
        db_path.unlink()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_postgres_engine_receives_configured_pool_bounds() -> None:
    """No real Postgres needed -- create_engine() never connects
    eagerly, so this only inspects the pool object's configured bounds.
    """
    script = (
        "from app.database import engine\n"
        "from app.config import settings\n"
        "pool = engine.pool\n"
        "assert pool.size() == settings.db_pool_size, pool.size()\n"
        "assert pool._max_overflow == settings.db_max_overflow\n"
        "assert pool._recycle == settings.db_pool_recycle_seconds\n"
        "print('OK')\n"
    )
    result = _run(
        script, "postgresql://user:pass@localhost:59999/discero_test"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_pool_settings_default_to_sqlalchemy_defaults() -> None:
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        database_url="sqlite://",
        jwt_secret="test-secret",
    )

    assert settings.db_pool_size == 5
    assert settings.db_max_overflow == 10
    assert settings.db_pool_recycle_seconds == 1800


def test_max_request_body_bytes_exceeds_csv_upload_cap() -> None:
    """The global body-size ceiling must stay above the CSV upload
    endpoint's own stricter cap -- otherwise a legitimate max-size CSV
    upload would be rejected by the global limit before ever reaching
    the endpoint's own, more precise, check.
    """
    from app.config import settings
    from app.routers.transactions import _MAX_CSV_UPLOAD_BYTES

    assert settings.max_request_body_bytes > _MAX_CSV_UPLOAD_BYTES
