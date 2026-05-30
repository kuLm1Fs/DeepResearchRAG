#!/bin/bash
set -e

# Run pending SQL migrations if POSTGRES_URL is set
if [ -n "$POSTGRES_URL" ]; then
  echo "[entrypoint] Running migrations..."
  for f in migrations/*.sql; do
    [ -f "$f" ] || continue
    echo "[entrypoint] Applying $f"
    psql "$POSTGRES_URL" -f "$f" 2>/dev/null || true
  done
  echo "[entrypoint] Migrations done."
fi

exec "$@"
