from importlib import import_module
from importlib import util
from pathlib import Path

import pytest

from opentakserver.extensions import db


def _load_oidc_module():
    module_path = Path(__file__).resolve().parents[1] / "opentakserver/blueprints/ots_api/oidc_api.py"
    spec = util.spec_from_file_location("test_oidc_blueprint", module_path)
    assert spec is not None
    module = util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None
    loader.exec_module(module)
    return module


oidc_api = _load_oidc_module()

_extract_roles = oidc_api._extract_roles
_extract_username = oidc_api._extract_username
_normalize_roles = oidc_api._normalize_roles
_sync_oidc_user = oidc_api._sync_oidc_user
_sanitize_next_url = oidc_api._sanitize_next_url


@pytest.fixture
def real_oidc_api(app):
    return import_module("opentakserver.blueprints.ots_api.oidc_api")


@pytest.fixture
def app_with_db(app):
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    db.init_app(app)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


class _MockOIDCClient:
    def __init__(self, token=None, fallback_userinfo=None, redirect_to="/idp/authorize"):
        self.token = token or {}
        self.fallback_userinfo = fallback_userinfo or {}
        self.redirect_to = redirect_to
        self.redirect_uri = None
        self.authorize_access_token_called = False
        self.userinfo_called = False

    def authorize_redirect(self, redirect_uri):
        self.redirect_uri = redirect_uri
        return ("", 302, {"Location": self.redirect_to})

    def authorize_access_token(self):
        self.authorize_access_token_called = True
        return self.token

    def userinfo(self, *args, **kwargs):
        self.userinfo_called = True
        return self.fallback_userinfo


@pytest.fixture
def client_with_db(app_with_db):
    with app_with_db.test_client() as client:
        yield client



def test_oidc_login_is_disabled(client):
    response = client.get("/api/oidc/login")

    assert response.status_code == 503
    assert response.json["success"] is False


def test_oidc_claim_helpers_extract_values(app):
    with app.app_context():
        app.config["OTS_OIDC_USERNAME_CLAIMS"] = "nested.name, email"
        app.config["OTS_OIDC_ROLE_CLAIM"] = "claims.roles"

        claims = {
            "nested": {"name": "sso-user"},
            "email": "sso-user@example.com",
            "claims": {"roles": "Admin,admin,operator"},
        }

        assert _extract_username(claims) == "sso.user"
        assert _extract_roles(claims) == ["Admin", "admin", "operator"]
        assert _normalize_roles([" Admin ", "admin", "", "Admin"]) == ["Admin"]


def test_oidc_extract_username_uses_normalized_email_claim(app):
    with app.app_context():
        app.config["OTS_OIDC_USERNAME_CLAIMS"] = "email"

        claims = {
            "email": "oidc.user+ops@example.com",
        }

        assert _extract_username(claims) == "oidc.user.ops.example.com"


def test_oidc_extract_username_rejects_unusable_claims(app):
    with app.app_context():
        app.config["OTS_OIDC_USERNAME_CLAIMS"] = "preferred_username"

        claims = {
            "preferred_username": "!!!",
        }

        assert _extract_username(claims) is None


def test_oidc_sync_user_rejects_missing_username_claim(app_with_db):
    app = app_with_db

    with app.app_context():
        app.config["OTS_OIDC_USERNAME_CLAIMS"] = "preferred_username2, upn2"
        synced = _sync_oidc_user({"iss": "https://issuer.example", "sub": "user-123"})

        assert synced is None


def test_oidc_sync_user_rejects_missing_issuer_identity(app_with_db):
    app = app_with_db

    with app.app_context():
        synced = _sync_oidc_user({"sub": "user-123", "preferred_username": "issuerless_user"})

        assert synced is None


