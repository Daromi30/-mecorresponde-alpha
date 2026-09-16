from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.operations.db_backup import BackupConfigurationError, verify_backup_archive


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a MECORRESPONDE PostgreSQL custom backup and checksum manifest."
    )
    parser.add_argument("backup", help="Path to the .dump archive")
    parser.add_argument("manifest", help="Path to the .manifest.json file")
    args = parser.parse_args()

    try:
        result = verify_backup_archive(Path(args.backup), Path(args.manifest))
    except BackupConfigurationError as exc:
        parser.error(str(exc))

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
