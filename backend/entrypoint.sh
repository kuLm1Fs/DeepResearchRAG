#!/bin/bash
set -e

# Run base schema + migrations if POSTGRES_URL is set
if [ -n "$POSTGRES_URL" ]; then
  echo "[entrypoint] Running migrations..."

  # Apply base schema if users table doesn't exist
  TABLE_EXISTS=$(psql "$POSTGRES_URL" -tAc "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='users');" 2>/dev/null || echo "f")
  if [ "$TABLE_EXISTS" != "t" ] && [ -f "migrations/schema.sql" ]; then
    echo "[entrypoint] Applying base schema"
    psql "$POSTGRES_URL" -f "migrations/schema.sql" 2>/dev/null || true
  fi

  # Apply incremental migrations
  for f in migrations/*.sql; do
    [ -f "$f" ] || continue
    [ "$(basename "$f")" = "schema.sql" ] && continue
    echo "[entrypoint] Applying $f"
    psql "$POSTGRES_URL" -f "$f" 2>/dev/null || true
  done
  echo "[entrypoint] Migrations done."
fi

exec "$@"