def test_oidc_sync_user_binds_user_to_stable_oidc_identity(app_with_db):
    app = app_with_db

    with app.app_context():
        synced = _sync_oidc_user(
            {
                "iss": "https://issuer.example",
                "sub": "user-123",
                "preferred_username": "stable_user",
                "email": "stable-user@example.com",
            }
        )

        assert synced is not None
        assert synced.username == "stable_user"
        assert synced.email == "stable-user@example.com"
        assert synced.oidc_issuer == "https://issuer.example"
        assert synced.oidc_subject == "user-123"

        db.session.delete(synced)
        db.session.commit()


def test_oidc_sync_user_normalizes_username_from_email_claim(app_with_db):
    app = app_with_db

    with app.app_context():
        app.config["OTS_OIDC_USERNAME_CLAIMS"] = "email"

        synced = _sync_oidc_user(
            {
                "iss": "https://issuer.example",
                "sub": "user-456",
                "email": "oidc.user+ops@example.com",
            }
        )

        assert synced is not None
        assert synced.username == "oidc.user.ops.example.com"
        assert synced.email == "oidc.user+ops@example.com"

        db.session.delete(synced)
        db.session.commit()


def test_oidc_sync_user_rejects_username_collision_for_unlinked_local_user(app_with_db):
    app = app_with_db

    with app.app_context():
        existing_user = app.security.datastore.create_user(
            username="existing_user",
            email="original@example.com",
            password=None,
        )
        db.session.commit()

        synced = _sync_oidc_user(
            {
                "iss": "https://issuer.example",
                "sub": "user-123",
                "preferred_username": "existing_user",
            }
        )

        assert synced is None

        db.session.delete(existing_user)
        db.session.commit()


def test_oidc_sync_user_preserves_linked_username_and_updates_roles(app_with_db):
    app = app_with_db

    app.config["OTS_OIDC_DEFAULT_ROLES"] = "user"
    app.config["OTS_OIDC_ADMIN_ROLES"] = "administrator,global-admin"

    with app.app_context():
        user = app.security.datastore.create_user(
            username="existing_user",
            email="original@example.com",
            password=None,
            oidc_issuer="https://issuer.example",
            oidc_subject="user-123",
        )
        app.security.datastore.add_role_to_user(
            user,
            app.security.datastore.find_or_create_role("administrator"),
        )
        db.session.commit()

        synced = _sync_oidc_user(
            {
                "iss": "https://issuer.example",
                "sub": "user-123",
                "preferred_username": "renamed_user",
                "groups": ["admin", "user"],
            }
        )

        assert synced is not None
        role_names = {role.name for role in synced.roles}
        assert synced.username == "existing_user"
        assert synced.email == "original@example.com"
        assert role_names == {"admin", "user"}

        db.session.delete(synced)
        db.session.commit()


def test_oidc_sync_user_adds_administrator_role_for_mapped_groups(app_with_db):
    app = app_with_db

    with app.app_context():
        app.config["OTS_OIDC_DEFAULT_ROLES"] = "user"
        app.config["OTS_OIDC_ADMIN_ROLES"] = "global-admin"

        synced = _sync_oidc_user(
            {
                "iss": "https://issuer.example",
                "sub": "admin-user-123",
                "preferred_username": "admin_map_user",
                "email": "admin@example.com",
                "groups": ["global-admin", "operator"],
            }
        )

        assert synced is not None
        role_names = {role.name for role in synced.roles}
        assert "administrator" in role_names
        assert "global-admin" in role_names
        assert "operator" in role_names

        db.session.delete(synced)
        db.session.commit()


def test_oidc_login_redirects_to_provider_when_enabled(
    real_oidc_api, app_with_db, client_with_db, monkeypatch
):
    app = app_with_db
    app.config["OTS_ENABLE_OIDC"] = True

    mock_client = _MockOIDCClient(redirect_to="/idp/authorize")
    monkeypatch.setattr(real_oidc_api, "_get_oidc_client", lambda: mock_client)

    response = client_with_db.get("/api/oidc/login?return_json=True&next=/dashboard")

    assert response.status_code == 302
    assert response.headers["Location"] == "/idp/authorize"
    assert mock_client.redirect_uri == "http://localhost/api/oidc/callback"


