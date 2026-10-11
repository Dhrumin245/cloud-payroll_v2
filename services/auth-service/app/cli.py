"""Bootstrap accounts. There is no public signup: the first admin is created here.

    python -m app.cli create-user --username admin --role admin
    ADMIN_PASSWORD=... python -m app.cli create-user \
        --username admin --role admin --password-env ADMIN_PASSWORD

The --password-env form is for non-interactive use (Docker/Kubernetes init jobs).
Add --if-not-exists to make it safe to run on every start: an existing username is left alone.
"""

import argparse
import getpass
import os
import sys

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.schemas import UserCreate
from app.user_service import create_user


def _read_password(env_name: str | None) -> str:
    if env_name:
        value = os.environ.get(env_name)
        if not value:
            sys.exit(f"Environment variable {env_name} is not set")
        return value
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        sys.exit("Passwords do not match")
    return password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    cu = sub.add_parser("create-user", help="create a user account")
    cu.add_argument("--username", required=True)
    cu.add_argument("--role", required=True, choices=["admin", "manager", "employee"])
    cu.add_argument("--employee-id", type=int, default=None)
    cu.add_argument("--password-env", default=None, help="read the password from this env var")
    cu.add_argument(
        "--if-not-exists",
        action="store_true",
        help="do nothing (exit 0) if the username already exists",
    )
    args = parser.parse_args(argv)

    if args.if_not_exists:
        with SessionLocal() as db:
            if db.scalar(select(User.id).where(User.username == args.username.strip())):
                print(f"User '{args.username}' already exists; nothing to do.")
                return 0

    password = _read_password(args.password_env)
    try:
        data = UserCreate(
            username=args.username,
            password=password,
            role=args.role,
            employee_id=args.employee_id,
        )
    except ValidationError as exc:
        for err in exc.errors():
            print(f"Invalid {'.'.join(map(str, err['loc'])) or 'input'}: {err['msg']}")
        return 1

    with SessionLocal() as db:
        try:
            user = create_user(db, data)
        except HTTPException as exc:
            print(exc.detail)
            return 1
    print(f"User '{user.username}' ({user.role}) created with id {user.id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
