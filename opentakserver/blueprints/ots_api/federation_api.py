import traceback

import bleach
import sqlalchemy.exc
from flask import Blueprint
from flask import current_app as app
from flask import jsonify, request
from flask_babel import gettext
from flask_security import roles_required

from opentakserver.blueprints.ots_api.api import paginate, search
from opentakserver.extensions import db, logger
from opentakserver.federation import truststore
from opentakserver.federation.engine import parse_protocol_version
from opentakserver.models.Federation import Federation

federation_api_blueprint = Blueprint("federation_api_blueprint", __name__)


@federation_api_blueprint.route("/api/federation")
@roles_required("administrator")
def get_federation():
    """Search federates with filters and pagination

    :parameter: name
    :parameter: enabled
    :parameter: page
    :parameter: per_page

    :return: JSON array of federates
    """
    query = db.session.query(Federation)
    query = search(query, Federation, "name")
    query = search(query, Federation, "enabled")

    return paginate(query)


@federation_api_blueprint.route("/api/federation", methods=["POST"])
@roles_required("administrator")
def add_federation():
    """Create or update a federate.

    Body: name (required), address, port, protocol_version, outbound, enabled,
    reconnect_interval, inbound_groups, outbound_groups.

    A federate exchanges no data until inbound_groups/outbound_groups are set.
    """
    if not request.json or not request.json.get("name"):
        return jsonify({"success": False, "error": gettext("Please specify a name")}), 400

    name = bleach.clean(request.json.get("name"))

    federation = db.session.execute(db.session.query(Federation).filter_by(name=name)).first()
    if federation:
        federation = federation[0]
    else:
        federation = Federation()
        federation.name = name
        federation.inbound_groups = []
        federation.outbound_groups = []

    if "address" in request.json:
        federation.address = bleach.clean(request.json.get("address") or "") or None
    if "port" in request.json:
        try:
            federation.port = int(request.json.get("port"))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": gettext("Invalid port")}), 400
        if not 1 <= federation.port <= 65535:
            return jsonify({"success": False, "error": gettext("Invalid port")}), 400
    if "protocol_version" in request.json:
        try:
            federation.protocol_version = parse_protocol_version(
                request.json.get("protocol_version")
            )
        except ValueError:
            return (
                jsonify({"success": False, "error": gettext("Invalid protocol_version")}),
                400,
            )
    if "outbound" in request.json:
        federation.outbound = bool(request.json.get("outbound"))
    if "enabled" in request.json:
        federation.enabled = bool(request.json.get("enabled"))
    if "reconnect_interval" in request.json:
        try:
            federation.reconnect_interval = int(request.json.get("reconnect_interval"))
        except (TypeError, ValueError):
            return (
                jsonify({"success": False, "error": gettext("Invalid reconnect_interval")}),
                400,
            )

    for field in ("inbound_groups", "outbound_groups"):
        if field in request.json:
            groups = request.json.get(field) or []
            if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
                return (
                    jsonify({"success": False, "error": gettext("Groups must be a list of names")}),
                    400,
                )
            setattr(federation, field, [bleach.clean(g) for g in groups])

    if federation.outbound and not federation.address:
        return (
            jsonify({"success": False, "error": gettext("Outbound federates require an address")}),
            400,
        )

    try:
        db.session.add(federation)
        db.session.commit()
    except sqlalchemy.exc.SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Failed to save federate: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 400

    return jsonify({"success": True, "federation": federation.to_json()})


@federation_api_blueprint.route("/api/federation", methods=["DELETE"])
@roles_required("administrator")
def delete_federation():
    """Delete a federate

    :parameter: name
    """
    name = request.args.get("name")
    if not name:
        return jsonify({"success": False, "error": gettext("Please specify a name")}), 400

    federation = db.session.execute(
        db.session.query(Federation).filter_by(name=bleach.clean(name))
    ).first()
    if not federation:
        return jsonify({"success": False, "error": gettext("No such federate")}), 404

    db.session.delete(federation[0])
    db.session.commit()

    return jsonify({"success": True})


@federation_api_blueprint.route("/api/federation/ca")
@roles_required("administrator")
def get_federation_cas():
    """List CA certificates in the federation truststore"""
    return jsonify(truststore.list_cas(app.config))


@federation_api_blueprint.route("/api/federation/ca", methods=["POST"])
@roles_required("administrator")
def add_federation_ca():
    """Add a peer's CA certificate to the federation truststore.

    Accepts a PEM file upload (multipart field ``ca``) or a JSON body with
    ``filename`` and ``pem``.
    """
    if "ca" in request.files:
        filename = request.files["ca"].filename
        pem = request.files["ca"].read()
    elif request.is_json and request.json.get("pem"):
        filename = request.json.get("filename") or "federate-ca.pem"
        pem = request.json.get("pem").encode()
    else:
        return (
            jsonify({"success": False, "error": gettext("Please provide a PEM certificate")}),
            400,
        )

    try:
        result = truststore.save_ca(app.config, filename, pem)
    except ValueError as e:
        return (
            jsonify(
                {"success": False, "error": gettext("Invalid certificate: %(error)s", error=str(e))}
            ),
            400,
        )

    return jsonify({"success": True, "ca": result})


@federation_api_blueprint.route("/api/federation/ca", methods=["DELETE"])
@roles_required("administrator")
def delete_federation_ca():
    """Remove a CA certificate from the federation truststore

    :parameter: filename
    """
    filename = request.args.get("filename")
    if not filename:
        return jsonify({"success": False, "error": gettext("Please specify a filename")}), 400

    if truststore.delete_ca(app.config, filename):
        return jsonify({"success": True})

    return jsonify({"success": False, "error": gettext("No such certificate")}), 404