def test_oidc_login_uses_forwarded_proto_for_callback_url(
    real_oidc_api, app_with_db, client_with_db, monkeypatch
):
    app = app_with_db
    app.config["OTS_ENABLE_OIDC"] = True

    mock_client = _MockOIDCClient(redirect_to="/idp/authorize")
    monkeypatch.setattr(real_oidc_api, "_get_oidc_client", lambda: mock_client)

    response = client_with_db.get(
        "/api/oidc/login",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "ots.example.com",
        },
    )

    assert response.status_code == 302
    assert mock_client.redirect_uri == "https://ots.example.com/api/oidc/callback"


def test_oidc_login_clears_stale_state_when_args_are_missing(
    real_oidc_api, app_with_db, client_with_db, monkeypatch
):
    app = app_with_db
    app.config["OTS_ENABLE_OIDC"] = True

    mock_client = _MockOIDCClient(redirect_to="/idp/authorize")
    monkeypatch.setattr(real_oidc_api, "_get_oidc_client", lambda: mock_client)

    with client_with_db.session_transaction() as session:
        session["ots_oidc_next"] = "/stale"
        session["ots_oidc_return_json"] = True

    response = client_with_db.get("/api/oidc/login")

    assert response.status_code == 302
    with client_with_db.session_transaction() as session:
        assert "ots_oidc_next" not in session
        assert session["ots_oidc_return_json"] is False


def test_oidc_next_url_is_sanitized():
    assert _sanitize_next_url("/dashboard") == "/dashboard"
    assert _sanitize_next_url("dashboard") == "/"
    assert _sanitize_next_url("https://malicious.example/callback") == "/"
    assert _sanitize_next_url("//malicious.example/callback") == "/"
    assert _sanitize_next_url("") == "/"
    assert _sanitize_next_url(None) == "/"


def test_oidc_login_stores_sanitized_next(real_oidc_api, app_with_db, client_with_db, monkeypatch):
    app = app_with_db
    app.config["OTS_ENABLE_OIDC"] = True

    mock_client = _MockOIDCClient(redirect_to="/idp/authorize")
    monkeypatch.setattr(real_oidc_api, "_get_oidc_client", lambda: mock_client)

    response = client_with_db.get("/api/oidc/login?next=https://malicious.example/callback")

    assert response.status_code == 302
    with client_with_db.session_transaction() as session:
        assert session["ots_oidc_next"] == "/"


def test_oidc_login_authorize_redirect_failure_returns_error(
    real_oidc_api, app_with_db, client_with_db, monkeypatch
):
    app = app_with_db
    app.config["OTS_ENABLE_OIDC"] = True

    class BrokenOIDCClient(_MockOIDCClient):
        def authorize_redirect(self, redirect_uri):  # type: ignore[override]
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(real_oidc_api, "_get_oidc_client", lambda: BrokenOIDCClient())

    with client_with_db.session_transaction() as session:
        session["ots_oidc_next"] = "/stale"
        session["ots_oidc_return_json"] = True

    response = client_with_db.get("/api/oidc/login")

    assert response.status_code == 500
    assert response.json["success"] is False
    assert response.json["error"] == "OIDC login failed"
    with client_with_db.session_transaction() as session:
        assert "ots_oidc_next" not in session
        assert "ots_oidc_return_json" not in session


