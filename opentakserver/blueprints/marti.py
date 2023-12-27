import base64
import json
import os
import datetime
import traceback

from xml.etree.ElementTree import Element, tostring, fromstring, SubElement

import bleach
import sqlalchemy
from OpenSSL import crypto
from bs4 import BeautifulSoup
from flask import current_app as app, request, Blueprint, send_from_directory
from flask_security import verify_password
from extensions import logger, db

from config import Config
from models.EUD import EUD
from models.DataPackage import DataPackage
from werkzeug.utils import secure_filename

from models.Video import Video

from certificate_authority import CertificateAuthority

from models.Certificate import Certificate

marti_blueprint = Blueprint('marti_blueprint', __name__)


def basic_auth(credentials):
    username, password = base64.b64decode(credentials.split(" ")[-1].encode('utf-8')).decode('utf-8').split(":")
    username = bleach.clean(username)
    password = bleach.clean(password)
    user = app.security.datastore.find_user(username=username)
    return user and verify_password(password, user.password)


@marti_blueprint.route('/Marti/api/clientEndPoints', methods=['GET'])
def client_end_points():
    logger.warning(request.headers)
    euds = db.session.execute(db.select(EUD)).scalars()
    return_value = {'version': 3, "type": "com.bbn.marti.remote.ClientEndpoint", 'data': [],
                    'nodeId': Config.OTS_NODE_ID}
    for eud in euds:
        return_value['data'].append({
            'callsign': eud.callsign,
            'uid': eud.uid,
            'username': 'anonymous',  # TODO: change this once auth is working
            'lastEventTime': eud.last_event_time,
            'lastStatus': eud.last_status
        })

    return return_value, 200, {'Content-Type': 'application/json'}


# require basic auth
@marti_blueprint.route('/Marti/api/tls/config')
def tls_config():
    if not basic_auth(request.headers.get('Authorization')):
        return '', 401

    logger.warning(request.headers)
    root_element = Element('ns2:certificateConfig')
    root_element.set('xmlns', "http://bbn.com/marti/xml/config")
    root_element.set('xmlns:ns2', "com.bbn.marti.config")

    name_entries = SubElement(root_element, "nameEntries")
    first_name_entry = SubElement(name_entries, "nameEntry")
    first_name_entry.set('name', 'O')
    first_name_entry.set('value', 'Test Organization Name')

    second_name_entry = SubElement(name_entries, "nameEntry")
    second_name_entry.set('name', 'OU')
    second_name_entry.set('value', 'Test Organization Unit Name')

    return tostring(root_element), 200, {'Content-Type': 'application/xml', 'Content-Encoding': 'charset=UTF-8'}


@marti_blueprint.route('/Marti/api/tls/profile/enrollment')
def enrollment():
    if not basic_auth(request.headers.get('Authorization')):
        return '', 401
    logger.error("enrollment {}".format(request.args.get('clientUid')))
    return '', 204


@marti_blueprint.route('/Marti/api/tls/signClient/', methods=['POST'])
def sign_csr():
    if not basic_auth(request.headers.get('Authorization')):
        return '', 401
    logger.error(request.headers)
    logger.error(request.data)
    return '', 200


