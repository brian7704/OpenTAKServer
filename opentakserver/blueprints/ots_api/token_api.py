import datetime
import os
import time
import traceback
from urllib.parse import urlparse

import bleach
import jwt
from flask import jsonify, request, current_app as app, Blueprint
from flask_babel import gettext
from flask_ldap3_login import AuthenticationResponseStatus
from flask_login import current_user
from flask_security import auth_required, verify_password
from sqlalchemy import delete

from opentakserver.extensions import db, logger, ldap_manager
from opentakserver.models.Token import Token
from opentakserver.models.user import User

token_api_blueprint = Blueprint('token_api_blueprint', __name__)


@token_api_blueprint.route("/oauth/token", methods=['GET', 'POST'])
def cloudtak_oauth_token():
    """
    Provides an OAuth token for TAKX and CloudTAK

    :param username:
    :param password:

    :return: jwt
    """

    username = bleach.clean(request.args.get("username"))
    password = bleach.clean(request.args.get("password"))

    if app.config.get("OTS_ENABLE_LDAP"):
        result = ldap_manager.authenticate(username, password)

        if result.status == AuthenticationResponseStatus.success:
            # Keep this import here to avoid a circular import when OTS is started
            from opentakserver.blueprints.ots_api.ldap_api import save_user

            save_user(result.user_dn, result.user_id, result.user_info, result.user_groups)

        else:
            return jsonify({'success': False, 'error': 'Invalid username or password'}), 400

    else:
        user = app.security.datastore.find_user(username=username)
        if not user or not verify_password(password, user.password):
            return jsonify({'success': False, 'error': 'Invalid username or password'}), 400

    with open(os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", "opentakserver", "opentakserver.nopass.key"),
              "rb") as key:
        token = jwt.encode({
            "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365),
            "nbf": datetime.datetime.now(datetime.timezone.utc),
            "iss": "OpenTAKServer",
            "aud": "OpenTAKServer",
            "iat": datetime.datetime.now(datetime.timezone.utc),
            "sub": user.username
        }, key.read(), algorithm="RS256")

        return jsonify({"access_token": token, "token_type": "Bearer", "expires_in": 365 * 24 * 60 * 60})


@token_api_blueprint.route("/api/atak_qr_string", methods=['POST'])
@auth_required()
def new_atak_qr_string():
    """
    Generates a QR string for ATAK certificate enrollment. ATAK certificate enrollment via QR code
    only works if your server has a Let's Encrypt certificate. Params are sent as JSON.

    :param username:
    :param exp: The expiration time in unix epoch seconds i.e.1764260510
    :param nbf: Not Before, the token will not be valid until this date in unix epoch seconds.
    :param max: The maximum number of uses for this token.

    :return: String in the format of tak://com.atakmap.app/enroll?host=server_address.com&username=your_username&token=jwt_token
    """
    try:
        username = request.json.get("username") or current_user.username
        if username != current_user.username and not current_user.has_role("administrator"):
            return jsonify({'success': False, 'error': 'Cannot generate QR for another user'}), 401

        else:
            if username != current_user.username and current_user.has_role("administrator"):
                user = db.session.query(User).filter_by(username=username).first()
                if not user:
                    return jsonify({'success': False, 'error': f"No such user: {username}"}), 404

            token = db.session.execute(db.session.query(Token).filter_by(username=username)).first()
            if token:
                token = token[0]
            else:
                token = Token()
                token.creation = int(time.time())

            expiration = int(request.json.get("exp")) if request.json.get("exp") else None
            # PyJWT uses timestamps in seconds to check expiration and not_before
            # This makes sure these timestamps are in seconds and not milliseconds
            # TODO: Fix this before January 19, 2038 03:14:07Z
            if expiration and expiration > 2147483647:
                token.expiration = expiration / 1000
            elif expiration:
                token.expiration = expiration

            not_before = int(request.json.get("nbf")) if request.json.get("nbf") else None
            if not_before and not_before > 2147483647:
                token.not_before = not_before / 1000
            elif not_before:
                token.not_before = not_before

            if request.json.get("max"):
                try:
                    max_uses = int(request.json.get("max"))
                    if max_uses > 0:
                        token.max_uses = max_uses
                except ValueError:
                    pass

            token.username = username
            token.disabled = request.json.get("disabled") if "disabled" in request.json.keys() else None
            token.hash_token()

            db.session.add(token)
            db.session.commit()

            response = token.to_json()
            response["success"] = True
            response["disabled"] = token.disabled
            response["qr_string"] = f"tak://com.atakmap.app/enroll?host={urlparse(request.url_root).hostname}&username={username}&token={token.generate_token()}"
            return jsonify(response)

    except BaseException as e:
        logger.error(f"Failed to create token: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 400


@token_api_blueprint.route("/api/atak_qr_string", methods=['GET'])
@auth_required()
def get_atak_qr_strings():
    """
    Returns an existing ATAK QR string

    :return: String in the format of tak://com.atakmap.app/enroll?host=server_address.com&username=your_username&token=jwt_token
    """

    query = db.session.query(Token)

    if current_user.has_role("administrator") and request.args.get("username"):
        username = request.args.get("username")
    else:
        username = current_user.username

    query = query.filter_by(username=username)

    token = db.session.execute(query).first()
    if token:
        response = token[0].to_json()
        response["success"] = True
        response["disabled"] = token[0].disabled
        response["total_uses"] = token[0].total_uses
        response["qr_string"] = f"tak://com.atakmap.app/enroll?host={urlparse(request.url_root).hostname}&username={token[0].username}&token={token[0].generate_token()}"
        return jsonify(response)
    else:
        return jsonify({'success': False, 'error': gettext(u"No token found for %s(username)s", username=username)}), 404


@token_api_blueprint.route("/api/atak_qr_string", methods=["DELETE"])
@auth_required()
def delete_token():
    """ Deletes a token

    :parameter username:

    :return: 200 on success
    """
    try:
        if current_user.has_role("administrator") and request.args.get("username"):
            username = request.args.get("username")
        else:
            username = current_user.username

        db.session.execute(delete(Token).where(Token.username == username))
        db.session.commit()

        return jsonify({"success": True})
    except BaseException as e:
        logger.error(f"Failed to delete token: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": gettext(u"Failed to delete token: %(e)s", e=str(e))}), 500
