import datetime
import traceback

import bleach
import pika
from OpenSSL.crypto import X509
from flask import Blueprint, current_app as app, jsonify, request
from flask_security import current_user

from opentakserver.blueprints.marti_api.marti_api import verify_client_cert
from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.extensions import db, logger
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
        return jsonify({"success": False, "error": "Groups are only supported on SSL connections"}), 400

    username = cert.get_subject().commonName
    user = app.security.datastore.find_user(username=username)

    response = {"version": "3", "type": "com.bbn.marti.remote.groups.Group", "nodeId": app.config.get("OTS_NODE_ID"), "data": []}

    for group in user.groups:
        group = group

        response['data'].append(group.to_marti_json_in())
        response['data'].append(group.to_marti_json_out())

    return jsonify(response)


@group_api.route('/Marti/api/groups')
def get_ldap_groups():
    # Always return an empty response until LDAP support is implemented
    group_name = request.args.get("groupNameFilter")
    if not group_name:
        return jsonify({'success': False, 'error': "Please specify a groupNameFilter"}), 400

    groups = db.session.execute(db.session.query(Group).filter_by(group_name=group_name)).all()
    if not groups:
        return jsonify({'success': False, 'error': f"Group {group_name} not found"}), 404

    response = {"version": "3", "type": "com.bbn.marti.remote.groups.LdapGroup", "data": [],
                "nodeId": app.config.get("OTS_NODE_ID")}

    return jsonify(response)


@group_api.route('/Marti/api/groups/members')
def get_ldap_group_members():
    # Always return 0 until LDAP support is implemented
    group_name = request.args.get("groupNameFilter")
    if not group_name:
        return jsonify({'success': False, 'error': "Please specify a groupNameFilter"}), 400

    response = {"version": "3", "type": "java.lang.Integer", "data": 0, "nodeId": app.config.get("OTS_NODE_ID")}

    return jsonify(response)


@group_api.route('/Marti/api/groupprefix')
def get_ldap_group_prefix():
    # Always return and empty string until LDAP support is implemented
    response = {"version": "3", "type": "java.lang.String", "data": "", "nodeId": app.config.get("OTS_NODE_ID")}

    return jsonify(response)


@group_api.route('/Marti/api/groups/activebits', methods=['PUT'])
def put_active_bits():
    client_uid = request.args.get("clientUid")
    bits = request.json

    return '', 200


@group_api.route('/Marti/api/groups/active', methods=['PUT'])
def put_active_groups():
    uid = request.args.get("clientUid")
    if not uid:
        logger.error("clientUid required")
        return jsonify({'success': False, 'error': "clientUid required"}), 400

    cert = verify_client_cert()
    username = cert.get_subject().commonName
    user = app.security.datastore.find_user(username=username)

    groups_users = db.session.execute(db.session.query(GroupUser).filter_by(user_id=user.id)).all()
    if not groups_users:
        logger.warning(f"User {username} doesn't belong to any groups, defaulting to __ANON__")
        return '', 400

    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()

    group_subscriptions = db.session.execute(db.session.query(GroupUser).filter_by(user_id=user.id)).all()

    for subscription in request.json:
        direction = subscription.get("direction")
        if not direction and direction != Group.IN and direction != Group.OUT:
            logger.error(f"Direction must be IN or OUT: {direction}")
            return jsonify({"success": False, "error": f"Direction must be IN or OUT"}), 400

        active = subscription.get("active")
        if not isinstance(active, bool):
            logger.error("The active attribute must be true or false")
            return jsonify({"success": False, "error": "The active attribute must be true or false"}), 400

        group_name = subscription.get("name")
        if not group_name:
            logger.error("Group name is required")
            return jsonify({"success": False, "error": "Group name is required"}), 400

        group_name = bleach.clean(group_name)

        user_in_group = False
        for group_subscription in group_subscriptions:
            group_subscription = group_subscription[0]
            if group_subscription.group.name == group_name and group_subscription.direction == direction:
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
            return jsonify({"success": False, "error": f"{username} is not in the {group_name} group"}), 403

    try:
        db.session.commit()
        return '', 200
    except BaseException as e:
        logger.error(f"Failed to update group subscriptions for {current_user.username}: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": f"Failed to update group subscriptions for {current_user.username}: {e}"}), 400


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
        return jsonify({'success': False, 'error': "Please provide a group name and direction"}), 400

    group = db.session.execute(db.session.query(Group).filter_by(group_name=group_name, direction=direction)).first()
    if not group:
        return jsonify({'success': False, 'error': f"No group found: {group_name}, {direction}"}), 404

    return jsonify({"version": "3", "type": "com.bbn.marti.remote.groups.Group", "data": group[0].to_json(),
                    "nodeId": app.config.get("OTS_NODE_ID")})


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
