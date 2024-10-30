import base64
import os
import datetime
import traceback
from urllib.parse import urlparse

from xml.etree.ElementTree import Element, tostring, SubElement

import bleach
import sqlalchemy
from OpenSSL import crypto
from flask import current_app as app, request, Blueprint, jsonify
from flask_security import verify_password, current_user

from opentakserver.extensions import logger, db
from opentakserver.forms.MediaMTXPathConfig import MediaMTXPathConfig
from opentakserver import __version__ as version

from opentakserver.models.EUD import EUD
from opentakserver.models.DataPackage import DataPackage

from opentakserver.models.VideoStream import VideoStream

from opentakserver.certificate_authority import CertificateAuthority

from opentakserver.models.Certificate import Certificate

certificate_authority_api_blueprint = Blueprint('certificate_authority_api_blueprint', __name__)


# flask-security's http_auth_required() decorator will deny access because ATAK doesn't do CSRF,
# so we handle basic auth ourselves
def basic_auth(credentials):
    try:
        username, password = base64.b64decode(credentials.split(" ")[-1].encode('utf-8')).decode('utf-8').split(":")
        username = bleach.clean(username)
        password = bleach.clean(password)
        user = app.security.datastore.find_user(username=username)
        return user and verify_password(password, user.password)
    except BaseException as e:
        logger.error("Failed to verify credentials: {}".format(e))
        return False


# require basic auth
@certificate_authority_api_blueprint.route('/Marti/api/tls/config')
def tls_config():
    root_element = Element('ns2:certificateConfig')
    root_element.set('xmlns', "http://bbn.com/marti/xml/config")
    root_element.set('xmlns:ns2', "com.bbn.marti.config")

    name_entries = SubElement(root_element, "nameEntries")
    first_name_entry = SubElement(name_entries, "nameEntry")
    first_name_entry.set('name', 'O')
    first_name_entry.set('value', app.config.get('OTS_CA_ORGANIZATION'))

    second_name_entry = SubElement(name_entries, "nameEntry")
    second_name_entry.set('name', 'OU')
    second_name_entry.set('value', app.config.get('OTS_CA_ORGANIZATIONAL_UNIT'))

    return tostring(root_element), 200, {'Content-Type': 'application/xml'}


@certificate_authority_api_blueprint.route('/Marti/api/tls/signClient/', methods=['POST'])
def sign_csr():
    if not basic_auth(request.headers.get('Authorization')):
        return '', 401
    return '', 200


@certificate_authority_api_blueprint.route('/Marti/api/tls/signClient/v2', methods=['POST'])
def sign_csr_v2():
    if not basic_auth(request.headers.get('Authorization')):
        return '', 401

    try:
        if 'clientUID' in request.args.keys():
            uid = request.args.get('clientUID')
        else:
            uid = request.args.get("clientUid")

        csr = request.data.decode('utf-8')
        if "BEGIN CERTIFICATE REQUEST" not in csr:
            csr = '-----BEGIN CERTIFICATE REQUEST-----\n' + csr + '-----END CERTIFICATE REQUEST-----'

        x509 = crypto.load_certificate_request(crypto.FILETYPE_PEM, csr.encode())

        common_name = x509.get_subject().CN
        logger.debug("Attempting to sign CSR for {}".format(common_name))

        cert_authority = CertificateAuthority(logger, app)

        signed_csr = cert_authority.sign_csr(csr.encode(), common_name, False).decode("utf-8")
        signed_csr = signed_csr.replace("-----BEGIN CERTIFICATE-----\n", "")
        signed_csr = signed_csr.replace("\n-----END CERTIFICATE-----\n", "")

        f = open(os.path.join(app.config.get("OTS_CA_FOLDER"), "ca.pem"), 'r')
        cert = f.read()
        f.close()

        cert = cert.replace("-----BEGIN CERTIFICATE-----\n", "")
        cert = cert.replace("\n-----END CERTIFICATE-----\n", "")

        # iTAK expects a JSON response but with the Content-Type header set to text/plain for some reason
        if request.headers.get('Accept') == 'text/plain' or request.headers.get('Accept') == 'application/json' or request.headers.get('Accept') == "*/*":
            response = {'signedCert': signed_csr, 'ca0': cert, 'ca1': cert}
        else:
            enrollment = Element('enrollment')
            signed_cert = SubElement(enrollment, 'signedCert')
            signed_cert.text = signed_csr
            ca = SubElement(enrollment, 'ca')
            ca.text = cert

            response = tostring(enrollment).decode('utf-8')
            response = '<?xml version="1.0" encoding="UTF-8"?>\n' + response

        username, password = base64.b64decode(
            request.headers.get("Authorization").split(" ")[-1].encode('utf-8')).decode(
            'utf-8').split(":")
        username = bleach.clean(username)
        user = app.security.datastore.find_user(username=username)

        try:
            eud = EUD()
            eud.uid = uid
            eud.user_id = user.id

            db.session.add(eud)
            db.session.commit()
        except sqlalchemy.exc.IntegrityError:
            db.session.rollback()
            eud = db.session.execute(db.session.query(EUD).filter_by(uid=uid)).first()[0]
            if user and not eud.user_id:
                eud.user_id = user.id
                db.session.add(eud)
                db.session.commit()

        try:
            certificate = Certificate()
            certificate.common_name = common_name
            certificate.eud_uid = uid
            certificate.callsign = eud.callsign
            certificate.expiration_date = datetime.datetime.today() + datetime.timedelta(
                days=app.config.get("OTS_CA_EXPIRATION_TIME"))
            certificate.server_address = urlparse(request.url_root).hostname
            certificate.server_port = app.config.get("OTS_MARTI_HTTPS_PORT")
            certificate.truststore_filename = os.path.join(app.config.get("OTS_CA_FOLDER"), "truststore-root.p12")
            certificate.user_cert_filename = os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", common_name,
                                                          common_name + ".pem")
            certificate.csr = os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + ".csr")
            certificate.cert_password = app.config.get("OTS_CA_PASSWORD")

            db.session.add(certificate)
            db.session.commit()
        except sqlalchemy.exc.IntegrityError:
            db.session.rollback()
            certificate = db.session.execute(db.session.query(Certificate).filter_by(eud_uid=eud.uid)).scalar_one()
            certificate.common_name = common_name
            certificate.callsign = eud.callsign
            certificate.expiration_date = datetime.datetime.today() + datetime.timedelta(
                days=app.config.get("OTS_CA_EXPIRATION_TIME"))
            certificate.server_address = urlparse(request.url_root).hostname
            certificate.server_port = app.config.get("OTS_MARTI_HTTPS_PORT")
            certificate.truststore_filename = os.path.join(app.config.get("OTS_CA_FOLDER"), "truststore-root.p12")
            certificate.user_cert_filename = os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", common_name,
                                                          common_name + ".pem")
            certificate.csr = os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + ".csr")
            certificate.cert_password = app.config.get("OTS_CA_PASSWORD")

            db.session.commit()

        if request.headers.get('Accept') == 'text/plain':
            return response, 200, {'Content-Type': 'text/plain', 'Content-Encoding': 'charset=UTF-8'}
        elif request.headers.get('Accept') == 'application/json' or request.headers.get('Accept') == "*/*":
            return jsonify(response)
        else:
            return response, 200, {'Content-Type': 'application/xml', 'Content-Encoding': 'charset=UTF-8'}
    except BaseException as e:
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
