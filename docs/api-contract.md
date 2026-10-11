# API Contract (Phase 0)

Frozen design for the four services. Build to this; if you need to change it, change this file first.

## 1. Architecture

```
                 ┌────────────────────────── Gateway (nginx / k8s Ingress) ──────────────────────────┐
  Client ──────► │  /auth,/users ─► auth-service      /employees ─► employee-service                  │
  (Swagger/UI)   │  /leaves,/leave-types ─► leave-service      /payroll,/payslips ─► payroll-service  │
                 └────────────────────────────────────────────────────────────────────────────────────┘

  leave-service   ── GET /employees/{id}/exists ──►  employee-service
  payroll-service ── GET /employees/payroll-data, /employees/{id}/bank-details/reveal ──►  employee-service
  payroll-service ── GET /leaves/approved?month= ──►  leave-service

  auth_db      employee_db      leave_db      payroll_db      (one database per service, one Postgres server)
```

| Service | Owns (tables) | DB | Container port | Local dev port |
|---|---|---|---|---|
| auth-service | users | auth_db | 8000 | 8001 |
| employee-service | employees, bank details, salary structures | employee_db | 8000 | 8002 |
| leave-service | leave types, leave requests, leave balances | leave_db | 8000 | 8003 |
| payroll-service | attendance, variable pay, payroll runs, line items, payslips | payroll_db | 8000 | 8004 |

### Gateway (nginx)
One public entry point; routes by path prefix and exposes nothing else (`/metrics`, `/ready`, `/docs`, `/openapi.json` of the services are **not** public; Prometheus scrapes the services directly on the internal network).

| Prefix | Service |
|---|---|
| `/auth`, `/users` | auth-service |
| `/employees` | employee-service |
| `/leaves`, `/leave-types` | leave-service |
| `/payroll`, `/payslips`, `/attendance`, `/variable-pay`, `/settings` | payroll-service |

`GET /health` is answered by the gateway itself. The gateway **overwrites** `X-Forwarded-For` with the real client address (auth-service rate-limits on it, so a client must not be able to choose its own), adds an `X-Request-ID`, and returns its own JSON `503` when a service is down or too slow. A specific `503` sent by a service (e.g. "employee-service is unavailable") passes through unchanged. Access logs are JSON.

**Rules**
1. A service only reads/writes its own database. No cross-database queries, **no cross-service foreign keys**: `employee_id` / `user_id` stored in another service's tables are plain integers, validated over HTTP.
2. Only auth-service **issues** JWTs. The other three only **verify** them (shared `JWT_SECRET`).
3. Service-to-service calls **forward the caller's JWT** in the `Authorization` header. No separate service accounts.
4. Every service exposes `GET /health`, `GET /ready`, `GET /metrics` (public, no auth).

## 2. JWT

Algorithm HS256. Header: `Authorization: Bearer <token>`.

| Claim | Type | Meaning |
|---|---|---|
| `sub` | string | user id (auth-service `users.id`) |
| `role` | string | `admin` \| `manager` \| `employee` |
| `employee_id` | int \| null | linked employee record (employee-service) |
| `iat`, `exp` | int | issued-at / expiry (access token: 60 min) |

Status codes: **401** missing/invalid/expired token, **403** valid token but wrong role or not the owner, **404** not found, **409** state conflict (e.g. approving an already-approved leave), **422** validation error, **503** a downstream service is unavailable.

## 3. auth-service

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | /auth/login | public | `{username, password}` -> `{access_token, token_type, expires_in}` |
| POST | /auth/register | admin | create user `{username, password, role, employee_id?}` |
| GET | /auth/me | any | current user from token + DB |
| POST | /auth/change-password | any | change own password |
| GET | /users | admin | list users (`role`, `is_active`, `limit`, `offset`) |
| GET | /users/{id} | admin | one user |
| PATCH | /users/{id} | admin | change `role` / `is_active` / `employee_id` (null unlinks) |
| POST | /users/{id}/reset-password | admin | set a new password |

