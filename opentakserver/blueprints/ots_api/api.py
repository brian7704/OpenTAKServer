import datetime
import hashlib
import json
import os
import platform
import traceback
from shutil import copyfile

from urllib.parse import urlparse

import pika
import yaml

import bleach
import psutil
import sqlalchemy.exc
from flask import current_app as app, request, Blueprint, jsonify, send_from_directory, session
from flask_ldap3_login import AuthenticationResponseStatus
from flask_security import auth_required, current_user, verify_password
from flask_babel import gettext
from sqlalchemy import select

from opentakserver.extensions import logger, db, ldap_manager, babel

from opentakserver.models.Alert import Alert
from opentakserver.models.CasEvac import CasEvac
from opentakserver.models.CoT import CoT
from opentakserver.models.DataPackage import DataPackage
from opentakserver.models.EUD import EUD
from opentakserver.models.Group import Group
from opentakserver.models.GroupUser import GroupUser
from opentakserver.models.Token import Token
from opentakserver.models.ZMIST import ZMIST
from opentakserver.models.Point import Point
from opentakserver.models.user import User
from opentakserver.models.Certificate import Certificate
from opentakserver.models.APSchedulerJobs import APSchedulerJobs

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


def paginate(query: db.Query, model=None):
    try:
        page = int(request.args.get('page')) if 'page' in request.args else 1
        per_page = int(request.args.get('per_page')) if 'per_page' in request.args else 10
    except ValueError:
        return {'success': False, 'error': 'Invalid page or per_page number'}, 400, {'Content-Type': 'application/json'}

    try:
        if model:
            sort_by = request.args.get("sort_by")
            sort_direction = request.args.get("sort_direction")
            logger.warning(f"sort_by: {sort_by} direction: {sort_direction}")
            if sort_by and (sort_direction == "asc" or not sort_direction):
                query = query.order_by(getattr(model, sort_by).asc())
            elif sort_by and sort_direction == "desc":
                query = query.order_by(getattr(model, sort_by).desc())

            logger.warning(query)
    except BaseException as e:
        return jsonify({"success": False, "error": gettext("Invalid sort column: %(sort_by)s", sort_by=request.args.get("sort_by"))}), 400

    pagination = db.paginate(query, page=page, per_page=per_page)
    rows = pagination.items

    results = {'results': [], 'total_pages': pagination.pages, 'current_page': page, 'per_page': per_page, 'total': 0}

    for row in rows:
        mission = row.to_json()
        # Filter out duplicate results caused by missions belonging to multiple groups
        if mission not in results['results']:
            results['results'].append(row.to_json())

    results["total"] = pagination.total

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


def route_cot(event: str, user: User):
    """Used by API endpoints such as ``/api/markers`` to route CoT messages to the correct groups that a user belongs to.

    :param event: The CoT to be routed as a string
    :param user: The user object
    :return: None
    """

    rabbit_credentials = pika.PlainCredentials(app.config.get("OTS_RABBITMQ_USERNAME"), app.config.get("OTS_RABBITMQ_PASSWORD"))
    rabbit_host = app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")
    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbit_host, credentials=rabbit_credentials))
    channel = rabbit_connection.channel()

    group_memberships = db.session.execute(db.session.query(GroupUser).filter_by(user_id=user.id, direction=Group.IN, enabled=True)).all()
    if not group_memberships:
        # Default to the __ANON__ group if the user doesn't belong to any IN groups
        channel.basic_publish(exchange='groups', routing_key="__ANON__.OUT", body=json.dumps({'uid': app.config['OTS_NODE_ID'], 'cot': str(event)}),
                              properties=pika.BasicProperties(expiration=app.config.get("OTS_RABBITMQ_TTL")))

    for membership in group_memberships:
        membership = membership[0]
        channel.basic_publish(exchange='groups', routing_key=f"{membership.group.name}.{Group.OUT}",
                              body=json.dumps({'uid': app.config['OTS_NODE_ID'], 'cot': str(event)}),
                              properties=pika.BasicProperties(expiration=app.config.get("OTS_RABBITMQ_TTL")))
    channel.close()
    rabbit_connection.close()


