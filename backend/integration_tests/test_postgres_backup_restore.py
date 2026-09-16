from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

from app.operations.db_backup import (
    create_backup,
    restore_backup_archive,
    verify_backup_archive,
)


SOURCE_URL = os.environ["DATABASE_URL"]
RESTORE_DATABASE = "mecorresponde_restore_ci"


def with_database(database_url: str, database: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", parsed.query, parsed.fragment))


def drop_restore_database(admin_url: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
            (RESTORE_DATABASE,),
        )
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(RESTORE_DATABASE)))


def test_real_backup_can_be_restored_into_disposable_database(tmp_path: Path):
    admin_url = with_database(SOURCE_URL, "postgres")
    restore_url = with_database(SOURCE_URL, RESTORE_DATABASE)

    with psycopg.connect(SOURCE_URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS backup_restore_sentinel")
        conn.execute(
            "CREATE TABLE backup_restore_sentinel (id integer PRIMARY KEY, value text NOT NULL)"
        )
        conn.execute(
            "INSERT INTO backup_restore_sentinel (id, value) VALUES (%s, %s)",
            (1, "mecorresponde-backup-roundtrip"),
        )

    backup, manifest = create_backup(SOURCE_URL, tmp_path)
    verification = verify_backup_archive(backup, manifest)
    assert verification["valid"] is True
    assert verification["archive_entries"] > 0

    drop_restore_database(admin_url)
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(RESTORE_DATABASE)))

    try:
        restored = restore_backup_archive(backup, manifest, restore_url)
        assert restored["restored"] is True
        assert restored["target_database"] == RESTORE_DATABASE

        with psycopg.connect(restore_url) as conn:
            row = conn.execute(
                "SELECT id, value FROM backup_restore_sentinel WHERE id = 1"
            ).fetchone()
        assert row == (1, "mecorresponde-backup-roundtrip")
    finally:
        drop_restore_database(admin_url)
