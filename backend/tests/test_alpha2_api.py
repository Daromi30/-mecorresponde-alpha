def post_fact(client, cid, key, value, state="confirmed", user_confirmed=True):
    r = client.post(f"/api/cases/{cid}/facts", json={
        "key": key, "value": value, "state": state, "user_confirmed": user_confirmed
    })
    assert r.status_code == 200
    return r.json()


def test_classifier_routes_e04a(client):
    r = client.post("/api/cases", json={"message": "En la factura de luz me cobran un mantenimiento que nunca contraté"})
    assert r.status_code == 200
    assert r.json()["family"] == "E04-A"


def test_classifier_routes_e02a(client):
    r = client.post("/api/cases", json={"message": "La factura de luz es incorrecta y me han cobrado de más"})
    assert r.status_code == 200
    assert r.json()["family"] == "E02-A"


def test_classifier_routes_e02b(client):
    r = client.post("/api/cases", json={"message": "Endesa me ha cobrado dos veces la misma factura de luz"})
    assert r.status_code == 200
    assert r.json()["family"] == "E02-B"


def test_e04a_end_to_end_and_claim(client):
    c = client.post("/api/cases", json={"message": "En la factura de luz me cobran un mantenimiento que nunca contraté"}).json()
    cid = c["id"]
    post_fact(client, cid, "electricity.addon.identity", "Protección Hogar")
    post_fact(client, cid, "electricity.addon.ever_contracted", False)
    client.post(f"/api/cases/{cid}/charges", json={"charges": [{"amount": 9.99, "evidence_verified": True}]})
    d = client.post(f"/api/cases/{cid}/diagnose")
    assert d.status_code == 200
    assert d.json()["viability"] == "HIGH"
    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200
    assert "66 quáter" in claim.json()["text"]


def test_e02a_end_to_end(client):
    c = client.post("/api/cases", json={"message": "La factura eléctrica me ha cobrado de más"}).json()
    cid = c["id"]
    post_fact(client, cid, "electricity.billing.invoice_date", "2026-07-01")
    post_fact(client, cid, "electricity.billing.billed_amount", 150)
    post_fact(client, cid, "electricity.billing.correct_amount", 100)
    d = client.post(f"/api/cases/{cid}/diagnose")
    assert d.status_code == 200
    assert d.json()["claimable_amount"] == 50
    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200
    assert "45.2" in claim.json()["text"]


def test_e02b_end_to_end(client):
    c = client.post("/api/cases", json={"message": "Me han cobrado dos veces la misma factura de luz"}).json()
    cid = c["id"]
    post_fact(client, cid, "electricity.billing.same_debt", True)
    client.post(f"/api/cases/{cid}/charges", json={"charges": [
        {"amount": 74.30, "evidence_verified": True},
        {"amount": 74.30, "evidence_verified": True},
    ]})
    d = client.post(f"/api/cases/{cid}/diagnose")
    assert d.status_code == 200
    assert d.json()["claimable_amount"] == 74.30
    claim = client.post(f"/api/cases/{cid}/prepare-claim")
    assert claim.status_code == 200
    assert "1895" in claim.json()["text"]


def test_user_fact_has_provenance_evidence(client):
    c = client.post("/api/cases", json={"message": "Me han cobrado dos veces la misma factura de luz"}).json()
    cid = c["id"]
    post_fact(client, cid, "electricity.billing.same_debt", True)
    body = client.get(f"/api/cases/{cid}").json()
    fact = next(f for f in body["facts"] if f["key"] == "electricity.billing.same_debt")
    assert any(e["fact_id"] == fact["id"] and e["source_type"] == "user" for e in body["evidence"])


def test_document_fact_confirmation_links_evidence(client):
    c = client.post("/api/cases", json={"message": "En la factura de luz me cobran un mantenimiento que nunca contraté"}).json()
    cid = c["id"]
    up = client.post(
        f"/api/cases/{cid}/documents",
        files={"file": ("factura.txt", b"Servicio mantenimiento 8,99 EUR", "text/plain")},
    )
    assert up.status_code == 200
    doc_id = up.json()["document_id"]
    r = client.post(f"/api/cases/{cid}/documents/{doc_id}/confirm-fact", json={
        "key": "electricity.addon.identity", "value": "Servicio mantenimiento", "locator": "linea 1", "excerpt": "Servicio mantenimiento 8,99 EUR"
    })
    assert r.status_code == 200
    body = client.get(f"/api/cases/{cid}").json()
    assert any(e["document_id"] == doc_id and e["fact_id"] == r.json()["fact_id"] for e in body["evidence"])


def test_legacy_diagnosis_creates_human_review(client):
    c = client.post("/api/cases", json={"message": "La factura de luz es incorrecta y me han cobrado de más"}).json()
    cid = c["id"]
    post_fact(client, cid, "electricity.billing.invoice_date", "2026-05-01")
    post_fact(client, cid, "electricity.billing.billed_amount", 150)
    post_fact(client, cid, "electricity.billing.correct_amount", 100)
    d = client.post(f"/api/cases/{cid}/diagnose")
    assert d.status_code == 200
    assert d.json()["scope_status"] == "LEGACY_REVIEW"
    reviews = client.get(f"/api/cases/{cid}/reviews").json()
    assert reviews and reviews[0]["status"] == "OPEN"
