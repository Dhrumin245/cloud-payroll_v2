# auth-service

Issues JWTs and manages user accounts. Owns `auth_db` (table `users`).
Endpoint list and rules: [`../../docs/api-contract.md`](../../docs/api-contract.md) section 3.

## Configuration (environment variables)

| Variable | Required | Default | Notes |
|---|---|---|---|
| `JWT_SECRET` | yes | none | >= 32 chars, shared by all services |
| `DATABASE_URL` | yes | none | `postgresql+psycopg://user:pass@host:5432/auth_db` (SQLite works for dev) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | 60 | |
| `BCRYPT_ROUNDS` | no | 12 | |
| `LOGIN_RATE_LIMIT_PER_MINUTE` | no | 5 | per client IP |
| `TRUST_FORWARDED_FOR` | no | false | set `true` behind nginx/Ingress, otherwise all users share one rate-limit bucket |

## Run

```bash
pip install -r requirements-dev.txt
export JWT_SECRET=... DATABASE_URL=sqlite:///./auth.db
alembic upgrade head
python -m app.cli create-user --username admin --role admin
uvicorn app.main:app --reload --port 8001
```

In Swagger (`/docs`): call `POST /auth/login`, copy `access_token`, click **Authorize**, paste it.

Non-interactive bootstrap (Docker/Kubernetes init job):
`ADMIN_PASSWORD=... python -m app.cli create-user --username admin --role admin --password-env ADMIN_PASSWORD`

## Migrations

```bash
alembic upgrade head                              # apply
alembic revision --autogenerate -m "describe"     # after changing app/models.py
```

`tests/test_migrations.py` fails if the models and migrations drift apart.

## Tests

```bash
pytest --cov=app && ruff check .
```

## Differences from the legacy monolith

- JSON API, JWT bearer tokens; sessions, CSRF and HTML templates are gone.
- `employee_id` has no foreign key (employee data lives in employee-service).
- Password hashing uses `bcrypt` directly (existing `$2b$` hashes from passlib still verify); minimum password length is 8 (was 6).
- `toggle-active` became `PATCH /users/{id}`; admins also can't change their own role.
- Deactivated/demoted admins are locked out of user management immediately.
