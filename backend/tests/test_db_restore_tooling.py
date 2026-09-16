from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from app.operations.db_backup import BackupConfigurationError, restore_backup_archive


def write_backup(tmp_path, *, source_database="mecorresponde"):
    backup = tmp_path / "case.dump"
    backup.write_bytes(b"archive-data")
    manifest = tmp_path / "case.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "sha256": hashlib.sha256(b"archive-data").hexdigest(),
                "database_name": source_database,
            }
        ),
        encoding="utf-8",
    )
    return backup, manifest


def test_restore_rehearsal_refuses_source_database(tmp_path):
    backup, manifest = write_backup(tmp_path)
    with pytest.raises(BackupConfigurationError, match="never target the source"):
        restore_backup_archive(
            backup,
            manifest,
            "postgresql://user:secret@db.example.test/mecorresponde",
            pg_restore_binary="/usr/bin/pg_restore",
        )


def test_restore_rehearsal_refuses_non_disposable_target_name(tmp_path):
    backup, manifest = write_backup(tmp_path)
    with pytest.raises(BackupConfigurationError, match="must start"):
        restore_backup_archive(
            backup,
            manifest,
            "postgresql://user:secret@db.example.test/customer_data",
            pg_restore_binary="/usr/bin/pg_restore",
        )


def test_restore_rehearsal_verifies_archive_then_restores_without_credentials_in_argv(tmp_path):
    backup, manifest = write_backup(tmp_path)
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        if "--list" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="; header\n1; 0 0 TABLE public cases owner\n",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = restore_backup_archive(
        backup,
        manifest,
        "postgresql://restore_user:restore-secret@db.example.test:5433/mecorresponde_restore_ci?sslmode=require",
        pg_restore_binary="/usr/bin/pg_restore",
        runner=fake_runner,
    )

    assert result["restored"] is True
    assert result["source_database"] == "mecorresponde"
    assert result["target_database"] == "mecorresponde_restore_ci"
    restore_command, restore_kwargs = calls[-1]
    joined = " ".join(restore_command)
    assert "restore-secret" not in joined
    assert "db.example.test" not in joined
    assert "--exit-on-error" in restore_command
    assert "--clean" not in restore_command
    assert restore_kwargs["env"]["PGPASSWORD"] == "restore-secret"
    assert restore_kwargs["env"]["PGDATABASE"] == "mecorresponde_restore_ci"
    assert restore_kwargs["env"]["PGSSLMODE"] == "require"
