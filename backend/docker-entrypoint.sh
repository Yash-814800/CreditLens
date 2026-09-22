#!/usr/bin/env bash
# Runs pending migrations (as the admin/migration Postgres role -- see alembic/env.py)
# before starting the app, so every container start guarantees an up-to-date schema
# and the least-privilege app role/audit-log trigger exist.
#
# A small retry allowance is defense-in-depth against `depends_on: service_healthy`
# still leaving a brief window before Postgres accepts connections -- not required
# for the common case, but cheap insurance on a fresh clone's first `make up`.
set -euo pipefail

max_attempts=5
attempt=1
until alembic upgrade head; do
    if [ "$attempt" -ge "$max_attempts" ]; then
        echo "alembic upgrade head failed after $max_attempts attempts, giving up" >&2
        exit 1
    fi
    echo "alembic upgrade head failed (attempt $attempt/$max_attempts), retrying in 2s..." >&2
    attempt=$((attempt + 1))
    sleep 2
done

exec "$@"
