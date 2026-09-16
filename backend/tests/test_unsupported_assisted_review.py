ADMIN = {"Authorization": "Bearer test-admin-token"}


def test_unclassified_problem_is_queued_for_assisted_review_instead_of_abandoned(client):
    response = client.post(
        "/api/cases",
        json={"message": "Mi comunidad de propietarios me reclama una derrama extraordinaria"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["family"] is None
    assert body["vertical"] is None
    assert body["status"] == "HUMAN_REVIEW"
    assert body["title"] == "Caso para revisión asistida"
    assert body["decisions"] == []
    assert len(body["human_reviews"]) == 1
    review = body["human_reviews"][0]
    assert review["reason"] == "UNSUPPORTED_CLASSIFICATION"
    assert review["status"] == "OPEN"

    queue = client.get("/api/admin/reviews?status=OPEN", headers=ADMIN)
    assert queue.status_code == 200, queue.text
    queued = next(item for item in queue.json() if item["id"] == review["id"])
    assert queued["case_id"] == body["id"]
    assert queued["case"]["status"] == "HUMAN_REVIEW"
    assert queued["case"]["family"] is None


def test_supported_problem_still_enters_its_automated_family_without_fallback_review(client):
    response = client.post(
        "/api/cases",
        json={"message": "Me han cambiado de compañía de luz sin mi consentimiento"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["family"] == "E03"
    assert body["status"] == "INTAKE"
    assert body["human_reviews"] == []
