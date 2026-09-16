ADMIN = {"Authorization": "Bearer test-admin-token"}


def test_readiness_exposes_all_family_response_resolution_proof(client):
    response = client.get("/api/admin/readiness", headers=ADMIN)
    assert response.status_code == 200, response.text
    checks = {item["key"]: item for item in response.json()["checks"]}

    item = checks["fourteen_family_response_resolution_loop"]
    assert item["ok"] is True
    assert item["severity"] == "INTERNAL_BETA_BLOCKER"
    assert item["metadata"]["family_count"] == 14
    assert item["metadata"]["verification"] == "ci_all_family_response_resolution_loop"
    assert item["metadata"]["partial_response_escalation_guard"] is True
    assert "probabilidad" not in item["detail"].lower()
    assert "regulador" not in item["detail"].lower()
