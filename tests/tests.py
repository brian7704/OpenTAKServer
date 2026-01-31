import base64


def test_marti_api_clientendpoints(client):
    response = client.get("/Marti/api/clientEndPoints")
    assert response.status_code == 200


def test_mart_api_tls_config(auth):
    creds = base64.b64encode(b"TestUser:TestPass").decode("utf-8")
    response = auth.get(
        "/Marti/api/tls/config", headers={"Authorization": "Basic {}".format(creds)}
    )
    assert response.status_code == 200


def test_points(auth):
    response = auth.get("/api/point")
    assert response.status_code == 200


def test_me(auth):
    response = auth.get("/api/me")
    assert response.json["username"] == "TestUser"
