import datetime
import hashlib
import json
import os
import platform
import shutil
import traceback
import uuid
from shutil import copyfile

import pathlib
from urllib.parse import urlparse

import ffmpeg
import yaml
from sqlalchemy import update
from werkzeug.datastructures import ImmutableMultiDict

import bleach
import psutil
import requests
import sqlalchemy.exc
from flask import current_app as app, request, Blueprint, jsonify, send_from_directory
from flask_security import auth_required, roles_accepted, hash_password, current_user, \
    admin_change_password, verify_password

from opentakserver.extensions import logger, db
from .marti import data_package_share

from opentakserver.models.Alert import Alert
from opentakserver.models.CasEvac import CasEvac
from opentakserver.models.CoT import CoT
from opentakserver.models.DataPackage import DataPackage
from opentakserver.models.EUD import EUD
from opentakserver.models.ZMIST import ZMIST
from opentakserver.models.Point import Point
from opentakserver.models.user import User
from opentakserver.models.Certificate import Certificate
from opentakserver.models.VideoStream import VideoStream

from opentakserver.forms.MediaMTXPathConfig import MediaMTXPathConfig

from opentakserver.SocketServer import SocketServer
from opentakserver.certificate_authority import CertificateAuthority
from opentakserver.models.Icon import Icon
from opentakserver.models.Marker import Marker
from opentakserver.models.RBLine import RBLine
from opentakserver.models.VideoRecording import VideoRecording
from opentakserver import __version__ as version

api_blueprint = Blueprint('api_blueprint', __name__)

p = psutil.Process()


def search(query, model, field):
    arg = request.args.get(field)
    if arg:
        arg = bleach.clean(arg)
        return query.where(getattr(model, field) == arg)
    return query


def paginate(query):
    try:
        page = int(request.args.get('page')) if 'page' in request.args else 1
        per_page = int(request.args.get('per_page')) if 'per_page' in request.args else 10
    except ValueError:
        return {'success': False, 'error': 'Invalid page or per_page number'}, 400, {'Content-Type': 'application/json'}

    pagination = db.paginate(query, page=page, per_page=per_page)
    rows = pagination.items

    results = {'results': [], 'total_pages': pagination.pages, 'current_page': page, 'per_page': per_page}

    for row in rows:
        results['results'].append(row.to_json())

    return jsonify(results)


def change_config_setting(setting, value):
    try:
        with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), "r") as config_file:
            config = yaml.safe_load(config_file.read())

        config[setting] = value
        with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), "w") as config_file:
            yaml.safe_dump(config, config_file)

    except BaseException as e:
        logger.error("Failed to change setting {} to {} in config.yml: {}".format(setting, value, e))


@api_blueprint.route('/api/status')
@auth_required()
def status():
    now = datetime.datetime.now()
    system_boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
    system_uptime = now - system_boot_time

    ots_uptime = now - app.start_time

    cpu_time = psutil.cpu_times()
    cpu_time_dict = {'user': cpu_time.user, 'system': cpu_time.system, 'idle': cpu_time.idle}

    vmem = psutil.virtual_memory()
    vmem_dict = {'total': vmem.total, 'available': vmem.available, 'used': vmem.used, 'free': vmem.free,
                 'percent': vmem.percent}

    disk_usage = psutil.disk_usage('/')
    disk_usage_dict = {'total': disk_usage.total, 'used': disk_usage.used, 'free': disk_usage.free,
                       'percent': disk_usage.percent}

    temps_dict = {}

    if hasattr(psutil, "sensors_temperatures"):
        for name, value in psutil.sensors_temperatures().items():
            temps_dict[name] = {}
            for val in value:
                temps_dict[name][val.label] = {'current': val.current, 'high': val.high, 'critical': val.critical}

    fans_dict = {}
    if hasattr(psutil, 'sensors_fans'):
        for name, value in psutil.sensors_fans():
            for val in value:
                fans_dict[name][val.label] = {val.current}

    battery_dict = {}
    if hasattr(psutil, "sensors_battery") and psutil.sensors_battery():
        battery = psutil.sensors_battery()
        battery_dict = {'percent': battery.percent, 'charging': battery.power_plugged, 'time_left': battery.secsleft}

    try:
        os_release = platform.freedesktop_os_release()
    except:
        os_release = {'NAME': None, 'PRETTY_NAME': None, 'VERSION': None, 'VERSION_CODENAME': None}

    uname = {'system': platform.system(), 'node': platform.node(), 'release': platform.release(),
             'version': platform.version(), 'machine': platform.machine()}

    response = {
        'tcp': app.tcp_thread.is_alive(), 'ssl': app.ssl_thread.is_alive(),
        'cot_router': app.cot_thread.iothread.is_alive(),
        'online_euds': app.cot_thread.online_euds, 'system_boot_time': system_boot_time.strftime("%Y-%m-%d %H:%M:%SZ"),
        'system_uptime': system_uptime.total_seconds(), 'ots_start_time': app.start_time.strftime("%Y-%m-%d %H:%M:%SZ"),
        'ots_uptime': ots_uptime.total_seconds(), 'cpu_time': cpu_time_dict, 'cpu_percent': p.cpu_percent(),
        'load_avg': psutil.getloadavg(), 'memory': vmem_dict, 'disk_usage': disk_usage_dict, 'temps': temps_dict,
        'fans': fans_dict, 'battery': battery_dict, 'ots_version': version, 'uname': uname,
        'os_release': os_release, 'python_version': platform.python_version()
    }

    return jsonify(response)


