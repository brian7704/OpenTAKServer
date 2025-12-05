import datetime
import traceback

import bleach
import pika
from OpenSSL.crypto import X509
from flask import Blueprint, current_app as app, jsonify, request
from flask_babel import gettext
from flask_security import current_user

from opentakserver.blueprints.marti_api.marti_api import verify_client_cert
from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.extensions import db, logger, ldap_manager
from opentakserver.models.Group import Group
from opentakserver.models.GroupUser import GroupUser

group_api = Blueprint('group_api', __name__)


@group_api.route('/Marti/api/groups/groupCacheEnabled')
def group_cache_enabled():
    return jsonify(
        {"version": "3", "type": "java.lang.Boolean", "nodeId": app.config.get("OTS_NODE_ID"),
         "data": app.config.get("OTS_ENABLE_CHANNELS")})


@group_api.route('/Marti/api/groups/all')
def get_all_groups():
    cert = verify_client_cert()
    if not cert:
        return jsonify({"success": False, "error": gettext(u"Groups are only supported on SSL connections")}), 400

    response = {"version": "3", "type": "com.bbn.marti.remote.groups.Group", "nodeId": app.config.get("OTS_NODE_ID"), "data": []}

    username = cert.get_subject().commonName

    if not app.config.get("OTS_ENABLE_LDAP"):
        user = app.security.datastore.find_user(username=username)
        groups = db.session.execute(db.session.query(GroupUser).filter_by(user_id=user.id)).scalars()

        number_of_groups = 0

        if groups:
            for group in groups:
                if group.direction == Group.IN:
                    response['data'].append(group.group.to_marti_json_in())
                else:
                    response['data'].append(group.group.to_marti_json_out())
                number_of_groups += 1

        # If a user is not assigned to any groups, default them to the __ANON__ group
        if not groups or not number_of_groups:
            logger.info(f"{username} has no groups, defaulting to __ANON__")
            group = Group()
            group.name = "__ANON__"
            group.created = datetime.datetime.now(datetime.timezone.utc)
            group.type = Group.SYSTEM
            group.bitpos = 2

            response['data'].append(group.to_marti_json_out())
            response['data'].append(group.to_marti_json_in())

    else:
        groups = ldap_manager.get_user_groups(username)
        for group in groups:
            if app.config.get("OTS_LDAP_GROUP_PREFIX") and not group['cn'].startswith(app.config.get("OTS_LDAP_GROUP_PREFIX")):
                continue

            g = Group()
            g.name = group['cn']
            g.distinguishedName = group['dn']
            g.type = Group.LDAP

            if group['cn'].lower().endswith("_write"):
                response['data'].append(g.to_marti_json_in())
            elif group['cn'].lower().endswith("_read"):
                response['data'].append(g.to_marti_json_out())

    return jsonify(response)


@group_api.route('/Marti/api/groups')
def get_ldap_groups():

    group_name = request.args.get("groupNameFilter")
    if not group_name:
        return jsonify({'success': False, 'error': gettext(u"Please specify a groupNameFilter")}), 400

    group_name = bleach.clean(group_name)

    if not group_name.startswith(app.config.get("OTS_LDAP_GROUP_PREFIX")):
        return jsonify({'success': False, 'error': gettext(u"Please specify a groupNameFilter that starts with %(prefix)s", prefix=app.config.get('OTS_LDAP_GROUP_PREFIX'))}), 400

    if not group_name.endswith("_READ") and not group_name.endswith("_WRITE"):
        return jsonify({'success': False,'error': gettext(u"groupNameFilter must end with either _READ or _WRITE")}), 400

    response = {"version": "3", "type": "com.bbn.marti.remote.groups.LdapGroup", "data": [],
                "nodeId": app.config.get("OTS_NODE_ID")}

    if app.config.get("OTS_ENABLE_LDAP"):
        group = ldap_manager.get_group_info(group_name)
        g = Group()
        g.name = group['cn']
        g.distinguishedName = group['dn']
        g.type = Group.LDAP

        if group['cn'].endswith("_WRITE"):
            response['data'].append(g.to_marti_json_in())
        elif group['cn'].endswith("_READ"):
            response['data'].append(g.to_marti_json_out())

    return jsonify(response)


