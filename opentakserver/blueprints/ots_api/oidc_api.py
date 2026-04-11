import unicodedata
from urllib.parse import urlparse

from flask import Blueprint
from flask import current_app as app
from flask import jsonify, redirect, request, session, url_for
from flask_security import login_user

from opentakserver.UsernameValidator import UsernameValidator
from opentakserver.extensions import logger, oidc
from opentakserver.oidc import _resolve_configured_issuer


oidc_blueprint = Blueprint("oidc_blueprint", __name__)


def _to_bool(value):
    return str(value).lower() in ["true", "1", "yes", "on"]


def _as_list(value):
    if not value:
        return []

    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]

    return [item.strip() for item in str(value).split(",") if item.strip()]


def _sanitize_next_url(value, default="/"):
    if not value:
        return default

    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return default

    if not value.startswith("/"):
        return default

    if value.startswith("//"):
        return default

    return value


def _read_claim(data, claim):
    if not claim or not isinstance(data, dict):
        return None

    value = data
    for key in claim.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
        if value is None:
            return None

    return value


def _read_string_claim(data, claim):
    value = _read_claim(data, claim)
    if value is None:
        return None

    value = str(value).strip()
    return value or None


def _read_configured_string_claim(claims, config_key, default_claim):
    return _read_string_claim(claims, app.config.get(config_key, default_claim))


def _iter_configured_string_claims(claims, config_key, default_claims):
    for claim in _as_list(app.config.get(config_key, default_claims)):
        value = _read_string_claim(claims, claim)
        if value:
            yield claim, value


def _get_oidc_client():
    if not app.config.get("OTS_ENABLE_OIDC") or oidc is None:
        return None

    oauth = getattr(oidc, "oauth", None)
    if oauth is None:
        return None

    return getattr(oauth, "oidc", None)


def _get_callback_url():
    callback = app.config.get("OTS_OIDC_REDIRECT_URI", "/api/oidc/callback")
    if callback.startswith("http://") or callback.startswith("https://"):
        return callback

    if callback.startswith("/"):
        return f"{request.host_url.rstrip('/')}{callback}"

    return url_for(".oidc_callback", _external=True)


def _extract_issuer(claims):
    return _read_configured_string_claim(claims, "OTS_OIDC_ISSUER_CLAIM", "iss") or _resolve_configured_issuer(app)


def _extract_subject(claims):
    return _read_configured_string_claim(claims, "OTS_OIDC_SUBJECT_CLAIM", "sub")


def _extract_oidc_identity(claims):
    return _extract_issuer(claims), _extract_subject(claims)


def _iter_username_claim_values(claims):
    yield from _iter_configured_string_claims(
        claims,
        "OTS_OIDC_USERNAME_CLAIMS",
        "preferred_username, sub",
    )


def _normalize_username_candidate(value):
    if value is None:
        return None

    raw_username = str(value).strip()
    if not raw_username:
        return None

    username_validator = UsernameValidator(app)
    error, normalized_username = username_validator.validate(raw_username)
    if not error and normalized_username:
        return normalized_username

    safe_username = []
    last_was_separator = False
    for character in raw_username:
        if unicodedata.category(character)[0] in ["L", "N"] or character in ["_", "."]:
            safe_character = character
        else:
            safe_character = "."

        if safe_character == ".":
            if last_was_separator:
                continue
            last_was_separator = True
        else:
            last_was_separator = False

        safe_username.append(safe_character)

    fallback_username = "".join(safe_username).strip("._")
    if not fallback_username:
        return None

    fallback_error, fallback_normalized_username = username_validator.validate(fallback_username)
    if fallback_error or not fallback_normalized_username:
        return None

    logger.warning(
        "Normalized OIDC username %s to local username %s",
        raw_username,
        fallback_normalized_username,
    )
    return fallback_normalized_username


def _extract_username(claims):
    for claim, raw_username in _iter_username_claim_values(claims):
        username = _normalize_username_candidate(raw_username)
        if username:
            return username

        logger.warning(
            "OIDC username claim %s could not be normalized into a valid local username",
            claim,
        )

    return None


def _extract_email(claims):
    return _read_configured_string_claim(claims, "OTS_OIDC_EMAIL_CLAIM", "email")