@api_blueprint.route('/api/tcp/<action>')
@roles_accepted('administrator')
def control_tcp_socket(action):
    action = bleach.clean(action).lower()

    if action == 'start':
        if app.tcp_thread.is_alive():
            return jsonify({'success': False, 'error': 'TCP thread is already active'}), 400

        change_config_setting("OTS_ENABLE_TCP_STREAMING_PORT", True)
        app.config.update(OTS_ENABLE_TCP_STREAMING_PORT=True)

        tcp_thread = SocketServer(logger, app.app_context(), app.config.get("OTS_TCP_STREAMING_PORT"))
        tcp_thread.start()
        app.tcp_thread = tcp_thread

        return jsonify({'success': True})

    elif action == 'stop':
        if not app.tcp_thread.is_alive():
            return jsonify({'success': False, 'error': 'TCP thread is not active'}), 400

        change_config_setting("OTS_ENABLE_TCP_STREAMING_PORT", False)
        app.config.update(OTS_ENABLE_TCP_STREAMING_PORT=False)

        app.tcp_thread.stop()
        return jsonify({'success': True})

    else:
        return jsonify({'success': False, 'error': 'Valid actions are start and stop'}), 400


@api_blueprint.route('/api/ssl/<action>')
@roles_accepted('administrator')
def control_ssl_socket(action):
    action = bleach.clean(action).lower()

    if action == 'start':
        if app.ssl_thread.is_alive():
            return jsonify({'success': False, 'error': 'ssl thread is already active'}), 400

        with app.app_context():
            ssl_thread = SocketServer(logger, app.app_context(), app.config.get("OTS_SSL_STREAMING_PORT"), True)
            ssl_thread.start()
            app.ssl_thread = ssl_thread

            return jsonify({'success': True})

    elif action == 'stop':
        if not app.ssl_thread.is_alive():
            return jsonify({'success': False, 'error': 'SSL thread is not active'}), 400

        app.ssl_thread.stop()
        return jsonify({'success': True})

    else:
        return jsonify({'success': False, 'error': 'Valid actions are start and stop'}), 400


@api_blueprint.route("/api/certificate", methods=['GET', 'POST'])
@auth_required()
def certificate():
    if request.method == 'POST' and 'username' in request.json.keys():
        try:
            username = bleach.clean(request.json.get('username'))
            truststore_filename = os.path.join(app.config.get("OTS_CA_FOLDER"), 'certs', "opentakserver",
                                               "truststore-root.p12")
            user_filename = os.path.join(app.config.get("OTS_CA_FOLDER"), 'certs', username,
                                         "{}.p12".format(username))

            user = app.security.datastore.find_user(username=username)

            if not user:
                return ({'success': False, 'error': 'Invalid username: {}'.format(username)}, 400,
                        {'Content-Type': 'application/json'})

            ca = CertificateAuthority(logger, app)
            filenames = ca.issue_certificate(username, False)

            for filename in filenames:
                file_hash = hashlib.sha256(
                    open(os.path.join(app.config.get("OTS_CA_FOLDER"), 'certs', username, filename),
                         'rb').read()).hexdigest()

                data_package = DataPackage()
                data_package.filename = filename
                data_package.keywords = "public"
                data_package.creator_uid = request.json['uid'] if 'uid' in request.json.keys() else str(uuid.uuid4())
                data_package.submission_time = datetime.datetime.now()
                data_package.mime_type = "application/x-zip-compressed"
                data_package.size = os.path.getsize(
                    os.path.join(app.config.get("OTS_CA_FOLDER"), 'certs', username, filename))
                data_package.hash = file_hash
                data_package.submission_user = current_user.id

                try:
                    db.session.add(data_package)
                    db.session.commit()
                except sqlalchemy.exc.IntegrityError as e:
                    db.session.rollback()
                    logger.error(e)
                    return ({'success': False, 'error': 'Certificate already exists for {}'.format(username)}, 400,
                            {'Content-Type': 'application/json'})

                copyfile(os.path.join(app.config.get("OTS_CA_FOLDER"), 'certs', username, "{}".format(filename)),
                         os.path.join(app.config.get("UPLOAD_FOLDER"), "{}.zip".format(file_hash)))

                cert = Certificate()
                cert.common_name = username
                cert.username = username
                cert.expiration_date = datetime.datetime.today() + datetime.timedelta(
                    days=app.config.get("OTS_CA_EXPIRATION_TIME"))
                cert.server_address = urlparse(request.url_root).hostname
                cert.server_port = app.config.get("OTS_SSL_STREAMING_PORT")
                cert.truststore_filename = truststore_filename
                cert.user_cert_filename = user_filename
                cert.cert_password = app.config.get("OTS_CA_PASSWORD")
                cert.data_package_id = data_package.id if data_package else None

                db.session.add(cert)
                db.session.commit()

            return {'success': True}, 200, {'Content-Type': 'application/json'}
        except BaseException as e:
            logger.error(traceback.format_exc())
            return {'success': False, 'error': str(e)}, 500, {'Content-Type': 'application/json'}
    elif request.method == 'POST':
        return ({'success': False, 'error': "Please specify a callsign"}, 400,
                {'Content-Type': 'application/json'})
    elif request.method == 'GET':
        query = db.session.query(Certificate)
        query = search(query, Certificate, 'callsign')
        query = search(query, Certificate, 'username')

        return paginate(query)