def test_oidc_callback_token_exchange_failure_clears_temporary_state(
    real_oidc_api, client_with_db, app_with_db, monkeypatch
):
    app = app_with_db
    app.config["OTS_ENABLE_OIDC"] = True

    class BrokenOIDCClient(_MockOIDCClient):
        def authorize_access_token(self):  # type: ignore[override]
            raise RuntimeError("bad callback")

    monkeypatch.setattr(real_oidc_api, "_get_oidc_client", lambda: BrokenOIDCClient())

    with client_with_db.session_transaction() as session:
        session["ots_oidc_next"] = "/stale"
        session["ots_oidc_return_json"] = True

    response = client_with_db.get("/api/oidc/callback?code=test-code")

    assert response.status_code == 400
    assert response.json["success"] is False
    assert response.json["error"] == "Invalid OIDC callback"
    with client_with_db.session_transaction() as session:
        assert "ots_oidc_next" not in session
        assert "ots_oidc_return_json" not in session


def test_oidc_callback_rejects_provider_error_response(real_oidc_api, client_with_db, app_with_db, monkeypatch):
    app = app_with_db
    app.config["OTS_ENABLE_OIDC"] = True

    mock_client = _MockOIDCClient()
    monkeypatch.setattr(real_oidc_api, "_get_oidc_client", lambda: mock_client)

    with client_with_db.session_transaction() as session:
        session["ots_oidc_return_json"] = True

    response = client_with_db.get(
        "/api/oidc/callback?error=access_denied&error_description=user%20cancelled"
    )

    assert response.status_code == 400
    assert response.headers["Cache-Control"] == "no-store, no-cache, max-age=0, must-revalidate, private"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.json["success"] is False
    assert response.json["error"] == "OIDC provider rejected authentication"


def test_oidc_callback_rejects_missing_authorization_code(
    real_oidc_api, client_with_db, app_with_db, monkeypatch
):
    app = app_with_db
    app.config["OTS_ENABLE_OIDC"] = True

    mock_client = _MockOIDCClient()
    monkeypatch.setattr(real_oidc_api, "_get_oidc_client", lambda: mock_client)

    with client_with_db.session_transaction() as session:
        session["ots_oidc_return_json"] = True

    response = client_with_db.get("/api/oidc/callback")

    assert response.status_code == 400
    assert response.headers["Cache-Control"] == "no-store, no-cache, max-age=0, must-revalidate, private"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.json["success"] is False
    assert response.json["error"] == "Invalid OIDC callback"


def test_oidc_callback_hydrates_user_and_returns_json(
    real_oidc_api, client_with_db, app_with_db, monkeypatch
):
    app = app_with_db
    app.config["OTS_ENABLE_OIDC"] = True
    app.config["OTS_OIDC_DEFAULT_ROLES"] = "user"

    claims = {
        "iss": "https://issuer.example",
        "sub": "callback-user-123",
        "preferred_username": "callback_user",
        "email": "callback-user@example.com",
        "groups": ["operator", "admin"],
    }

    mock_client = _MockOIDCClient(token={"userinfo": claims})
    monkeypatch.setattr(real_oidc_api, "_get_oidc_client", lambda: mock_client)

    with client_with_db.session_transaction() as session:
        session["ots_oidc_return_json"] = True

    response = client_with_db.get("/api/oidc/callback?code=test-code")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, no-cache, max-age=0, must-revalidate, private"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    payload = response.json
    assert payload["success"] is True
    assert payload["identity_attributes"]["oidc"]["provider"] == "oidc"
    assert payload["username"] == "callback_user"
    assert payload["email"] == "callback-user@example.com"
    assert "token" not in payload

    role_names = {role["name"] for role in payload["roles"]}
    assert role_names == {"operator", "admin"}

    with client_with_db.session_transaction() as session:
        assert session["oidc_auth_token"]
        assert session["oidc_auth_profile"]["sub"] == "callback-user-123"

    with app.app_context():
        user = app.security.datastore.find_user(username="callback_user")
        assert user is not None
        assert user.oidc_issuer == "https://issuer.example"
        assert user.oidc_subject == "callback-user-123"


