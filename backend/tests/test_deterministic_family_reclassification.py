from sqlalchemy import select

from app.family_manifest import FAMILY_MANIFEST
from app.models import Action, AuditEvent, Case
from app.reviews import HumanReview


def _case(client, message: str) -> dict:
    response = client.post("/api/cases", json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()


def _fact(client, case_id: str, key: str, value) -> None:
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _actions(db, case_id: str) -> list[Action]:
    return list(db.scalars(select(Action).where(Action.case_id == case_id).order_by(Action.id.asc())).all())


def _assert_reclassified(db, case_id: str, source_action: str, target_family: str) -> Case:
    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.family == target_family
    assert case.vertical == FAMILY_MANIFEST[target_family].vertical
    assert case.title == FAMILY_MANIFEST[target_family].title
    historical = [item for item in _actions(db, case_id) if item.type == source_action]
    assert historical and all(item.status == "COMPLETED" for item in historical)
    event = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "CASE_RECLASSIFIED_BY_ENGINE",
        )
        .order_by(AuditEvent.created_at.desc())
    ).first()
    assert event is not None
    assert event.payload_json["to_family"] == target_family
    current = db.get(Action, case.current_action_id) if case.current_action_id else None
    assert current is not None
    assert current.status in {"OPEN", "READY"}
    return case


def test_e04b_reclassifies_to_e04a_and_returns_target_diagnosis(client, db):
    created = _case(client, "Me cambié de compañía de luz y me siguen cobrando un mantenimiento")
    case_id = created["id"]
    assert created["family"] == "E04-B"
    _fact(client, case_id, "electricity.addon.identity", "Protección Hogar")
    _fact(client, case_id, "electricity.addon.ever_contracted", False)
    charges = client.post(
        f"/api/cases/{case_id}/charges",
        json={"charges": [{"amount": 9.99, "evidence_verified": True}]},
    )
    assert charges.status_code == 200, charges.text

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] in {"HIGH", "MEDIUM"}
    assert diagnosis.json()["next_action"] == "PREPARE_INITIAL_CLAIM"

    case = _assert_reclassified(db, case_id, "RECLASSIFY_E04A", "E04-A")
    assert case.status == "DIAGNOSED"


def test_e04a_reclassifies_to_e04b_and_continues_with_target_questions(client, db):
    created = _case(client, "En la factura de luz me cobran un mantenimiento que nunca contraté")
    case_id = created["id"]
    assert created["family"] == "E04-A"
    _fact(client, case_id, "electricity.addon.identity", "Protección Hogar")
    _fact(client, case_id, "electricity.addon.ever_contracted", True)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] == "INSUFFICIENT_INFORMATION"

    case = _assert_reclassified(db, case_id, "RECLASSIFY_CONTRACTED_ADDON", "E04-B")
    assert case.status == "NEEDS_INFORMATION"


def test_purchase_reclassification_works_in_both_directions(client, db):
    c01 = _case(client, "Compré un televisor en una tienda, está defectuoso y me rechazan la garantía")
    _fact(client, c01["id"], "purchase.repair_attempts", 1)
    first = client.post(f"/api/cases/{c01['id']}/diagnose")
    assert first.status_code == 200, first.text
    assert first.json()["viability"] == "INSUFFICIENT_INFORMATION"
    assert _assert_reclassified(db, c01["id"], "RECLASSIFY_C02", "C02").status == "NEEDS_INFORMATION"

    c02 = _case(client, "Compré un portátil, ya lo repararon y volvió a fallar")
    _fact(client, c02["id"], "purchase.conformity_attempts", 0)
    second = client.post(f"/api/cases/{c02['id']}/diagnose")
    assert second.status_code == 200, second.text
    assert second.json()["viability"] == "INSUFFICIENT_INFORMATION"
    assert _assert_reclassified(db, c02["id"], "RECLASSIFY_C01", "C01").status == "NEEDS_INFORMATION"


def test_e06_overbilling_reclassifies_to_e02a_without_stranding_case(client, db):
    created = _case(client, "Mi factura de luz tiene una lectura estimada porque falló la lectura remota")
    case_id = created["id"]
    assert created["family"] == "E06"
    _fact(client, case_id, "electricity.reading_issue_invoice_date", "2026-09-01")
    _fact(client, case_id, "electricity.meter_fraud_tampering_or_complex_technical_issue", False)
    _fact(client, case_id, "electricity.reading_issue_type", "overbilling_regularization")

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] == "INSUFFICIENT_INFORMATION"

    case = _assert_reclassified(db, case_id, "RECLASSIFY_E02_A", "E02-A")
    assert case.status == "NEEDS_INFORMATION"


def test_unregistered_same_family_reclassification_fails_closed_to_human_review(client, db):
    created = _case(client, "Mi compañía de luz me ha subido el precio sin avisar")
    case_id = created["id"]
    assert created["family"] == "E07"
    _fact(client, case_id, "electricity.contract_change_effective_date", "2026-09-01")
    _fact(client, case_id, "electricity.contract_change_kind", "contractual_price_review")
    _fact(client, case_id, "electricity.price_review_formula_preagreed", False)

    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] == "RECLASSIFY"

    db.expire_all()
    case = db.get(Case, case_id)
    assert case is not None
    assert case.family == "E07"
    assert case.status == "HUMAN_REVIEW"
    current = db.get(Action, case.current_action_id)
    assert current is not None
    assert current.type == "HUMAN_REVIEW"
    assert current.status == "OPEN"
    source = [item for item in _actions(db, case_id) if item.type == "RECLASSIFY_E07_CONDITION_CHANGE"]
    assert source and all(item.status == "COMPLETED" for item in source)
    review = db.scalars(
        select(HumanReview).where(
            HumanReview.case_id == case_id,
            HumanReview.reason == "ENGINE_RECLASSIFICATION_REVIEW",
            HumanReview.status == "OPEN",
        )
    ).first()
    assert review is not None
    event = db.scalars(
        select(AuditEvent).where(
            AuditEvent.case_id == case_id,
            AuditEvent.event_type == "ENGINE_RECLASSIFICATION_REVIEW_REQUIRED",
        )
    ).first()
    assert event is not None
    assert event.payload_json["requested_action"] == "RECLASSIFY_E07_CONDITION_CHANGE"
