#!/bin/bash
# Runs ONCE, the first time the Postgres volume is created (official image behaviour).
# Creates one database AND one login role per service. Each role owns only its own database,
# and PUBLIC is stripped of CONNECT, so a service cannot even open another service's database.
set -euo pipefail

create_service_db() {
  local role="$1" db="$2" password="$3"
  if [ -z "$password" ]; then
    echo "init-databases: password for role '$role' is empty; set it in .env" >&2
    exit 1
  fi
  psql -v ON_ERROR_STOP=1 -v pw="$password" --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE ${role} LOGIN PASSWORD :'pw';
CREATE DATABASE ${db} OWNER ${role};
REVOKE ALL ON DATABASE ${db} FROM PUBLIC;
SQL
  echo "init-databases: created ${db} owned by ${role}"
}

create_service_db auth_svc     auth_db     "${AUTH_DB_PASSWORD:-}"
create_service_db employee_svc employee_db "${EMPLOYEE_DB_PASSWORD:-}"
create_service_db leave_svc    leave_db    "${LEAVE_DB_PASSWORD:-}"
create_service_db payroll_svc  payroll_db  "${PAYROLL_DB_PASSWORD:-}"
