# Service template

Blank FastAPI service with everything all four services share:
`/health`, `/ready`, `/metrics`, JSON logs, env config (no default secrets),
JWT verification and role guards (`require_admin`, `require_manager_or_above`).

Delete `app/routers/example.py` (and its include in `main.py`) in each real service.
