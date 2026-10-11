#!/usr/bin/env python3
"""Create .env from .env.example with freshly generated random secrets (standard library only).

python scripts/init_env.py            # refuses to overwrite an existing .env
python scripts/init_env.py --force    # overwrite (NEW secrets: see the warning below)
"""

import argparse
import base64
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALNUM = string.ascii_letters + string.digits  # safe inside connection URLs


def alnum(n: int) -> str:
    return "".join(secrets.choice(ALNUM) for _ in range(n))


GENERATORS = {
    "JWT_SECRET": lambda: secrets.token_urlsafe(48),
    "BANK_ENCRYPTION_KEY": lambda: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "POSTGRES_PASSWORD": lambda: alnum(24),
    "AUTH_DB_PASSWORD": lambda: alnum(24),
    "EMPLOYEE_DB_PASSWORD": lambda: alnum(24),
    "LEAVE_DB_PASSWORD": lambda: alnum(24),
    "PAYROLL_DB_PASSWORD": lambda: alnum(24),
    "ADMIN_PASSWORD": lambda: alnum(16),
    "GRAFANA_ADMIN_PASSWORD": lambda: alnum(16),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="overwrite an existing .env")
    args = parser.parse_args()

    target, template = ROOT / ".env", ROOT / ".env.example"
    if target.exists() and not args.force:
        print(f"{target} already exists; not touching it (use --force to replace).")
        return 1

    lines, admin_password, grafana_password = [], "", ""
    for line in template.read_text().splitlines():
        key, sep, _ = line.partition("=")
        if sep and key in GENERATORS:
            value = GENERATORS[key]()
            if key == "ADMIN_PASSWORD":
                admin_password = value
            if key == "GRAFANA_ADMIN_PASSWORD":
                grafana_password = value
            line = f"{key}={value}"
        lines.append(line)
    target.write_text("\n".join(lines) + "\n")
    try:
        target.chmod(0o600)
    except OSError:
        pass  # e.g. Windows

    print(f"Wrote {target}")
    print(f"  admin login:  username 'admin'  password '{admin_password}'")
    print(f"  Grafana:      http://localhost:3000  username 'admin'  password '{grafana_password}'")
    print("  Back up BANK_ENCRYPTION_KEY: without it stored bank account numbers cannot be read.")
    if args.force:
        print("  WARNING: new database passwords only take effect on a fresh volume:")
        print("           run  docker compose down -v  (this DELETES the stored data).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