def test_oidc_callback_redirects_to_return_url(real_oidc_api, app_with_db, client_with_db, monkeypatch):
    app = app_with_db
    app.config["OTS_ENABLE_OIDC"] = True

    claims = {
        "iss": "https://issuer.example",
        "sub": "redirect-user-123",
        "preferred_username": "redirect_user",
        "email": "redirect-user@example.com",
        "groups": ["user"],
    }

    mock_client = _MockOIDCClient(token={"userinfo": claims})
    monkeypatch.setattr(real_oidc_api, "_get_oidc_client", lambda: mock_client)

    with client_with_db.session_transaction() as session:
        session["ots_oidc_next"] = "/dashboard"

    response = client_with_db.get("/api/oidc/callback?code=test-code", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/dashboard"
    assert response.headers["Cache-Control"] == "no-store, no-cache, max-age=0, must-revalidate, private"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_oidc_callback_can_include_auth_token_when_explicitly_enabled(
    real_oidc_api, client_with_db, app_with_db, monkeypatch
):
    app = app_with_db
    app.config["OTS_ENABLE_OIDC"] = True
    app.config["OTS_OIDC_INCLUDE_AUTH_TOKEN_IN_CALLBACK_JSON"] = True

    claims = {
        "iss": "https://issuer.example",
        "sub": "token-user-123",
        "preferred_username": "token_user",
        "email": "token-user@example.com",
        "groups": ["user"],
    }

    mock_client = _MockOIDCClient(token={"userinfo": claims})
    monkeypatch.setattr(real_oidc_api, "_get_oidc_client", lambda: mock_client)

    with client_with_db.session_transaction() as session:
        session["ots_oidc_return_json"] = True

    response = client_with_db.get("/api/oidc/callback?code=test-code")

    assert response.status_code == 200
    payload = response.json
    assert payload["success"] is True
    assert payload["username"] == "token_user"
    assert "token" in payload
    assert payload["token"]


def test_oidc_callback_returns_error_when_login_user_fails(
    real_oidc_api, client_with_db, app_with_db, monkeypatch
):
    app = app_with_db
    app.config["OTS_ENABLE_OIDC"] = True

    claims = {
        "iss": "https://issuer.example",
        "sub": "login-fail-user-123",
        "preferred_username": "login_fail_user",
        "email": "login-fail-user@example.com",
        "groups": ["user"],
    }

    mock_client = _MockOIDCClient(token={"userinfo": claims})
    monkeypatch.setattr(real_oidc_api, "_get_oidc_client", lambda: mock_client)
    monkeypatch.setattr(real_oidc_api, "login_user", lambda *args, **kwargs: False)

    with client_with_db.session_transaction() as session:
        session["ots_oidc_return_json"] = True

    response = client_with_db.get("/api/oidc/callback?code=test-code")

    assert response.status_code == 403
    assert response.headers["Cache-Control"] == "no-store, no-cache, max-age=0, must-revalidate, private"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.json["success"] is False
    assert response.json["error"] == "Failed to establish OIDC session"


def test_oidc_callback_fetches_userinfo_when_token_missing(
    real_oidc_api, client_with_db, app_with_db, monkeypatch
):
    app = app_with_db
    app.config["OTS_ENABLE_OIDC"] = True
    app.config["OTS_OIDC_DEFAULT_ROLES"] = "user"

    claims = {
        "iss": "https://issuer.example",
        "sub": "userinfo-user-123",
        "preferred_username": "userinfo_user",
        "email": "userinfo-user@example.com",
    }

    mock_client = _MockOIDCClient(token={"access_token": "tok"}, fallback_userinfo=claims)
    monkeypatch.setattr(real_oidc_api, "_get_oidc_client", lambda: mock_client)

    with client_with_db.session_transaction() as session:
        session["ots_oidc_return_json"] = True

    response = client_with_db.get("/api/oidc/callback?code=test-code")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, no-cache, max-age=0, must-revalidate, private"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    payload = response.json
    assert payload["success"] is True
    assert payload["username"] == "userinfo_user"
    assert payload["email"] == "userinfo-user@example.com"
    assert "token" not in payload

    role_names = {role["name"] for role in payload["roles"]}
    assert role_names == {"user"}

    assert mock_client.authorize_access_token_called is True
    assert mock_client.userinfo_called is True


@pytest.fixture
def app_module():
    return import_module("opentakserver.app")


@pytest.fixture
def oidc_module():
    return import_module("opentakserver.oidc")


def test_app_can_start_without_oidc_configuration(app_module, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module.DefaultConfig, "OTS_DATA_FOLDER", str(tmp_path))
    (tmp_path / "config.yml").write_text("OTS_ENABLE_OIDC: false\nSQLALCHEMY_DATABASE_URI: sqlite://\n")

    app = app_module.create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.get("/api/oidc/login")

    assert response.status_code == 503
    assert response.json["success"] is False
    assert response.json["error"] == "OIDC is not enabled"


def test_build_oidc_client_registration_enables_pkce_for_public_client(app, oidc_module):
    app.config.update(
        {
            "OTS_OIDC_CLIENT_ID": "public-client",
            "OTS_OIDC_CLIENT_SECRET": "",
            "OTS_OIDC_METADATA_URL": "https://issuer.example/.well-known/openid-configuration",
            "OTS_OIDC_SCOPE": "openid profile email",
            "OTS_OIDC_USE_PKCE": False,
        }
    )

    registration = oidc_module._build_client_registration(app)

    assert registration["client_id"] == "public-client"
    assert registration["client_secret"] is None
    assert (
        registration["server_metadata_url"]
        == "https://issuer.example/.well-known/openid-configuration"
    )
    assert registration["client_kwargs"]["scope"] == "openid profile email"
    assert registration["client_kwargs"]["code_challenge_method"] == "S256"


def test_build_oidc_client_registration_can_enable_pkce_for_confidential_client(app, oidc_module):
    app.config.update(
        {
            "OTS_OIDC_CLIENT_ID": "confidential-client",
            "OTS_OIDC_CLIENT_SECRET": "super-secret",
            "OTS_OIDC_METADATA_URL": "https://issuer.example/.well-known/openid-configuration",
            "OTS_OIDC_SCOPE": "openid profile email",
            "OTS_OIDC_USE_PKCE": True,
            "OTS_OIDC_PKCE_METHOD": "S256",
        }
    )

    registration = oidc_module._build_client_registration(app)

    assert registration["client_secret"] == "super-secret"
    assert registration["client_kwargs"]["code_challenge_method"] == "S256"


@pytest.mark.parametrize("pkce_method", ["plain", "s256", "S512"])
def test_build_oidc_client_registration_rejects_invalid_pkce_method(app, oidc_module, pkce_method):
    app.config.update(
        {
            "OTS_OIDC_CLIENT_ID": "public-client",
            "OTS_OIDC_CLIENT_SECRET": "",
            "OTS_OIDC_METADATA_URL": "https://issuer.example/.well-known/openid-configuration",
            "OTS_OIDC_SCOPE": "openid profile email",
            "OTS_OIDC_USE_PKCE": True,
            "OTS_OIDC_PKCE_METHOD": pkce_method,
        }
    )

    with pytest.raises(RuntimeError, match="OTS_OIDC_PKCE_METHOD must be S256"):
        oidc_module._build_client_registration(app)


def test_build_oidc_client_registration_supports_manual_endpoints(app, oidc_module):
    app.config.update(
        {
            "OTS_OIDC_CLIENT_ID": "public-client",
            "OTS_OIDC_CLIENT_SECRET": "",
            "OTS_OIDC_METADATA_URL": "",
            "OTS_OIDC_SCOPE": "openid profile email",
            "OTS_OIDC_AUTHORIZATION_ENDPOINT": "https://issuer.example/authorize",
            "OTS_OIDC_TOKEN_ENDPOINT": "https://issuer.example/token",
            "OTS_OIDC_USERINFO_ENDPOINT": "https://issuer.example/userinfo",
        }
    )

    registration = oidc_module._build_client_registration(app)

    assert registration["authorize_url"] == "https://issuer.example/authorize"
    assert registration["access_token_url"] == "https://issuer.example/token"
    assert registration["userinfo_endpoint"] == "https://issuer.example/userinfo"
    assert registration["client_kwargs"]["code_challenge_method"] == "S256"


def test_build_oidc_client_secrets_uses_configured_issuer(app, oidc_module):
    app.config.update(
        {
            "OTS_OIDC_NAME": "main-oidc",
            "OTS_OIDC_CLIENT_ID": "public-client",
            "OTS_OIDC_CLIENT_SECRET": "",
            "OTS_OIDC_ISSUER": "https://issuer.example",
        }
    )

    secrets = oidc_module._build_client_secrets(app)

    assert secrets == {
        "web": {
            "client_id": "public-client",
            "client_secret": "",
            "issuer": "https://issuer.example",
        }
    }


def test_build_oidc_client_secrets_can_derive_issuer_from_metadata_url(app, oidc_module):
    app.config.update(
        {
            "OTS_OIDC_NAME": "main-oidc",
            "OTS_OIDC_CLIENT_ID": "public-client",
            "OTS_OIDC_CLIENT_SECRET": "",
            "OTS_OIDC_ISSUER": "",
            "OTS_OIDC_METADATA_URL": "https://issuer.example/.well-known/openid-configuration",
        }
    )

    secrets = oidc_module._build_client_secrets(app)

    assert secrets["web"]["issuer"] == "https://issuer.example"


def test_resolve_configured_issuer_can_use_internal_oidc_client_secrets(app, oidc_module):
    app.config.update(
        {
            "OTS_OIDC_ISSUER": "",
            "OTS_OIDC_METADATA_URL": "",
            "OIDC_CLIENT_SECRETS": {"web": {"issuer": "https://issuer.example"}},
        }
    )

    assert oidc_module._resolve_configured_issuer(app) == "https://issuer.example"


def test_build_oidc_client_secrets_requires_real_issuer(app, oidc_module):
    app.config.update(
        {
            "OTS_OIDC_NAME": "main-oidc",
            "OTS_OIDC_CLIENT_ID": "public-client",
            "OTS_OIDC_CLIENT_SECRET": "",
            "OTS_OIDC_ISSUER": "",
            "OTS_OIDC_METADATA_URL": "",
        }
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "OTS_ENABLE_OIDC is enabled but OTS_OIDC_ISSUER is not configured and could not be "
            "derived from OTS_OIDC_METADATA_URL."
        ),
    ):
        oidc_module._build_client_secrets(app)


