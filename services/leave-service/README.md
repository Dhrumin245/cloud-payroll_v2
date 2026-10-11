# leave-service

Leave types, leave requests (apply / approve / reject / cancel), balances, and the approved-leave
feed that payroll-service consumes. Owns `leave_db`.
Endpoint list and rules: [`../../docs/api-contract.md`](../../docs/api-contract.md) section 5.

## Configuration (environment variables)

| Variable | Required | Default | Notes |
|---|---|---|---|
| `JWT_SECRET` | yes | none | >= 32 chars, same value in all services |
| `DATABASE_URL` | yes | none | `postgresql+psycopg://user:pass@host:5432/leave_db` (SQLite works for dev) |
| `EMPLOYEE_SERVICE_URL` | no | `http://employee-service:8000` | set to `http://localhost:8002` for local runs |
| `EMPLOYEE_SERVICE_TIMEOUT_SECONDS` | no | 3 | beyond this, applying for leave answers 503 |

## Run

```bash
pip install -r requirements-dev.txt
export JWT_SECRET=... DATABASE_URL=sqlite:///./leave.db EMPLOYEE_SERVICE_URL=http://localhost:8002
alembic upgrade head
uvicorn app.main:app --reload --port 8003
```

Applying for leave calls employee-service, so run it too (port 8002). Log in on auth-service (8001)
and paste the token into Swagger (`/docs`, **Authorize**). An admin creates leave types first
(`POST /leave-types`), e.g. "Casual Leave" (12 days) and an unpaid type (`is_paid: false`).

## Try the workflow

1. Employee: `POST /leaves` -> `pending`; `GET /leaves/my`, `GET /leaves/balance`.
2. Manager/admin: `GET /leaves/pending`, then `POST /leaves/{id}/approve` or `/reject` (reason required).
3. Admin (payroll): `GET /leaves/approved?month=2026-10` -> paid / unpaid days per employee.

## Who can do what

| | employee | manager | admin |
|---|---|---|---|
| Apply, view/cancel own requests, own balance | yes | yes | yes (needs a linked employee record) |
| See all / pending requests, anyone's balance | no | yes | yes |
| Approve / reject (never your own) | no | yes | yes |
| Manage leave types, `/leaves/approved` | no | no | yes |

## Tests

```bash
pytest --cov=app && ruff check .
```

`tests/test_clients.py` tests the real HTTP client against a mocked transport; the other tests
swap in a fake employee-service client.

## Differences from the legacy monolith

- JSON API; no sessions, CSRF or templates. The applicant comes from the JWT.
- Attendance sync is gone: payroll-service pulls `/leaves/approved?month=` instead of this service writing into payroll tables.
- New: `cancelled` status, mandatory rejection reason (stored in `decision_note`, not appended to the reason), no self-approval, early limit check when applying, usage tracked for unlimited types too, 365-day and "no working days" validation.
- `employee_id` and approver ids are plain integers (no foreign keys across services).

## Metrics

`/metrics` (internal only) exposes the standard HTTP metrics plus this service's business counters and `downstream_calls_total{target,outcome}`; see [`../../monitoring/README.md`](../../monitoring/README.md).
