from datetime import timedelta

from sqlalchemy import func, select

from app.calendar_clock import spain_today
from app.models import Action, LegalRuleVersion


RECENT_C05_RECEIVED_DATE = (spain_today() - timedelta(days=7)).isoformat()


def fact(client, case_id, key, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def diagnose_and_prepare(client, case_id):
    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    claim = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert claim.status_code == 200, claim.text
    return claim.json()


def assert_verified_basis(package):
    basis = package["legal_basis"]
    assert basis
    for item in basis:
        assert item["rule_id"]
        assert item["version"] >= 1
        assert item["article"]
        assert item["source_id"]
        assert item["source"]
        assert item["official_url"].startswith("https://www.boe.es/")


def build_e04b(client):
    case_id = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    ).json()["id"]
    for key, value in {
        "electricity.supply_end_date": "2026-06-03",
        "electricity.addon.identity": "Protección Hogar",
        "electricity.addon.ever_contracted": True,
        "electricity.addon.contracted_with_supply": True,
        "electricity.addon.keep_requested": False,
    }.items():
        fact(client, case_id, key, value)
    charges = client.post(
        f"/api/cases/{case_id}/charges",
        json={"charges": [{
            "amount": 8.99,
            "service_period_start": "2026-06-04",
            "service_period_end": "2026-07-03",
            "evidence_verified": True,
        }]},
    )
    assert charges.status_code == 200
    return case_id


def build_e04a(client):
    case_id = client.post(
        "/api/cases",
        json={"message": "En la factura de luz me cobran un mantenimiento que nunca contraté"},
    ).json()["id"]
    fact(client, case_id, "electricity.addon.identity", "Protección Hogar")
    fact(client, case_id, "electricity.addon.ever_contracted", False)
    charges = client.post(
        f"/api/cases/{case_id}/charges",
        json={"charges": [{"amount": 9.99, "evidence_verified": True}]},
    )
    assert charges.status_code == 200
    return case_id


def build_e02a(client):
    case_id = client.post(
        "/api/cases", json={"message": "La factura eléctrica me ha cobrado de más"}
    ).json()["id"]
    fact(client, case_id, "electricity.billing.invoice_date", "2026-07-01")
    fact(client, case_id, "electricity.billing.billed_amount", 150)
    fact(client, case_id, "electricity.billing.correct_amount", 100)
    return case_id


def build_e02b(client):
    case_id = client.post(
        "/api/cases", json={"message": "Me han cobrado dos veces la misma factura de luz"}
    ).json()["id"]
    fact(client, case_id, "electricity.billing.same_debt", True)
    charges = client.post(
        f"/api/cases/{case_id}/charges",
        json={"charges": [
            {"amount": 74.30, "evidence_verified": True},
            {"amount": 74.30, "evidence_verified": True},
        ]},
    )
    assert charges.status_code == 200
    return case_id


def build_c01(client):
    case_id = client.post(
        "/api/cases",
        json={"message": "Compré un televisor en una tienda, está defectuoso y me rechazan la garantía"},
    ).json()["id"]
    for key, value in {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.second_hand": False,
        "purchase.product_name": "Televisor",
        "purchase.delivery_date": "2026-01-10",
        "purchase.defect_manifested_date": "2026-09-01",
        "purchase.defect_description": "La pantalla se queda negra",
        "purchase.accidental_damage_or_misuse": False,
        "purchase.price": 1299.0,
        "purchase.seller_denied_conformity": True,
    }.items():
        fact(client, case_id, key, value)
    return case_id


def build_c04(client):
    case_id = client.post(
        "/api/cases",
        json={"message": "Compré una cafetera online y no me ha llegado el pedido"},
    ).json()["id"]
    for key, value in {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.product_name": "Cafetera",
        "purchase.order_date": "2026-07-01",
        "purchase.amount_paid": 149.90,
        "purchase.delivered": False,
        "purchase.delivery_date_was_agreed": False,
        "purchase.seller_refused_delivery": False,
        "purchase.delivery_date_essential": False,
        "purchase.additional_delivery_period_requested": True,
        "purchase.additional_delivery_period_deadline": "2026-09-10",
    }.items():
        fact(client, case_id, key, value)
    return case_id


def build_c05(client):
    case_id = client.post(
        "/api/cases",
        json={"message": "Compré unos auriculares online y quiero devolver la compra dentro de 14 días"},
    ).json()["id"]
    for key, value in {
        "purchase.buyer_is_consumer": True,
        "purchase.seller_is_business": True,
        "purchase.distance_contract": True,
        "purchase.product_name": "Auriculares",
        "purchase.received_date": RECENT_C05_RECEIVED_DATE,
        "purchase.amount_paid": 120.0,
        "purchase.premium_delivery_extra": 0.0,
        "purchase.withdrawal_exception_possible": False,
        "purchase.withdrawal_information_provided": True,
        "purchase.withdrawal_sent": False,
    }.items():
        fact(client, case_id, key, value)
    return case_id


def test_all_base_family_claim_packages_are_enriched_with_exact_official_provenance(client, db):
    builders = [build_e04b, build_e04a, build_e02a, build_e02b, build_c01, build_c04, build_c05]
    for builder in builders:
        case_id = builder(client)
        package = diagnose_and_prepare(client, case_id)
        assert_verified_basis(package)
        action = db.get(Action, package["action_id"])
        assert action is not None
        assert action.payload_json["legal_basis"] == package["legal_basis"]


def test_base_renderer_fails_closed_before_ready_action_if_rule_review_is_revoked(client, db):
    case_id = build_e02b(client)
    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200

    rule = db.scalar(
        select(LegalRuleVersion).where(
            LegalRuleVersion.rule_id == "UNDUE_PAYMENT_RESTITUTION"
        )
    )
    assert rule is not None
    rule.review_status = "pending"
    db.commit()

    blocked = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert blocked.status_code == 422
    assert "Reviewed legal rule version missing" in blocked.json()["detail"]
    assert db.scalar(
        select(func.count()).select_from(Action).where(
            Action.case_id == case_id,
            Action.type == "SUBMIT_INITIAL_CLAIM",
        )
    ) == 0
