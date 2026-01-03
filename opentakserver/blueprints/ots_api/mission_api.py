import datetime
import json
import traceback
import uuid

import bleach
import sqlalchemy.exc
from flask import Blueprint, request, jsonify, current_app as app
from flask_babel import gettext
from flask_security import auth_required, current_user, roles_required, hash_password, verify_password
from xml.etree.ElementTree import tostring
import pika
from sqlalchemy import or_

from opentakserver.blueprints.marti_api.mission_marti_api import invite, generate_mission_delete_cot, generate_new_mission_cot, generate_invitation_cot
from opentakserver.extensions import db, logger
from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.models.CoT import CoT
from opentakserver.models.EUD import EUD
from opentakserver.models.Group import Group
from opentakserver.models.GroupMission import GroupMission
from opentakserver.models.GroupUser import GroupUser
from opentakserver.models.Mission import Mission
from opentakserver.models.MissionChange import MissionChange
from opentakserver.models.MissionContentMission import MissionContentMission
from opentakserver.models.MissionInvitation import MissionInvitation
from opentakserver.models.MissionLogEntry import MissionLogEntry
from opentakserver.models.MissionRole import MissionRole
from opentakserver.models.MissionUID import MissionUID

data_sync_api = Blueprint("data_sync_api", __name__)


@data_sync_api.route('/api/missions')
@auth_required()
def get_missions():
    query: db.Query = db.session.query(Mission)
    query = search(query, Mission, 'name')
    query = search(query, Mission, 'guid')
    query = search(query, Mission, 'tool')

    # Only show users missions that belong to the same groups they belong to
    if not current_user.has_role("administrator"):
        group_filters = []
        groups = db.session.execute(db.session.query(GroupUser).filter_by(user_id=current_user.id, direction=Group.IN)).scalars()
        for group in groups:
            group_filters.append(GroupMission.group_id == group.group_id)
        if group_filters:
            query = query.outerjoin(GroupMission).where(or_(*group_filters)).distinct(Mission.name)

    return paginate(query, Mission)


@data_sync_api.route('/api/missions', methods=['PUT', 'POST'])
@auth_required()
def create_edit_mission():
    mission_name = request.json.get('name')
    creator_uid = request.json.get('creator_uid')
    if not mission_name or not creator_uid:
        return jsonify({'success': False, 'error': 'Please provide a mission name and creator UID'}), 400

    mission_name = bleach.clean(mission_name)
    creator_uid = bleach.clean(creator_uid)

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()

    # Creates a new mission
    if not mission:
        eud = db.session.execute(db.session.query(EUD).filter_by(uid=creator_uid)).first()
        if not eud:
            return jsonify({'success': False, 'error': f"Invalid UID: {creator_uid}"}), 400

        groups = None
        mission_groups = []

        mission = Mission()
        mission.create_time = datetime.datetime.now(datetime.timezone.utc)
        mission.guid = str(uuid.uuid4())
        mission.creator_uid = creator_uid

        for key in request.json.keys():
            if key == 'password' and request.json.get('password'):
                mission.password = hash_password(request.json.get('password'))
            elif key == 'groups':
                group_ids = request.json.get('groups')
                groups = db.session.execute(db.session.query(GroupUser).filter_by(user_id=current_user.id, enabled=True, direction=Group.IN)).scalars()

                # Make sure the user is a member of the IN group that they want the mission to be associated with. Also allow
                # administrators to associate a mission with any group
                for group_id in group_ids:
                    user_in_group = False

                    if not current_user.has_role("administrator"):
                        for group in groups:
                            if group.id == group_id:
                                user_in_group = True
                                break

                    if not user_in_group and not current_user.has_role("administrator"):
                        group = db.session.execute(db.session.query(Group).filter_by(id=group_id)).first()
                        if group:
                            return jsonify({"success": False, "error": f"User is not a member of {group[0].name}"}), 403
                        else:
                            return jsonify({"success": False, "error": f"Invalid group ID: {group_id}"}), 400

                    group_id = int(group_id)
                    group = db.session.execute(db.session.query(Group).filter_by(id=group_id)).first()
                    if not group:
                        continue

                    group_mission = GroupMission()
                    group_mission.mission_name = mission_name
                    group_mission.group_id = group_id
                    mission_groups.append(group_mission)

            elif hasattr(mission, key):
                setattr(mission, key, request.json[key])
            else:
                return jsonify({'success': False, 'error': gettext("Invalid property: %(key)s", key=key)}), 400

        mission.password_protected = (mission.password != '' and mission.password is not None)

        role = MissionRole()
        role.clientUid = creator_uid
        role.username = current_user.username
        role.createTime = datetime.datetime.now(datetime.timezone.utc)
        role.role_type = MissionRole.MISSION_OWNER
        role.mission_name = mission_name

        invitation = MissionInvitation()
        invitation.mission_name = mission_name
        invitation.client_uid = creator_uid
        invitation.creator_uid = creator_uid
        invitation.role = MissionRole.MISSION_OWNER

        try:
            db.session.add(mission)
            db.session.add(role)
            db.session.add(invitation)
            db.session.commit()

            for group in mission_groups:
                db.session.add(group)
            db.session.commit()
        except sqlalchemy.exc.IntegrityError as e:
            logger.error(f"Failed to add mission: {e}")
            logger.debug(mission.serialize())
            return jsonify({'success': False, 'error': gettext("Failed to add mission: %(e)s", e=str(e))}), 400

        rabbit_credentials = pika.PlainCredentials(app.config.get("OTS_RABBITMQ_USERNAME"), app.config.get("OTS_RABBITMQ_PASSWORD"))
        rabbit_host = app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")
        rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbit_host, credentials=rabbit_credentials))
        channel = rabbit_connection.channel()

        for group in groups:
            logger.error(f"Publishing to {group.group.name}.{group.direction}")
            channel.basic_publish(exchange="groups", routing_key=f"{group.group.name}.{group.direction}", body=json.dumps(
                {'uid': app.config.get("OTS_NODE_ID"), 'cot': tostring(generate_new_mission_cot(mission)).decode('utf-8')}))

        channel.basic_publish(exchange="dms", routing_key=creator_uid,
                              body=json.dumps({'uid': creator_uid,
                                               'cot': tostring(generate_invitation_cot(mission, creator_uid)).decode('utf-8')}))
        channel.close()

        return jsonify({'success': True})

    # Update an existing mission

    # Checks if current user is the mission creator
    mission = mission[0]
    is_user_mission_creator = False
    for eud in current_user.euds:
        if eud.uid == mission.creator_uid:
            is_user_mission_creator = True
            break

    # Only allows admins and the mission creator to change existing missions
    if not current_user.has_role('administrator') and not is_user_mission_creator:
        return jsonify({'success': False, 'error': gettext(u'Only an admin or the mission creator can change this mission')}), 403

    for key in request.json:
        if key == 'groups':
            db.session.execute(sqlalchemy.delete(GroupMission).filter_by(mission_name=mission_name))
            db.session.commit()

            for group_id in request.json.get('groups'):
                group_id = int(group_id)
                group = db.session.execute(db.session.query(Group).filter_by(id=group_id)).first()
                if not group:
                    continue

                group_mission = GroupMission()
                group_mission.mission_name = mission_name
                group_mission.group_id = group_id
                db.session.add(group_mission)
            db.session.commit()
        elif hasattr(mission, key):
            setattr(mission, key, request.json.get(key))
        else:
            return jsonify({'success': False, 'error': gettext(u"Invalid property: %(key)s")}), 400

    db.session.execute(sqlalchemy.update(Mission).filter(Mission.name == mission_name).values(**mission.serialize()))
    db.session.commit()

    return jsonify({'success': True})


