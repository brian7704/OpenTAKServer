import traceback

import bleach
import sqlalchemy
from flask import current_app as app, request, Blueprint, jsonify
from flask_babel import gettext
from flask_security import roles_accepted, hash_password, current_user, admin_change_password, auth_required

from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.extensions import logger, db, ldap_manager
from opentakserver.models.EUD import EUD
from opentakserver.models.Group import Group
from opentakserver.models.GroupUser import GroupUser
from opentakserver.models.user import User
from opentakserver.UsernameValidator import UsernameValidator

user_api_blueprint = Blueprint('user_api_blueprint', __name__)


@user_api_blueprint.route("/api/user/add", methods=['POST'])
@roles_accepted("administrator")
def create_user():
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': gettext(u'LDAP is enabled, please use your LDAP server to create users')}), 400

    username = bleach.clean(request.json.get('username'))
    password = bleach.clean(request.json.get('password'))
    confirm_password = bleach.clean(request.json.get('confirm_password'))

    validated_username = UsernameValidator(app).validate(username)
    if validated_username[0]:
        return jsonify({"success": False, "error": f"{validated_username[0]}"}), 400

    if password != confirm_password:
        return jsonify({'success': False, 'error': gettext(u'Passwords do not match')}), 400

    roles = request.json.get("roles")
    roles_cleaned = []

    for role in roles:
        role = bleach.clean(role)
        role_exists = app.security.datastore.find_role(role)

        if not role_exists:
            return jsonify({'success': False, 'error': gettext(u'Role %(role)s does not exist', role=role)}), 400

        elif role == 'administrator' and not current_user.has_role('administrator'):
            return jsonify({'success': False, 'error': gettext(u'Only administrators can add users to the administrators role')}), 403

        elif role not in roles_cleaned:
            roles_cleaned.append(role)

    if not app.security.datastore.find_user(username=username):
        logger.info("Creating user {}".format(username))
        app.security.datastore.create_user(username=username, password=hash_password(password), roles=roles_cleaned)
        db.session.commit()
        return jsonify({'success': True}), 200
    else:
        logger.error("User {} already exists".format(username))
        return jsonify({'success': False, 'error': gettext(u'User %(username)s already exists', username=username)}), 400


@user_api_blueprint.route("/api/user/delete", methods=['POST'])
@roles_accepted("administrator")
def delete_user():
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': gettext(u'LDAP is enabled, please use your LDAP server to delete users')}), 400

    username = bleach.clean(request.json.get('username'))

    if username == current_user.username:
        return jsonify({'success': False, 'error': gettext(u"You can't delete your own account")}), 400

    logger.info("Deleting user {}".format(username))

    try:
        user = app.security.datastore.find_user(username=username)
        db.session.execute(sqlalchemy.delete(GroupUser).where(GroupUser.user_id == user.id))
        app.security.datastore.delete_user(user)
    except BaseException as e:
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': gettext(u'Failed to delete user: %(e)s', e=str(e))}), 400

    db.session.commit()
    return jsonify({'success': True}), 200


@user_api_blueprint.route("/api/user/password/reset", methods=['POST'])
@roles_accepted("administrator")
def admin_reset_password():
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': gettext(u'LDAP is enabled, please use your LDAP server to reset passwords')}), 400

    username = bleach.clean(request.json.get("username"))
    new_password = bleach.clean(request.json.get("new_password"))

    if not username or not new_password:
        return jsonify({'success': False, 'error': gettext(u'Please specify a username and new password')}), 400

    if len(new_password) < app.config.get("SECURITY_PASSWORD_LENGTH_MIN"):
        return jsonify({'success': False, 'error': gettext(u'Your password must be at least %(characters)s characters long', characters=app.config.get("SECURITY_PASSWORD_LENGTH_MIN"))}), 400

    user = app.security.datastore.find_user(username=username)
    if user:
        admin_change_password(user, new_password, False)
        db.session.commit()
        return jsonify({'success': True}), 200
    else:
        return jsonify({'success': False, 'error': gettext(u'Could not find user %(username)s', username=username)}), 400


@user_api_blueprint.route('/api/user/deactivate', methods=['POST'])
@roles_accepted('administrator')
def deactivate_user():
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': gettext(u'LDAP is enabled, please use your LDAP server to deactivate users')}), 400

    username = bleach.clean(request.json.get("username", ""))
    if not username:
        return jsonify({'success': False, 'error': gettext(u'Please specify the username to deactivate')}), 400

    user = app.security.datastore.find_user(username=username)
    if not user:
        return jsonify({'success': False, 'error': gettext(u'User %(username)s does not exist', username=username)}), 400

    deactivated = app.security.datastore.deactivate_user(user)
    if deactivated:
        db.session.commit()
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': gettext('%(username)s is already deactivated', username=username)})


@user_api_blueprint.route('/api/user/activate', methods=['POST'])
@roles_accepted('administrator')
def activate_user():
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': gettext(u'LDAP is enabled, please use your LDAP server to activate users')}), 400

    username = bleach.clean(request.json.get("username", ""))
    if not username:
        return jsonify({'success': False, 'error': gettext(u'Please specify the username to activate')}), 400

    user = app.security.datastore.find_user(username=username)
    if not user:
        return jsonify({'success': False, 'error': gettext(u'User %(username)s does not exist', username=username)}), 400

    activated = app.security.datastore.activate_user(user)
    if activated:
        db.session.commit()
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': gettext(u'%(username)s is already activated', username=username)})