@api_blueprint.route('/api/me')
@auth_required()
def me():
    me = db.session.execute(db.session.query(User).where(User.id == current_user.id)).first()[0]
    return jsonify(me.serialize())


@api_blueprint.route('/api/data_packages', methods=['POST'])
@auth_required()
def upload_data_package():
    return data_package_share()


@api_blueprint.route('/api/data_packages', methods=['DELETE'])
@auth_required()
def delete_data_package():
    file_hash = request.args.get('hash')
    if not file_hash:
        return jsonify({'success': False, 'error': 'Please provide a file hash'}), 400

    query = db.session.query(DataPackage)
    query = search(query, DataPackage, 'hash')
    data_package = db.session.execute(query).first()
    if not data_package:
        return jsonify({'success': False, 'error': 'Invalid/unknown hash'}), 400

    try:
        logger.warning("Deleting data package {} - {}".format(data_package[0].filename, data_package[0].hash))
        db.session.delete(data_package[0])
        db.session.commit()
        os.remove(os.path.join(app.config.get("UPLOAD_FOLDER"), "{}.zip".format(data_package[0].hash)))

        if data_package[0].certificate:
            Certificate.query.filter_by(id=data_package[0].certificate.id).delete()
            db.session.commit()
            shutil.rmtree(
                os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", data_package[0].certificate.common_name),
                ignore_errors=True)
    except BaseException as e:
        logger.error("Failed to delete data package")
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({'success': True})


@api_blueprint.route('/api/data_packages')
@auth_required()
def data_packages():
    query = db.session.query(DataPackage)
    query = search(query, DataPackage, 'filename')
    query = search(query, DataPackage, 'hash')
    query = search(query, DataPackage, 'createor_uid')
    query = search(query, DataPackage, 'keywords')
    query = search(query, DataPackage, 'mime_type')
    query = search(query, DataPackage, 'size')
    query = search(query, DataPackage, 'tool')

    return paginate(query)


@api_blueprint.route('/api/data_packages/download')
@auth_required()
def data_package_download():
    if 'hash' not in request.args.keys():
        return ({'success': False, 'error': 'Please provide a data package hash'}, 400,
                {'Content-Type': 'application/json'})

    file_hash = request.args.get('hash')

    query = db.session.query(DataPackage)
    query = search(query, DataPackage, 'hash')

    data_package = db.session.execute(query).first()

    if not data_package:
        return ({'success': False, 'error': "Data package with hash '{}' not found".format(file_hash)}, 404,
                {'Content-Type': 'application/json'})

    download_name = data_package[0].filename
    if not download_name.endswith('.zip'):
        download_name += ".zip"

    return send_from_directory(app.config.get("UPLOAD_FOLDER"), "{}.zip".format(file_hash), as_attachment=True,
                               download_name=download_name)


@api_blueprint.route('/api/cot', methods=['GET'])
@auth_required()
def query_cot():
    query = db.session.query(CoT)
    query = search(query, CoT, 'how')
    query = search(query, CoT, 'type')
    query = search(query, CoT, 'sender_callsign')
    query = search(query, CoT, 'sender_uid')

    return paginate(query)


@api_blueprint.route("/api/alerts", methods=['GET'])
@auth_required()
def query_alerts():
    query = db.session.query(Alert)
    query = search(query, Alert, 'uid')
    query = search(query, Alert, 'sender_uid')
    query = search(query, Alert, 'alert_type')

    return paginate(query)


@api_blueprint.route("/api/point", methods=['GET'])
@auth_required()
def query_points():
    query = db.session.query(Point)

    query = search(query, EUD, 'uid')
    query = search(query, EUD, 'callsign')

    return paginate(query)


@api_blueprint.route("/api/casevac", methods=['GET'])
@auth_required()
def query_casevac():
    query = db.session.query(CasEvac)

    query = search(query, EUD, 'callsign')
    query = search(query, CasEvac, 'sender_uid')
    query = search(query, CasEvac, 'uid')

    return paginate(query)


