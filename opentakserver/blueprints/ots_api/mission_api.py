import sqlalchemy.exc
from flask import Blueprint, request, jsonify
from flask_security import auth_required, current_user

from opentakserver.blueprints.marti_api.mission_marti_api import invite
from opentakserver.extensions import db
from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.models.Mission import Mission

data_sync_api = Blueprint("data_sync_api", __name__)


@data_sync_api.route('/api/missions')
@auth_required()
def get_missions():
    query = db.session.query(Mission)
    query = search(query, Mission, 'name')
    query = search(query, Mission, 'guid')
    query = search(query, Mission, 'tool')
    query = search(query, Mission, 'group')

    return paginate(query)


@data_sync_api.route('/api/missions', methods=['PUT', 'POST'])
@auth_required()
def create_edit_mission():
    mission_name = request.json.get('mission_name')
    if not mission_name:
        return jsonify({'success': False, 'error': 'Please provide a mission name'}), 400

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()

    # Creates a new mission
    if not mission:
        mission = Mission()
        for key, value in request.json:
            if hasattr(mission, key):
                setattr(mission, key, value)
            else:
                return jsonify({'success': False, 'error': f"Invalid property: {key}"}), 400

        db.session.add(mission)
        db.session.commit()

        return jsonify({'success': True})

    mission = mission[0]
    for key, value in request.json:
        if hasattr(mission, key):
            setattr(mission, key, value)
        else:
            return jsonify({'success': False, 'error': f"Invalid property: {key}"}), 400

    # Checks if current user is the mission creator
    is_user_mission_creator = False
    for eud in current_user.euds:
        if eud.uid == mission.creator_uid:
            is_user_mission_creator = True
            break

    # Only allows admins and the mission creator to change existing missions
    if current_user.has_role('administrator') or is_user_mission_creator:
        db.session.execute(sqlalchemy.update(Mission).where(name=mission_name).values(**mission.serialize()))
        db.session.commit()

        return jsonify({'success': True})

    return jsonify({'success': False, 'error': 'Only an admin or the mission creator can change this mission'}), 403


@data_sync_api.route('/api/missions', methods=['DELETE'])
@auth_required()
def delete_mission():
    mission_name = request.args.get('name')
    if not mission_name:
        return jsonify({'success': False, 'error': 'Please specify a mission name'}), 404

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': f"Mission {mission_name} not found"}), 404
    mission = mission[0]

    if current_user.has_role('administrator'):
        db.session.delete(mission)
        db.session.commit()
        return jsonify({'success': True})

    elif mission.creator_uid:
        for eud in current_user.euds:
            if eud.uid == mission.creator_uid:
                db.session.delete(mission)
                db.session.commit()
                return jsonify({'success': True})

    return jsonify({'success': False, 'error': f"Only an admin or the mission creator can delete this mission"}), 403


@data_sync_api.route('/api/missions/invite', methods=['POST'])
@auth_required()
def invite_eud():
    mission_name = request.json['mission_name']
    eud_uid = request.json['uid']
    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': f"Mission not found: {mission_name}"}), 404

    if mission[0].password_protected and not current_user.has_role("administrator"):
        return jsonify({'success': False, 'error': "Only administrators can send invitations to password protected missions"}), 403

    return invite(mission_name, 'clientuid', eud_uid)
