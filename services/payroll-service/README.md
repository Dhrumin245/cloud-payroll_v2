# payroll-service

Payroll runs with loss-of-pay, statutory deductions, payslip PDFs, CSV export and the bank payout file.
Owns `payroll_db`. Endpoint list and rules: [`../../docs/api-contract.md`](../../docs/api-contract.md) section 6.

## Configuration (environment variables)

| Variable | Required | Default | Notes |
|---|---|---|---|
| `JWT_SECRET` | yes | none | >= 32 chars, same value in all services |
| `DATABASE_URL` | yes | none | `postgresql+psycopg://user:pass@host:5432/payroll_db` (SQLite works for dev) |
| `EMPLOYEE_SERVICE_URL` | no | `http://employee-service:8000` | `http://localhost:8002` for local runs |
| `LEAVE_SERVICE_URL` | no | `http://leave-service:8000` | `http://localhost:8003` for local runs |
| `DOWNSTREAM_TIMEOUT_SECONDS` | no | 10 | per call to employee/leave service |
| `COMPANY_NAME`, `COMPANY_ADDRESS` | no | placeholder | printed on payslips |

## Run

```bash
pip install -r requirements-dev.txt
export JWT_SECRET=... DATABASE_URL=sqlite:///./payroll.db
export EMPLOYEE_SERVICE_URL=http://localhost:8002 LEAVE_SERVICE_URL=http://localhost:8003
alembic upgrade head        # also seeds the statutory defaults and starter PT slabs
uvicorn app.main:app --reload --port 8004
```

Running payroll needs auth (8001), employee (8002) and leave (8003) services up, because it pulls salaries
and approved leave from them.

## A typical month

1. Managers/admins record unexplained absence: `PUT /attendance/{employee_id}/2026-08 {"days_absent": "1"}`.
2. Admin adds one-off pay: `POST /variable-pay` (bonus or deduction).
3. Admin (once) switches statutory deductions on: `PUT /settings/statutory`.
4. Admin runs `POST /payroll/runs {"period": "2026-08"}`. If anything is wrong the response lists every problem.
5. Employees download payslips (`GET /payslips/my`, then `/payslips/{id}/pdf`). Admin exports the CSV or the bank file.

## How pay is calculated

See "Loss-of-pay rules" in the contract. In short: approved paid leave is paid; unpaid leave and unexplained
absence reduce pay proportionally; bonuses and deductions are not prorated. The maths lives in `app/engine.py`
with no database or HTTP imports, and has its own unit tests.

## Tests

```bash
pytest --cov=app && ruff check .
```

`tests/test_clients.py` tests the real HTTP clients against a mocked transport; the other tests swap in fakes.

## Differences from the legacy monolith

- No HTML, sessions or CSRF. Salary and leave come from other services over HTTP with the caller's JWT.
- **Loss-of-pay is new.** HR no longer types `days_present` for everyone: only unexplained absences are recorded.
- Run history, details, CSV, bank file and payslip access are restricted (legacy: any logged-in user).
- The bank file reads account numbers through employee-service, so every reveal is audit-logged there.
- Extra safety: future months are refused, all problems are reported at once, CSV cells starting with `=`, `+`, `-`, `@` are neutralised.
- Not ported: Excel export, analytics dashboard, the `payslips` cache table (PDFs are generated on demand).
- Mid-month joiners are paid for the full month, as in the legacy app (no joining-date proration yet).

## Metrics

`/metrics` (internal only) exposes the standard HTTP metrics plus this service's business counters and `downstream_calls_total{target,outcome}`; see [`../../monitoring/README.md`](../../monitoring/README.md).