def test_init_oidc_calls_extension_init_app(app, app_module, monkeypatch):
    class FakeOIDC:
        def __init__(self):
            self.init_app_called = False

        def init_app(self, flask_app):
            self.init_app_called = True

    fake_oidc = FakeOIDC()
    monkeypatch.setattr(app_module, "oidc", fake_oidc)

    app.config.update(
        {
            "OTS_ENABLE_OIDC": True,
            "OTS_OIDC_NAME": "main-oidc",
            "OTS_OIDC_CLIENT_ID": "public-client",
            "OTS_OIDC_CLIENT_SECRET": "",
            "OTS_OIDC_METADATA_URL": "https://issuer.example/.well-known/openid-configuration",
            "OTS_OIDC_SCOPE": "openid profile email",
        }
    )

    app_module._init_oidc(app)

    assert fake_oidc.init_app_called is True


def test_oidc_extension_init_app_populates_internal_oidc_settings(app, oidc_module):
    extension = oidc_module.OpenTAKOIDCExtension()
    app.config.update(
        {
            "OTS_OIDC_NAME": "main-oidc",
            "OTS_OIDC_CLIENT_ID": "public-client",
            "OTS_OIDC_CLIENT_SECRET": "",
            "OTS_OIDC_METADATA_URL": "https://issuer.example/.well-known/openid-configuration",
            "OTS_OIDC_SCOPE": "openid profile email",
        }
    )

    extension.init_app(app)

    assert app.config["OIDC_ENABLED"] is True
    assert app.config["OIDC_RESOURCE_SERVER_ONLY"] is True
    assert app.config["OIDC_SCOPES"] == "openid profile email"
    assert app.config["OIDC_INTROSPECTION_AUTH_METHOD"] == "none"
    assert app.config["OIDC_CLIENT_SECRETS"]["web"]["issuer"] == "https://issuer.example"
    assert app.config["OTS_OIDC_CLIENT_REGISTRATION"]["client_kwargs"]["code_challenge_method"] == "S256"



