from unittest.mock import patch


def test_health_endpoints(auth):
    for endpoint in ("ots", "eud"):
        response = auth.get(f"/api/health/{endpoint}")
        assert response.status_code == 200


def test_health_cot_healthy(auth):
    with patch("opentakserver.health.cot_parser.query_systemd", return_value="active"), \
        patch(
            "opentakserver.health.cot_parser.tail_ots_log_for_cot_parser_entries",
            return_value=["all good"],
        ), \
        patch("opentakserver.health.cot_parser.find_errors", return_value=[]), \
        patch("opentakserver.health.cot_parser.rabbitmq_check", return_value=True):
        response = auth.get("/api/health/cot")
    assert response.status_code == 200
    data = response.json
    assert data["overall"] == "healthy"
    assert data["problems"] == []
    assert "timestamp" in data


def test_health_cot_unhealthy_strict(auth):
    with patch("opentakserver.health.cot_parser.query_systemd", return_value="inactive"), \
        patch(
            "opentakserver.health.cot_parser.tail_ots_log_for_cot_parser_entries",
            return_value=["error"],
        ), \
        patch("opentakserver.health.cot_parser.find_errors", return_value=["error"]), \
        patch("opentakserver.health.cot_parser.rabbitmq_check", return_value=False):
        response = auth.get("/api/health/cot?strict=true")
    assert response.status_code == 503
    data = response.json
    assert data["overall"] == "unhealthy"
    assert data["problems"]


def test_health_requires_auth(client):
    for endpoint in ("ots", "cot", "eud"):
        response = client.get(f"/api/health/{endpoint}")
        assert response.status_code in (401, 302)
