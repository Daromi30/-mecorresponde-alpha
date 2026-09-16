def create_case(client, message):
    response = client.post("/api/cases", json={"message": message})
    assert response.status_code == 200, response.text
    body = response.json()
    return body["id"], body["access_token"]


def register(client, email, password):
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201, response.text


def login(client, email, password):
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text


def test_anonymous_case_capabilities_are_strictly_scoped_to_one_case(client):
    case_a, token_a = create_case(client, "Me han cobrado dos veces la misma factura de luz")
    case_b, token_b = create_case(client, "Compré un pedido online y no me ha llegado")

    # A valid token for another real case must look exactly like a missing case.
    cross_read = client.get(
        f"/api/cases/{case_a}",
        headers={"X-Case-Token": token_b},
    )
    assert cross_read.status_code == 404
    assert cross_read.json()["detail"] == "Case not found"

    # The same isolation must protect state-changing routes, not only reads.
    cross_write = client.post(
        f"/api/cases/{case_a}/facts",
        headers={"X-Case-Token": token_b},
        json={
            "key": "electricity.billing.synthetic_probe",
            "value": "must-not-be-written",
            "state": "confirmed",
            "user_confirmed": True,
        },
    )
    assert cross_write.status_code == 404

    cross_delete = client.request(
        "DELETE",
        f"/api/cases/{case_a}",
        headers={"X-Case-Token": token_b},
        json={"confirmation": "DELETE"},
    )
    assert cross_delete.status_code == 404

    own_read = client.get(
        f"/api/cases/{case_a}",
        headers={"X-Case-Token": token_a},
    )
    assert own_read.status_code == 200
    assert not any(
        fact["key"] == "electricity.billing.synthetic_probe"
        for fact in own_read.json()["facts"]
    )
    assert client.get(
        f"/api/cases/{case_b}", headers={"X-Case-Token": token_b}
    ).status_code == 200


def test_claiming_case_revokes_anonymous_token_and_accounts_cannot_cross_cases(client):
    case_a, token_a = create_case(client, "Me cambiaron de compañía de luz sin permiso")
    case_b, token_b = create_case(client, "Compré un televisor defectuoso y rechazan la garantía")

    password_a = "owner-a-strong-password"
    password_b = "owner-b-strong-password"
    register(client, "owner-a@example.com", password_a)
    assert client.post(f"/api/cases/{case_a}/claim").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200

    # Once claimed, possession of the old anonymous capability is no longer enough.
    old_a = client.get(f"/api/cases/{case_a}", headers={"X-Case-Token": token_a})
    assert old_a.status_code == 404

    register(client, "owner-b@example.com", password_b)
    assert client.post(f"/api/cases/{case_b}/claim").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get(f"/api/cases/{case_b}", headers={"X-Case-Token": token_b}).status_code == 404

    login(client, "owner-a@example.com", password_a)
    assert client.get(f"/api/cases/{case_a}").status_code == 200
    assert client.get(f"/api/cases/{case_b}").status_code == 404
    assert client.request(
        "DELETE",
        f"/api/cases/{case_b}",
        json={"confirmation": "DELETE"},
    ).status_code == 404
    assert client.post("/api/auth/logout").status_code == 200

    login(client, "owner-b@example.com", password_b)
    assert client.get(f"/api/cases/{case_b}").status_code == 200
