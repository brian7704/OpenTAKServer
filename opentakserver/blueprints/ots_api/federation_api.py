import datetime
import os

import jwt
from flask import Blueprint, request, jsonify, current_app as app
from flask_login import current_user
from flask_security import roles_required
from werkzeug.datastructures import ImmutableMultiDict

from opentakserver.blueprints.ots_api.api import paginate, search
from opentakserver.extensions import db
from opentakserver.forms.FedTokenForm import FedTokenForm
from opentakserver.forms.FederationConnectionForm import FederationConnectionForm
from opentakserver.models.FederateToken import FederateToken
from opentakserver.models.FederationConnection import FederationConnection

federation_blueprint = Blueprint("federation_blueprint", __name__)


@roles_required("administrator")
@federation_blueprint.route("/api/federation/token")
def get_tokens():
    """
    Get a list of tokens. All URL parameters are optional

    :param name: Token name
    :param expiration: Token expiration date
    :param token: Token encoded in Base64
    :param share_alerts: Boolean
    :param archive: Boolean
    :param notes: String

    :return: Flask response object with ist of FederationTokens
    """
    query = db.session.query(FederateToken)
    query = search(query, FederateToken, "name")
    query = search(query, FederateToken, "expiration")
    query = search(query, FederateToken, "token")
    query = search(query, FederateToken, "share_alerts")
    query = search(query, FederateToken, "archives")
    query = search(query, FederateToken, "notes")

    return paginate(query)


@roles_required("administrator")
@federation_blueprint.route("/api/federation/token", methods=["POST"])
def create_token():
    """
    Creates a new federation token and saves it to the database.

    :param name: Token name (Required)
    :param expiration: Token expiration date
    :param share_alerts: Boolean
    :param archive: Boolean
    :param notes: String

    :return: New FederationToken
    """
    form = FedTokenForm(formdata=ImmutableMultiDict(request.json))
    if not form.validate():
        return jsonify({"success": False, "errors": form.errors}), 400

    with open(
        os.path.join(
            app.config.get("OTS_CA_FOLDER"), "certs", "opentakserver", "opentakserver.nopass.key"
        ),
        "rb",
    ) as key:
        expiration_date = form.expiration.data or 0

        jwt_token = jwt.encode(
            {
                "exp": expiration_date,
                "nbf": datetime.datetime.now(datetime.timezone.utc),
                "iss": "OpenTAKServer",
                "aud": "OpenTAKServer",
                "iat": datetime.datetime.now(datetime.timezone.utc),
                "sub": current_user.username,
            },
            key.read(),
            algorithm="RS256",
        )

        fed_token = FederateToken()
        fed_token.name = form.name.data
        fed_token.expiration = form.expiration.data
        fed_token.token = jwt_token
        fed_token.share_alerts = form.share_alerts.data
        fed_token.archive = form.archive.data
        fed_token.notes = form.notes.data

        db.session.add(fed_token)
        db.commit()

        return jsonify({"success": True, "token": fed_token.to_json()})


@roles_required("administrator")
@federation_blueprint.route("/api/federation")
def get_federations():
    """
    Gets a list of federation connections
    :param display_name: Name of the connection
    :param address: Federate server's address
    :param port: Federate server's port
    :param enabled:
    :param protocol_version: Federation protocol version

    :return: A list of federation connections
    """

    query = db.session.query(FederationConnection)
    query = search(query, FederationConnection, "display_name")
    query = search(query, FederationConnection, "address")
    query = search(query, FederationConnection, "port")
    query = search(query, FederationConnection, "enabled")
    query = search(query, FederationConnection, "protocol_version")

    return paginate(query)


@roles_required("administrator")
@federation_blueprint.route("/api/federation", methods=["POST"])
def create_federation():
    """
    Creates a new federation connection
    :return:
    """

    form = FederationConnectionForm(formdata=ImmutableMultiDict(request.json))
    if not form.validate():
        return jsonify({"success": False, "error": form.errors}), 400

    fed_connection = FederationConnection().from_wtforms(form)
    db.session.add(fed_connection)
    db.session.commit()

    # TODO: Fork a fed client process here

    return jsonify({"success": True}), 200


# TODO: Endpoints for enabling/disabling, deleting
