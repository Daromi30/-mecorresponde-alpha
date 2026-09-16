from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

import pytest

from app.operations.db_backup import (
    BackupConfigurationError,
    create_backup,
    postgres_connection,
    verify_backup_archive,
)


def test_postgres_connection_keeps_credentials_out_of_command_material():
    connection = postgres_connection(
        "postgresql://backup_user:p%40ssword@db.example.test:5433/mecorresponde?sslmode=require"
    )
    assert connection.database == "mecorresponde"
    assert connection.env == {
        "PGHOST": "db.example.test",
        "PGPORT": "5433",
        "PGDATABASE": "mecorresponde",
        "PGUSER": "backup_user",
        "PGPASSWORD": "p@ssword",
        "PGSSLMODE": "require",
    }


def test_backup_uses_environment_for_credentials_and_writes_restricted_manifest(tmp_path):
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        output = command[command.index("--file") + 1]
        with open(output, "wb") as handle:
            handle.write(b"synthetic-postgresql-custom-archive")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    backup, manifest = create_backup(
        "postgresql://user:secret-password@db.example.test/mecorresponde?sslmode=require",
        tmp_path,
        pg_dump_binary="/usr/bin/pg_dump",
        runner=fake_runner,
        now=datetime(2026, 9, 16, 8, 45, tzinfo=timezone.utc),
    )

    command, kwargs = calls[0]
    joined = " ".join(command)
    assert "secret-password" not in joined
    assert "db.example.test" not in joined
    assert kwargs["env"]["PGPASSWORD"] == "secret-password"
    assert kwargs["env"]["PGHOST"] == "db.example.test"
    assert backup.exists()
    assert manifest.exists()
    assert oct(backup.stat().st_mode & 0o777) == "0o600"
    assert oct(manifest.stat().st_mode & 0o777) == "0o600"

    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    assert metadata["format"] == "postgresql-custom"
    assert metadata["database_name"] == "mecorresponde"
    assert metadata["size_bytes"] == backup.stat().st_size
    assert len(metadata["sha256"]) == 64
    assert "secret-password" not in manifest.read_text(encoding="utf-8")
    assert "db.example.test" not in manifest.read_text(encoding="utf-8")


def test_backup_archive_verification_checks_hash_and_pg_restore_catalog(tmp_path):
    backup = tmp_path / "case.dump"
    backup.write_bytes(b"archive-data")

    import hashlib

    digest = hashlib.sha256(b"archive-data").hexdigest()
    manifest = tmp_path / "case.manifest.json"
    manifest.write_text(json.dumps({"sha256": digest}), encoding="utf-8")

    def fake_runner(command, **kwargs):
        assert command == ["/usr/bin/pg_restore", "--list", str(backup.resolve())]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="; archive header\n1; 0 0 TABLE public cases owner\n2; 0 0 TABLE public facts owner\n",
            stderr="",
        )

    result = verify_backup_archive(
        backup,
        manifest,
        pg_restore_binary="/usr/bin/pg_restore",
        runner=fake_runner,
    )
    assert result["valid"] is True
    assert result["archive_entries"] == 2
    assert result["sha256"] == digest


def test_backup_archive_rejects_tampering_before_pg_restore(tmp_path):
    backup = tmp_path / "case.dump"
    backup.write_bytes(b"changed")
    manifest = tmp_path / "case.manifest.json"
    manifest.write_text(json.dumps({"sha256": "0" * 64}), encoding="utf-8")

    with pytest.raises(BackupConfigurationError, match="checksum"):
        verify_backup_archive(
            backup,
            manifest,
            pg_restore_binary="/usr/bin/pg_restore",
        )


def test_backup_tooling_fails_closed_for_non_postgres_database():
    with pytest.raises(BackupConfigurationError, match="only supports PostgreSQL"):
        postgres_connection("sqlite:///mecorresponde.db")