@marti_blueprint.route('/Marti/api/tls/signClient/v2', methods=['POST'])
def sign_csr_v2():
    if not basic_auth(request.headers.get('Authorization')):
        return '', 401

    uid = request.args.get("clientUid")
    csr = '-----BEGIN CERTIFICATE REQUEST-----\n' + request.data.decode('utf-8') + '-----END CERTIFICATE REQUEST-----'

    x509 = crypto.load_certificate_request(crypto.FILETYPE_PEM, csr.encode())
    common_name = x509.get_subject().CN
    logger.debug("Attempting to sign CSR for {}".format(common_name))

    cert_authority = CertificateAuthority(logger, app)

    signed_csr = cert_authority.sign_csr(csr.encode(), common_name, False).decode("utf-8")
    signed_csr = signed_csr.replace("-----BEGIN CERTIFICATE-----\n", "")
    signed_csr = signed_csr.replace("\n-----END CERTIFICATE-----\n", "")

    enrollment = Element('enrollment')
    signed_cert = SubElement(enrollment, 'signedCert')
    signed_cert.text = signed_csr
    ca = SubElement(enrollment, 'ca')

    f = open(os.path.join(app.config.get("OTS_CA_FOLDER"), "ca.pem"), 'r')
    cert = f.read()
    f.close()

    cert = cert.replace("-----BEGIN CERTIFICATE-----\n", "")
    cert = cert.replace("\n-----END CERTIFICATE-----\n", "")

    ca.text = cert

    response = tostring(enrollment).decode('utf-8')
    response = '<?xml version="1.0" encoding="UTF-8"?>\n' + response

    eud = db.session.execute(db.session.query(EUD).filter_by(uid=uid)).first()[0]

    logger.info(eud)

    certificate = Certificate()
    certificate.common_name = common_name
    certificate.eud_uid = uid
    certificate.callsign = eud.callsign
    certificate.expiration_date = datetime.datetime.today() + datetime.timedelta(days=app.config.get("OTS_CA_EXPIRATION_TIME"))
    certificate.server_address = app.config.get("OTS_SERVER_ADDRESS")
    certificate.server_port = app.config.get("OTS_HTTPS_PORT")
    certificate.truststore_filename = os.path.join(app.config.get("OTS_CA_FOLDER"), "truststore-root.p12")
    certificate.user_cert_filename = os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + ".pem")
    certificate.csr = os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + ".csr")
    certificate.cert_password = app.config.get("OTS_CA_PASSWORD")

    db.session.add(certificate)
    db.session.commit()

    return response, 200, {'Content-Type': 'application/xml', 'Content-Encoding': 'charset=UTF-8'}


@marti_blueprint.route('/Marti/api/version/config', methods=['GET'])
def marti_config():
    return {"version": "3", "type": "ServerConfig",
            "data": {"version": Config.OTS_VERSION, "api": "3", "hostname": Config.OTS_SERVER_ADDRESS},
            "nodeId": Config.OTS_NODE_ID}, 200, {'Content-Type': 'application/json'}


@marti_blueprint.route('/Marti/sync/missionupload', methods=['POST'])
def data_package_share():
    logger.warning(request.headers)
    logger.warning(request.data)
    if not len(request.files):
        return {'error': 'no file'}, 400, {'Content-Type': 'application/json'}
    for file in request.files:
        file = request.files[file]
        logger.debug("Got file: {} - {}".format(file.filename, request.args.get('hash')))
        if file:
            file_hash = request.args.get('hash')
            if file.content_type != 'application/x-zip-compressed':
                logger.error("Not a zip")
                return {'error': 'Please only upload zip files'}, 415, {'Content-Type': 'application/json'}
            filename = secure_filename(file_hash + '.zip')
            file.save(os.path.join(Config.UPLOAD_FOLDER, filename))

            try:
                data_package = DataPackage()
                data_package.filename = file.filename
                data_package.hash = file_hash
                data_package.creator_uid = request.args.get('creatorUid')
                data_package.submission_time = datetime.datetime.now().isoformat() + "Z"
                data_package.mime_type = file.mimetype
                data_package.size = os.path.getsize(os.path.join(Config.UPLOAD_FOLDER, filename))
                db.session.add(data_package)
                db.session.commit()
            except sqlalchemy.exc.IntegrityError as e:
                db.session.rollback()
                logger.error("Failed to save data package: {}".format(e))

            # TODO: Handle HTTP/HTTPS properly
            return 'http://{}:{}/Marti/api/sync/metadata/{}/tool'.format(
                Config.OTS_SERVER_ADDRESS, Config.OTS_HTTP_PORT, file_hash), 200


@marti_blueprint.route('/Marti/api/sync/metadata/<file_hash>/tool', methods=['GET', 'PUT'])
def data_package_metadata(file_hash):
    if request.method == 'PUT':
        try:
            data_package = db.session.execute(db.select(DataPackage).filter_by(hash=file_hash)).scalar_one()
            if data_package:
                data_package.keywords = bleach.clean(request.data.decode("utf-8"))
                db.session.add(data_package)
                db.session.commit()
                return '', 200
            else:
                return '', 404
        except BaseException as e:
            logger.error("Data package PUT failed: {}".format(e))
            logger.error(traceback.format_exc())
            return {'error': str(e)}, 500
    elif request.method == 'GET':
        data_package = db.session.execute(db.select(DataPackage).filter_by(hash=file_hash)).scalar_one()
        return send_from_directory(Config.UPLOAD_FOLDER, data_package.hash + ".zip",
                                   download_name=data_package.filename)


