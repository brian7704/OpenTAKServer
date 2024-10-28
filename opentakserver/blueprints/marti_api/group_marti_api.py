import datetime

from flask import Blueprint, current_app as app, jsonify, request

from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.extensions import db, logger
from opentakserver.models.Group import Group
from opentakserver.models.GroupEud import GroupEud

group_api = Blueprint('group_api', __name__)


@group_api.route('/Marti/api/groups/groupCacheEnabled')
def group_cache_enabled():
    return jsonify(
        {"version": "3", "type": "java.lang.Boolean", "nodeId": app.config.get("OTS_NODE_ID"),
         "data": app.config.get("OTS_ENABLE_CHANNELS")})


@group_api.route('/Marti/api/groups/all')
def get_all_groups():
    # Only return the __ANON__ in and out groups until group support is fully implemented
    response = {"version": "3", "type": "com.bbn.marti.remote.groups.Group", "nodeId": app.config.get("OTS_NODE_ID"), "data": [{
            "name": "__ANON__",
            "direction": "IN",
            "created": iso8601_string_from_datetime(datetime.datetime.now()).split("T")[0],
            "type": "SYSTEM",
            "bitpos": 2,
            "active": True,
            "description": ""
        },
        {
            "name": "__ANON__",
            "direction": "OUT",
            "created": iso8601_string_from_datetime(datetime.datetime.now()).split("T")[0],
            "type": "SYSTEM",
            "bitpos": 2,
            "active": True,
            "description": ""
        }
    ]}

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
    # [{"name":"__ANON__","direction":"OUT","created":1729814400000,"type":"SYSTEM","bitpos":2,"active":true},{"name":"__ANON__","direction":"IN","created":1729814400000,"type":"SYSTEM","bitpos":2,"active":true}]
    # OTS only supports the __ANON__ group now so just return 200 until group support is fully implemented

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
