import datetime
import os
import pathlib
import traceback

from cryptography import x509
from cryptography.hazmat.backends import default_backend

import jwt
from flask import Blueprint, request, jsonify, current_app as app, send_from_directory
from flask_login import current_user
from flask_security import roles_required
from flask_babel import gettext
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import ImmutableMultiDict

from opentakserver.forms.FederateForm import FederateForm
from opentakserver.models.Federate import Federate
from opentakserver.blueprints.ots_api.api import paginate, search, change_config_setting
from opentakserver.extensions import db, logger
from opentakserver.forms.FedTokenForm import FedTokenForm
from opentakserver.forms.FederationConnectionForm import FederationConnectionForm
from opentakserver.models.FederateToken import FederateToken
from opentakserver.models.FederationConnection import FederationConnection
from opentakserver.certificate_authority import CertificateAuthority

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

    return paginate(query, FederateToken)


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

    return paginate(query, FederationConnection)


@roles_required("administrator")
@federation_blueprint.route("/api/federation/all")
def get_all_federations():
    federation_connections = db.session.execute(db.session.query(FederationConnection)).scalars()
    return_value = []
    for federation_connection in federation_connections:
        return_value.append(federation_connection.to_json())

    return jsonify({"success": True, "results": return_value})


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

    try:
        fed_connection = FederationConnection()
        fed_connection.from_wtforms(form)
        db.session.add(fed_connection)
        db.session.commit()
    except BaseException as e:
        logger.error(f"Failed to create connection: {e}")
        logger.debug(traceback.format_exc())
        return (
            jsonify(
                {
                    "success": False,
                    "error": gettext("Failed to create connection: %(error)s", error=str(e)),
                }
            ),
            500,
        )

    # TODO: Fork a fed client process here

    return jsonify({"success": True}), 200


