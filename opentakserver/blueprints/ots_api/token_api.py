import datetime
import os
import time
import traceback
from urllib.parse import urlparse

import jwt
from flask import jsonify, request, current_app as app, Blueprint
from flask_login import current_user
from flask_security import auth_required, verify_password
from sqlalchemy import delete

from opentakserver.extensions import db, logger
from opentakserver.models.Token import Token
from opentakserver.models.user import User

token_api_blueprint = Blueprint('token_api_blueprint', __name__)


@token_api_blueprint.route("/oauth/token", methods=['GET', 'POST'])
def cloudtak_oauth_token():
    user = app.security.datastore.find_user(username=request.args.get("username"))
    if not user or not verify_password(request.args.get("password"), user.password):
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

        return jsonify({"access_token": token})


@token_api_blueprint.route("/api/atak_qr_string", methods=['POST'])
@auth_required()
def new_atak_qr_string():
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
        return jsonify({'success': False, 'error': f"No token found for {username}"}), 404


@token_api_blueprint.route("/api/atak_qr_string", methods=["DELETE"])
@auth_required()
def delete_token():
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
        return jsonify({"success": False, "error": f"Failed to delete token: {e}"}), 500
