from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from .config import settings


class StorageConfigurationError(RuntimeError):
    pass


class UnsafeDocumentUpload(RuntimeError):
    pass


class StorageIntegrityError(RuntimeError):
    """Object content or metadata cannot be trusted."""


class StorageMetadataConflict(StorageIntegrityError):
    """Provider returned contradictory metadata for one object."""


class StorageWriteError(RuntimeError):
    """A write failed; ``created`` records a confirmed new object needing cleanup."""

    def __init__(self, message: str, *, created: bool = False):
        super().__init__(message)
        self.created = created


@dataclass(frozen=True)
class PutResult:
    created: bool


class ObjectProbe(str, Enum):
    MISSING = "MISSING"
    PRESENT_AND_VALID = "PRESENT_AND_VALID"
    PRESENT_CONFLICTING = "PRESENT_CONFLICTING"
    UNKNOWN = "UNKNOWN"


def validated_storage_key(key: str) -> str:
    """Return a canonical relative object key or reject an unsafe one.

    Object stores do not resolve ``..`` like a filesystem, but accepting it would
    make a future backend-specific normalisation capable of escaping the intended
    logical prefix.  Every backend therefore uses one deliberately small key
    grammar: non-empty, slash-separated segments, with no dot segments or
    backslashes.
    """
    if not isinstance(key, str):
        raise UnsafeDocumentUpload("Invalid storage key")
    clean = key.strip("/")
    if not clean or "\\" in clean or any(ord(char) < 32 for char in clean):
        raise UnsafeDocumentUpload("Invalid storage key")
    parts = clean.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise UnsafeDocumentUpload("Invalid storage key")
    return clean


@dataclass(frozen=True)
class StorageStatus:
    backend: str
    persistent: bool
    uploads_allowed: bool


class DocumentStorage(Protocol):
    backend_name: str
    persistent: bool

    def put_bytes(self, key: str, data: bytes, *, content_type: str, sha256: str) -> PutResult: ...
    def get_bytes(self, key: str) -> bytes: ...
    def delete_bytes(self, key: str) -> None: ...
    def probe_object(self, key: str, sha256: str) -> ObjectProbe: ...