@marti_blueprint.route('/Marti/sync/missionquery')
def data_package_query():
    try:
        data_package = db.session.execute(db.select(DataPackage).filter_by(hash=request.args.get('hash'))).scalar_one()
        if data_package:
            # TODO: Handle HTTP/HTTPS properly
            return 'http://{}:{}/Marti/api/sync/metadata/{}/tool'.format(
                Config.OTS_SERVER_ADDRESS, Config.OTS_HTTP_PORT, request.args.get('hash')), 200
        else:
            return {'error': '404'}, 404, {'Content-Type': 'application/json'}
    except sqlalchemy.exc.NoResultFound as e:
        logger.error("Failed to get dps: {}".format(e))
        return {'error': '404'}, 404, {'Content-Type': 'application/json'}


@marti_blueprint.route('/Marti/sync/search', methods=['GET'])
def data_package_search():
    data_packages = db.session.execute(db.select(DataPackage)).scalars()
    res = {'resultCount': 0, 'results': []}
    for dp in data_packages:
        res['results'].append(
            {'UID': dp.hash, 'Name': dp.filename, 'Hash': dp.hash, 'CreatorUid': dp.creator_uid,
             "SubmissionDateTime": dp.submission_time, "Expiration": -1, "Keywords": "[missionpackage]",
             "MIMEType": dp.mime_type, "Size": dp.size, "SubmissionUser": "anonymous", "PrimaryKey": dp.id,
             "Tool": "public"
             })
        res['resultCount'] += 1

    return json.dumps(res), 200, {'Content-Type': 'application/json'}


@marti_blueprint.route('/Marti/sync/content', methods=['GET'])
def download_data_package():
    file_hash = request.args.get('hash')
    data_package = db.session.execute(db.select(DataPackage).filter_by(hash=file_hash)).scalar_one()

    return send_from_directory(Config.UPLOAD_FOLDER, file_hash + ".zip", download_name=data_package.filename)


@marti_blueprint.route('/Marti/vcm', methods=['GET', 'POST'])
def video():
    if request.method == 'POST':
        soup = BeautifulSoup(request.data, 'xml')
        video_connections = soup.find('videoConnections')

        if video_connections:
            v = Video()
            v.protocol = video_connections.find('protocol').text
            v.alias = video_connections.find('alias').text
            v.uid = video_connections.find('uid').text
            v.address = video_connections.find('address').text
            v.port = video_connections.find('port').text
            v.rover_port = video_connections.find('roverPort').text
            v.ignore_embedded_klv = (video_connections.find('ignoreEmbeddedKLV').text.lower() == 'true')
            v.preferred_mac_address = video_connections.find('preferredMacAddress').text
            v.preferred_interface_address = video_connections.find('preferredInterfaceAddress').text
            v.path = video_connections.find('path').text
            v.buffer_time = video_connections.find('buffer').text
            v.network_timeout = video_connections.find('timeout').text
            v.rtsp_reliable = video_connections.find('rtspReliable').text
            v.xml = str(soup.find('feed'))

            with app.app_context():
                try:
                    db.session.add(v)
                    db.session.commit()
                    logger.debug("Inserted Video")
                except sqlalchemy.exc.IntegrityError as e:
                    logger.debug(e)
                    db.session.rollback()
                    v = db.session.execute(db.select(Video).filter_by(uid=v.uid)).scalar_one()
                    v.protocol = video_connections.find('protocol').text
                    v.alias = video_connections.find('alias').text
                    v.uid = video_connections.find('uid').text
                    v.address = video_connections.find('address').text
                    v.port = video_connections.find('port').text
                    v.rover_port = video_connections.find('roverPort').text
                    v.ignore_embedded_klv = (video_connections.find('ignoreEmbeddedKLV').text.lower() == 'true')
                    v.preferred_mac_address = video_connections.find('preferredMacAddress').text
                    v.preferred_interface_address = video_connections.find('preferredInterfaceAddress').text
                    v.path = video_connections.find('path').text
                    v.buffer_time = video_connections.find('buffer').text
                    v.network_timeout = video_connections.find('timeout').text
                    v.rtsp_reliable = video_connections.find('rtspReliable').text
                    v.xml = str(soup.find('feed'))

                    db.session.commit()
                    logger.debug("Updated video")

        return '', 200

    elif request.method == 'GET':
        try:
            with app.app_context():
                videos = db.session.execute(db.select(Video)).scalars()
                videoconnections = Element('videoConnections')

                for video in videos:
                    v = video.serialize()
                    videoconnections.append(fromstring(v['video']['xml']))

            return tostring(videoconnections), 200
        except BaseException as e:
            logger.error(traceback.format_exc())
            return '', 500
