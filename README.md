# Employee Leave & Payroll Management System

This project is a cloud-native employee management platform built with FastAPI microservices. It combines authentication, employee records, leave approvals, and payroll processing into a single system that can run locally with Docker or in Kubernetes for production-style deployment.

The stack includes JWT-based role authorization, service-level database separation, gateway routing, monitoring, and automated CI/CD workflows for testing and deployment.

Design and endpoints: [`docs/api-contract.md`](docs/api-contract.md)

```
                         ┌──────────────── gateway (nginx, :8080) ────────────────┐
 client ── JWT ────────► │ /auth /users → auth-service        /employees → employee-service
                         │ /leaves /leave-types → leave-service
                         │ /payroll /payslips /attendance /variable-pay /settings → payroll-service
                         └─────────────────────────────────────────────────────────┘
   leave-service ──► employee-service        payroll-service ──► employee-service, leave-service
   auth_db        employee_db        leave_db        payroll_db     (one Postgres server, one DB and one DB role per service)
```

## Quick start (Docker Compose)

Requires Docker with Compose v2.

```bash
python scripts/init_env.py          # once: writes .env with random secrets, prints the admin password
docker compose up --build           # builds 4 images, migrates 4 databases, creates the admin, starts everything
python scripts/seed_demo.py         # optional: demo leave types, 3 employees, 3 logins
curl http://localhost:8080/health   # -> ok
```

Monitoring starts with it: Grafana at http://localhost:3000 (login `admin` + the Grafana password printed by `init_env.py`),
Prometheus at http://localhost:9090. See [`monitoring/README.md`](monitoring/README.md).

Then log in and use the API (only the gateway port is published):

```bash
curl -X POST http://localhost:8080/auth/login -H 'Content-Type: application/json' \
     -d '{"username":"priya","password":"Demo@12345"}'
```

Demo logins created by `seed_demo.py` (password `Demo@12345`, demos only): `asha` (manager), `priya` and `karan` (employees).
The admin is `admin` with the password printed by `init_env.py` (also in `.env`).

Each service serves Swagger at `/docs`, but the gateway deliberately does not expose it. For development, publish the
services too: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`, then open
http://localhost:8001/docs (auth), `:8002` (employee), `:8003` (leave), `:8004` (payroll).

### What `docker compose up` does, in order

1. `postgres` starts. On first start it creates `auth_db`, `employee_db`, `leave_db`, `payroll_db`, **each owned by its own role** that cannot even connect to the others.
2. `*-migrate` one-shot containers run `alembic upgrade head` per service (migrations are a separate step, not part of app start-up).
3. `auth-bootstrap-admin` creates the first admin if it doesn't exist (safe on every restart).
4. The services start once their migration finished (and, for leave/payroll, once employee-service is healthy).
5. The `gateway` starts last, after all services report healthy.

### Useful commands

```bash
docker compose ps                     # health of everything
docker compose logs -f payroll-service
docker compose down                   # stop (data kept in the pgdata volume)
docker compose down -v                # stop AND delete all data (needed after changing DB passwords in .env)
```

### Troubleshooting

- **`variable is not set` on start:** run `python scripts/init_env.py` first.
- **Changed a DB password in `.env` and now services can't log in:** roles are created only when the volume is created. Run `docker compose down -v` (deletes data) and start again.
- **Lost `BANK_ENCRYPTION_KEY`:** stored bank account numbers can no longer be decrypted. Back up `.env`.
- **Port 8080 is taken:** set `GATEWAY_PORT` in `.env`.
- **Windows:** keep `infra/postgres/init-databases.sh` with LF line endings (`.gitattributes` does this when you clone with git).

## Quick start (Kubernetes / minikube)

Same system with 2 replicas per service, probes, rolling updates and an Ingress. Full walkthrough and demo scenarios: [`k8s/README.md`](k8s/README.md).

```bash
minikube start --cpus=2 --memory=4096 && minikube addons enable ingress
python scripts/init_env.py
python scripts/k8s_deploy.py --build
kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller 8080:80   # then use http://localhost:8080 as above
```

## CI/CD

GitHub Actions (`.github/workflows/ci-cd.yml`) lints and tests every service on SQLite and PostgreSQL, validates the Kubernetes
manifests, monitoring rules, compose file and Dockerfiles, deploys the whole system to a throw-away Kubernetes (kind) cluster and
runs an end-to-end smoke test (also after killing pods). On `main` it publishes the four images to GitHub Container Registry
and attaches ready-to-apply manifests. No secrets to configure. Details: [`docs/ci-cd.md`](docs/ci-cd.md).

## Layout

```
services/
  auth-service/      issues JWTs, manages users
  employee-service/  employees, salary + history, bank details
  leave-service/     leave types, requests, approvals, balances
  payroll-service/   attendance, payroll runs, payslips, bank file
  _template/         blank service (health, metrics, JSON logs, JWT guards)
infra/               nginx gateway config, Postgres init script
scripts/             init_env.py, seed_demo.py, smoke_test.py, k8s_deploy.py, check_k8s.py, sync_k8s_configs.py,
                     install_k8s_tools.sh, check_migrations_pg.sh, new_service.sh
docker-compose.yml   the whole system        docker-compose.dev.yml  dev extras (published ports)
monitoring/          Prometheus config + alert rules (unit-tested), Grafana provisioning + dashboard
k8s/                 Kubernetes manifests for minikube (kustomize), generated ConfigMaps, optional HPA
.github/             CI/CD workflow, Dependabot config, kind cluster config
docs/                api-contract.md (the design), ci-cd.md
```

## Run one service without Docker

```bash
cd services/auth-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" DATABASE_URL=sqlite:///./auth.db
alembic upgrade head && uvicorn app.main:app --reload --port 8001
```

Each service's README lists its variables. Use the **same** `JWT_SECRET` for all four.

## Tests and lint

```bash
cd services/<service> && pytest --cov=app && ruff check .
```

Tests use in-memory SQLite. To run a suite against PostgreSQL instead:
`TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/scratch_db pytest`.
All 326 service tests pass on both.

## Progress

- [x] Phase 0: repo layout and API contract
- [x] Phase 1: shared service template
- [x] Phase 2: auth-service (75 tests)
- [x] Phase 3: employee-service (73 tests)
- [x] Phase 4: leave-service (81 tests)
- [x] Phase 5: payroll-service (97 tests)
- [x] Phase 6: per-service migrations, admin bootstrap, demo seed script
- [x] Phase 7: role-matrix tests per service + end-to-end smoke test across all services
- [x] Phase 8: Docker Compose, nginx gateway, per-service DB roles
- [x] Phase 9: Prometheus + Grafana (7 unit-tested alert rules, provisioned dashboard)
- [x] Phase 10: Kubernetes (minikube): 26 objects validated, not yet run on a real cluster
- [x] Phase 11: CI/CD (GitHub Actions + ghcr.io); checked locally, first real run happens on GitHub
- [ ] Phase 12: final docs and demo script