@api_blueprint.route("/api/user/add", methods=['POST'])
@roles_accepted("administrator")
def create_user():
    username = bleach.clean(request.json.get('username'))
    password = bleach.clean(request.json.get('password'))
    confirm_password = bleach.clean(request.json.get('confirm_password'))

    if password != confirm_password:
        return {'success': False, 'error': 'Passwords do not match'}, 400, {'Content-Type': 'application/json'}

    roles = request.json.get("roles")
    roles_cleaned = []

    for role in roles:
        role = bleach.clean(role)
        role_exists = app.security.datastore.find_role(role)

        if not role_exists:
            return ({'success': False, 'error': 'Role {} does not exist'.format(role)}, 409,
                    {'Content-Type': 'application/json'})

        elif role == 'administrator' and not current_user.has_role('administrator'):
            return ({'success': False, 'error': 'Only administrators can add users to the administrators role'
                    .format(username)}, 403, {'Content-Type': 'application/json'})

        elif role not in roles_cleaned:
            roles_cleaned.append(role)

    if not app.security.datastore.find_user(username=username):
        logger.info("Creating user {}".format(username))
        app.security.datastore.create_user(username=username, password=hash_password(password), roles=roles_cleaned)
        db.session.commit()
        return {'success': True}, 200, {'Content-Type': 'application/json'}
    else:
        logger.error("User {} already exists".format(username))
        return {'success': False, 'error': 'User {} already exists'.format(username)}, 409, {
            'Content-Type': 'application/json'}


@api_blueprint.route("/api/user/delete", methods=['POST'])
@roles_accepted("administrator")
def delete_user():
    username = bleach.clean(request.json.get('username'))

    logger.info("Deleting user {}".format(username))

    try:
        user = app.security.datastore.find_user(username=username)
        app.security.datastore.delete_user(user)
    except BaseException as e:
        logger.error(traceback.format_exc())
        return {'success': False, 'error': 'Failed to delete user: {}'.format(e)}, 400

    db.session.commit()
    return {'success': True}, 200, {'Content-Type': 'application/json'}


@api_blueprint.route("/api/user/password/reset", methods=['POST'])
@roles_accepted("administrator")
def admin_reset_password():
    username = bleach.clean(request.json.get("username"))
    new_password = bleach.clean(request.json.get("new_password"))

    if not username or not new_password:
        return jsonify({'success': False, 'error': 'Please specify a username and new password'}), 400

    if len(new_password) < app.config.get("SECURITY_PASSWORD_LENGTH_MIN"):
        return jsonify({'success': False, 'error': 'Your password must be at least {} characters long'
                       .format(app.config.get("SECURITY_PASSWORD_LENGTH_MIN"))}), 400

    user = app.security.datastore.find_user(username=username)
    if user:
        admin_change_password(user, new_password, False)
        db.session.commit()
        return {'success': True}, 200, {'Content-Type': 'application/json'}
    else:
        return ({'success': False, 'error': 'Could not find user {}'.format(username)}, 400,
                {'Content-Type': 'application/json'})


@api_blueprint.route('/api/user/deactivate', methods=['POST'])
@roles_accepted('administrator')
def deactivate_user():
    username = bleach.clean(request.json.get("username", ""))
    if not username:
        return jsonify({'success': False, 'error': 'Please specify the username to deactivate'}), 400

    user = app.security.datastore.find_user(username=username)
    if not user:
        return jsonify({'success': False, 'error': 'User {} does not exist'.format(username)})

    deactivated = app.security.datastore.deactivate_user(user)
    if deactivated:
        db.session.commit()
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': '{} is already deactivated'.format(username)})


@api_blueprint.route('/api/user/activate', methods=['POST'])
@roles_accepted('administrator')
def activate_user():
    username = bleach.clean(request.json.get("username", ""))
    if not username:
        return jsonify({'success': False, 'error': 'Please specify the username to activate'}), 400

    user = app.security.datastore.find_user(username=username)
    if not user:
        return jsonify({'success': False, 'error': 'User {} does not exist'.format(username)})

    activated = app.security.datastore.activate_user(user)
    if activated:
        db.session.commit()
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': '{} is already activated'.format(username)})


@api_blueprint.route("/api/user/role", methods=['POST'])
@roles_accepted("administrator")
def set_user_role():
    username = bleach.clean(request.json.get("username", ""))
    roles = request.json.get("roles")
    roles_cleaned = []

    if not username or not roles:
        return jsonify({'success': False, 'error': 'Please specify a username and roles'}), 400

    for role in roles:
        role = bleach.clean(role)
        role_exists = app.security.datastore.find_role(role)

        if not role_exists:
            return ({'success': False, 'error': 'Role {} does not exist'.format(role)}, 409,
                    {'Content-Type': 'application/json'})

        elif role not in roles_cleaned:
            roles_cleaned.append(role)

    user = app.security.datastore.find_user(username=username)
    if not user:
        return ({'success': False, 'error': 'User {} does not exist'.format(username)}, 400,
                {'Content-Type': 'application/json'})

    for role in user.roles:
        app.security.datastore.remove_role_from_user(user, role)

    for role in roles_cleaned:
        app.security.datastore.add_role_to_user(user, role)

    db.session.commit()
    return jsonify({'success': True})


