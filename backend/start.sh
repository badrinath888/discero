#!/usr/bin/env bash
set -euo pipefail

echo "Applying database migrations..."
alembic upgrade head

echo "Starting Discero API..."
# --proxy-headers is already uvicorn's default, but is spelled out here
# for clarity. Render's Web Services are not directly publicly routable:
# inbound traffic can only reach this container through Render's own
# routing layer, so the sole TCP peer uvicorn ever sees IS Render's
# proxy. Render does not publish stable proxy IP ranges to allowlist,
# so pinning --forwarded-allow-ips to specific addresses isn't possible
# here; '*' is safe in this specific topology because it means "trust
# X-Forwarded-For from whichever peer connected", and no other peer can
# ever connect. This does not open header spoofing to end users, since
# Render's edge sets/overwrites X-Forwarded-For itself. Locally (no
# proxy in front), no X-Forwarded-For header is ever sent, so this has
# no effect on dev behavior.
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips='*'
