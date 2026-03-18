#!/bin/sh
set -eu

if [ "${SKIP_MIGRATIONS:-0}" != "1" ]; then
  max_attempts="${ALEMBIC_MAX_ATTEMPTS:-10}"
  retry_delay="${ALEMBIC_RETRY_DELAY_SECONDS:-2}"
  attempt=1

  while [ "$attempt" -le "$max_attempts" ]; do
    echo "Running database migrations (attempt ${attempt}/${max_attempts})"
    if alembic upgrade head; then
      break
    fi

    if [ "$attempt" -eq "$max_attempts" ]; then
      echo "Database migrations failed after ${max_attempts} attempts" >&2
      exit 1
    fi

    echo "Migration attempt ${attempt} failed; retrying in ${retry_delay}s" >&2
    sleep "$retry_delay"
    attempt=$((attempt + 1))
  done
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec uvicorn app.main:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}"
