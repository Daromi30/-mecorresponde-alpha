from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import settings


class StorageConfigurationError(RuntimeError):
    pass


class UnsafeDocumentUpload(RuntimeError):
    pass


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
    if not clean or "\\" in clean:
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

    def put_bytes(self, key: str, data: bytes, *, content_type: str, sha256: str) -> None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def delete_bytes(self, key: str) -> None: ...


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

    def put_bytes(self, key: str, data: bytes, *, content_type: str, sha256: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != data:
                raise UnsafeDocumentUpload("Immutable storage key already contains different bytes")
            return
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete_bytes(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            return


class S3DocumentStorage:
    backend_name = "s3"
    persistent = True

    def __init__(self):
        missing = [
            name for name, value in {
                "S3_BUCKET": settings.s3_bucket,
                "S3_ACCESS_KEY_ID": settings.s3_access_key_id,
                "S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
            }.items() if not value
        ]
        if missing:
            raise StorageConfigurationError(f"Missing object-storage settings: {', '.join(missing)}")
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

    def put_bytes(self, key: str, data: bytes, *, content_type: str, sha256: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._key(key),
            Body=data,
            ContentType=content_type,
            Metadata={"sha256": sha256},
        )

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        return response["Body"].read()

    def delete_bytes(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))


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
    uploads_allowed = storage.persistent or not settings.render
    return StorageStatus(
        backend=storage.backend_name,
        persistent=storage.persistent,
        uploads_allowed=uploads_allowed,
    )


def object_key(case_id: str, sha256: str) -> str:
    return f"originals/{case_id}/{sha256[:2]}/{sha256}"


def validate_document_bytes(filename: str, content_type: str, data: bytes) -> None:
    if not data:
        raise UnsafeDocumentUpload("Empty document")
    if len(data) > settings.max_upload_bytes:
        raise UnsafeDocumentUpload("Document exceeds upload limit")

    name = filename.lower()
    mime = (content_type or "").lower().split(";", 1)[0].strip()

    if mime == "application/pdf" or name.endswith(".pdf"):
        if not data.startswith(b"%PDF-"):
            raise UnsafeDocumentUpload("File does not match PDF signature")
        return
    if mime == "image/jpeg" or name.endswith((".jpg", ".jpeg")):
        if not data.startswith(b"\xff\xd8\xff"):
            raise UnsafeDocumentUpload("File does not match JPEG signature")
        return
    if mime == "image/png" or name.endswith(".png"):
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise UnsafeDocumentUpload("File does not match PNG signature")
        return
    if mime == "image/webp" or name.endswith(".webp"):
        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            raise UnsafeDocumentUpload("File does not match WEBP signature")
        return
    if mime in {"text/plain", "text/csv"} or name.endswith((".txt", ".csv")):
        if b"\x00" in data[:4096]:
            raise UnsafeDocumentUpload("Text document contains binary data")
        return

    raise UnsafeDocumentUpload("Unsupported document type")
