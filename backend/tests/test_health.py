def test_database_health_endpoint(client):
    r = client.get('/health/db')
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'ok'
    assert body['database'] in {'sqlite', 'postgresql'}
    assert body['persistent'] is (body['database'] == 'postgresql')
