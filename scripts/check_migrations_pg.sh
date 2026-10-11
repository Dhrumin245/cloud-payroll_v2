#!/usr/bin/env bash
# Check one service's Alembic migrations against a real PostgreSQL. Run it FROM the service directory:
#
#   cd services/auth-service
#   PGHOST=localhost PGUSER=postgres PGPASSWORD=postgres JWT_SECRET=... ../../scripts/check_migrations_pg.sh
#
# (employee-service also needs BANK_ENCRYPTION_KEY.) PGUSER must be allowed to create databases;
# use a password with letters and digits only, it is placed in a URL. It checks that:
#   1. upgrade head works and the models match the migration (alembic check)
#   2. downgrade base and a second upgrade work
#   3. THREE copies starting at once (like a 3-replica rollout) all succeed (advisory lock)
set -euo pipefail
: "${PGHOST:?set PGHOST}" "${PGUSER:?set PGUSER}" "${PGPASSWORD:?set PGPASSWORD}"
export PGDATABASE=postgres
DB="migcheck_$$"
export DATABASE_URL="postgresql+psycopg://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT:-5432}/${DB}"
trap 'psql -qc "drop database if exists ${DB}" >/dev/null 2>&1 || true' EXIT

fresh_db() { psql -v ON_ERROR_STOP=1 -qc "drop database if exists ${DB}" -c "create database ${DB}"; }

fresh_db
alembic upgrade head
alembic check
alembic downgrade base
alembic upgrade head
echo "ok: upgrade, drift check, downgrade, upgrade"

fresh_db
pids=()
for i in 1 2 3; do
  alembic upgrade head >"/tmp/${DB}_$i.log" 2>&1 &
  pids+=("$!")
done
failed=0
for pid in "${pids[@]}"; do wait "$pid" || failed=1; done
if [ "$failed" -ne 0 ]; then
  echo "concurrent migrations FAILED:" >&2
  cat /tmp/"${DB}"_*.log >&2
  exit 1
fi
alembic check
echo "ok: 3 concurrent migrations"
