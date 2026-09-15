from app.auth_models import User
from app.models import Case
from app.security import CaseAccess


def test_account_can_claim_case_and_recover_it_without_anonymous_token(client, db):
    created = client.post(
        "/api/cases",
        json={"message": "Me han cobrado dos veces la misma factura de luz"},
    )
    assert created.status_code == 200
    case_id = created.json()["id"]
    anonymous_token = created.json()["access_token"]
    assert anonymous_token
    assert db.get(CaseAccess, case_id) is not None

    password = "correct-horse-battery-staple"
    registered = client.post(
        "/api/auth/register",
        json={"email": " Persona@Example.com ", "password": password},
    )
    assert registered.status_code == 201
    assert registered.json()["user"]["email"] == "persona@example.com"
    assert registered.json()["user"]["email_verified"] is False

    user = db.query(User).filter(User.email == "persona@example.com").one()
    assert user.password_hash != password
    assert user.password_hash.startswith("pbkdf2_sha256$")

    claimed = client.post(f"/api/cases/{case_id}/claim")
    assert claimed.status_code == 200
    assert claimed.json()["owned"] is True
    assert claimed.json()["newly_claimed"] is True
    assert db.get(Case, case_id).user_id == user.id
    assert db.get(CaseAccess, case_id) is None

    mine = client.get("/api/auth/cases")
    assert mine.status_code == 200
    assert [item["id"] for item in mine.json()["cases"]] == [case_id]

    logged_out = client.post("/api/auth/logout")
    assert logged_out.status_code == 200
    assert client.get(f"/api/cases/{case_id}").status_code == 404
    assert client.get(
        f"/api/cases/{case_id}", headers={"X-Case-Token": anonymous_token}
    ).status_code == 404

    wrong = client.post(
        "/api/auth/login",
        json={"email": "persona@example.com", "password": "definitely-wrong-password"},
    )
    assert wrong.status_code == 401

    logged_in = client.post(
        "/api/auth/login",
        json={"email": "persona@example.com", "password": password},
    )
    assert logged_in.status_code == 200
    assert client.get(f"/api/cases/{case_id}").status_code == 200


def test_registration_rejects_duplicate_normalized_email(client):
    payload = {"email": "user@example.com", "password": "a-strong-alpha-password"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    duplicate = client.post(
        "/api/auth/register",
        json={"email": " USER@example.com ", "password": "another-strong-password"},
    )
    assert duplicate.status_code == 409
