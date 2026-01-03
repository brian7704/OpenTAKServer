import traceback

import bleach
import pika
import sqlalchemy.exc
from flask import Blueprint, request, jsonify, current_app as app, Response
from flask_babel import gettext
from flask_login import current_user
from flask_security import roles_required, auth_required

from opentakserver.extensions import db, logger, ldap_manager
from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.models.Group import Group
from opentakserver.models.GroupUser import GroupUser

group_api = Blueprint("group_api", __name__)


@group_api.route('/api/groups')
@roles_required("administrator")
def get_groups():
    """ Search groups with filters and pagination

    :parameter: name
    :parameter: type
    :parameter: bitpos
    :parameter: active
    :parameter: page
    :parameter: per_page

    :return: JSON array of groups
    """

    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify(
            {"success": False, "error": gettext(u"LDAP is enabled. Please view and edit groups on your LDAP server")}), 400

    query = db.session.query(Group)
    query = search(query, Group, 'name')
    query = search(query, Group, 'type')
    query = search(query, Group, 'bitpos')
    query = search(query, Group, 'active')

    return paginate(query)


@group_api.route('/api/groups/all', methods=["GET"])
@auth_required()
def get_all_groups():
    """ Get a list of all groups

    :return: JSON array of groups
    :rtype: Response
    """
    return_value = []

    if app.config.get("OTS_ENABLE_LDAP"):

        groups = ldap_manager.get_user_groups(current_user.username)
        for group in groups:
            if group['cn'].lower().startswith(app.config.get("OTS_LDAP_GROUP_PREFIX").lower()) and not \
                    (group['cn'].lower().endswith("_read") or group['cn'].lower().endswith("_write")):

                g = Group()
                g.id = group['entryuuid']
                g.name = group['cn']
                g.distinguishedName = group['dn']
                g.type = Group.LDAP

                return_value.append(g.to_json())

        return jsonify(return_value)

    if not current_user.has_role("administrator"):
        groups = db.session.execute(
            db.session.query(GroupUser).filter_by(user_id=current_user.id, direction=Group.OUT)).scalars()
        # Make sure a group is only added once, not twice for both IN and OUT
        group_names = []
        for group in groups:
            if group.group.name not in group_names:
                group_names.append(group.group.name)
            else:
                continue
            return_value.append(group.group.to_json())

    else:
        groups = db.session.execute(db.session.query(Group)).scalars()
        for group in groups:
            return_value.append(group.to_json())

    return jsonify(return_value)


@group_api.route('/api/groups/members')
@roles_required("administrator")
def get_group_members():
    """ Get a list of members of a group

    :parameter: name

    :return: JSON array of group members
    :rtype: Response
    """
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify(
            {"success": False, "error": gettext(u"LDAP is enabled. Please view and edit groups on your LDAP server")}), 400

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


@group_api.route('/api/groups/members', methods=["DELETE"])
@roles_required("administrator")
def remove_user_from_group():
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify(
            {"success": False, "error": gettext(u"LDAP is enabled. Please view and edit groups on your LDAP server")}), 400

    username = request.args.get("username")
    group_name = request.args.get("group_name")
    direction = request.args.get("direction")

    if not username or not group_name or not direction:
        return jsonify({"success": False, "error": gettext(u"Please provide the username, group name, and direction")}), 400

    username = bleach.clean(username)
    group_name = bleach.clean(group_name)
    direction = bleach.clean(direction)

    if direction != Group.IN and direction != Group.OUT:
        return jsonify({"success": False, "error": gettext(u"Invalid direction: %(direction)s", direction=direction)}), 400

    user = app.security.datastore.find_user(username=username)
    if not user:
        return jsonify({"success": False, "error": gettext(u"User %(username)s not found", username=username)}), 404

    group = db.session.execute(db.session.query(Group).filter_by(name=group_name)).first()
    if not group:
        return jsonify({"success": False, "error": gettext(u"Group %(group_name)s not found")}), 404

    try:
        GroupUser.query.filter_by(group_id=group[0].id, user_id=user.id, direction=direction).delete()
        db.session.commit()

        rabbit_credentials = pika.PlainCredentials(app.config.get("OTS_RABBITMQ_USERNAME"),
                                                   app.config.get("OTS_RABBITMQ_PASSWORD"))
        rabbit_host = app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")
        rabbit_connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=rabbit_host, credentials=rabbit_credentials))
        channel = rabbit_connection.channel()
        for eud in user.euds:
            channel.queue_unbind(exchange="groups", queue=eud.uid, routing_key=f"{group_name}.{direction}")

        channel.close()
        rabbit_connection.close()

        return jsonify({"success": True})
    except BaseException as e:
        logger.error(f"Failed to remove {username} from {group_name}: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": gettext(u"Failed to remove %(username)s from %(group_name)s: %(e)s",
                                                           username=username, group_name=group_name, e=str(e))}), 500


