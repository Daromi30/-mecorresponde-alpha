from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.operations.db_backup import BackupConfigurationError, create_backup


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a credential-safe MECORRESPONDE PostgreSQL backup archive."
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory outside ephemeral application storage where the archive will be written.",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        parser.error("DATABASE_URL is required")

    try:
        backup, manifest = create_backup(database_url, Path(args.output_dir))
    except BackupConfigurationError as exc:
        parser.error(str(exc))

    print(f"backup={backup}")
    print(f"manifest={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
