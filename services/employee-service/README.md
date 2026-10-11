# employee-service

Employee profiles, salary structures (with history) and encrypted bank details.
Owns `employee_db`. Endpoint list and rules: [`../../docs/api-contract.md`](../../docs/api-contract.md) section 4.

## Configuration (environment variables)

| Variable | Required | Notes |
|---|---|---|
| `JWT_SECRET` | yes | >= 32 chars, same value in all services |
| `DATABASE_URL` | yes | `postgresql+psycopg://user:pass@host:5432/employee_db` (SQLite works for dev) |
| `BANK_ENCRYPTION_KEY` | yes | Fernet key. `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. **Back it up**: losing it makes stored account numbers unreadable. |

## Run

```bash
pip install -r requirements-dev.txt
export JWT_SECRET=... DATABASE_URL=sqlite:///./employee.db BANK_ENCRYPTION_KEY=...
alembic upgrade head
uvicorn app.main:app --reload --port 8002
```

You need a JWT to call anything: log in on auth-service (port 8001) and paste the token into
Swagger (`/docs`, **Authorize**). Both services must share `JWT_SECRET`.

## Who can do what

| | employee | manager | admin |
|---|---|---|---|
| Own profile (`/employees/me`) | yes | yes | yes |
| List / read any profile, create, edit, (de)activate | no | yes | yes |
| Salary and bank details (own) | read | no | read/write |
| Salary and bank details (others) | no | no | read/write |
| Full account number (`/reveal`), `/payroll-data` | no | no | yes |

## Salary history

`PUT /employees/{id}/salary` with changed values stores the previous version in
`salary_structure_history` and starts a new one (`effective_from` = today unless you pass a date). The very first salary starts on the employee's joining date.
`GET .../salary?as_of=2026-03-01` returns the version that was in effect on that day.

## Tests

```bash
pytest --cov=app && ruff check .
```

## Differences from the legacy monolith

- JSON API; the single big form became separate endpoints (profile, salary, bank details).
- Salary and bank writes are admin-only (legacy let managers edit them).
- Salary history can be queried by date (`as_of`), and records who made each change.
- Money is returned as 2-decimal strings; IFSC codes are validated and upper-cased.
- Variable pay moved to payroll-service; attendance sync moved out (leave-service exposes approved leave instead).
