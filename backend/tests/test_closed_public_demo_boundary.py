"""Production HTTP boundary checks with wholly fictional marker strings."""

import pytest
from sqlalchemy import select

from app.demo_boundary import enforce_demo_boundary
from app.demo_scenarios import SCENARIOS
from app.main import app
from app.models import AIRun, AuditEvent, Case, Communication, Evidence, Fact
from app.reviews import HumanReview
from app.security import CaseAccess, hash_case_token
from app.services_v2 import create_case


@pytest.fixture
def public_client(client):
    client.app.dependency_overrides.pop(enforce_demo_boundary)
    return client


def test_catalog_is_multivertical_and_public_pages_request_no_free_text(public_client):
    catalog = public_client.get("/api/demo/scenarios")
    assert catalog.status_code == 200
    rows = catalog.json()["scenarios"]
    assert {item["vertical"] for item in rows} >= {"electricity", "purchases", "telecom", "rentals"}
    for path in ("/", "/demo/", "/demo/index.html"):
        page = public_client.get(path)
        assert page.status_code == 200
        assert "Escenarios ficticios" in page.text
        assert "Cuéntame qué te ha pasado" not in page.text
        assert 'id="story"' not in page.text
        assert 'id="accountEmail"' not in page.text
    # Static fallback must not accidentally expose the retained legacy intake.
    assert public_client.get("/demo/index.html/").status_code == 404


def test_every_case_write_route_has_the_server_side_demo_guard():
    routes = [
        route for included in app.routes
        for route in getattr(getattr(included, "original_router", None), "routes", [])
        if getattr(route, "path", "").startswith("/api/cases")
    ]
    assert routes
    for route in routes:
        if not getattr(route, "methods", set()).intersection({"POST", "PUT", "PATCH"}):
            continue
        assert any(dep.call is enforce_demo_boundary for dep in route.dependant.dependencies), route.path


@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_fictional_scenario_runs_the_real_motor(public_client, db, scenario_id):
    created = public_client.post("/api/cases", json={"scenario_id": scenario_id})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["mode"] == "SYNTHETIC"
    assert body["demo_scenario_id"] == scenario_id
    assert body["vertical"] == SCENARIOS[scenario_id].vertical
    assert body["raw_intake"] == SCENARIOS[scenario_id].message
    diagnosis = public_client.post(f"/api/cases/{body['id']}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert diagnosis.json()["viability"] == "HIGH", diagnosis.json()
    prepared = public_client.post(f"/api/cases/{body['id']}/prepare-claim")
    assert prepared.status_code == 200, prepared.text
    assert prepared.json().get("claim_type")
    db.expire_all()
    assert db.get(Case, body["id"]).mode == "SYNTHETIC"


def test_old_message_and_manipulated_scenario_are_rejected_without_persistence(public_client, db, caplog):
    marker = "FICTITIOUS-PRIVATE-MARKER-987654"
    for body in (
        {"message": marker},
        {"scenario_id": "scn_8a1f3c67", "message": marker},
        {"scenario_id": marker},
        {"scenario_id": "scn_8a1f3c67", "facts": {"name": marker}},
    ):
        result = public_client.post("/api/cases", json=body)
        assert result.status_code == 422
    assert db.scalars(select(Case)).all() == []
    events = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "SYNTHETIC_INPUT_REJECTED")).all()
    assert len(events) == 4
    assert all(marker not in str(event.payload_json) for event in events)
    assert marker not in caplog.text


def test_all_public_case_write_routes_deny_free_content_before_persistence(public_client, db, caplog):
    created = public_client.post("/api/cases", json={"scenario_id": "scn_8a1f3c67"})
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    marker = "FICTITIOUS-PRIVATE-MARKER-123456"
    attempts = (
        ("facts", {"key": "electricity.pricing_promised_terms", "value": marker}),
        ("charges", {"charges": [{"amount": 3.0, "reference": marker}]}),
        ("submission", {"submitted_on": "2026-09-01", "reference_number": marker}),
        ("responses", {"text": marker}),
        ("responses/evidenced", {"text": marker, "reference_number": marker}),
        ("outcome", {"result_type": marker}),
        ("outcome/evidenced", {"non_monetary_result": marker}),
        ("reviews/fake/complete", {"reviewer_decision": marker}),
        ("documents/fake/confirm-fact", {"key": "purchase.product_name", "value": marker, "excerpt": marker}),
        ("resume-wait", {"note": marker}),
        ("claim", {"note": marker}),
        ("diagnose", {"note": marker}),
        ("prepare-claim", {"note": marker}),
    )
    for suffix, body in attempts:
        result = public_client.post(f"/api/cases/{case_id}/{suffix}", json=body)
        assert result.status_code in {403, 409, 422}, (suffix, result.status_code, result.text)
    db.expire_all()
    case = db.get(Case, case_id)
    material = str(case.raw_intake)
    for model in (Fact, Communication, Evidence, HumanReview, AuditEvent, AIRun):
        rows = db.scalars(select(model).where(model.case_id == case_id)).all()
        material += str([row.__dict__ for row in rows])
    assert marker not in material
    assert marker not in caplog.text
    assert any(event.event_type == "SYNTHETIC_INPUT_REJECTED" for event in db.scalars(
        select(AuditEvent).where(AuditEvent.case_id == case_id)
    ))


def test_historical_synthetic_case_is_read_only_and_cannot_be_relabelled_real(public_client, db):
    historical = create_case(db, "En mi factura de luz me aplican un precio distinto al contratado")
    db.add(CaseAccess(case_id=historical.id, token_hash=hash_case_token("fictional-historical-token")))
    db.commit()
    denied = public_client.post(f"/api/cases/{historical.id}/facts", json={
        "key": "electricity.market_type", "value": "free_market",
    }, headers={"X-Case-Token": "fictional-historical-token"})
    assert denied.status_code == 422
    created = public_client.post("/api/cases", json={
        "scenario_id": "scn_8a1f3c67", "mode": "PRIVATE_REAL_BETA",
    })
    assert created.status_code == 422
    db.expire_all()
    assert db.get(Case, historical.id).mode == "SYNTHETIC"
