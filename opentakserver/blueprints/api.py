import datetime
import hashlib
import os
import traceback
import uuid
from shutil import copyfile

import bleach
import psutil
import sqlalchemy.exc
from flask import current_app as app, request, Blueprint, jsonify, send_from_directory
from flask_security import auth_required, roles_accepted, hash_password, current_user, \
    admin_change_password, verify_password

from extensions import logger, db

from config import Config
from models.Alert import Alert
from models.CasEvac import CasEvac
from models.CoT import CoT
from models.DataPackage import DataPackage
from models.EUD import EUD
from models.ZMIST import ZMIST
from models.point import Point
from models.user import User
from models.Certificate import Certificate
from models.Video import Video

from opentakserver.SocketServer import SocketServer
from opentakserver.certificate_authority import CertificateAuthority

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
        results['results'].append(row.serialize())

    return jsonify(results)


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
    vmem_dict = {'total': vmem.total, 'available': vmem.available, 'used': vmem.used, 'free': vmem.free, 'percent': vmem.percent}

    disk_usage = psutil.disk_usage('/')
    disk_usage_dict = {'total': disk_usage.total, 'used': disk_usage.used, 'free': disk_usage.free, 'percent': disk_usage.percent}

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

    response = {
        'tcp': app.tcp_thread.is_alive(), 'ssl': app.ssl_thread.is_alive(), 'cot_router': app.cot_thread.iothread.is_alive(),
        'online_euds': app.cot_thread.online_euds, 'system_boot_time': system_boot_time.strftime("%Y-%m-%d %H:%M:%SZ"),
        'system_uptime': system_uptime.total_seconds(), 'ots_start_time': app.start_time.strftime("%Y-%m-%d %H:%M:%SZ"),
        'ots_uptime': ots_uptime.total_seconds(), 'cpu_time': cpu_time_dict, 'cpu_percent': p.cpu_percent(),
        'load_avg': psutil.getloadavg(), 'memory': vmem_dict, 'disk_usage': disk_usage_dict, 'temps': temps_dict,
        'fans': fans_dict, 'battery': battery_dict, 'ots_version': app.config.get("OTS_VERSION")
    }

    return jsonify(response)


@api_blueprint.route('/api/tcp/<action>')
@roles_accepted('administrator')
def control_tcp_socket(action):
    action = bleach.clean(action).lower()

    if action == 'start':
        if app.tcp_thread.is_alive():
            return jsonify({'success': False, 'error': 'TCP thread is already active'}), 400

        tcp_thread = SocketServer(logger, app.config.get("OTS_TCP_STREAMING_PORT"))
        tcp_thread.start()
        app.tcp_thread = tcp_thread

        return jsonify({'success': True})

    elif action == 'stop':
        if not app.tcp_thread.is_alive():
            return jsonify({'success': False, 'error': 'TCP thread is not active'}), 400

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

        ssl_thread = SocketServer(logger, app.config.get("OTS_SSL_STREAMING_PORT"), True)
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
@roles_accepted('administrator')
def certificate():
    if request.method == 'POST' and 'callsign' in request.json.keys() and 'uid' in request.json.keys():
        try:
            callsign = bleach.clean(request.json.get('callsign'))
            truststore_filename = os.path.join(Config.OTS_CA_FOLDER, 'certs',
                                               Config.OTS_SERVER_ADDRESS,
                                               "truststore-root.p12")
            user_filename = os.path.join(Config.OTS_CA_FOLDER, 'certs', callsign,
                                         "{}.p12".format(callsign))

            eud = db.session.execute(db.session.query(EUD).where(EUD.callsign == callsign)).first()

            if not eud:
                return ({'success': False, 'error': 'Invalid callsign: {}'.format(callsign)}, 400,
                        {'Content-Type': 'application/json'})

            eud = eud[0]

            ca = CertificateAuthority(logger, app)
            filename = ca.issue_certificate(callsign, False)

            file_hash = hashlib.file_digest(open(os.path.join(Config.OTS_CA_FOLDER, 'certs', callsign, filename),
                                                 'rb'), 'sha256').hexdigest()

            data_package = DataPackage()
            data_package.filename = filename
            data_package.keywords = "public"
            data_package.creator_uid = str(uuid.uuid4())
            data_package.submission_time = datetime.datetime.now().isoformat() + "Z"
            data_package.mime_type = "application/x-zip-compressed"
            data_package.size = os.path.getsize(os.path.join(Config.OTS_CA_FOLDER, 'certs', callsign, filename))
            data_package.hash = file_hash
            data_package.submission_user = current_user.id

            try:
                db.session.add(data_package)
                db.session.commit()
            except sqlalchemy.exc.IntegrityError as e:
                db.session.rollback()
                logger.error(e)
                return ({'success': False, 'error': 'Certificate already exists for {}'.format(callsign)}, 400,
                        {'Content-Type': 'application/json'})

            copyfile(os.path.join(Config.OTS_CA_FOLDER, 'certs', callsign, "{}_DP.zip".format(callsign)),
                     os.path.join(Config.UPLOAD_FOLDER, "{}.zip".format(file_hash)))

            cert = Certificate()
            cert.common_name = callsign
            cert.callsign = callsign
            cert.expiration_date = datetime.datetime.today() + datetime.timedelta(days=Config.OTS_CA_EXPIRATION_TIME)
            cert.server_address = Config.OTS_SERVER_ADDRESS
            cert.server_port = Config.OTS_SSL_STREAMING_PORT
            cert.truststore_filename = truststore_filename
            cert.user_cert_filename = user_filename
            cert.cert_password = Config.OTS_CA_PASSWORD
            cert.data_package_id = data_package.id
            cert.eud_uid = eud.uid

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

        return paginate(query)


