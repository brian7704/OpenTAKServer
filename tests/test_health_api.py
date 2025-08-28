def test_health_endpoints(auth):
    for endpoint in ("ots", "cot", "eud"):
        response = auth.get(f"/api/health/{endpoint}")
        assert response.status_code == 200


def test_health_requires_auth(client):
    for endpoint in ("ots", "cot", "eud"):
        response = client.get(f"/api/health/{endpoint}")
        assert response.status_code in (401, 302)
