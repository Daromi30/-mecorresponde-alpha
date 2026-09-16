import json

from app.models import Case, Evidence, Fact
from app.services_v2 import create_human_review


def test_quality_profile_reports_factual_readiness_without_success_probability(client):
    created = client.post(
        "/api/cases",
        json={"message": "Compré un televisor y la tienda me rechaza la garantía porque está averiado"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]

    initial = client.get(f"/api/cases/{case_id}/quality")
    assert initial.status_code == 200
    body = initial.json()
    assert body["readiness"] == "INTAKE"
    assert body["facts"]["total"] == 0
    assert body["gates"]["current_decision_id"] is None
    serialized = json.dumps(body).lower()
    assert "success_probability" not in serialized
    assert "probabilidad de éxito" not in serialized

    confirmed = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": "purchase.buyer_is_consumer",
            "value": True,
            "state": "confirmed",
            "materiality": "critical",
            "user_confirmed": True,
        },
    )
    assert confirmed.status_code == 200
    unknown = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": "purchase.seller_is_business",
            "value": None,
            "state": "unknown",
            "materiality": "critical",
            "user_confirmed": False,
        },
    )
    assert unknown.status_code == 200

    profile = client.get(f"/api/cases/{case_id}/quality").json()
    assert profile["readiness"] == "NEEDS_INFORMATION"
    assert profile["facts"]["total"] == 2
    assert profile["facts"]["confirmed"] == 1
    assert profile["facts"]["unknown"] == 1
    assert profile["facts"]["critical_total"] == 2
    assert profile["facts"]["critical_confirmed"] == 1


def test_quality_profile_distinguishes_documentary_support_and_human_review(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Compré un televisor y la tienda me rechaza la garantía porque está averiado"},
    )
    case_id = created.json()["id"]
    case = db.get(Case, case_id)
    assert case is not None

    fact = Fact(
        case_id=case.id,
        key="purchase.delivery_date",
        value_json={"value": "2026-08-01"},
        state="confirmed",
        materiality="critical",
        user_confirmed=True,
        created_by="user",
    )
    db.add(fact)
    db.flush()
    db.add(
        Evidence(
            case_id=case.id,
            fact_id=fact.id,
            source_type="document",
            locator="invoice:delivery_date",
            strength="strong",
        )
    )
    create_human_review(
        db,
        case,
        reason="TEST_MATERIAL_UNCERTAINTY",
        priority="HIGH",
        context={"test": True},
    )
    db.commit()

    profile = client.get(f"/api/cases/{case_id}/quality")
    assert profile.status_code == 200
    body = profile.json()
    assert body["readiness"] == "HUMAN_REVIEW_REQUIRED"
    assert body["evidence"]["document_supported_facts"] == 1
    assert body["evidence"]["strong_supported_facts"] >= 1
    assert body["gates"]["open_human_reviews"] == 1


def test_quality_profile_uses_only_active_fact_versions_and_active_evidence(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Compré un televisor y la tienda me rechaza la garantía porque está averiado"},
    )
    case_id = created.json()["id"]

    first = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": "purchase.seller_is_business",
            "value": None,
            "state": "unknown",
            "materiality": "critical",
            "user_confirmed": False,
        },
    )
    assert first.status_code == 200
    old_fact_id = first.json()["fact_id"]
    db.add(
        Evidence(
            case_id=case_id,
            fact_id=old_fact_id,
            source_type="document",
            locator="obsolete:test",
            strength="strong",
        )
    )
    db.commit()

    replacement = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": "purchase.seller_is_business",
            "value": True,
            "state": "confirmed",
            "materiality": "critical",
            "user_confirmed": True,
        },
    )
    assert replacement.status_code == 200
    new_fact_id = replacement.json()["fact_id"]
    db.add(
        Evidence(
            case_id=case_id,
            fact_id=new_fact_id,
            source_type="human",
            locator="current:test",
            strength="strong",
        )
    )
    db.commit()

    body = client.get(f"/api/cases/{case_id}/quality").json()
    assert body["readiness"] == "INTAKE"
    assert body["facts"] == {
        "total": 1,
        "confirmed": 1,
        "asserted": 0,
        "unknown": 0,
        "critical_total": 1,
        "critical_confirmed": 1,
    }
    assert body["evidence"]["document_supported_facts"] == 0
    assert body["evidence"]["human_supported_facts"] == 1
    assert body["evidence"]["strong_supported_facts"] == 1
    assert body["evidence"]["links_total"] == 2  # user confirmation + active human evidence
    assert "historial sustituido" in body["note"].lower()


def test_quality_endpoint_uses_same_undiscoverable_case_access(client):
    created = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    case_id = created.json()["id"]
    assert client.get(f"/api/cases/{case_id}/quality").status_code == 200

    client.cookies.clear()
    denied = client.get(f"/api/cases/{case_id}/quality")
    assert denied.status_code == 404