def _extract_roles(claims):
    role_claim = _read_claim(claims, app.config.get("OTS_OIDC_ROLE_CLAIM", "groups"))
    if role_claim is None:
        return []

    if isinstance(role_claim, (list, tuple, set)):
        return [str(role).strip() for role in role_claim if str(role).strip()]

    if isinstance(role_claim, dict):
        return [str(key).strip() for key in role_claim.keys() if str(key).strip()]

    return [item.strip() for item in str(role_claim).split(",") if item.strip()]


def _normalize_roles(roles):
    normalized = []
    seen = set()
    for role in roles:
        normalized_role = str(role).strip()
        normalized_role_key = normalized_role.lower()

        if not normalized_role or normalized_role_key in seen:
            continue

        normalized.append(normalized_role)
        seen.add(normalized_role_key)

    return normalized


def _resolve_oidc_roles(claims):
    roles = _extract_roles(claims)
    if not roles:
        roles = _as_list(app.config.get("OTS_OIDC_DEFAULT_ROLES", "user"))

    admin_roles = {role.lower() for role in _as_list(app.config.get("OTS_OIDC_ADMIN_ROLES"))}
    if admin_roles.intersection({role.lower() for role in roles}):
        roles.append("administrator")

    roles = _normalize_roles(roles)
    if roles:
        return roles

    return _normalize_roles(_as_list(app.config.get("OTS_OIDC_DEFAULT_ROLES", "user")))


def _apply_roles_to_user(user, roles):
    for role in list(user.roles):
        app.security.datastore.remove_role_from_user(user, role)

    for role_name in roles:
        role = app.security.datastore.find_or_create_role(role_name)
        app.security.datastore.add_role_to_user(user, role)


def _apply_no_store_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _oidc_error_response(message, status_code, log_message=None, level="warning"):
    if log_message:
        getattr(logger, level)(log_message)

    return _apply_no_store_headers(jsonify({"success": False, "error": message})), status_code


def _build_oidc_callback_payload(user):
    payload = user.serialize()
    payload["success"] = True
    payload["identity_attributes"] = {
        "oidc": {
            "provider": app.config.get("OTS_OIDC_NAME", "oidc"),
        }
    }

    if _to_bool(app.config.get("OTS_OIDC_INCLUDE_AUTH_TOKEN_IN_CALLBACK_JSON", False)):
        payload["token"] = user.get_auth_token()

    return payload


def _find_linked_oidc_user(issuer, subject):
    return app.security.datastore.find_user(oidc_issuer=issuer, oidc_subject=subject)


def _create_oidc_user(username, email, issuer, subject):
    create_kwargs = {
        "username": username,
        "password": None,
        "oidc_issuer": issuer,
        "oidc_subject": subject,
    }
    if email:
        create_kwargs["email"] = email

    return app.security.datastore.create_user(**create_kwargs)


def _update_oidc_user_profile(user, username, email, subject):
    if user.username != username:
        logger.warning(
            "OIDC username claim changed for linked subject %s; keeping local username %s",
            subject,
            user.username,
        )

    if email and user.email != email:
        user.email = email


def _resolve_or_create_oidc_user(issuer, subject, username, email):
    user = _find_linked_oidc_user(issuer, subject)
    if not user:
        existing_user = app.security.datastore.find_user(username=username)
        if existing_user:
            logger.error("OIDC username collision for %s", username)
            return None

        return _create_oidc_user(username, email, issuer, subject)

    _update_oidc_user_profile(user, username, email, subject)
    return user


def _sync_oidc_user(claims):
    issuer, subject = _extract_oidc_identity(claims)
    if not issuer or not subject:
        logger.error("OIDC callback did not include a stable issuer/subject identity")
        return None

    username = _extract_username(claims)
    if not username:
        logger.error("OIDC callback did not include a usable username claim")
        return None

    email = _extract_email(claims)

    user = _resolve_or_create_oidc_user(issuer, subject, username, email)
    if not user:
        return None

    _apply_roles_to_user(user, _resolve_oidc_roles(claims))
    app.security.datastore.commit()
    return user


def _clear_oidc_flow_state():
    session.pop("ots_oidc_next", None)
    session.pop("ots_oidc_return_json", None)


def _pop_oidc_flow_state():
    return (
        _to_bool(session.pop("ots_oidc_return_json", False)),
        _sanitize_next_url(session.pop("ots_oidc_next", "/")),
    )