class LocalDocumentStorage:
    backend_name = "local"

    def __init__(self, root: str | Path, *, persistent: bool = False):
        self.root = Path(root)
        self.persistent = persistent

    def _path(self, key: str) -> Path:
        clean = validated_storage_key(key)
        path = (self.root / clean).resolve()
        root = self.root.resolve()
        if root not in path.parents and path != root:
            raise UnsafeDocumentUpload("Invalid storage key")
        return path

    def put_bytes(self, key: str, data: bytes, *, content_type: str, sha256: str) -> PutResult:
        _require_expected_digest(data, sha256)
        _require_content_addressed_key(key, sha256)
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # A unique, fully written sibling plus an exclusive hard link makes the
        # destination appear atomically and never replaces an existing object.
        tmp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".upload-", delete=False) as tmp:
                tmp_name = tmp.name
                tmp.write(data)
                tmp.flush()
                os.fsync(tmp.fileno())
            try:
                os.link(tmp_name, path)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise StorageIntegrityError("Immutable storage key has different bytes")
                return PutResult(created=False)
            return PutResult(created=True)
        finally:
            if tmp_name is not None:
                Path(tmp_name).unlink(missing_ok=True)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete_bytes(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            return

    def probe_object(self, key: str, sha256: str) -> ObjectProbe:
        try:
            data = self.get_bytes(key)
        except FileNotFoundError:
            return ObjectProbe.MISSING
        except Exception:
            return ObjectProbe.UNKNOWN
        return (ObjectProbe.PRESENT_AND_VALID if hashlib.sha256(data).hexdigest() == sha256
                else ObjectProbe.PRESENT_CONFLICTING)


class S3DocumentStorage:
    backend_name = "s3"
    persistent = True

    def __init__(self):
        missing = [
            name for name, value in {
                "S3_BUCKET": settings.s3_bucket.strip(),
                "S3_REGION": settings.s3_region.strip(),
                "S3_ACCESS_KEY_ID": settings.s3_access_key_id.strip(),
                "S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key.strip(),
            }.items() if not value
        ]
        if missing:
            raise StorageConfigurationError(f"Missing object-storage settings: {', '.join(missing)}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", settings.s3_bucket):
            raise StorageConfigurationError("Invalid object-storage bucket")
        if settings.s3_prefix:
            try:
                if validated_storage_key(settings.s3_prefix) != settings.s3_prefix.strip("/"):
                    raise StorageConfigurationError("Invalid object-storage prefix")
            except UnsafeDocumentUpload:
                raise StorageConfigurationError("Invalid object-storage prefix") from None
        if settings.s3_endpoint_url:
            try:
                parsed = urlsplit(settings.s3_endpoint_url)
            except ValueError:
                raise StorageConfigurationError("Invalid object-storage endpoint") from None
            if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise StorageConfigurationError("Invalid object-storage endpoint")
        elif settings.s3_region == "auto":
            raise StorageConfigurationError("An explicit region or HTTPS endpoint is required")
        try:
            import boto3
        except ImportError as exc:
            raise StorageConfigurationError("boto3 is required for S3-compatible storage") from exc

        kwargs = {
            "service_name": "s3",
            "aws_access_key_id": settings.s3_access_key_id,
            "aws_secret_access_key": settings.s3_secret_access_key,
            "region_name": settings.s3_region or None,
        }
        if settings.s3_endpoint_url:
            kwargs["endpoint_url"] = settings.s3_endpoint_url
        self.client = boto3.client(**kwargs)
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix.strip("/")

    def _key(self, key: str) -> str:
        clean = validated_storage_key(key)
        return f"{self.prefix}/{clean}" if self.prefix else clean

    def _existing_bytes(self, object_key: str) -> tuple[bytes, dict] | None:
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=object_key)
        except Exception as exc:
            error = getattr(exc, "response", {}).get("Error", {})
            code = str(error.get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise StorageIntegrityError("Could not verify existing object") from None
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=object_key)
            head_metadata = head.get("Metadata", {})
            get_metadata = response.get("Metadata", {})
            if head_metadata.get("sha256") and get_metadata.get("sha256") and head_metadata["sha256"] != get_metadata["sha256"]:
                raise StorageMetadataConflict("Object metadata changed during verification")
            return response["Body"].read(), head_metadata or get_metadata
        except StorageMetadataConflict:
            raise
        except Exception:
            raise StorageIntegrityError("Could not read existing object") from None

    def put_bytes(self, key: str, data: bytes, *, content_type: str, sha256: str) -> PutResult:
        _require_expected_digest(data, sha256)
        _require_content_addressed_key(key, sha256)
        object_key = self._key(key)
        existing = self._existing_bytes(object_key)
        if existing is not None:
            _require_existing_integrity(existing, sha256)
            return PutResult(created=False)
        try:
            # Conditional creation is required. Backends without this standard
            # precondition fail closed; no unconditional overwrite fallback.
            self.client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=data,
                ContentType=content_type,
                Metadata={"sha256": sha256},
                IfNoneMatch="*",
            )
        except Exception as exc:
            code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            if code in {"PreconditionFailed", "412", "ConditionalRequestConflict", "409"}:
                existing = self._existing_bytes(object_key)
                if existing is not None:
                    _require_existing_integrity(existing, sha256)
                    return PutResult(created=False)
            raise StorageWriteError("Object creation failed or its outcome is uncertain") from None
        try:
            written = self._existing_bytes(object_key)
            if written is None:
                raise StorageIntegrityError("New object is not readable")
            _require_existing_integrity(written, sha256)
        except Exception:
            raise StorageWriteError("New object could not be verified", created=True) from None
        return PutResult(created=True)

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        return response["Body"].read()

    def delete_bytes(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))

    def probe_object(self, key: str, sha256: str) -> ObjectProbe:
        try:
            existing = self._existing_bytes(self._key(key))
        except StorageMetadataConflict:
            return ObjectProbe.PRESENT_CONFLICTING
        except Exception:
            return ObjectProbe.UNKNOWN
        if existing is None:
            return ObjectProbe.MISSING
        try:
            _require_existing_integrity(existing, sha256)
        except StorageIntegrityError:
            return ObjectProbe.PRESENT_CONFLICTING
        return ObjectProbe.PRESENT_AND_VALID


