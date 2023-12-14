import datetime
import hashlib
import os
import traceback
import uuid
from shutil import copyfile

import bleach
from flask import current_app as app, request, Blueprint, jsonify
from flask_security import auth_required, roles_accepted, permissions_accepted, hash_password, current_user, \
    admin_change_password
from extensions import logger, db

from opentakserver.AtakOfTheCerts import AtakOfTheCerts
from opentakserver.config import Config
from opentakserver.models.Alert import Alert
from opentakserver.models.CasEvac import CasEvac
from opentakserver.models.CoT import CoT
from opentakserver.models.DataPackage import DataPackage
from opentakserver.models.EUD import EUD
from opentakserver.models.ZMIST import ZMIST
from opentakserver.models.point import Point

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


@api_blueprint.route('/api/cot', methods=['GET'])
@auth_required()
def query_cot():
    logger.info(request.args)
    query = db.session.query(CoT)
    query = search(query, CoT, 'how')
    query = search(query, CoT, 'type')
    query = search(query, CoT, 'type')
    query = search(query, CoT, 'sender_callsign')
    query = search(query, CoT, 'sender_uid')

    rows = db.session.execute(query).scalars()

    return jsonify([row.serialize() for row in rows])


@api_blueprint.route("/api/eud", methods=['GET'])
@auth_required()
def query_euds():
    query = db.session.query(EUD)

    query = search(query, EUD, 'uid')
    query = search(query, EUD, 'callsign')

    rows = db.session.execute(query)

    result = []
    if rows:
        for row in rows:
            for r in row:
                result.append(r.serialize())

    return jsonify(result)


@api_blueprint.route("/api/alert", methods=['GET'])
@auth_required()
def query_alerts():
    query = (db.session.query(Alert, CoT, EUD, Point)
             .join(CoT, CoT.id == Alert.cot_id)
             .join(EUD, EUD.uid == Alert.sender_uid)
             .join(Point, Point.id == Alert.point_id))

    query = search(query, Alert, 'uid')
    query = search(query, Alert, 'sender_uid')
    query = search(query, Alert, 'alert_type')

    rows = db.session.execute(query)

    result = []
    if rows:
        for row in rows:
            for r in row:
                result.append(r.serialize())

    return jsonify(result)


@api_blueprint.route("/api/point", methods=['GET'])
@auth_required()
def query_points():
    query = (db.session.query(Point, CoT, EUD)
             .join(CoT, CoT.id == Point.cot_id)
             .join(EUD, EUD.uid == Point.device_uid))

    query = search(query, EUD, 'uid')
    query = search(query, EUD, 'callsign')

    rows = db.session.execute(query)

    result = []
    if rows:
        for row in rows:
            for r in row:
                result.append(r.serialize())

    return jsonify(result)


@api_blueprint.route("/api/casevac", methods=['GET'])
@auth_required()
def query_casevac():
    query = (db.session.query(CasEvac, CoT, EUD, Point)
             .join(CoT, CoT.id == CasEvac.cot_id)
             .join(EUD, EUD.uid == CasEvac.sender_uid)
             .join(Point, Point.id == CasEvac.point_id))

    query = search(query, EUD, 'callsign')
    query = search(query, CasEvac, 'sender_uid')
    query = search(query, CasEvac, 'uid')

    rows = db.session.execute(query)

    result = []
    if rows:
        for row in rows:
            for r in row:
                result.append(r.serialize())

    return jsonify(result)


@api_blueprint.route("/api/user/create", methods=['POST'])
@roles_accepted("administrator")
def create_user():
    username = bleach.clean(request.json.get('username'))
    password = bleach.clean(request.json.get('password'))
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
        logger.error("exists")
        return {'success': False, 'error': 'User {} already exists'.format(username)}, 409, {'Content-Type': 'application/json'}


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