@group_api.route('/Marti/api/groups/members')
def get_ldap_group_members():
    group_name = request.args.get("groupNameFilter")
    if not group_name:
        return jsonify({'success': False, 'error': gettext(u"Please specify a groupNameFilter")}), 400

    group_name = bleach.clean(group_name)

    if not group_name.startswith(app.config.get("OTS_LDAP_GROUP_PREFIX")):
        return jsonify({'success': False, 'error': gettext(u"Please specify a groupNameFilter that starts with %(prefix)s", prefix=app.config.get('OTS_LDAP_GROUP_PREFIX'))}), 400

    if not group_name.endswith("_READ") and not group_name.endswith("_WRITE"):
        return jsonify({'success': False, 'error': gettext(u"groupNameFilter must end with either _READ or _WRITE")}), 400

    response = {"version": "3", "type": "java.lang.Integer", "data": 0, "nodeId": app.config.get("OTS_NODE_ID")}

    if app.config.get("OTS_ENABLE_LDAP"):
        group = {}
        try:
            group = ldap_manager.get_group_info(group_name)
            response['data'] = len(group['member'])
        except BaseException as e:
            logger.error(f"Failed to get member count for {group_name}: {e}")
            logger.debug(group)

    return jsonify(response)


@group_api.route('/Marti/api/groupprefix')
def get_ldap_group_prefix():
    response = {"version": "3", "type": "java.lang.String", "data": "", "nodeId": app.config.get("OTS_NODE_ID")}
    if app.config.get("OTS_ENABLE_LDAP"):
        response["data"] = app.config.get("OTS_LDAP_GROUP_PREFIX")

    return jsonify(response)


@group_api.route('/Marti/api/groups/activebits', methods=['PUT'])
def put_active_bits():
    client_uid = request.args.get("clientUid")
    bits = request.json

    return '', 200


@group_api.route('/Marti/api/groups/active', methods=['PUT'])
def put_active_groups():
    logger.info(request.args)
    logger.info(request.json)
    uid = request.args.get("clientUid")
    if not uid:
        logger.error("clientUid required")
        return jsonify({'success': False, 'error': gettext(u"clientUid required")}), 400

    cert = verify_client_cert()
    username = cert.get_subject().commonName
    user = app.security.datastore.find_user(username=username)

    groups_users = db.session.execute(db.session.query(GroupUser).filter_by(user_id=user.id)).all()
    if not groups_users:
        logger.warning(f"User {username} doesn't belong to any groups, defaulting to __ANON__")
        return '', 400

    rabbit_credentials = pika.PlainCredentials(app.config.get("OTS_RABBITMQ_USERNAME"), app.config.get("OTS_RABBITMQ_PASSWORD"))
    rabbit_host = app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")
    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbit_host, credentials=rabbit_credentials))
    channel = rabbit_connection.channel()

    group_subscriptions = db.session.execute(db.session.query(GroupUser).filter_by(user_id=user.id)).all()

    for subscription in request.json:
        direction = subscription.get("direction")
        if not direction and direction != Group.IN and direction != Group.OUT:
            logger.error(f"Direction must be IN or OUT: {direction}")
            return jsonify({"success": False, "error": gettext(u"Direction must be IN or OUT")}), 400

        active = subscription.get("active")
        if not isinstance(active, bool):
            logger.error("The active attribute must be true or false")
            return jsonify({"success": False, "error": gettext(u"The active attribute must be true or false")}), 400

        group_name = subscription.get("name")
        if not group_name:
            logger.error("Group name is required")
            return jsonify({"success": False, "error": gettext(u"Group name is required")}), 400

        group_name = bleach.clean(group_name)

        user_in_group = False
        for group_subscription in group_subscriptions:
            group_subscription = group_subscription[0]
            if group_subscription.group.name == group_name and group_subscription.direction == direction:
                if not app.config.get("OTS_ENABLE_LDAP"):
                    group_subscription.enabled = active
                    db.session.add(group_subscription)

                if active:
                    channel.queue_bind(queue=uid, exchange="groups", routing_key=f"{group_subscription.group.name}.{group_subscription.direction}")
                else:
                    channel.queue_unbind(queue=uid, exchange="groups", routing_key=f"{group_subscription.group.name}.{group_subscription.direction}")

                user_in_group = True

        if not user_in_group:
            logger.warning(f"{username} is not in the {group_name} group")
            db.session.rollback()
            channel.close()
            rabbit_connection.close()
            return jsonify({"success": False, "error": gettext(u"%(username)s is not in the %(group_name)s group", username=username, group_name=group_name)}), 403

    try:
        channel.close()
        rabbit_connection.close()
        db.session.commit()
        return '', 200
    except BaseException as e:
        logger.error(f"Failed to update group subscriptions for {current_user.username}: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": gettext("Failed to update group subscriptions for %(username)s: %(e)s",
                                                           username=current_user.username, e=str(e))}), 400


