from pathlib import Path
import shutil
import subprocess
import tempfile


STATIC = Path(__file__).parents[1] / "app" / "static"


def create_submitted_e04b(client):
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]
    for key, value in {
        "electricity.supply_end_date": "2026-06-03",
        "electricity.addon.identity": "Protección Hogar",
        "electricity.addon.ever_contracted": True,
        "electricity.addon.contracted_with_supply": True,
        "electricity.addon.keep_requested": False,
    }.items():
        assert client.post(
            f"/api/cases/{case_id}/facts",
            json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
        ).status_code == 200
    assert client.post(
        f"/api/cases/{case_id}/charges",
        json={"charges": [{
            "amount": 8.99,
            "service_period_start": "2026-06-04",
            "service_period_end": "2026-07-03",
            "evidence_verified": True,
        }]},
    ).status_code == 200
    assert client.post(f"/api/cases/{case_id}/diagnose").status_code == 200
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 200
    assert client.post(
        f"/api/cases/{case_id}/submission",
        json={"submitted_on": "2026-09-16", "channel": "web_form"},
    ).status_code == 200
    return case_id


def test_initial_mutation_endpoints_are_locked_after_submission(client):
    case_id = create_submitted_e04b(client)

    attempts = {
        "facts": client.post(
            f"/api/cases/{case_id}/facts",
            json={
                "key": "electricity.addon.keep_requested",
                "value": True,
                "state": "confirmed",
                "user_confirmed": True,
            },
        ),
        "charges": client.post(
            f"/api/cases/{case_id}/charges",
            json={"charges": [{"amount": 99.0, "evidence_verified": True}]},
        ),
        "diagnose": client.post(f"/api/cases/{case_id}/diagnose"),
        "prepare": client.post(f"/api/cases/{case_id}/prepare-claim"),
        "document_fact": client.post(
            f"/api/cases/{case_id}/documents/not-a-real-document/confirm-fact",
            json={"key": "electricity.addon.identity", "value": "Otro servicio"},
        ),
    }

    assert all(response.status_code == 409 for response in attempts.values())
    for name, response in attempts.items():
        detail = response.json()["detail"]
        if name == "prepare":
            assert "does not permit preparing" in detail
        else:
            assert "locked in the current phase" in detail


def test_response_flow_remains_available_after_initial_phase_is_locked(client):
    case_id = create_submitted_e04b(client)

    response = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Denegamos la devolución porque el contrato de mantenimiento es independiente.",
            "received_on": "2026-09-16",
            "channel": "email",
            "reference_number": "RESP-1",
        },
    )
    assert response.status_code == 200
    assert response.json()["analysis"]["type"] == "DENIAL"

    still_locked = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": "electricity.addon.keep_requested", "value": True, "state": "confirmed"},
    )
    assert still_locked.status_code == 409


def test_human_review_phase_cannot_be_rewound_through_claimant_fact_or_diagnose_routes(client):
    created = client.post(
        "/api/cases",
        json={"message": "La factura de luz es incorrecta y me han cobrado de más"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]
    for key, value in {
        "electricity.billing.invoice_date": "2026-05-01",
        "electricity.billing.billed_amount": 150.0,
        "electricity.billing.correct_amount": 100.0,
    }.items():
        assert client.post(
            f"/api/cases/{case_id}/facts",
            json={"key": key, "value": value, "state": "confirmed"},
        ).status_code == 200
    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200
    assert diagnosis.json()["scope_status"] == "LEGACY_REVIEW"

    fact_attempt = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": "electricity.billing.correct_amount", "value": 90.0, "state": "confirmed"},
    )
    diagnose_attempt = client.post(f"/api/cases/{case_id}/diagnose")
    assert fact_attempt.status_code == 409
    assert diagnose_attempt.status_code == 409


def test_case_phase_guard_ui_is_loaded_and_removes_intake_controls_in_locked_phases():
    loader = (STATIC / "dossier_quality.js").read_text(encoding="utf-8")
    script = (STATIC / "case_phase_guard.js").read_text(encoding="utf-8")
    assert "/demo/case_phase_guard.js" in loader
    for status in ("WAITING_RESPONSE", "RESPONSE_RECEIVED", "HUMAN_REVIEW", "RESOLVED_PENDING_EXECUTION", "RESOLVED"):
        assert status in script
    assert "questionArea" in script
    assert "diagnose()" not in script
    assert "prepareClaim()" not in script


def test_case_phase_guard_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    script = (STATIC / "case_phase_guard.js").read_text(encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        path = handle.name
    result = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