def _load_defaultconfig_module():
    module_path = Path(__file__).resolve().parents[1] / "opentakserver/defaultconfig.py"
    spec = util.spec_from_file_location("test_defaultconfig_module", module_path)
    assert spec is not None
    module = util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None
    loader.exec_module(module)
    return module


def test_defaultconfig_disables_oidc_by_default(monkeypatch):
    monkeypatch.delenv("OTS_ENABLE_OIDC", raising=False)

    module = _load_defaultconfig_module()
    cfg = module.DefaultConfig

    assert cfg.OTS_ENABLE_OIDC is False


def test_create_app_defaults_oidc_to_disabled(app):
    assert app.config["OTS_ENABLE_OIDC"] is False


def test_defaultconfig_reads_oidc_claim_and_role_mapping_from_env(monkeypatch):
    monkeypatch.setenv("OTS_OIDC_USERNAME_CLAIMS", "preferred_username,email")
    monkeypatch.setenv("OTS_OIDC_EMAIL_CLAIM", "mail")
    monkeypatch.setenv("OTS_OIDC_ROLE_CLAIM", "realm_access.roles")
    monkeypatch.setenv("OTS_OIDC_ADMIN_ROLES", "global-admin,ots-admin")
    monkeypatch.setenv("OTS_OIDC_DEFAULT_ROLES", "viewer")

    module = _load_defaultconfig_module()
    cfg = module.DefaultConfig

    assert cfg.OTS_OIDC_USERNAME_CLAIMS == "preferred_username,email"
    assert cfg.OTS_OIDC_EMAIL_CLAIM == "mail"
    assert cfg.OTS_OIDC_ROLE_CLAIM == "realm_access.roles"
    assert cfg.OTS_OIDC_ADMIN_ROLES == "global-admin,ots-admin"
    assert cfg.OTS_OIDC_DEFAULT_ROLES == "viewer"


def test_defaultconfig_oidc_claim_and_role_mapping_defaults_when_env_absent(monkeypatch):
    for key in [
        "OTS_OIDC_USERNAME_CLAIMS",
        "OTS_OIDC_EMAIL_CLAIM",
        "OTS_OIDC_ROLE_CLAIM",
        "OTS_OIDC_ADMIN_ROLES",
        "OTS_OIDC_DEFAULT_ROLES",
    ]:
        monkeypatch.delenv(key, raising=False)

    module = _load_defaultconfig_module()
    cfg = module.DefaultConfig

    assert cfg.OTS_OIDC_USERNAME_CLAIMS == "preferred_username, upn, email, sub"
    assert cfg.OTS_OIDC_EMAIL_CLAIM == "email"
    assert cfg.OTS_OIDC_ROLE_CLAIM == "groups"
    assert cfg.OTS_OIDC_ADMIN_ROLES == "administrator"
    assert cfg.OTS_OIDC_DEFAULT_ROLES == "user"