@group_api.route('/Marti/api/groups/update/<username>')
def update_group(username: str):

    response = {
        "version": "",
        "type": "",
        "data": True,
        "messages": [""],
        "nodeId": app.config.get("OTS_NODE_ID")
    }

    return jsonify(response)


@group_api.route('/Marti/api/groups/<group_name>/<direction>')
def get_group(group_name: str, direction: str):
    if not group_name or not direction:
        return jsonify({'success': False, 'error': gettext("Please provide a group name and direction")}), 400

    response = {"version": "3", "type": "com.bbn.marti.remote.groups.Group", "data": {}, "nodeId": app.config.get("OTS_NODE_ID")}

    if not app.config.get("OTS_ENABLE_LDAP"):
        group = db.session.execute(db.session.query(Group).filter_by(group_name=group_name, direction=direction)).first()
        if not group:
            return jsonify({'success': False, 'error': gettext("No group found: %(group_name)s, %(direction)s", group_name=group_name, direction=direction)}), 404
        if direction == Group.IN:
            response['data'] = group[0].to_marti_json_in()
        elif direction == Group.OUT:
            response['data'] = group[0].to_marti_json_out()

    else:
        group = ldap_manager.get_group_info(group_name)
        g = Group()
        g.name = group['cn']
        g.distinguishedName = group['dn']
        g.type = Group.LDAP
        if direction == Group.IN:
            response['data'] = g.to_marti_json_in()
        elif direction == Group.OUT:
            response['data'] = g.to_marti_json_out()

    return jsonify(response)


@group_api.route('/Marti/api/subscriptions/all')
def get_all_subscriptions():
    sortBy = request.args.get("sortBy")
    direction = request.args.get("direction")
    page = request.args.get("page")
    limit = request.args.get("limit")

    response = {"version": "3", "type": "SubscriptionInfo", "data": [], "messages": [], "nodeId": app.config.get("OTS_NODE_ID")}

    return jsonify(response)


@group_api.route('/Marti/api/groups/activeForce')
def group_active_force():
    username = request.args.get("username")
    if not username:
        return '', 400

    response = {
        "name": "",
        "distinguishedName": "",
        "direction": "",
        "created": "",
        "type": "SYSTEM",  # Can also be LDAP but OTS doesn't support LDAP yet
        "bitpos": 0,
        "active": True,
        "description": ""
    }

    return jsonify(response)


@group_api.route('/Marti/api/groups/user')
def get_user_groups():
    username = request.args.get("username")
    if not username:
        return '', 400

    groups = {}

    response = {
        "version": "",
        "type": "",
        "data": groups,
        "messages": [""],
        "nodeId": app.config.get("OTS_NODE_ID")
    }

    return jsonify(response)