@user_api_blueprint.route("/api/user/role", methods=['POST'])
@roles_accepted("administrator")
def set_user_role():
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': gettext(u'LDAP is enabled, please use your LDAP server to assign roles')}), 400

    username = bleach.clean(request.json.get("username", ""))
    roles = request.json.get("roles")
    roles_cleaned = []

    if not username or not roles:
        return jsonify({'success': False, 'error': gettext(u'Please specify a username and roles')}), 400

    for role in roles:
        role = bleach.clean(role)
        role_exists = app.security.datastore.find_role(role)

        if not role_exists:
            return jsonify({'success': False, 'error': gettext(u'Role %(role)s does not exist', role=role)}), 400

        elif role not in roles_cleaned:
            roles_cleaned.append(role)

    user = app.security.datastore.find_user(username=username)
    if not user:
        return jsonify({'success': False, 'error': gettext(u'User %(username)s does not exist', username=username)}), 400

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
            return jsonify({'success': False, 'error': gettext(u'User %(username)s does not exist', username=username)}), 404

    eud = db.session.query(EUD).filter_by(uid=eud_uid).first()

    if not eud:
        return jsonify({'success': False, 'error': gettext(u'EUD %(eud_uid)s not found', eud_uid=eud_uid)}), 404
    elif eud.user_id and not current_user.has_role('administrator') and current_user.id != eud.user_id:
        return jsonify({'success': False, 'error': gettext(u'%(uid)s is already assigned to another user', uid=eud.uid)}), 403
    else:
        eud.user_id = user.id
        db.session.add(eud)
        db.session.commit()

        return jsonify({'success': True})


@user_api_blueprint.route('/api/users')
@roles_accepted('administrator')
def get_users():
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': gettext(u'LDAP is enabled, please use your LDAP server to manage users')}), 400

    query = db.session.query(User)
    query = search(query, User, 'username')

    return paginate(query)


@user_api_blueprint.route('/api/users/all')
@roles_accepted('administrator')
def get_all_users():
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': gettext(u'LDAP is enabled, please use your LDAP server to manage users')}), 400

    users = db.session.execute(db.session.query(User)).all()
    return_value = []

    for user in users:
        user = user[0]
        return_value.append(user.serialize())

    return return_value


@user_api_blueprint.route('/api/users/groups')
@roles_accepted('administrator')
def get_user_groups():
    """ Gets a list of group memberships for a user
    :parameter: username

    :return: List of group memberships
    """
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': gettext(u'LDAP is enabled, please use your LDAP server to manage groups')}), 400

    username = request.args.get("username")
    if not username:
        return jsonify({"success": False, "error": gettext(u"Please provide a username")}), 400

    username = bleach.clean(username)

    user = app.security.datastore.find_user(username=username)
    if not user:
        return jsonify({"success": False, "error": gettext(u"User %(username)s not found", username=username)}), 404

    group_memberships = db.session.execute(db.session.query(GroupUser).filter_by(user_id=user.id)).all()
    memberships = []
    for membership in group_memberships:
        membership: GroupUser = membership[0]
        memberships.append({"group_name": membership.group.name, "direction": membership.direction, "active": membership.enabled})

    return jsonify({"success": True, "results": memberships})


@user_api_blueprint.route('/api/users/groups', methods=["PUT"])
@roles_accepted("administrator")
def add_user_to_groups():
    """ Adds a user to one or more groups
    :parameter: groups - List of groups to add a user to
    :parameter: username
    :parameter: direction - Group direction, must be either IN or OUT

    :return: 400 if LDAP is enabled, no group or username is specified, or if the specified group or user doesn't exist or the user is already in the group. 200 on success.
    :rtype: Response
    """

    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': gettext(u'LDAP is enabled, please use your LDAP server to add users to groups')}), 400

    groups = request.json.get("groups")
    username = request.json.get("username")
    direction = request.json.get("direction")

    if not groups or not username or not direction:
        return jsonify({"success": False, "error": gettext(u"Please provide a list of groups, a username, and a direction")}), 400

    if direction != "IN" and direction != "OUT":
        return jsonify({"success": False, "error": gettext(u"Direction must be IN or OUT")}), 400

    user = app.security.datastore.find_user(username=username)
    if not user:
        return jsonify({"success": False, "error": gettext(u"User %(username)s doesn't exist", username=username)}), 404

    for group_name in groups:
        group_name = bleach.clean(group_name)
        group = db.session.execute(db.session.query(Group).filter_by(name=group_name)).first()
        if not group:
            return jsonify({"success": False, "error": gettext(u"Group %(group_name)s doesn't exist", group_name=group_name)}), 404

        group = group[0]

        membership = GroupUser()
        membership.user_id = user.id
        membership.group_id = group.id
        membership.direction = direction

        try:
            db.session.add(membership)
            db.session.commit()
        except sqlalchemy.exc.IntegrityError:
            db.session.rollback()

    return jsonify({"success": True})