# This is mainly for mediamtx authentication
@api_blueprint.route('/api/external_auth', methods=['POST'])
def external_auth():
    username = bleach.clean(request.json.get('user'))
    password = bleach.clean(request.json.get('password'))
    action = bleach.clean(request.json.get('action'))
    query = bleach.clean(request.json.get('query'))

    user = app.security.datastore.find_user(username=username)
    if user and verify_password(password, user.password):
        if action == 'publish':
            logger.debug("Publish {}".format(request.json.get('path')))
            v = VideoStream()
            v.uid = bleach.clean(request.json.get('id')) if request.json.get('id') else None
            v.rover_port = -1
            v.ignore_embedded_klv = False
            v.buffer_time = None
            v.network_timeout = 10000
            v.protocol = bleach.clean(request.json.get('protocol'))
            v.path = bleach.clean(request.json.get('path'))
            v.alias = v.path.split("/")[-1]
            v.username = bleach.clean(request.json.get('user'))
            path_config = MediaMTXPathConfig(None).serialize()
            path_config['sourceOnDemand'] = False
            v.mediamtx_settings = json.dumps(path_config)

            if v.protocol == 'rtsp':
                v.port = 8554
                v.rtsp_reliable = 1
            elif v.protocol == 'rtmp':
                v.port = 1935
                v.rtsp_reliable = 1
            else:
                v.rtsp_reliable = 0

            v.generate_xml(request.json.get("ip"))

            with app.app_context():
                try:

                    db.session.add(v)
                    db.session.commit()
                    r = requests.post("{}/v3/config/paths/add/{}".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), v.path),
                                      json=path_config)
                    if r.status_code == 200:
                        logger.debug("Added path {} to mediamtx".format(v.path))
                    else:
                        logger.error(
                            "Failed to add path {} to mediamtx. Status code {} {}".format(v.path, r.status_code,
                                                                                          r.text))
                    logger.debug("Inserted video stream {}".format(v.uid))
                except sqlalchemy.exc.IntegrityError as e:
                    try:
                        db.session.rollback()
                        video = db.session.query(VideoStream).filter(VideoStream.path == v.path).first()
                        r = requests.post("{}/v3/config/paths/add/{}".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), v.path),
                                          json=json.loads(video.mediamtx_settings))
                        if r.status_code == 200:
                            logger.debug("Added path {} to mediamtx".format(v.path))
                        else:
                            logger.error(
                                "Failed to add path {} to mediamtx. Status code {} {}".format(v.path, r.status_code,
                                                                                              r.text))
                    except:
                        logger.error(traceback.format_exc())

        logger.debug("external_auth returning 200")
        return '', 200
    elif query:
        for arg in query.split("&"):
            key, value = arg.split("=")
            if key == 'token' and value == app.config.get("OTS_MEDIAMTX_TOKEN"):
                return '', 200
    else:
        logger.debug("external_auth returning 401")
        return '', 401


@api_blueprint.route('/api/videos/thumbnail', methods=['GET'])
@auth_required()
def thumbnail():
    path = request.args.get("path")
    recording = request.args.get("recording")
    if not path:
        return jsonify({"success": False, "error": "Please specify a path"}), 400

    if recording and os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "mediamtx", "recordings", path, recording + ".png")):
        logger.warning(os.path.join(app.config.get("OTS_DATA_FOLDER"), "mediamtx", "recordings", path, recording + ".png"))
        return send_from_directory(os.path.join(app.config.get("OTS_DATA_FOLDER"), "mediamtx", "recordings", path), recording + ".png")

    elif os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "mediamtx", "recordings", path)):
        return send_from_directory(os.path.join(app.config.get("OTS_DATA_FOLDER"), "mediamtx", "recordings", path), "thumbnail.png")

    return jsonify({"success": False, "error": "Please specify a valid path"}), 400


@api_blueprint.route('/api/videos/recordings')
@auth_required()
def video_recordings():
    query = db.session.query(VideoRecording)
    query = search(query, VideoRecording, 'path')

    return paginate(query)


@api_blueprint.route('/api/videos/recording', methods=['GET', 'DELETE', 'HEAD'])
@auth_required()
def download_recording():
    if not request.args.get("id"):
        return jsonify({'success': False, 'error': 'Please specify a recording ID'}), 400
    recording_id = bleach.clean(request.args.get('id'))

    try:
        recording = \
            db.session.execute(db.session.query(VideoRecording).filter(VideoRecording.id == recording_id)).first()[0]

        if request.method == 'GET':
            filename = pathlib.Path(recording.segment_path)
            return send_from_directory(filename.parent, filename.name)
        elif request.method == 'DELETE':
            os.remove(recording.segment_path)
            db.session.delete(recording)
            db.session.commit()
            return jsonify({'success': True})
        elif request.method == 'HEAD':
            return '', 200
    except:
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'Recording not found'}), 404


@api_blueprint.route('/api/user/assign_eud', methods=['POST'])
@auth_required()
def assign_eud_to_user():
    username = bleach.clean(request.json.get('username')) if 'username' in request.json else None
    eud_uid = bleach.clean(request.json.get('uid')) if 'uid' in request.json else None
    user = None

    if not eud_uid:
        return {'success': False, 'error': 'Please specify an EUD'}, 400, {'Content-Type': 'application/json'}
    if not username or username == current_user.username:
        user = current_user
    elif username != current_user.username and current_user.has_role('administrator'):
        user = app.security.datastore.find_user(username=username)
        if not user:
            return {'success': False, 'error': 'User {} does not exist'.format(username)}, 404, {
                'Content-Type': 'application/json'}

    eud = db.session.query(EUD).filter_by(uid=eud_uid).first()

    if not eud:
        return {'success': False, 'error': 'EUD {} not found'.format(eud_uid)}, 404, {
            'Content-Type': 'application/json'}
    elif eud.user_id and not current_user.has_role('administrator') and current_user.id != eud.user_id:
        return ({'success': False, 'error': '{} is already assigned to another user'.format(eud.uid)}, 403,
                {'Content-Type': 'application/json'})
    else:
        eud.user_id = user.id
        db.session.add(eud)
        db.session.commit()

        return jsonify({'success': True})


