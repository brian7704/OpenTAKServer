import traceback

import bleach
import sqlalchemy.exc
from flask import Blueprint, request, jsonify, current_app as app, Response
from flask_security import roles_required

from opentakserver.extensions import db, logger
from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.models.Group import Group
from opentakserver.models.GroupUser import GroupUser

group_api = Blueprint("group_api", __name__)


@group_api.route('/api/groups')
@roles_required("administrator")
def get_groups():
    """ Search groups with filters and pagination

    :parameter: name
    :parameter: direction
    :parameter: type
    :parameter: bitpos
    :parameter: active
    :parameter: page
    :parameter: per_page

    :return: JSON array of groups
    """
    query = db.session.query(Group)
    query = search(query, Group, 'name')
    query = search(query, Group, 'direction')
    query = search(query, Group, 'type')
    query = search(query, Group, 'bitpos')
    query = search(query, Group, 'active')

    return paginate(query)


@group_api.route('/api/groups/all', methods=["GET"])
@roles_required("administrator")
def get_all_groups():
    """ Get a list of all groups

    :return: JSON array of groups
    :rtype: Response
    """
    groups = db.session.execute(db.session.query(Group)).all()
    return_value = []

    for group in groups:
        group = group[0]
        return_value.append(group.to_json())

    return jsonify(return_value)


@group_api.route('/api/groups/members')
@roles_required("administrator")
def get_group():
    """ Get a list of members of a group

    :parameter: name

    :return: JSON array of group members
    :rtype: Response
    """
    group_name = request.args.get("name")
    if not group_name:
        return jsonify({"success": False, "error": "Please specify a group name"}), 400

    group_name = bleach.clean(group_name)
    group = db.session.execute(db.session.query(Group).filter_by(name=group_name)).first()
    if not group:
        return jsonify({"success": False, "error": f"Group {group_name} not found"}), 404

    group = group[0]
    members = db.session.execute(db.session.query(GroupUser).filter_by(group_id=group.id)).all()
    return_value = []
    for member in members:
        member = member[0]
        return_value.append({"username": member.user.username, "direction": member.direction, "active": member.enabled})

    return return_value


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
            group.type = Group.SYSTEM
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
    """ Adds a users to a group. This will allow all the user's EUDs to subscribe and unsubscribe from the channels/groups they're allowed to see.
    :parameter: users - A list of users to add to a group
    :parameter: group_name - Name of the group to add users to
    :parameter: direction - Group direction, can only be IN or OUT

    :return: 400 if LDAP is enabled, no group or username is specified, or if the specified group or user doesn't exist or the user is already in the group. 200 on success.
    :rtype: Response
    """

    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': 'LDAP is enabled, please use your LDAP server to add users to groups'}), 400

    users = request.json.get("users")
    group_name = request.json.get("group_name")
    direction = request.json.get("direction")

    if users is None or group_name is None or direction is None:
        return jsonify({"success": False, "error": "Please provide a list of users, group name, and direction"}), 400

    if direction != "IN" and direction != "OUT":
        return jsonify({"success": False, "error": "Direction must be IN or OUT"}), 400

    for username in users:
        user = app.security.datastore.find_user(username=username)
        if not user:
            return jsonify({"success": False, "error": f"User {users} does not exist"}), 400

        group = db.session.execute(db.session.query(Group).filter_by(name=group_name)).first()
        if not group:
            return jsonify({"success": False, "error": f"Group {group_name} does not exist"}), 400

        membership = GroupUser()
        membership.user_id = user.id
        membership.group_id = group[0].id
        membership.direction = direction

        try:
            db.session.add(membership)
            db.session.commit()
        except sqlalchemy.exc.IntegrityError:
            db.session.rollback()

    return jsonify({"success": True})


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