@api_blueprint.route('/api/me')
@auth_required()
def me():
    me = db.session.execute(db.session.query(User).where(User.id == current_user.id)).first()[0]
    return jsonify(me.serialize())


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

    return send_from_directory(Config.UPLOAD_FOLDER, "{}.zip".format(file_hash), as_attachment=True,
                               download_name=data_package[0].filename)


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


@api_blueprint.route("/api/user/create", methods=['POST'])
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
        return {'success': False, 'error': 'Failed to delete user: {}'.format(e)}

    db.session.commit()
    return {'success': True}, 200, {'Content-Type': 'application/json'}


@api_blueprint.route("/api/user/password/reset", methods=['POST'])
@roles_accepted("administrator")
def admin_reset_password():
    username = bleach.clean(request.json.get("username"))
    new_password = bleach.clean(request.json.get("new_password"))

    user = app.security.datastore.find_user(username=username)
    if user:
        admin_change_password(user, new_password, False)
        return {'success': True}, 200, {'Content-Type': 'application/json'}
    else:
        return ({'success': False, 'error': 'Could not find user {}'.format(username)}, 400,
                {'Content-Type': 'application/json'})


# This is mainly for mediamtx authentication
@api_blueprint.route('/api/external_auth', methods=['POST'])
def external_auth():
    username = bleach.clean(request.json.get('user'))
    password = bleach.clean(request.json.get('password'))
    action = bleach.clean(request.json.get('action'))

    user = app.security.datastore.find_user(username=username)
    if user and verify_password(password, user.password):
        if action == 'publish':
            v = Video()
            v.uid = bleach.clean(request.json.get('id'))
            v.rover_port = -1
            v.ignore_embedded_klv = False
            v.buffer_time = 5000
            v.network_timeout = 10000
            v.protocol = bleach.clean(request.json.get('protocol'))
            v.address = Config.OTS_SERVER_ADDRESS
            v.path = "/" + bleach.clean(request.json.get('path'))
            v.alias = v.path.split("/")[-1]
            v.username = bleach.clean(request.json.get('user'))

            if v.protocol == 'rtsp':
                v.port = 8554
                v.rtsp_reliable = 1
            elif v.protocol == 'rtmp':
                v.port = 1935
                v.rtsp_reliable = 0
            else:
                v.rtsp_reliable = 0

            v.generate_xml()

            with app.app_context():
                try:
                    db.session.add(v)
                    db.session.commit()
                    logger.debug("Inserted video stream {}".format(v.uid))
                except sqlalchemy.exc.IntegrityError as e:
                    db.session.rollback()

        return '', 200
    else:
        return '', 401


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
@auth_required()
def get_users():
    query = db.session.query(User)
    query = search(query, User, 'username')

    return paginate(query)


@api_blueprint.route('/api/video_streams')
@auth_required()
def get_video_streams():
    query = db.session.query(Video)
    query = search(query, Video, 'username')
    query = search(query, Video, 'protocol')
    query = search(query, Video, 'address')
    query = search(query, Video, 'path')
    query = search(query, Video, 'uid')

    return paginate(query)


@api_blueprint.route('/api/truststore')
def get_truststore():
    logger.info("truststore {}".format(os.path.join(app.config.get("OTS_CA_FOLDER"), 'truststore-root.p12')))
    return send_from_directory(app.config.get("OTS_CA_FOLDER"), 'truststore-root.p12', as_attachment=True)