@api_blueprint.route('/api/eud')
@auth_required()
def get_euds():
    query = db.session.query(EUD)

    if 'username' in request.args.keys():
        query = query.join(User, User.id == EUD.user_id)

    query = search(query, EUD, 'callsign')
    query = search(query, EUD, 'uid')
    query = search(query, User, 'username')

    return paginate(query)


@api_blueprint.route('/api/users')
@roles_accepted('administrator')
def get_users():
    query = db.session.query(User)
    query = search(query, User, 'username')

    return paginate(query)


@api_blueprint.route('/api/video_streams')
@auth_required()
def get_video_streams():
    query = db.session.query(VideoStream)
    query = search(query, VideoStream, 'username')
    query = search(query, VideoStream, 'protocol')
    query = search(query, VideoStream, 'path')
    query = search(query, VideoStream, 'uid')

    return paginate(query)


@api_blueprint.route('/api/truststore')
def get_truststore():
    return send_from_directory(app.config.get("OTS_CA_FOLDER"), 'truststore-root.p12', as_attachment=True)


def get_stream_protocol(source_type):
    protocol = "rtsp"
    if source_type.startswith('rtsps'):
        protocol = 'rtsps'
    if source_type.startswith('rtsp'):
        protocol = "rtsp"
    elif source_type == 'hlsSource':
        protocol = "hls"
    elif source_type == 'rpiCameraSource':
        protocol = "rpi_camera"
    elif source_type.startswith('rtmp'):
        protocol = 'rtmp'
    elif source_type.startswith('srt'):
        protocol = 'srt'
    elif source_type.startswith('udp'):
        protocol = 'udp'
    elif source_type.startswith('webRTC'):
        protocol = 'webrtc'

    return protocol