@data_sync_api.route('/api/missions', methods=['DELETE'])
@roles_required("administrator")
def delete_mission():
    mission_name = request.args.get('name')
    if not mission_name:
        return jsonify({'success': False, 'error': gettext(u'Please specify a mission name')}), 404

    mission_name = bleach.clean(mission_name)

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': gettext(u"Mission %(mission_name)s not found", mission_name=mission_name)}), 404
    mission = mission[0]

    db.session.execute(sqlalchemy.delete(GroupMission).where(GroupMission.mission_name == mission_name))
    db.session.execute(sqlalchemy.delete(MissionContentMission).where(MissionContentMission.mission_name == mission_name))
    db.session.execute(sqlalchemy.delete(MissionChange).where(MissionChange.mission_name == mission_name))
    db.session.execute(sqlalchemy.delete(CoT).where(CoT.mission_name == mission_name))
    db.session.execute(sqlalchemy.delete(MissionInvitation).where(MissionInvitation.mission_name == mission_name))
    db.session.execute(sqlalchemy.delete(MissionLogEntry).where(MissionLogEntry.mission_name == mission_name))
    db.session.execute(sqlalchemy.delete(MissionRole).where(MissionRole.mission_name == mission_name))
    db.session.execute(sqlalchemy.delete(MissionUID).where(MissionUID.mission_name == mission_name))
    db.session.execute(sqlalchemy.delete(Mission).where(Mission.name == mission_name))
    db.session.commit()

    rabbit_credentials = pika.PlainCredentials(app.config.get("OTS_RABBITMQ_USERNAME"), app.config.get("OTS_RABBITMQ_PASSWORD"))
    rabbit_host = app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")
    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbit_host, credentials=rabbit_credentials))
    channel = rabbit_connection.channel()
    channel.basic_publish(exchange="missions", routing_key="missions",
                          body=json.dumps({'uid': app.config.get("OTS_NODE_ID"),
                                           'cot': tostring(generate_mission_delete_cot(mission)).decode('utf-8')}))
    channel.close()
    rabbit_connection.close()

    return jsonify({'success': True})


@data_sync_api.route('/api/missions/invite', methods=['POST'])
@auth_required()
def invite_eud():
    mission_name = request.json['mission_name']
    eud_uid = request.json['uid']
    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': gettext(u"Mission not found: %(mission_name)s", mission_name=mission_name)}), 404
    mission = mission[0]

    # If the user isn't an admin an the mission is password protected, verify the password
    if mission.password_protected and not current_user.has_role("administrator") and not request.json.get('password'):
        return jsonify({'success': False, 'error': gettext(u"Please provide the mission password")}), 403

    elif (mission.password_protected and not current_user.has_role('administrator')
          and not verify_password(request.json.get('password'), mission.password)):
        return jsonify({'success': False, 'error': gettext(u'Invalid password')}), 401

    return invite(mission_name, 'clientuid', eud_uid)
