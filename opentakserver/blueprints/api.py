import datetime
import hashlib
import os
import traceback
import uuid
from shutil import copyfile

import bleach
import sqlalchemy.exc
from flask import current_app as app, request, Blueprint, jsonify
from flask_security import auth_required, roles_accepted, permissions_accepted, hash_password, current_user, \
    admin_change_password, verify_password
from extensions import logger, db
from sqlalchemy import update

from AtakOfTheCerts import AtakOfTheCerts
from config import Config
from models.Alert import Alert
from models.CasEvac import CasEvac
from models.CoT import CoT
from models.DataPackage import DataPackage
from models.EUD import EUD
from models.VideoStream import VideoStream
from models.ZMIST import ZMIST
from models.point import Point
from models.UsersEUDs import UsersEuds
from models.user import User

api_blueprint = Blueprint('api_blueprint', __name__)


@api_blueprint.route("/api/certificate", methods=['GET', 'POST'])
@roles_accepted('administrator')
def certificate():
    if request.method == 'POST' and 'common_name' in request.json.keys():
        try:
            common_name = bleach.clean(request.json.get('common_name'))
            aotc = AtakOfTheCerts(logger=logger, pwd=Config.CERT_PASSWORD, ca_storage=Config.CA_FOLDER,
                                  maximum_days=Config.CA_EXPIRATION_TIME)
            aotc.issue_certificate(hostname=common_name, common_name=common_name, cert_password=Config.CERT_PASSWORD)
            filename = aotc.generate_zip(server_address=Config.SERVER_DOMAIN_OR_IP,
                                         server_filename=os.path.join(Config.CA_FOLDER, 'certs',
                                                                      Config.SERVER_DOMAIN_OR_IP,
                                                                      "{}.p12".format(Config.SERVER_DOMAIN_OR_IP)),
                                         user_filename=os.path.join(Config.CA_FOLDER, 'certs', common_name,
                                                                    "{}.p12".format(common_name)))
            file_hash = hashlib.file_digest(open(os.path.join(Config.CA_FOLDER, 'certs', common_name, filename),
                                                 'rb'), 'sha256').hexdigest()
            data_package = DataPackage()
            data_package.filename = filename
            data_package.keywords = "public"
            data_package.creator_uid = str(uuid.uuid4())
            data_package.submission_time = datetime.datetime.now().isoformat() + "Z"
            data_package.mime_type = "application/x-zip-compressed"
            data_package.size = os.path.getsize(os.path.join(Config.CA_FOLDER, 'certs', common_name, filename))
            data_package.hash = file_hash
            data_package.submission_user = current_user.id
            db.session.add(data_package)
            db.session.commit()

            copyfile(os.path.join(Config.CA_FOLDER, 'certs', common_name, "{}_DP.zip".format(common_name)),
                     os.path.join(Config.UPLOAD_FOLDER, "{}.zip".format(file_hash)))

            return '', 200
        except BaseException as e:
            logger.error(traceback.format_exc())
            return {'error': str(e)}, 500, {'Content-Type': 'application/json'}


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
            video_stream = VideoStream()
            video_stream.id = bleach.clean(request.json.get('id'))
            video_stream.ip = bleach.clean(request.json.get('ip'))
            video_stream.username = bleach.clean(request.json.get('user'))
            video_stream.path = bleach.clean(request.json.get('path'))
            video_stream.protocol = bleach.clean(request.json.get('protocol'))
            video_stream.action = bleach.clean(request.json.get('action'))
            video_stream.query = bleach.clean(request.json.get('query'))

            with app.app_context():
                try:
                    db.session.add(video_stream)
                    db.session.commit()
                    logger.debug("Inserted video stream {}".format(video_stream.id))
                except sqlalchemy.exc.IntegrityError:
                    db.session.rollback()
                    db.session.execute(update(VideoStream).where(VideoStream.ip == video_stream.ip and
                                                                 VideoStream.path == video_stream.path)
                                       .values(id=video_stream.id, username=video_stream.username,
                                               protocol=video_stream.protocol, action=video_stream.action,
                                               query=video_stream.query))
                    db.session.commit()
                    logger.debug("Updated video stream {}".format(video_stream.id))

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
