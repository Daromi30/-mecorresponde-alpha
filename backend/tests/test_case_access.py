from app.security import CaseAccess, hash_case_token


def test_new_case_is_protected_by_session_cookie_and_header(client, db):
    created_response = client.post(
        "/api/cases",
        json={"message": "Me cambié de compañía de luz y me siguen cobrando mantenimiento"},
    )
    assert created_response.status_code == 200
    created = created_response.json()
    case_id = created["id"]
    token = created["access_token"]
    assert token

    stored = db.get(CaseAccess, case_id)
    assert stored is not None
    assert stored.token_hash == hash_case_token(token)
    assert stored.token_hash != token

    # The same anonymous browser session can continue without an account.
    assert client.get(f"/api/cases/{case_id}").status_code == 200

    # Without the scoped session cookie the case is undiscoverable.
    client.cookies.clear()
    assert client.get(f"/api/cases/{case_id}").status_code == 404
    assert client.get(
        f"/api/cases/{case_id}", headers={"X-Case-Token": "wrong-token"}
    ).status_code == 404

    # Native/future clients can use the one-time returned token as a header.
    authorized = client.get(
        f"/api/cases/{case_id}", headers={"X-Case-Token": token}
    )
    assert authorized.status_code == 200
    assert authorized.json()["id"] == case_id


def test_access_token_response_is_not_cacheable(client):
    response = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
    assert "access_token" in response.json()