def _fetch_oidc_userinfo(client, token):
    try:
        return client.userinfo(token=token)
    except TypeError:
        return client.userinfo()


def _store_flask_oidc_session(token, claims):
    session["oidc_auth_token"] = token if isinstance(token, dict) else {}
    session["oidc_auth_profile"] = claims


def _fetch_oidc_claims(client):
    try:
        token = client.authorize_access_token()
    except Exception as e:
        return None, _oidc_error_response(
            "Invalid OIDC callback",
            400,
            log_message=f"OIDC token exchange failed: {e}",
            level="warning",
        )

    claims = token.get("userinfo") if isinstance(token, dict) else None
    if claims:
        if isinstance(claims, dict):
            _store_flask_oidc_session(token, claims)
            return claims, None
        return None, _oidc_error_response(
            "Invalid OIDC user info",
            400,
            log_message="OIDC user info payload was not a JSON object",
            level="warning",
        )

    try:
        claims = _fetch_oidc_userinfo(client, token)
    except Exception as e:
        return None, _oidc_error_response(
            "Failed to fetch OIDC user info",
            400,
            log_message=f"Failed to read OIDC user info: {e}",
            level="warning",
        )

    if not isinstance(claims, dict):
        return None, _oidc_error_response(
            "Invalid OIDC user info",
            400,
            log_message="OIDC user info payload was not a JSON object",
            level="warning",
        )

    _store_flask_oidc_session(token, claims)
    return claims, None


def _complete_oidc_login(user):
    remember = bool(app.config.get("SECURITY_DEFAULT_REMEMBER_ME", False))
    if login_user(user, remember=remember, authn_via=["oidc"]):
        return None

    return _oidc_error_response(
        "Failed to establish OIDC session",
        403,
        log_message=f"OIDC login_user failed for {user.username}",
        level="error",
    )


def _build_oidc_success_response(user, return_json, next_url):
    payload = _build_oidc_callback_payload(user)
    if return_json:
        return _apply_no_store_headers(jsonify(payload))

    return _apply_no_store_headers(redirect(next_url))


@oidc_blueprint.route("/api/oidc/login", methods=["GET"])
def oidc_login():
    if not app.config.get("OTS_ENABLE_OIDC"):
        return jsonify({"success": False, "error": "OIDC is not enabled"}), 503

    client = _get_oidc_client()
    if not client:
        return jsonify({"success": False, "error": "OIDC client is not configured"}), 503

    _clear_oidc_flow_state()

    next_url = request.args.get("next")
    if next_url:
        session["ots_oidc_next"] = _sanitize_next_url(next_url)

    session["ots_oidc_return_json"] = _to_bool(request.args.get("return_json", "False"))

    try:
        return client.authorize_redirect(_get_callback_url())
    except Exception as e:
        logger.error(f"OIDC authorize redirect failed: {e}")
        _clear_oidc_flow_state()
        return jsonify({"success": False, "error": "OIDC login failed"}), 500


@oidc_blueprint.route("/api/oidc/callback", methods=["GET"])
def oidc_callback():
    return_json, next_url = _pop_oidc_flow_state()

    if not app.config.get("OTS_ENABLE_OIDC"):
        return _oidc_error_response("OIDC is not enabled", 503)

    client = _get_oidc_client()
    if not client:
        return _oidc_error_response("OIDC client is not configured", 503)

    provider_error = request.args.get("error")
    if provider_error:
        provider_error_description = request.args.get("error_description", "")
        log_message = f"OIDC provider returned error={provider_error!r}"
        if provider_error_description:
            log_message += f", description={provider_error_description!r}"
        return _oidc_error_response(
            "OIDC provider rejected authentication",
            400,
            log_message=log_message,
            level="warning",
        )

    if not request.args.get("code"):
        return _oidc_error_response(
            "Invalid OIDC callback",
            400,
            log_message="OIDC callback missing authorization code",
            level="warning",
        )

    claims, error_response = _fetch_oidc_claims(client)
    if error_response:
        return error_response

    user = _sync_oidc_user(claims)
    if not user:
        return _oidc_error_response(
            "Failed to sync OIDC user",
            400,
            log_message="OIDC user synchronization failed",
            level="warning",
        )

    error_response = _complete_oidc_login(user)
    if error_response:
        return error_response

    return _build_oidc_success_response(user, return_json, next_url)
