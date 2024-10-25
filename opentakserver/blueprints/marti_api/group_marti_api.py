import datetime

import sqlalchemy.exc
from sqlalchemy import update
from flask import Blueprint, current_app as app, jsonify, request
from opentakserver.functions import datetime_from_iso8601_string, iso8601_string_from_datetime
from opentakserver.extensions import db, logger
from opentakserver.models.Group import Group

group_api = Blueprint('group_api', __name__)


@group_api.route('/Marti/api/groups/groupCacheEnabled')
def group_cache_enabled():
    return jsonify(
        {"version": "3", "type": "java.lang.Boolean", "nodeId": app.config.get("OTS_NODE_ID"),
         "data": app.config.get("OTS_ENABLE_CHANNELS")})


@group_api.route('/Marti/api/groups/all')
def get_all_groups():
    response = {"version": "3", "type": "com.bbn.marti.remote.groups.Group", "data": [],
                "nodeId": app.config.get("OTS_NODE_ID")}

    groups = db.session.execute(db.session.query(Group)).all()
    if not groups:
        in_group = Group()
        in_group.group_name = "__ANON__"
        in_group.direction = Group.IN
        in_group.created = datetime.datetime.now()
        in_group.group_type = Group.SYSTEM
        in_group.bitpos = 2
        in_group.active = True

        out_group = Group()
        out_group.group_name = "__ANON__"
        out_group.direction = Group.OUT
        out_group.created = datetime.datetime.now()
        out_group.group_type = Group.SYSTEM
        out_group.bitpos = 2
        out_group.active = True

        db.session.add(in_group)
        db.session.add(out_group)
        db.session.commit()

        response['data'].append(in_group.to_json())

    for in_group in groups:
        in_group = in_group[0]
        response['data'].append(in_group.to_json())

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
    logger.debug(request.data)
    client_uid = request.args.get('clientUid')
    groups = request.json

    for group in groups:
        existing_group = db.session.execute(
            db.session.query(Group).filter_by(group_name=group['name'], direction=group['direction'], eud_uid=client_uid)).first()
        if existing_group:
            existing_group = existing_group[0]
            existing_group.created = datetime.datetime.fromtimestamp(group['created'])
            existing_group.group_type = group['type']
            existing_group.bitpos = group['bitpos']
            existing_group.active = group['active']
            existing_group.description = group['description']

            db.session.commit()
        else:
            new_group = Group()
            new_group.group_name = group['name']
            new_group.direction = group['direction']
            new_group.created = datetime.datetime.fromtimestamp(group['created'])
            new_group.group_type = group['type']
            new_group.bitpos = group['bitpos']
            new_group.active = group['active']
            new_group.description = group['description']
            new_group.eud_uid = client_uid

            db.session.add(new_group)
            db.session.commit()

    return '', 200


@group_api.route('/Marti/api/groups/update/<username>')
def update_group(username: str):
    # Not sure what this is supposed to return
    return '', 200


@group_api.route('/Marti/api/groups/<group_name>/<direction>')
def get_group(group_name: str, direction: str):
    if not group_name or not direction:
        return jsonify({'success': False, 'error': "Please provide a group name and direction"}), 400

    group = db.session.execute(db.session.query(Group).filter_by(group_name=group_name, direction=direction)).first()
    if not group:
        return jsonify({'success': False, 'error': f"No group found: {group_name}, {direction}"}), 404

    return jsonify({"version": "3", "type": "com.bbn.marti.remote.groups.Group", "data": group[0].to_json(),
                    "nodeId": app.config.get("OTS_NODE_ID")})