@group_api.route('/api/groups', methods=["POST"])
@roles_required("administrator")
def add_group():
    """ Creates a new group

    :return: 400 if LDAP is enabled, the request is missing the name key or the group exists. 500 on server errors.
    :rtype: Response
    """
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': gettext(u'LDAP is enabled, please use your LDAP server to add groups')}), 400

    if "name" not in request.json.keys():
        return jsonify({'success': False, 'error': gettext(u'Missing name')}), 400

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
            return jsonify({'success': False, 'error': gettext("%(name)s group already exists", name=name)}), 400

    except BaseException as e:
        logger.error(f"Failed to add {name} group: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({'success': False, "error": gettext(u"Failed to add %(name)s group: %(e)s", name=name, e=str(e))}), 500

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
        return jsonify(
            {'success': False, 'error': gettext(u'LDAP is enabled, please use your LDAP server to add users to groups')}), 400

    users = request.json.get("users")
    group_name = request.json.get("group_name")
    direction = request.json.get("direction")

    if users is None or group_name is None or direction is None:
        return jsonify({"success": False, "error": gettext(u"Please provide a list of users, group name, and direction")}), 400

    if direction != "IN" and direction != "OUT":
        return jsonify({"success": False, "error": gettext(u"Direction must be IN or OUT")}), 400

    for username in users:
        user = app.security.datastore.find_user(username=username)
        if not user:
            return jsonify({"success": False, "error": gettext(u"User %(username)s does not exist", username=username)}), 400

        group = db.session.execute(db.session.query(Group).filter_by(name=group_name)).first()
        if not group:
            return jsonify({"success": False, "error": gettext(u"Group %(group_name)s does not exist", group_name=group_name)}), 400

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
        return jsonify(
            {'success': False, 'error': gettext(u'LDAP is enabled, please use your LDAP server to delete groups')}), 400

    if "group_name" not in request.args.keys() or not request.args.get("group_name"):
        return jsonify({'success': False, 'error': gettext(u'Missing group name')}), 400

    group_name = bleach.clean(request.args.get("group_name"))
    if group_name == "__ANON__":
        return jsonify({'success': False, 'error': gettext(u'The __ANON__ group cannot be deleted')}), 400

    try:
        group = db.session.execute(
            db.session.query(Group).filter_by(name=group_name)).first()
        if not group:
            return jsonify({"success": False, "error": gettext(u"No such group: %(group_name)s", group_name=request.args.get('group_name'))}), 404

        group = group[0]

        GroupUser.query.filter_by(group_id=group.id).delete()
        db.session.delete(group)
        db.session.commit()
    except BaseException as e:
        logger.error(f"Failed to delete {request.args.get('group_name')}: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({'success': False, 'error': gettext(u"Failed to delete %(group_name)s: %(e)s",
                                                           group_name=request.args.get('group_name'), e=str(e))}), 500

    return jsonify({'success': True})
