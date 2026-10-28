"""RB-017 reproducible deny-by-default and multi-user isolation evidence."""

from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException, Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.backoffice_auth import COOKIE, create_reviewer
from app.db import Base
from app.models import Case, Fact
from app.reviews import HumanReview
from app.security import CaseAccess, generate_case_token, hash_case_token, require_case_access
from app.services_v2 import create_case


PASSWORD = "synthetic-rb017-password"


def _create_and_claim(client, email: str, message: str) -> tuple[str, str]:
    created = client.post("/api/cases", json={"message": message})
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    client.historical_account(email, PASSWORD)
    claimed = client.post(f"/api/cases/{case_id}/claim")
    assert claimed.status_code == 200, claimed.text
    return case_id, created.json()["access_token"]


def _login_user(client, email: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def _login_reviewer(client, login_id: str) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/backoffice-auth/login",
        json={"login_id": login_id, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return client.cookies.get(COOKIE)


def test_two_users_cannot_cross_read_write_export_or_delete(client, db):
    case_a, stale_token_a = _create_and_claim(
        client,
        "rb017-owner-a@example.com",
        "Factura sintética duplicada para el usuario A",
    )
    assert client.post("/api/auth/logout").status_code == 200
    client.cookies.clear()

    case_b, stale_token_b = _create_and_claim(
        client,
        "rb017-owner-b@example.com",
        "Pedido sintético no entregado para el usuario B",
    )
    assert client.post("/api/auth/logout").status_code == 200

    _login_user(client, "rb017-owner-a@example.com")
    assert client.get(f"/api/cases/{case_b}").status_code == 404
    assert client.get(
        f"/api/cases/{case_b}", headers={"X-Case-Token": stale_token_b}
    ).status_code == 404
    cross_write = client.post(
        f"/api/cases/{case_b}/facts",
        json={
            "key": "consumer.synthetic.cross_write",
            "value": "must-not-persist",
            "state": "confirmed",
            "user_confirmed": True,
        },
    )
    assert cross_write.status_code == 404
    assert client.request(
        "DELETE", f"/api/cases/{case_b}", json={"confirmation": "DELETE"}
    ).status_code == 404

    listed_ids = {item["id"] for item in client.get("/api/auth/cases").json()["cases"]}
    exported_ids = {item["id"] for item in client.get("/api/auth/export").json()["cases"]}
    assert listed_ids == {case_a}
    assert exported_ids == {case_a}

    deleted = client.request(
        "DELETE",
        "/api/auth/account",
        json={"password": PASSWORD, "confirmation": "DELETE"},
    )
    assert deleted.status_code == 200, deleted.text
    assert db.get(Case, case_a) is None
    assert db.get(Case, case_b) is not None
    assert db.scalar(
        select(Fact.id).where(
            Fact.case_id == case_b,
            Fact.key == "consumer.synthetic.cross_write",
        )
    ) is None

    _login_user(client, "rb017-owner-b@example.com")
    assert client.get(f"/api/cases/{case_b}").status_code == 200
    assert client.get(
        f"/api/cases/{case_a}", headers={"X-Case-Token": stale_token_a}
    ).status_code == 404


def test_reviewers_only_see_and_mutate_individually_assigned_cases(client, db):
    operator = create_reviewer(db, "rb017-operator", PASSWORD, "operator")
    reviewer_a = create_reviewer(db, "rb017-reviewer-a", PASSWORD, "reviewer")
    reviewer_b = create_reviewer(db, "rb017-reviewer-b", PASSWORD, "reviewer")
    case_a = create_case(db, "Caso sintético asignado al reviewer A")
    case_b = create_case(db, "Caso sintético asignado al reviewer B")
    review_a = HumanReview(
        case_id=case_a.id, reason="RB017", priority="HIGH", status="OPEN"
    )
    review_b = HumanReview(
        case_id=case_b.id, reason="RB017", priority="HIGH", status="OPEN"
    )
    db.add_all([review_a, review_b])
    db.commit()

    _login_reviewer(client, operator.login_id)
    for review, reviewer in ((review_a, reviewer_a), (review_b, reviewer_b)):
        assigned = client.post(
            f"/api/admin/reviews/{review.id}/assign",
            json={"reviewer_id": reviewer.id},
        )
        assert assigned.status_code == 200, assigned.text

    cookie_a = _login_reviewer(client, reviewer_a.login_id)
    queue_a = client.get("/api/admin/reviews")
    assert {item["case_id"] for item in queue_a.json()} == {case_a.id}
    assert client.get("/api/admin/stats").json()["total_cases"] == 1
    assert client.get(f"/api/admin/cases/{case_a.id}").status_code == 200
    assert client.get(f"/api/admin/cases/{case_b.id}").status_code == 403
    assert client.get(f"/api/admin/cases/{case_b.id}/handoff").status_code == 403
    assert client.post(
        f"/api/admin/reviews/{review_b.id}/complete",
        json={"reviewer_decision": "Intento sintético ajeno"},
    ).status_code == 403

    cookie_b = _login_reviewer(client, reviewer_b.login_id)
    queue_b = client.get("/api/admin/reviews")
    assert {item["case_id"] for item in queue_b.json()} == {case_b.id}
    assert client.get(f"/api/admin/cases/{case_a.id}").status_code == 403
    assert cookie_a != cookie_b


def _request(case_id: str, token: str) -> Request:
    path = f"/api/cases/{case_id}"
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"x-case-token", token.encode())],
            "client": ("test", 1),
            "server": ("test", 80),
            "root_path": "",
            "path_params": {"case_id": case_id},
        }
    )


def test_concurrent_capability_checks_never_cross_case_boundaries(tmp_path):
    database = tmp_path / "rb017-concurrency.sqlite"
    engine = create_engine(
        f"sqlite:///{database}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        case_a = Case(raw_intake="Synthetic A")
        case_b = Case(raw_intake="Synthetic B")
        token_a = generate_case_token()
        token_b = generate_case_token()
        db.add_all([case_a, case_b])
        db.flush()
        db.add_all(
            [
                CaseAccess(case_id=case_a.id, token_hash=hash_case_token(token_a)),
                CaseAccess(case_id=case_b.id, token_hash=hash_case_token(token_b)),
            ]
        )
        db.commit()
        case_a_id, case_b_id = case_a.id, case_b.id

    checks = [
        (case_a_id, token_a, True),
        (case_a_id, token_b, False),
        (case_b_id, token_b, True),
        (case_b_id, token_a, False),
    ] * 10

    def check(item: tuple[str, str, bool]) -> bool:
        case_id, token, expected = item
        with sessions() as db:
            try:
                require_case_access(_request(case_id, token), db)
                allowed = True
            except HTTPException as exc:
                assert exc.status_code == 404
                assert exc.detail == "Case not found"
                allowed = False
        return allowed is expected

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(check, checks))
