import traceback

import bleach
from flask import Blueprint, request, jsonify, current_app as app
from flask_security import roles_required

from opentakserver.extensions import db, logger
from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.models.Group import Group, GroupDirectionEnum, GroupTypeEnum

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
    if app.config.get("OTS_ENABLE_LDAP"):
        return jsonify({'success': False, 'error': 'LDAP is enabled, please use your LDAP server to add groups'}), 400

    if "name" not in request.json.keys():
        return jsonify({'success': False, 'error': 'Missing name'}), 400

    name = bleach.clean(request.json.get("name"))
    in_group = db.session.execute(db.session.query(Group).filter_by(name=name, direction=GroupDirectionEnum.IN)).first()
    out_group = db.session.execute(db.session.query(Group).filter_by(name=name, direction=GroupDirectionEnum.OUT)).first()

    if not in_group.count:
        in_group.name = name
        in_group.direction = GroupDirectionEnum.IN
        in_group.type = GroupTypeEnum.SYSTEM
        db.session.add(in_group)

    if not out_group.count:
        out_group.name = name
        out_group.direction = GroupDirectionEnum.OUT
        out_group.type = GroupTypeEnum.SYSTEM
        db.session.add(out_group)


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
