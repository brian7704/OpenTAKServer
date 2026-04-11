import logging

from authlib.integrations.flask_client import OAuth
from flask_oidc import OpenIDConnect
from werkzeug.utils import import_string


logger = logging.getLogger("OpenTAKServer")


def _normalize_optional_string(value):
    if value is None:
        return None

    value = str(value).strip()
    return value or None


def _derive_issuer_from_metadata_url(metadata_url):
    metadata_url = _normalize_optional_string(metadata_url)
    if not metadata_url:
        return None

    suffix = "/.well-known/openid-configuration"
    if metadata_url.endswith(suffix):
        issuer = metadata_url[: -len(suffix)].rstrip("/")
        return issuer or None

    return None


def _resolve_configured_issuer(app):
    issuer = _normalize_optional_string(app.config.get("OTS_OIDC_ISSUER"))
    if issuer:
        return issuer

    issuer = _derive_issuer_from_metadata_url(app.config.get("OTS_OIDC_METADATA_URL"))
    if issuer:
        return issuer

    oidc_client_secrets = app.config.get("OIDC_CLIENT_SECRETS") or {}
    if isinstance(oidc_client_secrets, dict):
        web_secrets = oidc_client_secrets.get("web") or {}
        if isinstance(web_secrets, dict):
            issuer = _normalize_optional_string(web_secrets.get("issuer"))
            if issuer:
                return issuer

    return None


def _build_client_registration(app):
    client_id = _normalize_optional_string(app.config.get("OTS_OIDC_CLIENT_ID"))
    client_secret = _normalize_optional_string(app.config.get("OTS_OIDC_CLIENT_SECRET"))
    metadata_url = _normalize_optional_string(app.config.get("OTS_OIDC_METADATA_URL"))

    client_kwargs = {"scope": app.config.get("OTS_OIDC_SCOPE")}

    use_pkce = bool(app.config.get("OTS_OIDC_USE_PKCE")) or not client_secret
    if use_pkce:
        pkce_method = _normalize_optional_string(app.config.get("OTS_OIDC_PKCE_METHOD")) or "S256"
        if pkce_method != "S256":
            raise RuntimeError("OTS_OIDC_PKCE_METHOD must be S256")

        client_kwargs["code_challenge_method"] = pkce_method
        if client_secret:
            logger.info("Enabling OIDC PKCE with %s", pkce_method)
        else:
            logger.info("Configuring OIDC as a public client with PKCE %s", pkce_method)

    registration = {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_kwargs": client_kwargs,
    }

    if metadata_url:
        logger.info("Using OIDC metadata URL: %s", metadata_url)
        registration["server_metadata_url"] = metadata_url
        return registration

    authorization_endpoint = _normalize_optional_string(app.config.get("OTS_OIDC_AUTHORIZATION_ENDPOINT"))
    token_endpoint = _normalize_optional_string(app.config.get("OTS_OIDC_TOKEN_ENDPOINT"))
    userinfo_endpoint = _normalize_optional_string(app.config.get("OTS_OIDC_USERINFO_ENDPOINT"))

    if not all([authorization_endpoint, token_endpoint, userinfo_endpoint]):
        raise RuntimeError(
            "OTS_ENABLE_OIDC is enabled but metadata or endpoint settings are missing. "
            "Configure OTS_OIDC_METADATA_URL or the per-endpoint URLs."
        )

    registration.update(
        {
            "authorize_url": authorization_endpoint,
            "access_token_url": token_endpoint,
            "userinfo_endpoint": userinfo_endpoint,
        }
    )
    return registration


def _build_client_secrets(app):
    issuer = _resolve_configured_issuer(app)
    if not issuer:
        raise RuntimeError(
            "OTS_ENABLE_OIDC is enabled but OTS_OIDC_ISSUER is not configured and could not be "
            "derived from OTS_OIDC_METADATA_URL."
        )

    return {
        "web": {
            "client_id": _normalize_optional_string(app.config.get("OTS_OIDC_CLIENT_ID")) or "",
            "client_secret": _normalize_optional_string(app.config.get("OTS_OIDC_CLIENT_SECRET"))
            or "",
            "issuer": issuer,
        }
    }


def _build_extension_config(app):
    if not _normalize_optional_string(app.config.get("OTS_OIDC_NAME")):
        raise RuntimeError("OTS_ENABLE_OIDC is enabled but OTS_OIDC_NAME is not configured")

    if not app.config.get("OTS_OIDC_CLIENT_ID") and not app.config.get("OTS_OIDC_METADATA_URL"):
        logger.warning(
            "OTS_OIDC_CLIENT_ID is empty. Public clients without client_id may fail for some providers."
        )

    registration = _build_client_registration(app)
    secrets = _build_client_secrets(app)
    token_endpoint_auth_method = "client_secret_post" if registration.get("client_secret") else "none"

    return {
        "OIDC_ENABLED": True,
        "OIDC_CLIENT_SECRETS": secrets,
        "OIDC_CLIENT_ID": secrets["web"]["client_id"],
        "OIDC_CLIENT_SECRET": secrets["web"]["client_secret"],
        "OIDC_SCOPES": app.config.get("OTS_OIDC_SCOPE"),
        "OIDC_USER_INFO_ENABLED": True,
        "OIDC_RESOURCE_SERVER_ONLY": True,
        "OIDC_INTROSPECTION_AUTH_METHOD": token_endpoint_auth_method,
        "OIDC_CLOCK_SKEW": 60,
        "OTS_OIDC_CLIENT_REGISTRATION": registration,
    }


class OpenTAKOIDCExtension(OpenIDConnect):
    def init_app(self, app, prefix=None):
        app.config.update(_build_extension_config(app))
        self.client_secrets = app.config["OIDC_CLIENT_SECRETS"]["web"]

        if "openid" not in app.config["OIDC_SCOPES"]:
            raise ValueError('The value "openid" must be in the OIDC_SCOPES')

        registration = dict(app.config["OTS_OIDC_CLIENT_REGISTRATION"])
        client_kwargs = dict(registration.get("client_kwargs") or {})
        client_kwargs.setdefault(
            "token_endpoint_auth_method", app.config["OIDC_INTROSPECTION_AUTH_METHOD"]
        )
        registration["client_kwargs"] = client_kwargs

        self.oauth = OAuth(app)
        self.oauth.register(name="oidc", update_token=self._update_token, **registration)

        app.config.setdefault("OIDC_USER_CLASS", "flask_oidc.model.User")
        if app.config["OIDC_USER_CLASS"]:
            app.extensions["_oidc_user_class"] = import_string(app.config["OIDC_USER_CLASS"])

        app.before_request(self._before_request)
