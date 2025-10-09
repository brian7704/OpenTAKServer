import traceback

import bleach
from flask import Blueprint, request, jsonify, current_app as app, Response
from flask_security import roles_required

from opentakserver.extensions import db, logger
from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.models.Group import Group, GroupDirectionEnum, GroupTypeEnum
from opentakserver.models.GroupUser import GroupUser

group_api = Blueprint("group_api", __name__)


@group_api.route('/api/groups')
@roles_required("administrator")
def get_groups():
    query = db.session.query(Group)
    query = search(query, Group, 'name')
    query = search(query, Group, 'direction')
    query = search(query, Group, 'type')
    query = search(query, Group, 'bitpos')
    query = search(query, Group, 'active')

    return paginate(query)


@group_api.route('/api/groups', methods=["POST"])
@roles_required("administrator")
def add_group():
    """ Creates a new group

    :return: 400 if LDAP is enabled, the request is missing the name key or the group exists. 500 on server errors.
    :rtype: Response
    """
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': 'LDAP is enabled, please use your LDAP server to add groups'}), 400

    if "name" not in request.json.keys():
        return jsonify({'success': False, 'error': 'Missing name'}), 400

    name = bleach.clean(request.json.get("name"))
    description = bleach.clean(request.json.get("description")) if "description" in request.json.keys() else None

    group = db.session.execute(db.session.query(Group).filter_by(name=name)).first()

    try:
        if not group:
            group = Group()
            group.name = name
            group.type = GroupTypeEnum.SYSTEM
            group.description = description
            db.session.add(group)
            db.session.commit()
        else:
            return jsonify({'success': False, 'error': f"{name} group already exists"}), 400

    except BaseException as e:
        logger.error(f"Failed to add {name} group: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({'success': False, "error": f"Failed to add {name} group: {e}"}), 500

    return jsonify({'success': True})


@group_api.route('/api/groups', methods=["PUT"])
@roles_required("administrator")
def add_user_to_group():
    """ Adds a user to a group. This will allow all the user's EUDs to subscribe and unsubscribe from the channels/groups they're allowed to see.

    :return: 400 if LDAP is enabled, no group or username is specified, or if the specified group or user doesn't exist or the user is already in the group. 200 on success.
    :rtype: Response
    """

    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': 'LDAP is enabled, please use your LDAP server to add users to groups'}), 400

    username = request.json.get("username")
    group_name = request.json.get("group_name")

    if username is None or group_name is None:
        return jsonify({"success": False, "error": "Please provide a username and group name"}), 400

    user = app.security.find_user(username=username)
    if not user:
        return jsonify({"success": False, "error": f"User {username} does not exist"}), 400

    group = db.session.execute(db.session.query(Group).filter_by(name=group_name)).first()
    if not group:
        return jsonify({"success": False, "error": f"Group {group_name} does not exist"}), 400

    group_user = GroupUser()
    group_user.user_id = user.id
    group_user.group_id = group[0].id

    try:
        db.session.add(group_user)
        db.session.commit()
        return jsonify({"success": True})
    except BaseException as e:
        return jsonify({"success": False, "error": f"User {username} is already in group {group_name}"}), 400


@group_api.route('/api/groups', methods=["DELETE"])
@roles_required("administrator")
def delete_group():
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': 'LDAP is enabled, please use your LDAP server to delete groups'}), 400

    if "name" not in request.json.keys():
        return jsonify({'success': False, 'error': 'Missing name'}), 400

    try:
        db.session.delete(Group).where(Group.name == bleach.clean(request.json.get("name")))
        db.session.commit()
    except BaseException as e:
        logger.error(f"Failed to delete {request.json.get('name')}: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({'success': False, 'error': f"Failed to delete {request.json.get('name')}: {e}"}), 500

    return jsonify({'success': True})