def get_document_storage() -> DocumentStorage:
    backend = settings.document_storage_backend.lower().strip()
    if backend == "local":
        return LocalDocumentStorage(
            settings.storage_dir,
            persistent=settings.document_storage_persistent,
        )
    if backend == "s3":
        return S3DocumentStorage()
    raise StorageConfigurationError(f"Unsupported document storage backend: {backend}")


def storage_status(storage: DocumentStorage | None = None) -> StorageStatus:
    storage = storage or get_document_storage()
    # Render's local filesystem is ephemeral. On Render, uploads are therefore
    # disabled unless the selected backend explicitly declares persistence.
    # A local flag cannot prove physical durability on Render's ephemeral disk.
    durable = storage.persistent and not (settings.render and storage.backend_name == "local")
    uploads_allowed = durable or not settings.render
    return StorageStatus(
        backend=storage.backend_name,
        persistent=durable,
        uploads_allowed=uploads_allowed,
    )


def object_key(case_id: str, sha256: str) -> str:
    return f"originals/{case_id}/{sha256[:2]}/{sha256}"


def _require_expected_digest(data: bytes, expected: str) -> None:
    if len(expected) != 64 or hashlib.sha256(data).hexdigest() != expected:
        raise StorageIntegrityError("Object SHA-256 does not match expected content")


def _require_content_addressed_key(key: str, expected: str) -> None:
    parts = validated_storage_key(key).split("/")
    if len(parts) != 4 or parts[0] != "originals" or not parts[1] or parts[2] != expected[:2] or parts[3] != expected:
        raise StorageIntegrityError("Object key is not content-addressed")


def _require_existing_integrity(existing: tuple[bytes, dict], expected: str) -> None:
    data, metadata = existing
    _require_expected_digest(data, expected)
    recorded = metadata.get("sha256") or metadata.get("SHA256")
    if recorded is not None and recorded != expected:
        raise StorageIntegrityError("Object SHA-256 metadata does not match")


def read_verified_document(storage: DocumentStorage, document) -> bytes:
    """Read once and fail closed before any download or processing consumer."""
    try:
        data = storage.get_bytes(document.storage_key)
    except Exception:
        raise StorageIntegrityError("Document object could not be read") from None
    _require_expected_digest(data, document.sha256)
    return data


def validate_document_bytes(filename: str, content_type: str, data: bytes) -> str:
    if not data:
        raise UnsafeDocumentUpload("Empty document")
    if len(data) > settings.max_upload_bytes:
        raise UnsafeDocumentUpload("Document exceeds upload limit")

    name = filename.lower()
    mime = (content_type or "").lower().split(";", 1)[0].strip()
    extensions = {
        ".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp",
        ".txt": "text/plain", ".csv": "text/csv",
    }
    canonical = next((value for suffix, value in extensions.items() if name.endswith(suffix)), None)
    if canonical is None:
        raise UnsafeDocumentUpload("Unsupported document type")
    if mime not in {canonical, "application/octet-stream", ""}:
        raise UnsafeDocumentUpload("Declared MIME does not match file type")
    signatures = {
        "application/pdf": data.startswith(b"%PDF-"),
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
    }
    if canonical in signatures and not signatures[canonical]:
        raise UnsafeDocumentUpload(f"File does not match {canonical.rsplit('/', 1)[-1].upper()} signature")
    if canonical.startswith("text/"):
        if any(signatures.values()):
            raise UnsafeDocumentUpload("Text document has a binary document signature")
        try:
            decoded = data.decode("utf-8")
        except UnicodeDecodeError:
            raise UnsafeDocumentUpload("Text document is not UTF-8") from None
        if any(ord(char) < 32 and char not in "\t\r\n" for char in decoded):
            raise UnsafeDocumentUpload("Text document contains binary data")
    return canonical