@api_blueprint.route('/files/api/config')
def cloudtak_config():
    """Required by CloudTAK, returns the following

    .. code-block:: json

        {"uploadSizeLimit": 400}
    """
    return jsonify({'uploadSizeLimit': 400})


# Simple health check for docker
@api_blueprint.route('/api/health')
def health():
    """Health check for Docker, returns the following

    .. code-block:: json
        {"status": "healthy"}
    """
    return jsonify({'status': 'healthy'})


@api_blueprint.route('/api/status')
@auth_required()
def status():
    """Server status used on the Dashboard page of the web UI

    :rtype: dict
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    system_boot_time = datetime.datetime.fromtimestamp(psutil.boot_time(), datetime.datetime.now().astimezone().tzinfo)
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

    try:
        os_release = platform.freedesktop_os_release()
    except:
        os_release = {'NAME': None, 'PRETTY_NAME': None, 'VERSION': None, 'VERSION_CODENAME': None}

    uname = {'system': platform.system(), 'node': platform.node(), 'release': platform.release(),
             'version': platform.version(), 'machine': platform.machine()}

    online_euds = db.session.execute(select(EUD).filter(EUD.last_status == 'Connected')).all()

    response = {
        'online_euds': len(online_euds), 'system_boot_time': system_boot_time.strftime("%Y-%m-%d %H:%M:%SZ"),
        'system_uptime': system_uptime.total_seconds(), 'ots_start_time': app.start_time.strftime("%Y-%m-%d %H:%M:%SZ"),
        'ots_uptime': ots_uptime.total_seconds(), 'cpu_time': cpu_time_dict, 'cpu_percent': p.cpu_percent(),
        'load_avg': psutil.getloadavg(), 'memory': vmem_dict, 'disk_usage': disk_usage_dict, 'ots_version': version,
        'uname': uname, 'os_release': os_release, 'python_version': platform.python_version()
    }

    return jsonify(response)


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
                return jsonify({'success': False, 'error': gettext(u'Invalid username: %(username)s', username=username)}), 400

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
                data_package.submission_time = datetime.datetime.now(datetime.timezone.utc)
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
                    return jsonify({'success': False, 'error': gettext(u'Certificate already exists for %(username)s', username=username)}), 400

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

            return jsonify({'success': True}), 200
        except BaseException as e:
            logger.error(traceback.format_exc())
            return jsonify({'success': False, 'error': str(e)}), 500
    elif request.method == 'POST':
        return jsonify({'success': False, 'error': gettext(u'Please specify a callsign')}), 400
    elif request.method == 'GET':
        query = db.session.query(Certificate)
        query = search(query, Certificate, 'callsign')
        query = search(query, Certificate, 'username')

        return paginate(query)


@api_blueprint.route('/api/me')
@auth_required()
def me():
    """Get the details of the currently logged in user

    :rtype: User
    """
    return jsonify(current_user.to_json())


@api_blueprint.route('/api/cot', methods=['GET'])
@auth_required()
def query_cot():
    """Get CoT messages. All parameters are optional.

    :param how: The how attribute of the CoT message, i.e. ``m-g``, ``h-g-i-g-o``
    :param type: The type attribute of the CoT message, i.e. ``a-f-G-U-C``
    :param sender_callsign: The callsign of the EUD that sent the CoT message
    :param sender_uid: The UID of the EUD that sent the CoT message
    :param page: The page number
    :param per_page: The number of results per page
    """
    query = db.session.query(CoT)
    query = search(query, CoT, 'how')
    query = search(query, CoT, 'type')
    query = search(query, CoT, 'sender_callsign')
    query = search(query, CoT, 'sender_uid')

    return paginate(query)


@api_blueprint.route("/api/alerts", methods=['GET'])
@auth_required()
def query_alerts():
    """Get alerts. All parameters are optional.

    :param uid: The alert's UID
    :param sender_uid: The UID of the EUD that sent the alert
    :param alert_type: The type of alert
    :param page: The page number
    :param per_page: The number of results per page
    """
    query = db.session.query(Alert)
    query = search(query, Alert, 'uid')
    query = search(query, Alert, 'sender_uid')
    query = search(query, Alert, 'alert_type')

    return paginate(query, Alert)


@api_blueprint.route("/api/point", methods=['GET'])
@auth_required()
def query_points():
    """Query points. All parameters are optional.

    :param uid: The point's UID
    :param callsign: The point's callsign
    :param page: The page number
    :param per_page: The number of results per page
    """
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

    username = bleach.clean(request.form.get('username'))
    password = None
    if 'password' in request.form.keys():
        password = bleach.clean(request.form.get('password'))

    if app.config.get("OTS_ENABLE_LDAP"):
        result = ldap_manager.authenticate(username, password)

        if result.status == AuthenticationResponseStatus.success:
            # Keep this import here to avoid a circular import when OTS is started
            from opentakserver.blueprints.ots_api.ldap_api import save_user

            save_user(result.user_dn, result.user_id, result.user_info, result.user_groups)

            for group in result.user_groups:
                if group['cn'] == app.config.get("OTS_LDAP_ADMIN_GROUP"):
                    return 'allow administrator', 200

            return 'allow', 200
        else:
            return 'deny', 200

    user = None
    if 'username' in request.form.keys():
        user = app.security.datastore.find_user(username=username)

    if user and 'password' in request.form.keys():
        if user.active and verify_password(password, user.password):
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
    """Query EUDS. All parameters are optional.

    :param callsign: The EUD's callsign
    :param uid: The EUD's callsign
    :param username: The username that the EUD belongs to
    :param page: The page number
    :param per_page: The number of results per page
    """

    if request.args.get("all"):
        all_euds = []
        euds = EUD.query.with_entities(EUD.uid, EUD.callsign).all()
        for eud in euds:
            if eud[0] and eud[1]:
                all_euds.append({"uid": eud[0], "callsign": eud[1]})
        return jsonify(all_euds)

    query = db.session.query(EUD)

    if 'username' in request.args.keys():
        query = query.join(User, User.id == EUD.user_id)

    query = search(query, EUD, 'callsign')
    query = search(query, EUD, 'uid')
    query = search(query, User, 'username')

    return paginate(query, EUD)


@api_blueprint.route('/api/truststore')
def get_truststore():
    """Downloads the server's truststore with no authentication required."""
    filename = f"truststore_root_{urlparse(request.url_root).hostname}.p12"
    return send_from_directory(app.config.get("OTS_CA_FOLDER"), 'truststore-root.p12', download_name=filename,
                               as_attachment=True)


