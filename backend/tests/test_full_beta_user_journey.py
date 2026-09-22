PASSWORD = "beta-journey-password-2026"
EMAIL = "beta-journey@example.com"


def _fact(client, case_id, key, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={
            "key": key,
            "value": value,
            "state": "confirmed",
            "user_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text


def _nested_keys(value):
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys.update(_nested_keys(child))
        return keys
    if isinstance(value, list):
        keys = set()
        for child in value:
            keys.update(_nested_keys(child))
        return keys
    return set()


def test_complete_saved_account_beta_resolution_journey(client):
    # 1. A person can start without an account and receives an isolated anonymous case.
    created = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando un mantenimiento"},
    )
    assert created.status_code == 200, created.text
    case = created.json()
    case_id = case["id"]
    anonymous_token = case["access_token"]
    assert case["family"] == "E04-B"
    assert case["vertical"] == "electricity"
    assert case["status"] == "INTAKE"
    assert anonymous_token

    # 2. The same person can create an optional account and attach the live case to it.
    registered = client.post(
        "/api/auth/register",
        json={"email": EMAIL, "password": PASSWORD},
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["user"]["email"] == EMAIL

    claimed = client.post(f"/api/cases/{case_id}/claim")
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["owned"] is True
    assert claimed.json()["newly_claimed"] is True

    mine = client.get("/api/auth/cases")
    assert mine.status_code == 200, mine.text
    assert case_id in {item["id"] for item in mine.json()["cases"]}

    # 3. Build a real, evidence-backed dossier and get a deterministic legal diagnosis.
    for key, value in {
        "electricity.supply_end_date": "2026-06-03",
        "electricity.addon.identity": "Protección Hogar",
        "electricity.addon.ever_contracted": True,
        "electricity.addon.contracted_with_supply": True,
        "electricity.addon.keep_requested": False,
    }.items():
        _fact(client, case_id, key, value)

    charges = client.post(
        f"/api/cases/{case_id}/charges",
        json={
            "charges": [
                {
                    "amount": 8.99,
                    "service_period_start": "2026-06-04",
                    "service_period_end": "2026-07-03",
                    "evidence_verified": True,
                },
                {
                    "amount": 8.99,
                    "service_period_start": "2026-07-04",
                    "service_period_end": "2026-08-03",
                    "evidence_verified": True,
                },
            ]
        },
    )
    assert charges.status_code == 200, charges.text

    diagnosed = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosed.status_code == 200, diagnosed.text
    diagnosis = diagnosed.json()
    assert diagnosis["viability"] == "HIGH"
    assert diagnosis["claimable_amount"] == 17.98

    prepared = client.post(f"/api/cases/{case_id}/prepare-claim")
    assert prepared.status_code == 200, prepared.text
    package = prepared.json()
    assert package["amount"] == 17.98
    assert package["legal_basis"]
    assert all(item["official_url"].startswith("https://www.boe.es/") for item in package["legal_basis"])
    assert client.get(f"/api/cases/{case_id}").json()["status"] == "READY_TO_SUBMIT"

    # 4. Record the real outbound action. The engine may expose a verified legal period,
    # but it must not fabricate an exact calendar deadline when the calendar is unverified.
    submitted = client.post(
        f"/api/cases/{case_id}/submission",
        json={
            "submitted_on": "2026-09-14",
            "channel": "web_form",
            "reference_number": "BETA-JOURNEY-001",
        },
    )
    assert submitted.status_code == 200, submitted.text
    submission = submitted.json()
    assert submission["deadline"] is None
    assert submission["deadline_status"] == "LEGAL_PERIOD_ONLY"
    assert submission["legal_response_period_business_days"] == 15
    assert client.get(f"/api/cases/{case_id}").json()["status"] == "WAITING_RESPONSE"

    # 5. Account ownership must survive logout/login, while the old anonymous capability
    # is no longer a second path into the claimed case.
    logged_out = client.post("/api/auth/logout")
    assert logged_out.status_code == 200, logged_out.text
    assert client.get(f"/api/cases/{case_id}").status_code == 404
    assert client.get(
        f"/api/cases/{case_id}",
        headers={"X-Case-Token": anonymous_token},
    ).status_code == 404

    logged_in = client.post(
        "/api/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
    )
    assert logged_in.status_code == 200, logged_in.text
    reopened = client.get(f"/api/cases/{case_id}")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "WAITING_RESPONSE"

    # 6. The company response is incorporated as evidence and acceptance does not close
    # the file until the person confirms that the promised remedy was actually executed.
    response = client.post(
        f"/api/cases/{case_id}/responses/evidenced",
        json={
            "text": "Aceptamos su reclamación y procederemos a devolver el importe.",
            "received_on": "2026-09-16",
            "channel": "email",
            "reference_number": "RESP-BETA-001",
        },
    )
    assert response.status_code == 200, response.text
    response_body = response.json()
    assert response_body["analysis"]["type"] == "ACCEPTANCE"
    assert response_body["case_status"] == "RESOLVED_PENDING_EXECUTION"

    pending = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "FAVORABLE",
            "amount_recovered": 17.98,
            "verified_by_user": False,
        },
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["case_status"] == "RESOLVED_PENDING_EXECUTION"

    resolved = client.post(
        f"/api/cases/{case_id}/outcome/evidenced",
        json={
            "result_type": "FAVORABLE",
            "amount_recovered": 17.98,
            "verified_by_user": True,
            "remaining_material_commitments": "none",
            "resolved_on": "2026-09-16",
            "resolution_channel": "bank_or_card_refund",
            "non_monetary_result": None,
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["case_status"] == "RESOLVED"
    assert client.get(f"/api/cases/{case_id}").json()["status"] == "RESOLVED"

    # 7. The finished case remains portable and auditable for the claimant/reviewer.
    timeline = client.get(f"/api/cases/{case_id}/timeline")
    assert timeline.status_code == 200, timeline.text
    timeline_body = timeline.json()
    assert timeline_body["current_status"] == "RESOLVED"
    event_types = {event["type"] for event in timeline_body["events"]}
    assert {
        "CASE_OPENED",
        "DIAGNOSIS_UPDATED",
        "CLAIM_SUBMITTED",
        "CLAIM_ACCEPTED_PENDING_EXECUTION",
        "RESOLUTION_VERIFIED",
    }.issubset(event_types)

    handoff = client.get(f"/api/cases/{case_id}/handoff")
    assert handoff.status_code == 200, handoff.text
    handoff_body = handoff.json()
    assert handoff_body["case"]["id"] == case_id
    assert not {"password_hash", "token_hash"}.intersection(_nested_keys(handoff_body))

    exported = client.get("/api/auth/export")
    assert exported.status_code == 200, exported.text
    export_body = exported.json()
    assert case_id in {item["id"] for item in export_body["cases"]}
    serialized_export = exported.text.lower()
    assert "password_hash" not in serialized_export
    assert "token_hash" not in serialized_export
    assert PASSWORD.lower() not in serialized_export
