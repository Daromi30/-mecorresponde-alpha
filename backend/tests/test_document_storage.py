import hashlib

import pytest
from sqlalchemy import select

from app.config import settings
from app.documents import save_upload
from app.models import DocumentExtraction, Evidence
from app.services_v2 import confirm_document_fact, create_case
from app.storage import LocalDocumentStorage, UnsafeDocumentUpload, validate_document_bytes


def test_local_storage_is_content_addressed_and_immutable(tmp_path, db):
    case = create_case(db, "Me cambié de compañía de luz y me siguen cobrando mantenimiento")
    data = b"Factura\nmantenimiento 8,99 EUR\n"
    digest = hashlib.sha256(data).hexdigest()
    storage = LocalDocumentStorage(tmp_path, persistent=True)

    document, extraction = save_upload(
        db,
        case,
        "factura.txt",
        "text/plain",
        data,
        storage=storage,
    )

    assert document.sha256 == digest
    assert document.storage_key == f"originals/{case.id}/{digest[:2]}/{digest}"
    assert storage.get_bytes(document.storage_key) == data
    assert extraction.structured_json["possible_addon_price"] == 8.99

    row = db.scalars(
        select(DocumentExtraction).where(DocumentExtraction.document_id == document.id)
    ).one()
    assert row.extractor_version == "local-text-3"


def test_document_fact_keeps_document_provenance(tmp_path, db):
    case = create_case(db, "Me cambié de compañía de luz y me siguen cobrando mantenimiento")
    storage = LocalDocumentStorage(tmp_path, persistent=True)
    document, _ = save_upload(
        db,
        case,
        "factura.txt",
        "text/plain",
        b"Periodo desde 04/06/2026. mantenimiento 8,99 EUR",
        storage=storage,
    )

    fact = confirm_document_fact(
        db,
        case,
        document,
        key="electricity.addon.identity",
        value="Mantenimiento Hogar",
        locator="page:1",
        excerpt="mantenimiento 8,99 EUR",
    )

    evidence = db.scalars(
        select(Evidence).where(Evidence.fact_id == fact.id, Evidence.document_id == document.id)
    ).one()
    assert evidence.source_type == "document"
    assert evidence.locator == "page:1"
    assert evidence.strength == "strong"


def test_invalid_file_signature_is_rejected():
    with pytest.raises(UnsafeDocumentUpload, match="PDF signature"):
        validate_document_bytes("fake.pdf", "application/pdf", b"this is not a pdf")


def test_render_blocks_document_upload_until_storage_is_persistent(client, monkeypatch):
    monkeypatch.setattr(settings, "render", True)
    monkeypatch.setattr(settings, "document_storage_backend", "local")
    monkeypatch.setattr(settings, "document_storage_persistent", False)

    case = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando mantenimiento"},
    ).json()
    response = client.post(
        f"/api/cases/{case['id']}/documents",
        files={"file": ("factura.txt", b"mantenimiento 8,99 EUR", "text/plain")},
    )
    assert response.status_code == 503
    assert "persistent object storage" in response.json()["detail"]


def test_alpha_total_document_quota_blocks_before_storage_write(tmp_path, db, monkeypatch):
    monkeypatch.setattr(settings, "alpha_max_documents_total", 1)
    monkeypatch.setattr(settings, "alpha_max_documents_per_case", 20)
    storage = LocalDocumentStorage(tmp_path, persistent=True)

    first = create_case(db, "Me cambié de compañía de luz y me siguen cobrando mantenimiento")
    save_upload(db, first, "uno.txt", "text/plain", b"documento uno", storage=storage)

    second = create_case(db, "Me han cobrado dos veces la misma factura de luz")
    second_data = b"documento dos"
    second_key = f"originals/{second.id}/{hashlib.sha256(second_data).hexdigest()[:2]}/{hashlib.sha256(second_data).hexdigest()}"
    with pytest.raises(UnsafeDocumentUpload, match="Alpha document quota reached"):
        save_upload(db, second, "dos.txt", "text/plain", second_data, storage=storage)
    assert not (tmp_path / second_key).exists()


def test_alpha_per_case_document_quota_blocks_second_document(tmp_path, db, monkeypatch):
    monkeypatch.setattr(settings, "alpha_max_documents_total", 100)
    monkeypatch.setattr(settings, "alpha_max_documents_per_case", 1)
    storage = LocalDocumentStorage(tmp_path, persistent=True)
    case = create_case(db, "Me cambié de compañía de luz y me siguen cobrando mantenimiento")

    save_upload(db, case, "uno.txt", "text/plain", b"documento uno", storage=storage)
    with pytest.raises(UnsafeDocumentUpload, match="Case document quota reached"):
        save_upload(db, case, "dos.txt", "text/plain", b"documento dos", storage=storage)