**Rules (implemented in Phase 2)**
- Username: 3-50 chars (letters, digits, `.`, `_`, `-`), unique. Password: 8-72 bytes (bcrypt limit).
- Role `employee` requires `employee_id`; any other role may have one too (managers also take leave). One employee can be linked to **one** user only.
- Login failure is always the same `401 Invalid username or password` (unknown user, wrong password, inactive account).
- Login is rate-limited per client IP (default 5/min, in-memory per replica; `429` + `Retry-After`).
- An admin cannot deactivate or change the role of **their own** account.
- User-management endpoints re-check the database, so a deactivated or demoted admin is locked out immediately. Other services trust the JWT only, so a deactivated account's token stays valid in *them* until it expires (<= 60 min). Keep the expiry short; this is the usual stateless-JWT trade-off.
- `employee_id` is **not** validated against employee-service when creating a user (that would make auth depend on employee). The admin links a real employee; revisit in Phase 3 if you want a check.
- First admin: `python -m app.cli create-user --username admin --role admin` (no public signup).

**Metrics:** `auth_logins_total{result=success|failure|rate_limited}`.

## 4. employee-service

Money values are always **2-decimal strings** (`"50000.00"`). Dates are `YYYY-MM-DD`.

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | /employees | admin, manager | create employee profile (code auto-generated `EMP0001...` if omitted) |
| GET | /employees | admin, manager | list (`search`, `status=active\|inactive\|all`, `limit`, `offset`) |
| GET | /employees/next-code | admin, manager | next free `EMPnnnn` code |
| GET | /employees/me | any | own record (`employee_id` from token) |
| GET | /employees/payroll-data?as_of= | admin | active employees who had joined by `as_of`, each with the salary **in effect on that date** (used by payroll) |
| GET | /employees/{id} | admin, manager, or self | one employee (profile only, no salary/bank) |
| GET | /employees/{id}/exists | any authenticated | `{exists, is_active}`, never 404 (used by leave) |
| PATCH | /employees/{id} | admin, manager | partial update |
| POST | /employees/{id}/deactivate, /reactivate | admin, manager | change status (idempotent) |
| GET | /employees/{id}/salary?as_of= | admin, or self | current salary, or the version in effect on `as_of` |
| PUT | /employees/{id}/salary | **admin** | set/replace salary (basic, hra, conveyance, components) |
| GET | /employees/{id}/salary/history | admin, or self | previous versions, newest first |
| GET | /employees/{id}/bank-details | admin, or self | masked (`****1234`) |
| PUT | /employees/{id}/bank-details | **admin** | set/update; `account_number` may be omitted on update to keep the stored one |
| GET | /employees/{id}/bank-details/reveal | **admin** | full account number for bank payout files; audit-logged |

**Rules (implemented in Phase 3)**
- Matches the legacy app: managers may create/edit/deactivate employee *profiles*. **Tightened vs legacy:** salary and bank details are writable by admin only, and managers cannot read them (admin + the employee themself only).
- A salary `PUT` that changes nothing is a no-op. A real change copies the old version to `salary_structure_history` (with who changed it) and sets the new `effective_from` (default today, or the date you send). A **first** salary defaults to the employee's **joining date**, so payroll for months before it was entered still finds a salary. `as_of` lookups therefore return the salary that was actually in effect on a past date, which is what payroll for an earlier month needs.
- Bank account numbers are Fernet-encrypted at rest (`BANK_ENCRYPTION_KEY`, separate from `JWT_SECRET`); only the last 4 digits are stored in clear. Every `reveal` is logged (event `bank_revealed`, no number in the log) and counted in `employee_bank_reveals_total`.
- Deactivating an employee does **not** deactivate their login; an admin does that in auth-service.
- Variable pay (one-off bonuses/deductions per month) is **not** here; it stays in payroll-service.

## 5. leave-service

