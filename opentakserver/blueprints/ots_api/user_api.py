import traceback

import bleach
from flask import current_app as app, request, Blueprint, jsonify
from flask_security import roles_accepted, hash_password, current_user, admin_change_password, auth_required

from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.extensions import logger, db
from opentakserver.models.EUD import EUD
from opentakserver.models.user import User

user_api_blueprint = Blueprint('user_api_blueprint', __name__)


@user_api_blueprint.route("/api/user/add", methods=['POST'])
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


@user_api_blueprint.route("/api/user/delete", methods=['POST'])
@roles_accepted("administrator")
def delete_user():
    username = bleach.clean(request.json.get('username'))

    if username == current_user.username:
        return jsonify({'success': False, 'error': "You can't delete your own account"}), 400

    logger.info("Deleting user {}".format(username))

    try:
        user = app.security.datastore.find_user(username=username)
        app.security.datastore.delete_user(user)
    except BaseException as e:
        logger.error(traceback.format_exc())
        return {'success': False, 'error': 'Failed to delete user: {}'.format(e)}, 400

    db.session.commit()
    return {'success': True}, 200, {'Content-Type': 'application/json'}


@user_api_blueprint.route("/api/user/password/reset", methods=['POST'])
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


@user_api_blueprint.route('/api/user/deactivate', methods=['POST'])
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


@user_api_blueprint.route('/api/user/activate', methods=['POST'])
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


@user_api_blueprint.route("/api/user/role", methods=['POST'])
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


@user_api_blueprint.route('/api/user/assign_eud', methods=['POST'])
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


@user_api_blueprint.route('/api/users')
@roles_accepted('administrator')
def get_users():
    query = db.session.query(User)
    query = search(query, User, 'username')

    return paginate(query)
