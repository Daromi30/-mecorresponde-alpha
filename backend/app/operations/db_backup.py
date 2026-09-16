from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urlsplit


SAFE_RESTORE_DATABASE_PREFIX = "mecorresponde_restore_"


class BackupConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PostgresConnection:
    database: str
    env: dict[str, str]


def postgres_connection(database_url: str) -> PostgresConnection:
    try:
        parsed = urlsplit(database_url)
        port = parsed.port
    except (ValueError, TypeError) as exc:
        raise BackupConfigurationError("Invalid PostgreSQL database URL") from exc

    if parsed.scheme not in {"postgres", "postgresql"}:
        raise BackupConfigurationError("Backup tooling only supports PostgreSQL")
    database = parsed.path.lstrip("/")
    if not parsed.hostname or not database:
        raise BackupConfigurationError("PostgreSQL host and database name are required")

    env = {
        "PGHOST": parsed.hostname,
        "PGPORT": str(port or 5432),
        "PGDATABASE": unquote(database),
    }
    if parsed.username:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)

    query = parse_qs(parsed.query)
    sslmode = query.get("sslmode", [None])[0]
    if sslmode:
        env["PGSSLMODE"] = sslmode

    return PostgresConnection(database=unquote(database), env=env)


def _binary(name: str, explicit: str | None = None) -> str:
    resolved = explicit or shutil.which(name)
    if not resolved:
        raise BackupConfigurationError(f"Required PostgreSQL client binary not found: {name}")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _paths_and_manifest(
    backup_path: str | Path,
    manifest_path: str | Path,
) -> tuple[Path, Path, dict[str, object]]:
    backup = Path(backup_path).expanduser().resolve()
    manifest_file = Path(manifest_path).expanduser().resolve()
    if not backup.is_file() or not manifest_file.is_file():
        raise BackupConfigurationError("Backup archive and manifest are both required")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupConfigurationError("Backup manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise BackupConfigurationError("Backup manifest must be a JSON object")
    return backup, manifest_file, manifest


def create_backup(
    database_url: str,
    output_dir: str | Path,
    *,
    pg_dump_binary: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    now: datetime | None = None,
) -> tuple[Path, Path]:
    """Create a PostgreSQL custom-format backup without putting credentials in argv."""
    connection = postgres_connection(database_url)
    pg_dump = _binary("pg_dump", pg_dump_binary)
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    final_path = destination / f"mecorresponde-{stamp}.dump"
    partial_path = final_path.with_suffix(".dump.partial")
    manifest_path = final_path.with_suffix(".manifest.json")

    command = [
        pg_dump,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(partial_path),
    ]
    child_env = os.environ.copy()
    child_env.update(connection.env)

    try:
        runner(
            command,
            env=child_env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if not partial_path.exists() or partial_path.stat().st_size == 0:
            raise BackupConfigurationError("pg_dump completed without producing a backup archive")
        os.replace(partial_path, final_path)
        os.chmod(final_path, 0o600)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise

    manifest = {
        "backup_filename": final_path.name,
        "created_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "format": "postgresql-custom",
        "sha256": _sha256(final_path),
        "size_bytes": final_path.stat().st_size,
        "database_name": connection.database,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(manifest_path, 0o600)
    return final_path, manifest_path


def verify_backup_archive(
    backup_path: str | Path,
    manifest_path: str | Path,
    *,
    pg_restore_binary: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, object]:
    """Verify checksum and that pg_restore can enumerate the custom archive."""
    backup, _manifest_file, manifest = _paths_and_manifest(backup_path, manifest_path)
    expected = str(manifest.get("sha256", ""))
    actual = _sha256(backup)
    if not expected or expected != actual:
        raise BackupConfigurationError("Backup checksum does not match its manifest")

    pg_restore = _binary("pg_restore", pg_restore_binary)
    result = runner(
        [pg_restore, "--list", str(backup)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    entries = [
        line for line in (result.stdout or "").splitlines()
        if line.strip() and not line.lstrip().startswith(";")
    ]
    if not entries:
        raise BackupConfigurationError("pg_restore did not find any archive entries")

    return {
        "valid": True,
        "sha256": actual,
        "size_bytes": backup.stat().st_size,
        "archive_entries": len(entries),
    }


def restore_backup_archive(
    backup_path: str | Path,
    manifest_path: str | Path,
    target_database_url: str,
    *,
    pg_restore_binary: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, object]:
    """Restore a verified archive only into an explicitly disposable rehearsal database.

    This helper deliberately refuses the source database and any target whose name
    does not start with ``mecorresponde_restore_``. It never creates, drops, or
    cleans a database; callers must provision an empty disposable target first.
    """
    backup, _manifest_file, manifest = _paths_and_manifest(backup_path, manifest_path)
    source_database = str(manifest.get("database_name") or "").strip()
    if not source_database:
        raise BackupConfigurationError("Backup manifest does not identify the source database")

    target = postgres_connection(target_database_url)
    if target.database == source_database:
        raise BackupConfigurationError("Restore rehearsal must never target the source database")
    if not target.database.startswith(SAFE_RESTORE_DATABASE_PREFIX):
        raise BackupConfigurationError(
            f"Restore target must start with {SAFE_RESTORE_DATABASE_PREFIX}"
        )

    verification = verify_backup_archive(
        backup,
        manifest_path,
        pg_restore_binary=pg_restore_binary,
        runner=runner,
    )
    pg_restore = _binary("pg_restore", pg_restore_binary)
    command = [
        pg_restore,
        "--exit-on-error",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        target.database,
        str(backup),
    ]
    child_env = os.environ.copy()
    child_env.update(target.env)
    runner(
        command,
        env=child_env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    return {
        **verification,
        "restored": True,
        "target_database": target.database,
        "source_database": source_database,
    }