Day counts are 1-decimal strings (`"3.0"`). Dates are `YYYY-MM-DD`, months `YYYY-MM`.

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | /leave-types | any | list leave types |
| POST | /leave-types | admin | create (`name`, `max_days_per_year` null = unlimited, `is_paid`) |
| PATCH | /leave-types/{id} | admin | update |
| POST | /leaves | any with `employee_id` in token | apply for leave (applicant = token `employee_id`, never the body) |
| GET | /leaves/my | any with `employee_id` | own requests + status (`status`, `limit`, `offset`) |
| GET | /leaves/balance?year=&employee_id= | any (own); admin/manager (anyone's) | used / pending / remaining per leave type |
| GET | /leaves/{id} | owner, admin, manager | one request |
| POST | /leaves/{id}/cancel | owner | cancel while pending |
| GET | /leaves/pending | admin, manager | awaiting a decision, oldest first |
| GET | /leaves | admin, manager | all requests (`status`, `employee_id`, `leave_type_id`, `month`, paging) |
| POST | /leaves/{id}/approve | admin, manager | approve (optional `{note}`); not your own request |
| POST | /leaves/{id}/reject | admin, manager | reject with mandatory `{reason}`; not your own request |
| GET | /leaves/approved?month=YYYY-MM | admin | `{month, employees: [{employee_id, paid_days, unpaid_days}]}` (used by payroll) |

Status flow: `pending -> approved | rejected | cancelled`. Only `pending` can change; approved leave cannot be cancelled.

**Rules (implemented in Phase 4)**
- **Any manager or admin may approve or reject any employee's request** (no manager hierarchy). Nobody may decide their own request.
- Days count every date in the range **except Sundays** (same as the legacy app; public holidays are not modelled).
- A request needs at least one counted day and may span at most 365 days. Past dates are allowed (back-filling sick leave).
- A new request may not overlap the same employee's pending or approved requests. Rejected and cancelled ones don't block.
- Yearly entitlement (`max_days_per_year`) is checked early when applying (against approved usage) and again, under a row lock, when approving. Usage is tracked for **all** types, limited or not. A request over New Year is split between the two years.
- Applying calls employee-service `GET /employees/{id}/exists` with the caller's JWT: unknown employee -> 404, inactive -> 403, employee-service down or erroring -> **503**. Reads and decisions don't depend on it.
- Changing `is_paid` on a leave type also changes how already-approved leave is split in `/leaves/approved`.
- Responses carry `employee_id` only, not names (names live in employee-service).

**Metrics:** `leave_requests_total{event=created|approved|rejected|cancelled}`.

## 6. payroll-service

Money is a 2-decimal string (`"50000.00"`), day counts a 1-decimal string (`"2.5"`). Periods are `YYYY-MM`.

| Method | Path | Who | Purpose |
|---|---|---|---|
| PUT | /attendance/{employee_id}/{period} | admin, manager | record **unexplained absence** `{days_absent}` (half days ok) |
| GET | /attendance/{period} | admin, manager | absences recorded for the month |
| POST | /variable-pay | **admin** | one-off bonus (`earning`) or `deduction` for one month |
| GET | /variable-pay | admin | list (`period`, `employee_id`) |
| DELETE | /variable-pay/{id} | admin | remove (month must not be locked) |
| POST | /payroll/runs | **admin** | run payroll for `{period}` |
| GET | /payroll/runs | admin | run history |
| GET | /payroll/runs/{id} | admin | one run with per-employee line items |
| GET | /payroll/runs/{id}/export.csv | admin | CSV export |
| GET | /payroll/runs/{id}/bank-file | **admin** | NEFT payout CSV with full account numbers |
| GET | /payslips/my | any with `employee_id` | own payslips |
| GET | /payslips/{id}/pdf | owner, admin | payslip PDF (`id` = line item id from `/payslips/my` or the run detail) |
| GET, PUT | /settings/statutory | admin | PF / ESI / Professional Tax switches and PT state |
| GET, POST | /settings/pt-slabs | admin | list (`state`) / create PT slabs |
| PUT, DELETE | /settings/pt-slabs/{id} | admin | update / delete a slab |

### Loss-of-pay rules (new; the legacy engine did not have them)

```
total_working_days = every day of the month except Sundays
paid_leave_days    = approved leave of a PAID type      (leave-service)
unpaid_leave_days  = approved leave of an UNPAID type   (leave-service)
absent_days        = unexplained absence recorded by HR (attendance)

loss_of_pay_days   = unpaid_leave_days + absent_days
payable_days       = total_working_days - loss_of_pay_days
days_present       = total_working_days - paid_leave - unpaid_leave - absent
```

Basic, HRA, conveyance and `allowance` components are prorated by `payable_days / total_working_days`
(half-up to 2 decimals). One-off bonuses (`earning`) and all deductions apply in full.
**Paid leave never reduces pay.** The legacy app prorated by a hand-typed `days_present`, so an employee on
approved paid leave was paid less unless HR remembered to count those days as present.
Net pay is not floored at zero (a negative number is shown, not hidden).

### Statutory deductions (ported)
PF 12% of **full** basic capped at 1,800; ESI 0.75% of the prorated gross while gross <= 21,000;
Professional Tax by state slab on the prorated gross. Each is off by default and switched on company-wide.
A deduction with the same name on the employee (e.g. "Provident Fund (PF)") replaces the automatic one.
Seeded in the migration: MH and KA starter slabs from the legacy app. **Verify them before real use.**

### Payroll run sequence
1. Admin calls `POST /payroll/runs {period}`. The month must not already have a run, and must not be in the future.
2. payroll-service -> employee-service `GET /employees/payroll-data?as_of=<last day of the month>`: active employees who had joined by then, each with the **salary in effect on that date**.
3. payroll-service -> leave-service `GET /leaves/approved?month=` : paid / unpaid leave days per employee.
4. Absences and variable pay for the month come from payroll's own database.
5. Every employee is checked first. Missing salary, or day counts that exceed the working days, are collected and returned **together** as `422 {message, problems[]}`. Nothing is stored.
6. Otherwise the whole run (totals, line items, components) is saved in **one transaction**. Names, codes, day counts and amounts are snapshotted, so history never changes afterwards.
7. employee-service or leave-service unreachable -> `503` naming the service; nothing is stored.

The month is **locked** once it has a run: attendance and variable pay for it can no longer be changed.

### Bank payout file
`GET /payroll/runs/{id}/bank-file` calls employee-service `/bank-details/reveal` for every employee with the admin's token
(each reveal is audit-logged there). An employee with no bank details gets a blank row so they are visible, not dropped.
If employee-service cannot answer, no file is produced (`503`), never a half-filled one.

### Access (tightened vs legacy)
In the legacy app any logged-in user could list payroll runs, read every employee's pay and download any payslip.
Now run history, run detail, CSV, bank file, variable pay and settings are **admin only**; attendance entry is
admin or manager; a payslip is visible only to its owner or an admin.

**Not ported:** the Excel export and the analytics dashboard (nothing in the assignment needs them).

**Metrics:** `payroll_runs_total{outcome=completed|rejected}`, `payroll_last_run_employees`,
`payroll_last_run_net_pay_total`, `payroll_bank_files_total`.

## 7. Legacy code -> new service map

| Legacy (`payroll_management`) | Goes to |
|---|---|
| models/user.py, routers/auth.py, routers/users.py, services/security.py | auth-service |
| models/employee*.py, salary_structure.py, routers/employees.py, employee_service.py | employee-service |
| models/leave.py, routers/leaves.py, leave part of routers/portal.py, leave_service.py | leave-service |
| models/payroll.py, attendance_record.py, variable_pay.py, statutory.py, routers/payroll.py, payroll_engine.py, payroll_service.py, payslip_pdf.py | payroll-service |
| templates/, CSRF, flash, session middleware | dropped (JSON API only) |

## 8. Open decisions (answer before Phase 4)

1. Can a manager approve **any** leave, or only their direct reports'? (Default here: any.)

Resolved: login identifier is **username** (matches the legacy `User` model).
