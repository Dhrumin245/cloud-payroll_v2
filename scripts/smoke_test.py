#!/usr/bin/env python3
"""End-to-end test through the public gateway (standard library only).

    python scripts/smoke_test.py                                   # gateway on :8080, admin from .env
    python scripts/smoke_test.py --url http://localhost:8080 --admin-password '...'
    python scripts/smoke_test.py --prometheus http://localhost:9090 --min-targets 8   # also check monitoring

It creates its own data (unique names, so it can run repeatedly) and walks the whole business flow:
employee applies for leave -> manager approves -> payroll run with loss-of-pay -> payslip PDF ->
bank file, plus access-control checks. Exits 1 at the first failure. Used by CI on every push.

Needs an administrator login and a system where every active employee has a salary
(true for a fresh install or after scripts/seed_demo.py).
"""

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

PASSWORD = "Smoke-Pass-1"
RUN = random.Random().randbytes(3).hex()
steps = 0


def ok(message: str) -> None:
    global steps
    steps += 1
    print(f"[ ok ] {message}", flush=True)


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def expect(condition: bool, message: str, detail=None) -> None:
    if not condition:
        fail(f"{message}" + (f"\n       got: {detail}" if detail is not None else ""))
    ok(message)


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def call(self, method, path, body=None, token=None, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status, payload, headers = resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as err:
            status, payload, headers = err.code, err.read(), err.headers
        except urllib.error.URLError as err:
            fail(f"cannot reach {self.base}: {err.reason}")
        if raw:
            return status, payload, headers
        try:
            return status, json.loads(payload) if payload else None, headers
        except ValueError:
            return status, payload.decode(errors="replace"), headers

    def login(self, username: str, password: str) -> str:
        for _ in range(3):  # tolerate the per-IP login rate limit
            status, body, headers = self.call("POST", "/auth/login", {"username": username, "password": password})
            if status == 429:
                wait = min(int(headers.get("Retry-After", "10")), 65)
                print(f"       login rate limited, waiting {wait}s", flush=True)
                time.sleep(wait)
                continue
            expect(status == 200, f"login as {username}", (status, body))
            return body["access_token"]
        fail(f"login as {username}: still rate limited")


def read_env() -> dict[str, str]:
    path = Path(__file__).resolve().parent.parent / ".env"
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                values[key.strip()] = value.strip()
    return values


def working_days(year: int, month: int) -> int:
    day, count = date(year, month, 1), 0
    while day.month == month:
        count += day.weekday() != 6
        day += timedelta(days=1)
    return count


def first_monday(year: int, month: int) -> date:
    day = date(year, month, 1)
    while day.weekday() != 0:
        day += timedelta(days=1)
    return day


def money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def main() -> int:
    env = read_env()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default=f"http://localhost:{env.get('GATEWAY_PORT', '8080')}")
    ap.add_argument("--admin-username", default=env.get("ADMIN_USERNAME", "admin"))
    ap.add_argument("--admin-password", default=env.get("ADMIN_PASSWORD"))
    ap.add_argument("--prometheus", help="Prometheus base URL, to also check the monitoring")
    ap.add_argument("--min-targets", type=int, default=4, help="scrape targets that must be up")
    args = ap.parse_args()
    if not args.admin_password:
        sys.exit("No admin password: run scripts/init_env.py first or pass --admin-password.")
    api = Api(args.url)

    print(f"Smoke test against {args.url} (run id {RUN})")
    # ---------------------------------------------------------------- gateway
    status, _, _ = api.call("GET", "/auth/me")
    expect(status == 401, "gateway reaches auth-service (unauthenticated request gets 401)", status)
    for path in ("/metrics", "/ready", "/docs", "/openapi.json"):
        status, _, _ = api.call("GET", path)
        expect(status == 404, f"{path} is not exposed publicly", status)

    # ---------------------------------------------------------------- set up people and leave types
    admin = api.login(args.admin_username, args.admin_password)
    status, runs, _ = api.call("GET", "/payroll/runs", token=admin)
    expect(status == 200, "admin can list payroll runs", status)
    taken = {r["period"] for r in runs}
    candidates = [f"{y}-{m:02d}" for y in range(2021, 2026) for m in range(1, 13) if f"{y}-{m:02d}" not in taken]
    expect(bool(candidates), "an unprocessed month is available for the test payroll run")
    period = random.choice(candidates)
    year, month = int(period[:4]), int(period[5:])

    people = {}
    for role, label, basic in (("employee", "worker", "26000"), ("manager", "approver", "52000")):
        status, emp, _ = api.call(
            "POST",
            "/employees",
            token=admin,
            body={
                "full_name": f"Smoke {label} {RUN}",
                "designation": "Smoke Test",
                "joining_date": "2020-01-01",
            },
        )
        expect(status == 201, f"admin creates employee '{label}'", (status, emp))
        status, _, _ = api.call("PUT", f"/employees/{emp['id']}/salary", {"basic_pay": basic}, token=admin)
        expect(status == 200, f"admin sets {label}'s salary", status)
        username = f"smoke_{label}_{RUN}"
        status, user, _ = api.call(
            "POST",
            "/auth/register",
            token=admin,
            body={"username": username, "password": PASSWORD, "role": role, "employee_id": emp["id"]},
        )
        expect(status == 201, f"admin creates login for {label}", (status, user))
        people[label] = {"employee_id": emp["id"], "username": username, "basic": Decimal(basic)}
    worker, approver = people["worker"], people["approver"]
    status, _, _ = api.call(
        "PUT",
        f"/employees/{worker['employee_id']}/bank-details",
        token=admin,
        body={
            "account_holder_name": f"Smoke worker {RUN}",
            "account_number": f"900{RUN}12345",
            "ifsc_code": "HDFC0001234",
        },
    )
    expect(status == 200, "admin saves the worker's bank details", status)

    status, ltype_paid, _ = api.call(
        "POST",
        "/leave-types",
        token=admin,
        body={"name": f"Smoke Casual {RUN}", "max_days_per_year": "12", "is_paid": True},
    )
    expect(status == 201, "admin creates a paid leave type", (status, ltype_paid))
    status, ltype_unpaid, _ = api.call(
        "POST", "/leave-types", token=admin, body={"name": f"Smoke Unpaid {RUN}", "is_paid": False}
    )
    expect(status == 201, "admin creates an unpaid leave type", (status, ltype_unpaid))

    worker_t = api.login(worker["username"], PASSWORD)
    approver_t = api.login(approver["username"], PASSWORD)

    # ---------------------------------------------------------------- leave workflow
    mon = first_monday(year, month)
    paid = (mon, mon + timedelta(days=2))  # Mon-Wed: 3 paid days
    unpaid = (mon + timedelta(days=7), mon + timedelta(days=8))  # next Mon-Tue: 2 unpaid days
    leave_ids = []
    for ltype, (start, end), days in ((ltype_paid, paid, "3.0"), (ltype_unpaid, unpaid, "2.0")):
        status, leave, _ = api.call(
            "POST",
            "/leaves",
            token=worker_t,
            body={"leave_type_id": ltype["id"], "start_date": start.isoformat(), "end_date": end.isoformat()},
        )
        expect(
            status == 201 and leave["status"] == "pending" and leave["total_days"] == days,
            f"worker applies for {days} days of '{ltype['name']}' ({start}..{end})",
            (status, leave),
        )
        leave_ids.append(leave["id"])

    status, _, _ = api.call("POST", f"/leaves/{leave_ids[0]}/approve", token=worker_t)
    expect(status == 403, "an employee cannot approve leave", status)
    status, pending, _ = api.call("GET", "/leaves/pending", token=approver_t)
    expect(
        status == 200 and set(leave_ids) <= {p["id"] for p in pending},
        "manager sees both requests as pending",
        status,
    )
    for lid in leave_ids:
        status, leave, _ = api.call("POST", f"/leaves/{lid}/approve", token=approver_t)
        expect(
            status == 200 and leave["status"] == "approved",
            f"manager approves request {lid}",
            (status, leave),
        )

    status, own, _ = api.call(
        "POST",
        "/leaves",
        token=approver_t,
        body={
            "leave_type_id": ltype_paid["id"],
            "start_date": (mon + timedelta(days=14)).isoformat(),
            "end_date": (mon + timedelta(days=14)).isoformat(),
        },
    )
    expect(status == 201, "manager applies for their own leave", (status, own))
    status, _, _ = api.call("POST", f"/leaves/{own['id']}/approve", token=approver_t)
    expect(status == 403, "nobody can approve their own leave", status)

    status, bal, _ = api.call("GET", f"/leaves/balance?year={year}", token=worker_t)
    used = {b["leave_type_name"]: b["days_used"] for b in bal["balances"]}
    expect(status == 200 and used.get(ltype_paid["name"]) == "3.0", "worker's balance shows 3.0 days used", used)
    status, summary, _ = api.call("GET", f"/leaves/approved?month={period}", token=admin)
    row = next((e for e in summary["employees"] if e["employee_id"] == worker["employee_id"]), None)
    expect(
        row == {"employee_id": worker["employee_id"], "paid_days": "3.0", "unpaid_days": "2.0"},
        "leave-service reports 3.0 paid and 2.0 unpaid days for payroll",
        row,
    )

    # ---------------------------------------------------------------- payroll
    status, _, _ = api.call("GET", "/payroll/runs", token=worker_t)
    expect(status == 403, "an employee cannot read payroll runs", status)
    status, run, _ = api.call("POST", "/payroll/runs", {"period": period}, token=admin)
    expect(
        status == 201 and run["status"] == "completed",
        f"admin runs payroll for {period}",
        (status, json.dumps(run)[:300] if run else run),
    )
    wd = working_days(year, month)
    line = next((li for li in run["line_items"] if li["employee_id"] == worker["employee_id"]), None)
    expected_gross = money(worker["basic"] * Decimal(wd - 2) / Decimal(wd))
    expect(
        line is not None
        and line["total_working_days"] == f"{wd}.0"
        and line["paid_leave_days"] == "3.0"
        and line["unpaid_leave_days"] == "2.0"
        and line["loss_of_pay_days"] == "2.0"
        and line["payable_days"] == f"{wd - 2}.0"
        and line["gross_pay"] == expected_gross,
        f"loss of pay is right: {wd} working days, 2 unpaid -> gross {expected_gross}",
        line,
    )
    status, _, _ = api.call("POST", "/payroll/runs", {"period": period}, token=admin)
    expect(status == 409, "a month cannot be run twice", status)

    # ---------------------------------------------------------------- payslips and bank file
    status, slips, _ = api.call("GET", "/payslips/my", token=worker_t)
    mine = next((s for s in slips if s["period"] == period), None)
    expect(
        status == 200 and mine is not None and mine["gross_pay"] == expected_gross,
        "worker sees their payslip",
        slips,
    )
    status, pdf, headers = api.call("GET", f"/payslips/{mine['id']}/pdf", token=worker_t, raw=True)
    expect(
        status == 200 and pdf.startswith(b"%PDF") and "pdf" in headers.get("Content-Type", ""),
        "worker downloads their payslip as a PDF",
        (status, pdf[:20]),
    )
    status, _, _ = api.call("GET", f"/payslips/{mine['id']}/pdf", token=approver_t, raw=True)
    expect(status == 403, "another employee cannot download it", status)
    status, bank, _ = api.call("GET", f"/payroll/runs/{run['id']}/bank-file", token=admin, raw=True)
    expect(
        status == 200 and f"900{RUN}12345" in bank.decode() and expected_gross in bank.decode(),
        "bank file contains the worker's account number and net pay",
        status,
    )
    status, _, _ = api.call("GET", f"/payroll/runs/{run['id']}/bank-file", token=approver_t, raw=True)
    expect(status == 403, "only admins can get the bank file", status)

    # ---------------------------------------------------------------- monitoring (optional)
    if args.prometheus:
        prom = Api(args.prometheus)
        deadline, up = time.time() + 90, 0
        while time.time() < deadline:
            status, res, _ = prom.call(
                "GET", "/api/v1/query?" + urllib.parse.urlencode({"query": 'count(up{job="services"} == 1)'})
            )
            up = int(float(res["data"]["result"][0]["value"][1])) if status == 200 and res["data"]["result"] else 0
            if up >= args.min_targets:
                break
            time.sleep(5)
        expect(
            up >= args.min_targets,
            f"Prometheus scrapes at least {args.min_targets} service targets (got {up})",
        )
        deadline, events = time.time() + 90, 0.0
        while time.time() < deadline:
            status, res, _ = prom.call(
                "GET",
                "/api/v1/query?" + urllib.parse.urlencode({"query": 'sum(leave_requests_total{event="approved"})'}),
            )
            events = float(res["data"]["result"][0]["value"][1]) if status == 200 and res["data"]["result"] else 0.0
            if events >= 2:
                break
            time.sleep(5)
        expect(events >= 2, "Prometheus has recorded the approved leave requests", events)

    print(f"\nAll {steps} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
