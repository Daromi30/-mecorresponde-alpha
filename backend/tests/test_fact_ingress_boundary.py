import pytest
from pydantic import ValidationError

from app.schemas import FactUpsert
from app.schemas_v2 import DocumentFactConfirm


@pytest.mark.parametrize(
    "key",
    [
        "system.analysis_date",
        "legal.rule_override",
        "rule.result",
        "decision.viability",
        "action.next",
        "company.asserts_consent",
        "human.reviewed",
        "ai.classification",
        "internal.flag",
    ],
)
def test_claimant_cannot_supply_trusted_fact_namespaces(key):
    with pytest.raises(ValidationError):
        FactUpsert(key=key, value=True, state="confirmed")
    with pytest.raises(ValidationError):
        DocumentFactConfirm(key=key, value=True)


def test_user_fact_schema_normalizes_key_and_bounds_control_fields():
    payload = FactUpsert(
        key="  electricity.billing.correct_amount  ",
        value=80.0,
        state="confirmed",
        materiality="critical",
        confidence=0.8,
        user_confirmed=True,
    )
    assert payload.key == "electricity.billing.correct_amount"

    with pytest.raises(ValidationError):
        FactUpsert(key="electricity.billing.correct_amount", value=80, state="trusted")
    with pytest.raises(ValidationError):
        FactUpsert(key="electricity.billing.correct_amount", value=80, materiality="absolute")
    with pytest.raises(ValidationError):
        FactUpsert(key="electricity.billing.correct_amount", value=80, confidence=1.1)


def test_fact_api_rejects_company_and_system_spoofing_but_accepts_user_namespace(client):
    created = client.post(
        "/api/cases",
        json={"message": "La factura de luz es incorrecta y me han cobrado de más"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]

    for reserved in ("company.asserts_correct_amount", "system.analysis_date"):
        blocked = client.post(
            f"/api/cases/{case_id}/facts",
            json={"key": reserved, "value": True, "state": "confirmed"},
        )
        assert blocked.status_code == 422

    accepted = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": "electricity.billing.correct_amount",
            "value": 80.0,
            "state": "confirmed",
            "materiality": "critical",
            "confidence": 1.0,
            "user_confirmed": True,
        },
    )
    assert accepted.status_code == 200


def test_document_fact_metadata_is_bounded_and_reserved_namespace_is_blocked():
    payload = DocumentFactConfirm(
        key="purchase.delivery_date",
        value="2026-09-01",
        locator="page 1",
        excerpt="Fecha de entrega: 01/09/2026",
        materiality="critical",
    )
    assert payload.key == "purchase.delivery_date"

    with pytest.raises(ValidationError):
        DocumentFactConfirm(key="purchase.delivery_date", value=True, locator="x" * 256)
    with pytest.raises(ValidationError):
        DocumentFactConfirm(key="purchase.delivery_date", value=True, materiality="supercritical")
