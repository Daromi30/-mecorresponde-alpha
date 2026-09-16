def create_case(client, message="Me cambié de compañía de luz y me siguen cobrando un mantenimiento"):
    response = client.post("/api/cases", json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()


def put_fact(client, case_id, key, value):
    response = client.post(
        f"/api/cases/{case_id}/facts",
        json={"key": key, "value": value, "state": "confirmed", "user_confirmed": True},
    )
    assert response.status_code == 200, response.text


def complete_e04b(client, case_id):
    put_fact(client, case_id, "electricity.supply_end_date", "2026-06-03")
    put_fact(client, case_id, "electricity.addon.identity", "Protección Hogar antigua")
    put_fact(client, case_id, "electricity.addon.identity", "Protección Hogar")
    put_fact(client, case_id, "electricity.addon.ever_contracted", True)
    put_fact(client, case_id, "electricity.addon.contracted_with_supply", True)
    put_fact(client, case_id, "electricity.addon.keep_requested", False)
    response = client.post(
        f"/api/cases/{case_id}/charges",
        json={
            "charges": [
                {
                    "amount": 8.99,
                    "service_period_start": "2026-06-04",
                    "service_period_end": "2026-07-03",
                    "evidence_verified": True,
                }
            ]
        },
    )
    assert response.status_code == 200, response.text


def nested_keys(value):
    if isinstance(value, dict):
        result = set(value)
        for child in value.values():
            result.update(nested_keys(child))
        return result
    if isinstance(value, list):
        result = set()
        for child in value:
            result.update(nested_keys(child))
        return result
    return set()


def test_case_handoff_contains_current_facts_and_exact_legal_provenance(client):
    created = create_case(client)
    case_id = created["id"]
    complete_e04b(client, case_id)
    diagnosis = client.post(f"/api/cases/{case_id}/diagnose")
    assert diagnosis.status_code == 200, diagnosis.text
    assert client.post(f"/api/cases/{case_id}/prepare-claim").status_code == 200

    response = client.get(f"/api/cases/{case_id}/handoff")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["package_version"] == 1
    assert body["scope"] == "single_case_resolution_handoff"
    assert body["case"]["id"] == case_id
    assert body["case"]["family"] == "E04-B"
    assert body["latest_decision"]["viability"] == "HIGH"

    current = {row["key"]: row for row in body["current_facts"]}
    assert current["electricity.addon.identity"]["value"] == "Protección Hogar"
    identity_history = [
        row for row in body["fact_history"] if row["key"] == "electricity.addon.identity"
    ]
    assert [row["value"] for row in identity_history] == [
        "Protección Hogar antigua",
        "Protección Hogar",
    ]
    assert identity_history[-1]["supersedes_fact_id"] == identity_history[0]["id"]

    provenance = body["legal_provenance"]
    assert provenance
    rule = next(row for row in provenance if row["rule_id"] == "ELEC_ADDON_END_WITH_SUPPLY")
    assert rule["article"] == "32.4"
    assert rule["review_status"] == "approved"
    assert rule["source"]["official_url"].startswith("https://www.boe.es/")
    assert rule["source"]["status"] == "active"

    keys = nested_keys(body)
    assert not {
        "token_hash",
        "access_token",
        "storage_key",
        "payload_json",
        "ai_runs",
    }.intersection(keys)
    assert "internal_audit_payloads" in body["excluded_internal_data"]
    assert response.headers["cache-control"] == "no-store"


def test_case_handoff_is_isolated_by_case_access(client):
    first = create_case(client, "Me han cobrado dos veces la misma factura de luz")
    second = create_case(client, "Compré un pedido online y no me ha llegado")

    blocked = client.get(
        f"/api/cases/{first['id']}/handoff",
        headers={"X-Case-Token": second["access_token"]},
    )
    assert blocked.status_code == 404

    allowed = client.get(
        f"/api/cases/{first['id']}/handoff",
        headers={"X-Case-Token": first["access_token"]},
    )
    assert allowed.status_code == 200
    assert allowed.json()["case"]["id"] == first["id"]
