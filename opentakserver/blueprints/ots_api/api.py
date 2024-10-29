import datetime
import hashlib
import os
import platform
import traceback
import uuid
from shutil import copyfile

from urllib.parse import urlparse

import yaml

import bleach
import psutil
import sqlalchemy.exc
from flask import current_app as app, request, Blueprint, jsonify, send_from_directory
from flask_security import auth_required, roles_accepted, current_user, verify_password

from opentakserver.extensions import logger, db

from opentakserver.models.Alert import Alert
from opentakserver.models.CasEvac import CasEvac
from opentakserver.models.CoT import CoT
from opentakserver.models.DataPackage import DataPackage
from opentakserver.models.EUD import EUD
from opentakserver.models.ZMIST import ZMIST
from opentakserver.models.Point import Point
from opentakserver.models.user import User
from opentakserver.models.Certificate import Certificate
from opentakserver.models.APSchedulerJobs import APSchedulerJobs

from opentakserver.SocketServer import SocketServer
from opentakserver.certificate_authority import CertificateAuthority
from opentakserver.models.Icon import Icon
from opentakserver.models.Marker import Marker
from opentakserver.models.RBLine import RBLine
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


@api_blueprint.route('/files/api/config')
def cloudtak_config():
    return jsonify({'uploadSizeLimit': 400})


@api_blueprint.route('/api/health')
def health():
    if not app.cot_thread.iothread.is_alive():
        return jsonify({'status': 'down', 'error': 'cot thread is dead'}), 503

    return jsonify({'status': 'healthy'})


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
    if hasattr(psutil, 'sensors_fans') and psutil:
        for name, value in psutil.sensors_fans().items():
            for val in value:
                fans_dict[name][val.label] = {val.current}

    battery_dict = {}
    if hasattr(psutil, "sensors_battery") and psutil.sensors_battery():
        battery = psutil.sensors_battery().items()
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
                data_package.creator_uid = request.json['uid'] if 'uid' in request.json.keys() else None
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
    logger.info(request.headers)
    logger.info(request.accept_encodings)
    me = db.session.execute(db.session.query(User).where(User.id == current_user.id)).first()[0]
    return jsonify(me.serialize())


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


@api_blueprint.route('/api/rabbitmq/<path>', methods=['POST'])
def rabbitmq_auth(path):
    # https://github.com/rabbitmq/rabbitmq-server/tree/v3.13.x/deps/rabbitmq_auth_backend_http

    # Only allow requests to this route from the RabbitMQ server
    if request.remote_addr != app.config.get("OTS_RABBITMQ_SERVER_ADDRESS"):
        return 'deny', 200

    user = None
    if 'username' in request.form.keys():
        user = app.security.datastore.find_user(username=bleach.clean(request.form.get('username')))

    if user and 'password' in request.form.keys():
        if user.active and verify_password(bleach.clean(request.form.get('password')), user.password):
            if user.has_role("administrator"):
                return 'allow administrator', 200
            return 'allow', 200
        else:
            return 'deny', 200
    # Always allow when path is topic, resource, or vhost if the user exists.
    # This only occurs after the user has been successfully authenticated
    elif user:
        return 'allow', 200
    else:
        return 'deny', 200


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


@api_blueprint.route('/api/truststore')
def get_truststore():
    filename = f"truststore_root_{urlparse(request.url_root).hostname}.p12"
    return send_from_directory(app.config.get("OTS_CA_FOLDER"), 'truststore-root.p12', download_name=filename, as_attachment=True)


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
