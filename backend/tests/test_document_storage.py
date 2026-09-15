import hashlib

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
    try:
        validate_document_bytes("fake.pdf", "application/pdf", b"this is not a pdf")
    except UnsafeDocumentUpload as exc:
        assert "PDF signature" in str(exc)
    else:
        raise AssertionError("spoofed PDF must be rejected")


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
