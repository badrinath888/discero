#!/usr/bin/env bash
set -euo pipefail

echo "Applying database migrations..."
alembic upgrade head

echo "Starting FinSight API..."
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}"