@api_blueprint.route('/api/mediamtx/webhook')
def mediamtx_webhook():
    token = request.args.get('token')
    if not token or bleach.clean(token) != app.config.get("OTS_MEDIAMTX_TOKEN"):
        logger.error('Invalid token')
        return jsonify({'success': False, 'error': 'Invalid token'}), 401

    event = bleach.clean(request.args.get('event'))
    if event == 'init':
        rtsp_port = bleach.clean(request.args.get("rtsp_port"))
        path = bleach.clean(request.args.get("path"))

        if path == 'startup':
            paths = VideoStream.query.all()
            for path in paths:
                r = requests.post("{}/v3/config/paths/add/{}".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), path.path),
                                  json=json.loads(path.mediamtx_settings))
                logger.debug("Init added {} {}".format(path, r.status_code))

            # Get all paths from MediaMTX and make sure they're in OTS's database
            r = requests.get("{}/v3/paths/list".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS")))
            paths = r.json()
            for path in paths['items']:
                video_stream = db.session.query(VideoStream).where(VideoStream.path == path['name']).first()
                if not video_stream:
                    if not path['source']:
                        continue
                    video_stream = VideoStream()
                    video_stream.protocol = get_stream_protocol(path['source']['type'])

                    r = requests.get("{}/v3/config/global/get".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS")))
                    video_stream.port = r.json()['rtspAddress'].replace(":", "")

                    r = requests.get("{}/v3/config/paths/get/{}".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), path['name']))
                    video_stream.mediamtx_settings = json.dumps(r.json())

                    video_stream.path = path['name']
                    video_stream.alias = path['name']
                    video_stream.rtsp_reliable = 1
                    video_stream.ready = event == 'ready'
                    video_stream.rover_port = -1
                    video_stream.ignore_embedded_klv = False
                    video_stream.buffer_time = None
                    video_stream.network_timeout = 10000
                    video_stream.uid = str(uuid.uuid4())
                    video_stream.generate_xml(urlparse(request.url_root).hostname)

                    db.session.add(video_stream)
                    db.session.commit()

    elif event == 'connect':
        connection_type = bleach.clean(request.args.get("connection_type"))
        connection_id = bleach.clean(request.args.get("connection_id"))
        rtsp_port = bleach.clean(request.args.get("rtsp_port"))
    elif event == 'ready' or event == 'notready':
        rtsp_port = bleach.clean(request.args.get("rtsp_port"))
        path = bleach.clean(request.args.get("path"))
        query = bleach.clean(request.args.get("query"))
        source_type = bleach.clean(request.args.get("source_type"))
        source_id = bleach.clean(request.args.get("source_id"))

        video_stream = db.session.query(VideoStream).where(VideoStream.path == path).first()
        if video_stream:
            video_stream.ready = event == 'ready'
            db.session.add(video_stream)
            db.session.commit()
            r = requests.patch("{}/v3/config/paths/patch/{}".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), path),
                               json=json.loads(video_stream.mediamtx_settings))
            logger.debug("Ready Patched path {}: {} - {}".format(path, r.status_code, r.text))
        else:
            video_stream = VideoStream()
            if source_type.startswith('rtsps'):
                video_stream.protocol = 'rtsps'
            if source_type.startswith('rtsp'):
                video_stream.protocol = "rtsp"
            elif source_type == 'hlsSource':
                video_stream.protocol = "hls"
            elif source_type == 'rpiCameraSource':
                video_stream.protocol = "rpi_camera"
            elif source_type.startswith('rtmp'):
                video_stream.protocol = 'rtmp'
            elif source_type.startswith('srt'):
                video_stream.protocol = 'srt'
            elif source_type.startswith('udp'):
                video_stream.protocol = 'udp'
            elif source_type.startswith('webRTC'):
                video_stream.protocol = 'webrtc'

            # video_stream.query = query
            video_stream.port = rtsp_port
            video_stream.path = path
            video_stream.alias = path
            video_stream.rtsp_reliable = 1
            video_stream.ready = event == 'ready'
            video_stream.rover_port = -1
            video_stream.ignore_embedded_klv = False
            video_stream.buffer_time = None
            video_stream.network_timeout = 10000
            video_stream.uid = str(uuid.uuid4())
            video_stream.generate_xml(urlparse(request.url_root).hostname)
            mediamtx_settings = MediaMTXPathConfig(None)
            mediamtx_settings.sourceOnDemand.data = source_id is not None
            mediamtx_settings.record.data = False
            video_stream.mediamtx_settings = json.dumps(mediamtx_settings.serialize())

            db.session.add(video_stream)
            db.session.commit()

        if event == 'ready':
            os.makedirs(os.path.join(app.config.get('OTS_DATA_FOLDER'), "mediamtx", "recordings", video_stream.path), exist_ok=True)

            (ffmpeg.input(video_stream.to_json()['rtsp_link'] + "?token={}".format(app.config.get("OTS_MEDIAMTX_TOKEN")))
             .output(os.path.join(app.config.get('OTS_DATA_FOLDER'), "mediamtx", "recordings", video_stream.path,
                                  "thumbnail.png"), vframes=1)
             .overwrite_output().run(capture_stdout=True, capture_stderr=True, quiet=True))

    elif event == 'read':
        rtsp_port = bleach.clean(request.args.get("rtsp_port"))
        path = bleach.clean(request.args.get("path"))
        query = bleach.clean(request.args.get("query"))
        reader_type = bleach.clean(request.args.get("reader_type"))
        reader_id = bleach.clean(request.args.get("reader_id"))
    elif event == 'disconnect':
        connection_type = bleach.clean(request.args.get("connection_type"))
        connection_id = bleach.clean(request.args.get("connection_id"))
        rtsp_port = bleach.clean(request.args.get("rtsp_port"))
    elif event == 'segment_record':
        recording = VideoRecording()
        recording.segment_path = bleach.clean(request.args.get('segment_path'))
        recording.path = bleach.clean(request.args.get('path'))
        recording.in_progress = True
        recording.start_time = datetime.datetime.now()

        with (app.app_context()):
            try:
                db.session.add(recording)
                db.session.commit()
            except sqlalchemy.exc.IntegrityError:
                db.session.rollback()
                db.session.execute(update(VideoRecording).filter(VideoRecording.segment_path == recording.segment_path)
                                   .values(**recording.serialize()))
                db.session.commit()
    elif event == 'segment_record_complete':
        segment_path = bleach.clean(request.args.get("segment_path"))
        with app.app_context():
            recording = db.session.execute(db.session.query(VideoRecording)
                                           .filter(VideoRecording.segment_path == segment_path)).first()
            if recording and recording.count:
                recording = recording[0]
                recording.in_progress = False
                recording.stop_time = datetime.datetime.now()
                recording.duration = (recording.stop_time - recording.start_time).seconds
            else:
                recording = VideoRecording()
                recording.segment_path = bleach.clean(request.args.get('segment_path'))
                recording.path = bleach.clean(request.args.get('path'))
                recording.in_progress = False
                recording.stop_time = datetime.datetime.now()

            try:
                probe = ffmpeg.probe(recording.segment_path)
                for stream in probe['streams']:
                    if stream['codec_type'].lower() == 'video':
                        recording.width = stream['width']
                        recording.height = stream['height']
                        recording.video_bitrate = stream['bit_rate']
                        recording.video_codec = stream['codec_name']
                        ffmpeg.input(recording.segment_path, ss="00:00:01").filter('scale', stream['width'], -1).output(
                            recording.segment_path + ".png", vframes=1).overwrite_output().run(capture_stdout=True,
                                                                                               capture_stderr=True,
                                                                                               quiet=True)
                    elif stream['codec_type'].lower() == 'audio':
                        recording.audio_codec = stream['codec_name']
                        recording.audio_samplerate = stream['sample_rate']
                        recording.audio_channels = stream['channels']
                        recording.audio_bitrate = stream['bit_rate']
                if 'format' in probe and 'size' in probe['format']:
                    recording.file_size = probe['format']['size']
            except:
                pass

            db.session.add(recording)
            db.session.commit()
        pass

    return '', 200


