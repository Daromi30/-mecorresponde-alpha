"""One-time local bootstrap; never exposes first-operator creation over HTTP.

Run only against an explicitly selected database during an authorized operation.
The password is read from the terminal, never argv, logs, or source files.
"""

from __future__ import annotations

import argparse
import getpass

from sqlalchemy import select

from .auth_models import Reviewer
from .backoffice_auth import create_reviewer
from .db import SessionLocal
from .services_v2 import audit


def bootstrap_first_operator(login_id: str, password: str) -> str:
    with SessionLocal() as db:
        if db.scalar(select(Reviewer.id).limit(1)) is not None:
            raise RuntimeError("Backoffice already has a reviewer; use an authenticated operator")
        reviewer = create_reviewer(db, login_id, password, "operator")
        audit(db, None, "BACKOFFICE_FIRST_OPERATOR_BOOTSTRAPPED", {}, actor_reviewer_id=reviewer.id)
        db.commit()
        return reviewer.id


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision the first backoffice operator locally")
    parser.add_argument("login_id", help="Unique non-email reviewer login identifier")
    args = parser.parse_args()
    first = getpass.getpass("Initial operator password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Passwords do not match")
    reviewer_id = bootstrap_first_operator(args.login_id, first)
    print(f"First operator created: {reviewer_id}")


if __name__ == "__main__":
    main()