@api_blueprint.route('/api/map_state')
@auth_required()
def get_map_state():
    """Gets the latest data to be displayed on the web UI's map"""
    try:
        results = {'euds': [], 'markers': [], 'rb_lines': [], 'casevacs': []}

        euds = db.session.execute(db.session.query(EUD)).all()
        for eud in euds:
            results['euds'].append(eud[0].to_json())

        markers = db.session.execute(
            db.session.query(Marker).join(CoT).filter(CoT.stale >= datetime.datetime.now(datetime.timezone.utc))).all()
        for marker in markers:
            results['markers'].append(marker[0].to_json())

        rb_lines = db.session.execute(
            db.session.query(RBLine).join(CoT).filter(CoT.stale >= datetime.datetime.now(datetime.timezone.utc))).all()
        for rb_line in rb_lines:
            results['rb_lines'].append(rb_line[0].to_json())

        casevacs = db.session.execute(
            db.session.query(CasEvac).join(CoT).filter(CoT.stale >= datetime.datetime.now(datetime.timezone.utc))).all()
        for casevac in casevacs:
            results['casevacs'].append(casevac[0].to_json())

    except BaseException as e:
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify(results)


@api_blueprint.route('/api/icon')
@auth_required()
def get_icon():
    """Query map icons. All parameters are optional.

    :param filename:
    :param groupName:
    :param type2525b:
    """
    query = db.session.query(Icon)
    query = search(query, Icon, 'filename')
    query = search(query, Icon, 'groupName')
    query = search(query, Icon, 'type2525b')

    return paginate(query)


@api_blueprint.route('/api/itak_qr_string')
@auth_required()
def get_settings():
    """The iTAK QR string in the following format:

    ``OpenTAKServer_SERVER-ADDRESS,SERVER-ADDRESS,8089,SSL``
    """
    url = urlparse(request.url_root).hostname
    return "OpenTAKServer_{},{},{},SSL".format(url, url, app.config.get("OTS_SSL_STREAMING_PORT"))