@roles_required("administrator")
@federation_blueprint.route("/api/federation", methods=["DELETE"])
def delete_federation():
    """
    Delete a federation connection

    :return:
    """

    connection_id = request.args.get("id")
    if not connection_id:
        return jsonify({"success": False, "error": gettext("Missing connection ID")}), 400

    try:
        FederationConnection.query.filter_by(id=int(connection_id)).delete()
        db.session.commit()
        return jsonify({"success": True}), 200
    except BaseException as e:
        logger.error(f"Failed to delete connection: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500


@roles_required("administrator")
@federation_blueprint.route("/api/federation", methods=["PATCH"])
def toggle_federation():
    """
    Enable or disable a federation connection

    :return:
    """


@roles_required("administrator")
@federation_blueprint.route("/api/federation/certificate")
def get_federation_certificate():
    """
    Download the federation cert needed by the server you're federating to

    :return: Federation certificate file
    """

    fed_cert = pathlib.Path(app.config.get("OTS_FEDERATION_CERTIFICATE"))
    send_from_directory(fed_cert.parent, fed_cert.name)


@roles_required("administrator")
@federation_blueprint.route("/api/federation/certificate", methods=["PATCH"])
def regenerate_federation_certificate():
    """
    Regenerates the federation certificate. <b>THIS WILL DELETE THE OLD FEDERATION CERTIFICATE!</b> You will need to re-upload
    this certificate to any servers you're currently federated with.

    Use this to change the common name of the certificate to something other than the default "federation" such as your FQDN.

    :param: common_name - (Optional) The common name for the new certificate. Will default to "federation" if none is provided.

    :return: 200 on success, 500 on error
    """

    common_name = request.json.get("common_name", "federation")

    try:
        certificate_authority = CertificateAuthority(logger, app)
        certificate_authority.issue_certificate(common_name, True)
        cert_file = os.path.join(
            app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + ".pem"
        )
        change_config_setting("OTS_FEDERATION_CERTIFICATE", cert_file)

        return jsonify({"success": True, "cert_file": cert_file})

    except BaseException as e:
        logger.error(f"Failed to generate federation certificate: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500


@roles_required("administrator")
@federation_blueprint.route("/api/federation/federate")
def get_federates():
    query = db.session.query(Federate)
    query = search(query, Federate, "name")
    query = search(query, Federate, "issuer")
    query = search(query, Federate, "subject")
    query = search(query, Federate, "serial_number")

    return paginate(query, Federate)


@roles_required("administrator")
@federation_blueprint.route("/api/federation/federate/all")
def get_all_federates():
    federates = db.session.execute(db.session.query(Federate)).scalars()
    return_value = []

    for federate in federates:
        return_value.append(federate.to_json())

    return jsonify({"success": True, "results": return_value})


@roles_required("administrator")
@federation_blueprint.route("/api/federation/federate", methods=["DELETE"])
def delete_federate():
    federation_id = request.args.get("id", None)
    if not federation_id:
        return jsonify({"success": False, "error": gettext("Please provide a federation ID")}), 400

    try:
        Federate.query.filter_by(id=int(federation_id)).delete()
        db.session.commit()
        return jsonify({"success": True}), 200
    except BaseException as e:
        logger.error(f"Failed to delete federation {e}")
        logger.debug(traceback.format_exc())
        return (
            jsonify(
                {
                    "success": False,
                    "error": gettext(
                        "Cannot delete a federate that is associated with a federation connection"
                    ),
                }
            ),
            400,
        )
    except BaseException as e:
        logger.error(f"Failed to delete federation {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500


@roles_required("administrator")
@federation_blueprint.route("/api/federation/federate", methods=["POST"])
def add_federate():
    form = FederateForm(formdata=ImmutableMultiDict(request.json))
    if form.validate():
        federate = Federate()
        federate.from_wtf(form)

        if not federate.certificate_file:
            return (
                jsonify({"success": False, "error": gettext("Certificate file is required")}),
                400,
            )
        if not os.path.exists(
            os.path.join(
                app.config.get("OTS_DATA_FOLDER"), "federation", str(federate.certificate_file)
            )
        ):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": gettext(
                            "Cannot find certificate file %(cert_file)s",
                            cert_file=federate.certificate_file,
                        ),
                    }
                ),
                400,
            )
        if not federate.issuer or not federate.subject or not federate.serial_number:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": gettext("Serial number, subject, and issuer are required"),
                    }
                ),
                400,
            )

        try:
            db.session.add(federate)
            db.session.commit()
            return jsonify({"success": True, "federate": federate.to_json()}), 200
        except IntegrityError:
            db.session.rollback()
            db.session.execute(
                update(Federate)
                .where(Federate.serial_number == federate.serial_number)
                .values(**federate.serialize())
            )
            db.session.commit()
            return jsonify({"success": True, "federate": federate.to_json()}), 200
        except BaseException as e:
            logger.error(f"Failed to add federation: {e}")
            logger.debug(traceback.format_exc())
            return jsonify({"success": False, "error": str(e)}), 500

    else:
        return jsonify({"success": False, "error": form.errors}), 400


@roles_required("administrator")
@federation_blueprint.route("/api/federation/certificate", methods=["POST"])
def upload_federation_certificate():
    """
    Uploads a new federate certificate
    """
    # application/x-pem-file
    cert_file = request.files.get("cert_file")
    if not cert_file:
        return jsonify({"success": False, "error": gettext("No file uploaded")}), 400

    if (
        cert_file.mimetype != "application/x-x509-ca-cert"
        and cert_file.mimetype != "application/x-pem-file"
    ):
        return (
            jsonify({"success": False, "error": gettext("Certificates must be in PEM format")}),
            400,
        )

    pathlib.Path(os.path.join(app.config.get("OTS_DATA_FOLDER"), "federation")).mkdir(
        parents=True, exist_ok=True
    )

    cert_file.stream.seek(0)
    cert_bytes = cert_file.stream.read()

    try:
        cert = x509.load_pem_x509_certificate(cert_bytes, default_backend())

        # Use the cert's serial number as the file name to avoid file naming conflicts since most certs will be named ca.pem
        cert_file.save(
            os.path.join(
                app.config.get("OTS_DATA_FOLDER"), "federation", f"{cert.serial_number}.pem"
            )
        )
    except BaseException as e:
        logger.error(f"Failed to load certificate: {e}")
        return jsonify({"success": False, "error": str(e)}), 400

    return (
        jsonify(
            {
                "success": True,
                "certificate_file": cert_file.filename,
                "issuer": cert.issuer.rfc4514_string(),
                "subject": cert.subject.rfc4514_string(),
                "serial_number": str(cert.serial_number),
            }
        ),
        200,
    )
