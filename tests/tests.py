import base64
from urllib.parse import parse_qs, urlparse

from opentakserver.extensions import db
from opentakserver.models.Token import Token


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


def _extract_jwt_from_qr(qr_string):
    qs = parse_qs(urlparse(qr_string.replace("tak://", "http://")).query)
    return qs["token"][0]


def test_atak_qr_token_default_max_uses_1(auth):
    response = auth.client.post(
        "/api/atak_qr_string", headers=auth.headers, json={"username": "TestUser"}
    )
    assert response.status_code == 200
    assert response.json["success"] is True
    assert response.json["max"] == 1


def test_atak_qr_token_rejects_second_use(auth):
    response = auth.client.post(
        "/api/atak_qr_string", headers=auth.headers, json={"username": "TestUser"}
    )
    assert response.status_code == 200
    jwt_token = _extract_jwt_from_qr(response.json["qr_string"])

    with auth.client.application.app_context():
        assert Token.verify_token(jwt_token) is True
        assert Token.verify_token(jwt_token) is False
        assert db.session.query(Token).filter_by(username="TestUser").first() is None


def test_atak_qr_token_get_returns_404_when_exhausted(auth):
    post_response = auth.client.post(
        "/api/atak_qr_string", headers=auth.headers, json={"username": "TestUser"}
    )
    assert post_response.status_code == 200
    jwt_token = _extract_jwt_from_qr(post_response.json["qr_string"])

    with auth.client.application.app_context():
        assert Token.verify_token(jwt_token) is True

    get_response = auth.get("/api/atak_qr_string?username=TestUser")
    assert get_response.status_code == 404
