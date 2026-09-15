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