@api_blueprint.route('/api/mediamtx/stream/add', methods=['POST'])
@api_blueprint.route('/api/mediamtx/stream/update', methods=['PATCH'])
@auth_required()
def add_update_stream():
    try:
        form = MediaMTXPathConfig(formdata=ImmutableMultiDict(request.json))
        if not form.validate():
            return jsonify({'success': False, 'errors': form.errors}), 400

        path = bleach.clean(request.json.get("path", ""))

        if not path:
            return jsonify({'success': False, 'error': 'Please specify a path name'}), 400

        if path.startswith("/"):
            return jsonify({'success': False, 'error': 'Path cannot begin with a slash'}), 400

        video = db.session.query(VideoStream).where(VideoStream.path == path).first()
        if not video and request.path.endswith('add'):
            video = VideoStream()
            video.path = path
            video.username = current_user.username
            video.mediamtx_settings = json.dumps(form.serialize())
            video.rover_port = -1
            video.ignore_embedded_klv = False
            video.buffer_time = None
            video.rtsp_reliable = 1
            video.network_timeout = 10000
            video.generate_xml(urlparse(request.url_root).hostname)
            db.session.add(video)
            db.session.commit()
        elif not video and request.path.endswith('update'):
            return jsonify({'success': False, 'error': 'Path {} not found'.format(path)}), 400

        settings = json.loads(video.mediamtx_settings)

        for setting in request.json:
            if setting == 'csrf_token' or setting == 'sourceOnDemand' or setting == 'path':
                continue
            key = bleach.clean(setting)
            value = request.json.get(setting)
            if isinstance(value, str):
                value = bleach.clean(value)
            if value is not None:
                settings[key] = value
                logger.debug("set {} to {}".format(key, value))

        if request.path.endswith('update'):
            r = requests.patch("{}/v3/config/paths/patch/{}".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), path), json=settings)
        else:
            r = requests.post("{}/v3/config/paths/add/{}".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), path), json=settings)

        if r.status_code == 200:
            logger.debug("Patched path {}: {}".format(path, r.status_code))
            video.mediamtx_settings = json.dumps(settings)
            db.session.add(video)
            db.session.commit()
            return jsonify({'success': True})

        else:
            action = 'add' if request.path.endswith('add') else 'update'
            logger.error("Failed to {} mediamtx path: {} - {}".format(action, r.status_code, r.json()['error']))
            return jsonify({'success': False, 'error': r.json()['error']}), 400

    except BaseException as e:
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500


@api_blueprint.route('/api/mediamtx/stream/delete', methods=['DELETE'])
@auth_required()
def delete_stream():
    try:
        path = bleach.clean(request.args.get("path", ""))

        if not path:
            return jsonify({'success': False, 'error': 'Please specify a path name'}), 400

        r = requests.delete('{}/v3/config/paths/delete/{}'.format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), path))
        logger.debug("Delete status code: {}".format(r.status_code))
        video = db.session.query(VideoStream).filter(VideoStream.path == path)
        if not video:
            return jsonify({'success': False, 'error': 'Path {} not found'.format(path)}), 400

        video.delete()
        db.session.commit()
    except requests.exceptions.ConnectionError as e:
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'MediaMTX is not running'}), 500

    if r.status_code != 404:
        return r.text, r.status_code
    else:
        return "", 200


@api_blueprint.route('/api/markers')
@auth_required()
def get_markers():
    query = db.session.query(Marker)
    query = search(query, Marker, 'uid')
    query = search(query, Marker, 'affiliation')
    query = search(query, Marker, 'callsign')

    return paginate(query)


@api_blueprint.route('/api/map_state')
@auth_required()
def get_map_state():
    try:
        results = {'euds': [], 'markers': [], 'rb_lines': [], 'casevacs': []}

        euds = db.session.execute(db.session.query(EUD)).all()
        for eud in euds:
            results['euds'].append(eud[0].to_json())

        markers = db.session.execute(
            db.session.query(Marker).join(CoT).filter(CoT.stale >= datetime.datetime.now())).all()
        for marker in markers:
            results['markers'].append(marker[0].to_json())

        rb_lines = db.session.execute(
            db.session.query(RBLine).join(CoT).filter(CoT.stale >= datetime.datetime.now())).all()
        for rb_line in rb_lines:
            results['rb_lines'].append(rb_line[0].to_json())

        casevacs = db.session.execute(
            db.session.query(CasEvac).join(CoT).filter(CoT.stale >= datetime.datetime.now())).all()
        for casevac in casevacs:
            results['casevacs'].append(casevac[0].to_json())

    except BaseException as e:
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify(results)


@api_blueprint.route('/api/icon')
@auth_required()
def get_icon():
    query = db.session.query(Icon)
    query = search(query, Icon, 'filename')
    query = search(query, Icon, 'groupName')
    query = search(query, Icon, 'type2525b')

    return paginate(query)


@api_blueprint.route('/api/itak_qr_string')
@auth_required()
def get_settings():
    url = urlparse(request.url_root).hostname
    return "OpenTAKServer_{},{},{},SSL".format(url, url, app.config.get("OTS_SSL_STREAMING_PORT"))
