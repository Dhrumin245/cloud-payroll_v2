#!/usr/bin/env python3
"""Fill a running system with demo data through the gateway (standard library only).

    python scripts/seed_demo.py                       # reads ADMIN_* from .env, gateway on :8080
    python scripts/seed_demo.py --url http://localhost:8080 --admin-password '...'

Creates leave types, 3 employees (with salaries and bank details) and logins for them.
Safe to run twice: anything that already exists is left alone. FOR DEMOS ONLY: it uses a
well-known password for the demo users.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEMO_PASSWORD = "Demo@12345"

LEAVE_TYPES = [
    {"name": "Casual Leave", "max_days_per_year": "12", "is_paid": True},
    {"name": "Sick Leave", "max_days_per_year": "10", "is_paid": True},
    {"name": "Unpaid Leave", "is_paid": False},
]
# (full name, designation, joining date, basic, hra, conveyance, login username, role)
PEOPLE = [
    ("Asha Rao", "HR Manager", "2022-04-01", "60000", "24000", "1600", "asha", "manager"),
    ("Priya Shah", "Software Engineer", "2024-01-15", "50000", "20000", "1600", "priya", "employee"),
    ("Karan Verma", "QA Engineer", "2025-03-03", "40000", "16000", "1600", "karan", "employee"),
]


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token: str | None = None

    def call(self, method: str, path: str, body: dict | None = None, ok=(200, 201, 204)):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as err:
            status, raw = err.code, err.read()
        except urllib.error.URLError as err:
            sys.exit(f"Cannot reach {self.base}: {err.reason}. Is `docker compose up` running?")
        payload = json.loads(raw) if raw else None
        return status, payload


def read_env(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                values[key.strip()] = value.strip()
    return values


def main() -> int:
    env = read_env(Path(__file__).resolve().parent.parent / ".env")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default=f"http://localhost:{env.get('GATEWAY_PORT', '8080')}")
    ap.add_argument("--admin-username", default=env.get("ADMIN_USERNAME", "admin"))
    ap.add_argument("--admin-password", default=env.get("ADMIN_PASSWORD"))
    args = ap.parse_args()
    if not args.admin_password:
        sys.exit("No admin password: run scripts/init_env.py first or pass --admin-password.")

    api = Api(args.url)
    status, body = api.call("POST", "/auth/login", {"username": args.admin_username, "password": args.admin_password})
    if status != 200:
        sys.exit(f"Admin login failed ({status}): {body}")
    api.token = body["access_token"]
    print(f"Logged in as {args.admin_username}")

    for lt in LEAVE_TYPES:
        status, _ = api.call("POST", "/leave-types", lt)
        print(f"  leave type {lt['name']:<14} {'created' if status == 201 else 'exists' if status == 409 else status}")

    status, existing = api.call("GET", "/employees?status=all&limit=200")
    by_name = {e["full_name"]: e for e in existing} if status == 200 else {}

    for name, designation, joined, basic, hra, conv, username, role in PEOPLE:
        employee = by_name.get(name)
        if employee is None:
            status, employee = api.call(
                "POST",
                "/employees",
                {"full_name": name, "designation": designation, "joining_date": joined},
            )
            if status != 201:
                sys.exit(f"Could not create employee {name}: {status} {employee}")
        eid = employee["id"]
        api.call("PUT", f"/employees/{eid}/salary", {"basic_pay": basic, "hra": hra, "conveyance_allowance": conv})
        bank_number = f"5000{eid:08d}"
        api.call(
            "PUT",
            f"/employees/{eid}/bank-details",
            {
                "account_holder_name": name,
                "account_number": bank_number,
                "ifsc_code": "HDFC0001234",
                "bank_name": "HDFC Bank",
            },
        )
        status, _ = api.call(
            "POST",
            "/auth/register",
            {"username": username, "password": DEMO_PASSWORD, "role": role, "employee_id": eid},
        )
        state = "created" if status == 201 else "exists" if status == 409 else f"FAILED {status}"
        print(f"  {employee['employee_code']}  {name:<12} {role:<9} login '{username}': {state}")

    print()
    print("Demo logins (password for all three: %s)" % DEMO_PASSWORD)
    print("  asha  = manager (approves leave)   priya, karan = employees (apply for leave)")
    print(
        f"Try:  curl -X POST {args.url}/auth/login -H 'Content-Type: application/json' "
        '-d \'{"username":"priya","password":"%s"}\'' % DEMO_PASSWORD
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
