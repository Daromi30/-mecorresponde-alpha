from app.runtime_revision import normalize_runtime_revision


VALID_RUNTIME_REVISION = "0123456789abcdef0123456789abcdef01234567"


def test_health_exposes_full_valid_runtime_revision(client, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", VALID_RUNTIME_REVISION)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "mecorresponde-alpha"
    assert body["version"] == "0.5.0-alpha"
    assert body["families"] > 0
    assert body["runtime_revision"] == VALID_RUNTIME_REVISION


def test_health_uses_unknown_when_runtime_revision_is_absent(client, monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["runtime_revision"] == "unknown"


def test_health_uses_unknown_when_runtime_revision_is_invalid(client, monkeypatch):
    invalid_revision = "not-a-trustworthy-sha"
    monkeypatch.setenv("RENDER_GIT_COMMIT", invalid_revision)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["runtime_revision"] == "unknown"
    assert invalid_revision not in response.text


def test_shared_runtime_revision_normalization_for_health_and_startup():
    assert normalize_runtime_revision(VALID_RUNTIME_REVISION) == VALID_RUNTIME_REVISION
    assert normalize_runtime_revision(None) == "unknown"
    assert normalize_runtime_revision("invalid") == "unknown"


def test_database_health_endpoint(client):
    r = client.get('/health/db')
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'ok'
    assert body['database'] in {'sqlite', 'postgresql'}
    assert body['persistent'] is (body['database'] == 'postgresql')


def test_persistence_health_rejects_ephemeral_sqlite(client):
    r = client.get('/health/persistence')
    assert r.status_code == 503
    body = r.json()['detail']
    assert body['database'] == 'sqlite'
    assert body['persistent'] is False
