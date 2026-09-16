ADMIN = {"Authorization": "Bearer test-admin-token"}


def test_readiness_exposes_safe_professional_handoff_proof(client):
    response = client.get("/api/admin/readiness", headers=ADMIN)
    assert response.status_code == 200, response.text
    checks = {item["key"]: item for item in response.json()["checks"]}

    item = checks["post_response_professional_handoff"]
    assert item["ok"] is True
    assert item["severity"] == "INTERNAL_BETA_BLOCKER"
    assert item["metadata"]["verification"] == "ci_professional_escalation_handoff_and_guards"
    assert item["metadata"]["generic_note_completion_fail_closed"] is True
    assert item["metadata"]["post_response_reanalysis_guard"] is True
    assert item["metadata"]["automatic_legal_route_selection"] is False
    assert "probabilidad de éxito" in item["detail"].lower()
    assert "no reabrir" in item["detail"].lower()
