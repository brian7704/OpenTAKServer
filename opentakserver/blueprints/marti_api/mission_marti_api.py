import datetime
import hashlib
import json
import os
import time
import traceback
import uuid
from urllib.parse import urlparse

import flask
import jwt

import bleach
import sqlalchemy.exc
from bs4 import BeautifulSoup
from flask import Blueprint, request, current_app as app, jsonify
from flask_security import current_user, hash_password, verify_password
from sqlalchemy import update, insert
from werkzeug.utils import secure_filename
import pika

from xml.etree.ElementTree import tostring, Element, fromstring, SubElement

from opentakserver.blueprints.marti_api.marti_api import verify_client_cert
from opentakserver.functions import iso8601_string_from_datetime, datetime_from_iso8601_string
from opentakserver.extensions import db, logger
from opentakserver.models.CoT import CoT
from opentakserver.models.EUD import EUD
from opentakserver.models.Group import Group
from opentakserver.models.Mission import Mission
from opentakserver.models.MissionChange import MissionChange, generate_mission_change_cot
from opentakserver.models.MissionContent import MissionContent
from opentakserver.models.MissionContentMission import MissionContentMission
from opentakserver.models.MissionInvitation import MissionInvitation
from opentakserver.models.MissionLogEntry import MissionLogEntry
from opentakserver.models.MissionRole import MissionRole
from opentakserver.models.MissionUID import MissionUID
from opentakserver.models.Team import Team
from opentakserver.models.user import User

mission_marti_api = Blueprint('mission_marti_api', __name__)


# Only allow access to the mission/data sync API over SSL/port 8443 with a valid client cert.
# nginx will proxy the cert in a header called X-Ssl-Cert by default. This is configurable in ots_https and with the
# OTS_SSL_CERT_HEADER option in config.yml
#@mission_marti_api.before_request
#def verify_client_cert_before_request():
#    if not verify_client_cert():
#        return jsonify({'success': False, 'error': 'Missing or invalid client certificate'}), 400


def verify_token() -> dict | bool:
    token = request.headers.get('Authorization')
    if not token or "Bearer" not in token:
        return False

    token = token.replace("Bearer ", "")

    with open(os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", "opentakserver", "opentakserver.pub"), "r") as key:
        try:
            return jwt.decode(token, key.read(), algorithms=["RS256"])
        except BaseException as e:
            logger.error("Failed to validate mission token: {}".format(e))
            logger.debug(traceback.format_exc())
            return False


# iTAK sucks and doesn't send a token for some reason...
def verify_itak_certificate(mission_name: str = None, mission_guid: str = None) -> MissionRole | flask.Response:
    # Get the username from the client cert forwarded by nginx
    cert = verify_client_cert()
    username = cert.get_subject().commonName

    # Check that the user exists
    user = db.session.execute(db.session.query(User).filter_by(username=username)).first()
    if not user:
        return jsonify({'success': False, 'error': f'User {username} not found'}), 401
    user = user[0]

    # Check that the user owns this EUD
    eud_uid = request.args.get('creatorUid')
    if not eud_uid:
        return jsonify({'success': False, 'error': 'Invalid creatorUid'}), 400

    eud = db.session.execute(db.session.query(EUD).filter_by(uid=eud_uid, user_id=user.id)).first()
    if not eud:
        return jsonify({'success': False, 'error': f'User {username} does not own EUD {eud_uid}'}), 401
    eud = eud[0]

    if not mission_name and mission_guid:
        mission = db.session.execute(db.session.query(Mission).filter_by(guid=mission_guid)).first()
        if not mission:
            return jsonify({'success': False, 'error': f'Invalid mission GUID: {mission_guid}'}), 404
        mission_name = mission[0].name

    # Check that the EUD is subscribed to this mission
    mission_role = db.session.execute(db.session.query(MissionRole).filter_by(clientUid=eud.uid, username=username,
                                                                              mission_name=mission_name)).first()
    if not mission_role:
        logger.error(f"Access denied {username} {mission_name} {eud_uid}")
        return jsonify({'success': False, 'error': 'Access Denied'}), 403

    return mission_role


def check_permission(mission_name: str = None, mission_guid: str = None):
    if "iTAK" not in request.user_agent.string:
        token = verify_token()
        if mission_name and (not token or token['MISSION_NAME'] != mission_name):
            return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401
        elif mission_guid and (not token or token['MISSION_GUID'] != mission_guid):
            return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401
    else:
        cert_is_valid = verify_itak_certificate(mission_name, mission_guid)
        if isinstance(cert_is_valid, flask.Response):
            return cert_is_valid

    return True


def generate_token(mission: Mission, eud_uid: str):
    """
    jti: Unique UUID for the token
    iat: Time token was issued. Can be used to invalidate a token if it was issued before a security event occurred
    sub: The thing the token identifies, the EUD's UID in this case. Used to verify EUD roles, ie MISSION_SUBSCRIBER, MISSION_OWNER, or MISSION_READ_ONLY
    MISSION_NAME: The mission this token is for
    MISSION_GUID: The guid of the mission this token is for

    :param mission:
    :param eud_uid:
    :return: string token
    """
    payload = {'jti': str(uuid.uuid4()), 'iat': int(time.time()), 'sub': eud_uid,
               'iss': urlparse(request.base_url).hostname, 'MISSION_NAME': mission.name,
               'MISSION_GUID': mission.guid}

    server_key = open(os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", "opentakserver",
                                   "opentakserver.nopass.key"), "r")

    token = jwt.encode(payload, server_key.read(), algorithm="RS256")
    server_key.close()

    return token


def generate_new_mission_cot(mission: Mission) -> Element:
    event = Element("event", {"type": "t-x-m-n", "how": "h-g-i-g-o", "version": "2.0", "uid": str(uuid.uuid4()),
                              "start": iso8601_string_from_datetime(datetime.datetime.now()),
                              "time": iso8601_string_from_datetime(datetime.datetime.now()),
                              "stale": iso8601_string_from_datetime(
                                  datetime.datetime.now() + datetime.timedelta(hours=1))})
    SubElement(event, "point", {'ce': '9999999', 'le': '9999999', 'hae': '0', 'lat': '0', 'lon': '0'})
    detail = SubElement(event, "detail")
    SubElement(detail, "mission", {'type': Mission.CREATE, 'tool': mission.tool, 'name': mission.name,
                                   'guid': mission.guid, 'authorUid': mission.creator_uid})

    return event


def generate_invitation_cot(mission: Mission, uid: str, cot_type: str = "t-x-m-i", delete: bool = False) -> Element:
    """
    Generates an invitation (t-x-m-i) or role change (t-x-m-r) cot
    :param mission:
    :param uid:
    :param cot_type:
    :param delete:
    :return:
    """

    event = Element("event", {"type": cot_type, "how": "h-g-i-g-o", "version": "2.0", "uid": str(uuid.uuid4()),
                              "start": iso8601_string_from_datetime(datetime.datetime.now()),
                              "time": iso8601_string_from_datetime(datetime.datetime.now()),
                              "stale": iso8601_string_from_datetime(
                                  datetime.datetime.now() + datetime.timedelta(hours=1))})

    SubElement(event, "point", {"ce": "9999999", "le": "9999999", "hae": "0", "lat": "0", "lon": "0"})
    detail = SubElement(event, "detail")
    mission_tag = SubElement(detail, "mission", {"type": Mission.INVITE, "tool": mission.tool, "name": mission.name,
                                                 "guid": mission.guid, "authorUid": mission.creator_uid,
                                                 "token": generate_token(mission, uid)})

    if not delete:
        role = SubElement(mission_tag, "role", {"type": mission.default_role})
        permissions = SubElement(role, "permissions")

        if mission.default_role == MissionRole.MISSION_SUBSCRIBER:
            SubElement(permissions, "permission", {"type": MissionRole.MISSION_READ})
            SubElement(permissions, "permission", {"type": MissionRole.MISSION_WRITE})
        elif mission.default_role == MissionRole.MISSION_OWNER:
            SubElement(permissions, "permission", {"type": MissionRole.MISSION_MANAGE_FEEDS})
            SubElement(permissions, "permission", {"type": MissionRole.MISSION_SET_PASSWORD})
            SubElement(permissions, "permission", {"type": MissionRole.MISSION_WRITE})
            SubElement(permissions, "permission", {"type": MissionRole.MISSION_MANAGE_LAYERS})
            SubElement(permissions, "permission", {"type": MissionRole.MISSION_UPDATE_GROUPS})
            SubElement(permissions, "permission", {"type": MissionRole.MISSION_DELETE})
            SubElement(permissions, "permission", {"type": MissionRole.MISSION_SET_ROLE})
            SubElement(permissions, "permission", {"type": MissionRole.MISSION_READ})
        else:
            SubElement(permissions, "permission", {"type": MissionRole.MISSION_READ})

    return event


def generate_mission_delete_cot(mission: Mission) -> Element:
    event = Element("event", {"type": "t-x-m-d", "how": "h-g-i-g-o", "version": "2.0", "uid": str(uuid.uuid4()),
                              "start": iso8601_string_from_datetime(datetime.datetime.now()),
                              "time": iso8601_string_from_datetime(datetime.datetime.now()),
                              "stale": iso8601_string_from_datetime(datetime.datetime.now() + datetime.timedelta(hours=1))})
    SubElement(event, "point", {'ce': '9999999', 'le': '9999999', 'hae': '0', 'lat': '0', 'lon': '0'})
    detail = SubElement(event, "detail")
    SubElement(detail, "mission", {'type': Mission.DELETE, 'tool': mission.tool, 'name': mission.name,
                                             'guid': mission.guid, 'authorUid': mission.creator_uid})

    return event


@mission_marti_api.route('/Marti/api/missions/guid/<mission_guid>')
def get_mission_by_guid(mission_guid: str):
    permission_granted = check_permission(mission_guid=mission_guid)
    if isinstance(permission_granted, flask.Response):
        return permission_granted

    password = request.args.get('password')
    mission = db.session.execute(db.session.query(Mission).filter_by(guid=mission_guid)).first()
    if not mission:
        return jsonify({'success': False, 'error': f'No mission found with guid: {mission_guid}'}), 404
    mission = mission[0]

    if mission.password_protected and not verify_password(password, mission.password):
        return jsonify({'success': False, 'error': 'Invalid password'}), 401

    logger.info({'version': "3", 'type': 'Mission', 'data': [mission.to_json()], 'nodeId': app.config.get("OTS_NODE_ID")})
    return jsonify({'version': "3", 'type': 'Mission', 'data': [mission.to_json()], 'nodeId': app.config.get("OTS_NODE_ID")})


@mission_marti_api.route('/Marti/api/missions')
def get_missions():
    password_protected = request.args.get('passwordProtected', False)

    tool = request.args.get('tool')
    if tool:
        tool = bleach.clean(tool)

    default_role = request.args.get('defaultRole')
    if default_role:
        default_role = bleach.clean(default_role).lower() == 'true'

    response = {
        'version': 3, 'type': 'Mission', 'data': [], 'nodeId': app.config.get('OTS_NODE_ID')
    }

    try:
        query = db.session.query(Mission)
        if not password_protected:
            query = query.where(Mission.password_protected is False)
        if tool:
            query = query.where(Mission.tool == tool)
        missions = db.session.execute(query).scalars()
        for mission in missions:
            response['data'].append(mission.to_json())

    except BaseException as e:
        logger.error(f"Failed to get missions: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify(response)


@mission_marti_api.route('/Marti/api/missions/all/invitations', methods=['GET'])
@mission_marti_api.route('/Marti/api/missions/invitations', methods=['GET'])
def all_invitations():
    if 'clientUid' in request.args and request.args.get('clientUid'):
        client_uid = bleach.clean(request.args.get('clientUid'))
    else:
        return '', 200

    response = {
        'version': "3", 'type': 'Mission', 'data': [],
        'nodeId': app.config.get("OTS_NODE_ID"), 'messages': []
    }

    invitations = db.session.execute(db.session.query(MissionInvitation).filter_by(client_uid=client_uid)).all()

    for invitation in invitations:
        response['data'].append(invitation[0].mission_name)

    return jsonify(response)


@mission_marti_api.route('/Marti/api/missions/<mission_name>', methods=['PUT', 'POST'])
def put_mission(mission_name: str):
    """ Used by the Data Sync plugin to create or change a mission """
    new_mission = True

    if not mission_name or not request.args.get('creatorUid'):
        return jsonify({'success': False, 'error': 'Please provide a mission name and creatorUid'}), 400

    eud = db.session.execute(db.session.query(EUD).filter_by(uid=request.args.get('creatorUid'))).first()
    if not eud:
        return jsonify({'success': False, 'error': f"Invalid creatorUid: {request.args.get('creatorUid')}"}), 400
    eud = eud[0]

    password = None
    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if mission:
        mission = mission[0]
        new_mission = False
    else:
        mission = Mission()
        mission.name = bleach.clean(mission_name)
        if 'password' in request.args and request.args.get('password'):
            password = hash_password(request.args.get('password'))

    mission.creator_uid = mission.creator_uid or request.args.get('creatorUid') or mission.creator_uid or None
    mission.description = request.args.get('description') or mission.description or None
    mission.tool = request.args.get('tool') or mission.tool or "public"
    mission.group = request.args.get('group') or mission.group or "__ANON__"
    mission.default_role = request.args.get('defaultRole') or mission.default_role or MissionRole.MISSION_SUBSCRIBER
    mission.password = password or mission.password or None
    mission.password_protected = (mission.password is not None)
    mission.guid = mission.guid or str(uuid.uuid4())
    mission.create_time = mission.create_time or datetime.datetime.now()

    try:
        db.session.add(mission)
        # Will raise IntegrityError if the mission exists, meaning we should update it
        db.session.commit()

        if new_mission:
            mission_role = MissionRole()
            mission_role.clientUid = mission.creator_uid
            mission_role.username = eud.user.username if eud.user else "anonymous"
            mission_role.createTime = datetime.datetime.now()
            mission_role.role_type = MissionRole.MISSION_OWNER
            mission_role.mission_name = mission_name
            db.session.add(mission_role)

            mission_change = MissionChange()
            mission_change.isFederatedChange = False
            mission_change.change_type = MissionChange.CREATE_MISSION
            mission_change.mission_name = mission_name
            mission_change.timestamp = mission.create_time
            mission_change.creator_uid = mission.creator_uid
            mission_change.server_time = mission.create_time

            db.session.add(mission_change)
            db.session.commit()

            event = generate_new_mission_cot(mission)

            rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
            channel = rabbit_connection.channel()
            channel.basic_publish(exchange="missions", routing_key="missions",
                                  body=json.dumps(
                                      {'uid': app.config.get("OTS_NODE_ID"), 'cot': tostring(event).decode('utf-8')}))
    except sqlalchemy.exc.IntegrityError:
        # Mission exists, needs updating
        db.session.rollback()
        db.session.execute(update(Mission).where(Mission.name == mission_name).values(**mission.serialize()))
        db.session.commit()
        return jsonify({'version': "3", 'type': 'Mission', 'data': [mission.to_json()], 'nodeId': app.config.get("OTS_NODE_ID")})
    except BaseException as e:
        logger.error(f"Failed to add mission: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({'success': False, 'error': f"Failed to add mission: {e}"}), 500

    token = generate_token(mission, mission.creator_uid)
    mission_json = mission.to_json()
    mission_json['token'] = token

    if new_mission:
        mission_json['ownerRole'] = MissionRole.OWNER_ROLE

    response = {'version': "3", 'type': 'Mission', 'data': [mission_json], 'nodeId': app.config.get("OTS_NODE_ID")}

    if new_mission:
        return jsonify(response), 201
    else:
        return jsonify(response), 200


@mission_marti_api.route('/Marti/api/missions/<mission_name>', methods=['GET'])
def get_mission(mission_name: str):
    """ Used by the Data Sync plugin to get a feed's metadata """
    if not mission_name:
        return jsonify({'success': False, 'error': 'Invalid mission name'}), 400

    mission_name = bleach.clean(mission_name)

    try:
        mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
        if not mission:
            return jsonify({'success': False, 'error': f'Mission {mission_name} not found'}), 404

        return jsonify({'version': "3", 'type': 'Mission', 'data': [mission[0].to_json()], 'nodeId': app.config.get("OTS_NODE_ID")})
    except BaseException as e:
        logger.error(f"Failed to get mission: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 400


@mission_marti_api.route('/Marti/api/missions/<mission_name>', methods=['DELETE'])
def delete_mission(mission_name: str):
    """ Used by the Data Sync plugin to delete a feed """

    # ATAK sends a creatorUid param, but we ignore it in favor of the UID in the signed JWT token that ATAK also sends.
    creator_uid = request.args.get('creatorUid')

    if "iTAK" not in request.user_agent.string:
        token = verify_token()
        if not token or token['MISSION_NAME'] != mission_name:
            return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401
        eud_uid = token['sub']
    else:
        # cert_is_valid will either be True or flask.Response. If it's flask.Response it indicates an error
        role = verify_itak_certificate(mission_name)
        if isinstance(role, flask.Response):
            return role
        eud_uid = role.clientUid

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if mission:
        mission = mission[0]

        can_delete = False

        # Check if the UID in the token has the MISSION_OWNER role for this mission. If not, it can't delete the mission
        for role in mission.roles:
            if role.clientUid == eud_uid and role.role_type == MissionRole.MISSION_OWNER:
                can_delete = True
                break

        if not can_delete:
            return jsonify({'success': False, 'error': 'Only mission owners can delete missions'}), 403

        db.session.delete(mission)
        db.session.commit()

        rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
        channel = rabbit_connection.channel()
        channel.basic_publish(exchange="missions", routing_key="missions",
                              body=json.dumps({'uid': app.config.get("OTS_NODE_ID"),
                                               'cot': tostring(generate_mission_delete_cot(mission)).decode('utf-8')}))

        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': f'Mission {mission_name} not found'}), 404


@mission_marti_api.route('/Marti/api/missions/<mission_name>/password', methods=['PUT', 'DELETE'])
def set_password(mission_name: str):
    """ Used by the Data Sync plugin to add a password to a feed """
    if "iTAK" not in request.user_agent.string:
        token = verify_token()
        if not token or token['MISSION_NAME'] != mission_name:
            return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401
        eud_uid = token['sub']
    else:
        # cert_is_valid will either be True or flask.Response. If it's flask.Response it indicates an error
        role = verify_itak_certificate(mission_name)
        if isinstance(role, flask.Response):
            return role
        eud_uid = role.clientUid

    if request.method == 'PUT' and 'password' not in request.args:
        return jsonify({'success': False, 'error': 'Please provide the password'}), 400

    role = db.session.execute(db.session.query(MissionRole).filter_by(mission_name=mission_name, clientUid=eud_uid)).first()
    if not role or role[0].role_type != MissionRole.MISSION_OWNER:
        return jsonify({'success': False, 'error': "You do not have permission to change this mission's password"}), 403

    creator_uid = request.args.get('creatorUid')

    if request.method == 'PUT':
        password = hash_password(request.args.get('password'))
        db.session.execute(update(Mission).where(Mission.name == mission_name).values(password=password, password_protected=True))
    elif request.method == 'DELETE':
        db.session.execute(update(Mission).where(Mission.name == mission_name).values(password=None, password_protected=False))
    db.session.commit()

    return jsonify({'success': True})


@mission_marti_api.route('/Marti/api/missions/<mission_name>/invite/<invitation_type>/<invitee>', methods=['PUT'])
def invite(mission_name: str, invitation_type: str, invitee: str):
    permission_granted = check_permission(mission_name)
    if isinstance(permission_granted, flask.Response):
        return permission_granted

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': f"Mission {mission_name} not found"}), 404

    mission = mission[0]

    invitation = MissionInvitation()
    invitation.mission_name = mission_name

    if invitation_type.lower() == "clientuid":
        eud = db.session.execute(db.session.query(EUD).filter_by(uid=invitee)).first()
        if not eud:
            return jsonify({'success': False, 'error': f"No EUD found with UID {invitee}"}), 404
        invitation.client_uid = invitee

    elif invitation_type == "callsign":
        eud = db.session.execute(db.session.query(EUD).filter_by(callsign=invitee)).first()
        if not eud:
            return jsonify({'success': False, 'error': f"No EUD found with callsign {invitee}"}), 404
        invitation.callsign = invitee

    elif invitation_type.lower() == "username":
        eud = db.session.execute(db.session.query(User).filter_by(username=invitee)).first()
        if not eud:
            return jsonify({'success': False, 'error': f"No user found with username {invitee}"}), 404
        invitation.username = invitee

    elif invitation_type == "group":
        group = db.session.execute(db.session.query(Group).filter_by(group_name=invitee)).first()
        if not group:
            return jsonify({'success': False, 'error': f"No group found: {invitee}"}), 404
        invitation.group_name = invitee

    elif invitation_type == "team":
        team = db.session.execute(db.session.query(Team).filter_by(name=invitee)).first()
        if not team:
            return jsonify({'success': False, 'error': f"Team not found: {invitee}"}), 404
        invitation.team_name = invitee

    db.session.add(invitation)
    db.session.commit()

    event = generate_invitation_cot(mission, invitee)
    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()
    channel.basic_publish(exchange="dms", routing_key=invitee, body=json.dumps({"uid": app.config.get("OTS_NODE_ID"),
                                                                                "cot": tostring(event).decode('utf-8')}))

    return '', 200


@mission_marti_api.route('/Marti/api/missions/<mission_name>/invite/<invitation_type>/<invitee>', methods=['DELETE'])
def delete_invitation(mission_name: str, invitation_type: str, invitee: str):
    permission_granted = check_permission(mission_name)
    if isinstance(permission_granted, flask.Response):
        return permission_granted

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': f"Mission {mission_name} not found"}), 404

    mission = mission[0]

    if invitation_type.lower() not in ['clientuid', 'callsign', 'username', 'group', 'team']:
        return jsonify({'success': False, 'error': f"Invalid invitation type: {invitation_type}"}), 400

    # Doing it like this because I can select an EUD, user, group, or team and automatically
    # get all of their invitations
    query = db.session.query(MissionInvitation).where(MissionInvitation.mission_name == mission_name)
    if invitation_type.lower() == 'clientuid':
        query = query.where(MissionInvitation.client_uid == invitee)
    elif invitation_type.lower() == 'callsign':
        query = query.where(MissionInvitation.callsign == invitee)
    elif invitation_type.lower() == 'username':
        query = query.where(MissionInvitation.username == invite)
    elif invitation_type.lower() == 'group':
        query = query.where(MissionInvitation.group == invite)
    elif invitation_type.lower() == 'team':
        query = query.where(MissionInvitation.team == invite)

    invitations = db.session.execute(query).scalars()
    for invitation in invitations:
        db.session.delete(invitation)
    db.session.commit()

    return jsonify({'success': True})


@mission_marti_api.route('/Marti/api/missions/<mission_name>/invite', methods=['POST'])
def invite_json(mission_name: str):
    permission_granted = check_permission(mission_name)
    if isinstance(permission_granted, flask.Response):
        return permission_granted

    creator_uid = request.args.get("creatorUid")
    invitees = request.json

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': f"Mission not found: {mission_name}"}), 404
    mission = mission[0]

    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()

    for invitee in invitees:
        invitation = MissionInvitation()
        invitation.mission_name = mission_name
        invitation.role = invitee['role']['type']

        if invitee['type'].lower() == 'clientuid':
            invitation.client_uid = invitee['invitee']
        elif invitee['type'].lower() == 'callsign':
            invitation.callsign = invitee['invitee']
        elif invitee['type'].lower() == 'username':
            invitation.username = invitee['invitee']
        elif invitee['type'].lower() == 'group':
            invitation.group = invitee['invitee']
        elif invitee['type'].lower() == 'team':
            invitation.team = invitee['invitee']
        else:
            return jsonify({'success': False, 'error': f"Invalid invitation type: {invitation['type']}"}), 400

        db.session.add(invitation)
        db.session.commit()

        event = generate_invitation_cot(mission, invitee['invitee'])

        logger.debug(f"Sending invitation to mission {mission_name} to {invitee['invitee']}")
        channel.basic_publish(exchange="dms", routing_key=invitee['invitee'],
                              body=json.dumps({'uid': app.config['OTS_NODE_ID'], "cot": tostring(event).decode('utf-8')}))

    return jsonify({'success': True})


@mission_marti_api.route('/Marti/api/missions/<mission_name>/subscriptions/roles')
def mission_roles(mission_name: str):
    permission_granted = check_permission(mission_name)
    if isinstance(permission_granted, flask.Response):
        return permission_granted

    response = {"version": "3", "type": "MissionSubscription", "data": [], "nodeId": app.config.get("OTS_NODE_ID")}
    roles = db.session.execute(db.session.query(MissionRole).filter_by(mission_name=mission_name))
    for role in roles:
        response['data'].append(role[0].to_json())

    return jsonify(response)


@mission_marti_api.route('/Marti/api/missions/<mission_name>/role', methods=['PUT'])
def change_eud_role(mission_name: str):
    """ Used by Data Sync to change EUD mission roles or kick an EUD off of a mission """
    if "iTAK" not in request.user_agent.string:
        token = verify_token()
        if not token or token['MISSION_NAME'] != mission_name:
            return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401
        eud_uid = token['sub']
    else:
        # cert_is_valid will either be True or flask.Response. If it's flask.Response it indicates an error
        role = verify_itak_certificate(mission_name)
        if isinstance(role, flask.Response):
            return role
        eud_uid = role.clientUid

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': f"No such mission found: {mission_name}"}), 404
    mission = mission[0]

    role = db.session.execute(db.session.query(MissionRole).filter_by(clientUid=eud_uid, role_type=MissionRole.MISSION_OWNER)).first()
    if not role:
        return jsonify({'success': False, 'error': 'Only mission owners can change EUD roles'}), 403

    client_uid = request.args.get('clientUid')
    if not client_uid:
        return jsonify({'success': False, 'error': 'Please provide a UID'}), 400

    eud = db.session.execute(db.session.query(EUD).filter_by(uid=client_uid)).first()
    if not eud:
        return jsonify({'success': False, 'error': f'Invalid UID: {client_uid}'}), 400
    eud = eud[0]

    new_role = request.args.get('role')
    if new_role and new_role not in [MissionRole.MISSION_OWNER, MissionRole.MISSION_SUBSCRIBER, MissionRole.MISSION_READ_ONLY]:
        return jsonify({'success': False, 'error': f"Invalid role: {new_role}"})
    elif new_role:
        r = db.session.execute(db.session.query(MissionRole).filter_by(clientUid=client_uid, mission_name=mission_name)).all()
        for role in r:
            db.session.delete(role[0])
        db.session.commit()

        role = MissionRole()
        role.clientUid = client_uid
        try:
            role.username = eud.user.username
        except BaseException as e:
            role.username = "anonymous"
        role.createTime = datetime.datetime.now()
        role.role_type = new_role
        role.mission_name = mission_name

        db.session.add(role)
        db.session.commit()

        event = generate_invitation_cot(mission, role.clientUid)
        body = {'uid': app.config.get("OTS_NODE_ID"), 'cot': tostring(event).decode('utf-8')}

        rabbit_connection = pika.BlockingConnection(
            pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
        channel = rabbit_connection.channel()
        channel.basic_publish(exchange="dms", routing_key=client_uid, body=json.dumps(body))

    # No new role provided, kick the EUD off the mission
    else:
        old_role = db.session.execute(db.session.query(MissionRole).filter_by(mission_name=mission_name, clientUid=client_uid)).first()
        if old_role:
            db.session.delete(old_role[0])
            db.session.commit()

        event = generate_invitation_cot(mission, client_uid, 't-x-m-r', delete=True)
        body = {'uid': app.config.get("OTS_NODE_ID"), 'cot': tostring(event).decode('utf-8')}

        rabbit_connection = pika.BlockingConnection(
            pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
        channel = rabbit_connection.channel()
        channel.basic_publish(exchange="dms", routing_key=client_uid, body=json.dumps(body))

    return '', 200


@mission_marti_api.route('/Marti/api/missions/guid/<mission_guid>/role')
def get_role_by_guid(mission_guid: str):
    permission_granted = check_permission(mission_guid=mission_guid)
    if isinstance(permission_granted, flask.Response):
        return permission_granted

    mission = db.session.execute(db.session.query(Mission).filter_by(guid=mission_guid)).first()
    if not mission:
        return jsonify({'success': False, 'error': f'No mission found with guid: {mission_guid}'}), 404
    mission = mission[0]

    response = {"version": "3", "type": "com.bbn.marti.sync.model.MissionRole", "data": [mission.roles[0].to_json()['role']], "nodeId": app.config.get("OTS_NODE_ID")}
    logger.error(response)
    return jsonify(response)


@mission_marti_api.route('/Marti/api/missions/<mission_name>/subscriptions')
def get_subscriptions(mission_name: str):
    permission_granted = check_permission(mission_name)
    if isinstance(permission_granted, flask.Response):
        return permission_granted

    subscriptions = db.session.execute(db.session.query(MissionRole).filter_by(mission_name=mission_name)).all()
    response = {
        "version": "3", "type": "MissionSubscription", "data": [], "nodeId": app.config.get("OTS_NODE_ID")
    }

    for subscription in subscriptions:
        response['data'].append(subscription[0].clientUid)

    return jsonify(response)


@mission_marti_api.route('/Marti/api/missions/<mission_name>/keywords', methods=['PUT'])
def put_mission_keywords(mission_name):
    permission_granted = check_permission(mission_name)
    if isinstance(permission_granted, flask.Response):
        return permission_granted

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': f"Cannot find mission {mission_name}"}), 404
    mission = mission[0]

    new_keywords = request.json
    current_keywords = mission.keywords or []
    for keyword in new_keywords:
        if keyword not in current_keywords:
            current_keywords.append(keyword)

    db.session.execute(update(Mission).where(Mission.name == mission_name).values(keywords=current_keywords))
    db.session.commit()

    return '', 200


@mission_marti_api.route('/Marti/api/missions/<mission_name>/subscription', methods=['PUT'])
def mission_subscribe(mission_name: str):
    """ Used by the Data Sync plugin to subscribe to a feed """

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': f"Cannot find mission {mission_name}"}), 404

    mission = mission[0]

    response = {
        "version": "3", "type": "com.bbn.marti.sync.model.MissionSubscription", "data": {}, "nodeId": app.config.get("OTS_NODE_ID")
    }

    # And EUD will send a token if it has previously subscribed to the mission
    if 'Authorization' in request.headers:
        token = verify_token()
        if not token or token['MISSION_NAME'] != mission_name:
            return jsonify({'success': False, 'error': 'Invalid token'}), 400

        eud = db.session.execute(db.session.query(EUD).filter_by(uid=token['sub'])).first()[0]
        uid = token['sub']
        role = db.session.execute(db.session.query(MissionRole).filter_by(mission_name=mission_name, clientUid=uid)).first()

        # If this request has a token but no role in the DB, this EUD was invited and this is its first time subscribing
        if not role:
            role = MissionRole()
            role.clientUid = token['sub']
            role.username = eud.user.username if eud.user else 'anonymous'
            role.createTime = datetime.datetime.now()
            role.role_type = mission.default_role
            role.mission_name = token['MISSION_NAME']

            db.session.add(role)
            db.session.commit()
        else:
            role = role[0]

        response['data'] = {
            "token": request.headers.get('Authorization').replace('Bearer ', ''),
            "clientUid": token['sub'],
            "username": role.username,
            "createTime": role.createTime,
            "role": role.to_json()['role'],
        }

    # If no token is sent, this is a new subscription request
    else:
        if "uid" not in request.args:
            return jsonify({'success': False, 'error': 'Missing UID'}), 400

        uid = bleach.clean(request.args.get("uid"))
        eud = db.session.execute(db.session.query(EUD).filter_by(uid=uid)).first()
        if not eud:
            return jsonify({'success': False, 'error': f"Invalid UID: {uid}"}), 400
        eud = eud[0]

        if mission.password_protected:
            if not verify_password(request.args.get('password', ''), mission.password):
                return jsonify({'success': False, 'error': 'Invalid password'}), 401

        role = db.session.execute(db.session.query(MissionRole).filter_by(mission_name=mission_name, clientUid=uid)).first()
        if not role:
            role = MissionRole()
            role.clientUid = uid
            role.username = eud.user.username
            role.createTime = datetime.datetime.now()
            role.role_type = mission.default_role
            role.mission_name = mission.name

            db.session.add(role)
            db.session.commit()
        else:
            role = role[0]

        token = generate_token(mission, uid)

        response['data'] = {
            "token": token,
            "clientUid": uid,
            "mission": mission.to_json(),
            "username": role.username,
            "createTime": role.createTime,
            "role": role.to_json()['role'],
        }

    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()
    channel.queue_bind(queue=uid, exchange="missions", routing_key=f"missions.{mission_name}")

    # Delete any invitations to this mission for this EUD
    invitations = db.session.execute(db.session.query(MissionInvitation).filter_by(mission_name=mission_name, client_uid=uid)).all()
    for invitation in invitations:
        db.session.delete(invitation[0])
    db.session.commit()

    return jsonify(response), 201


@mission_marti_api.route('/Marti/api/missions/<mission_name>/subscription', methods=['DELETE'])
def mission_unsubscribe(mission_name: str):
    """ Used by the Data Sync plugin to unsubscribe to a feed """
    if "iTAK" not in request.user_agent.string:
        token = verify_token()
        if not token or token['MISSION_NAME'] != mission_name:
            return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401
        eud_uid = token['sub']
    else:
        # cert_is_valid will either be True or flask.Response. If it's flask.Response it indicates an error
        role = verify_itak_certificate(mission_name)
        if isinstance(role, flask.Response):
            return role
        eud_uid = role.clientUid

    #if "uid" not in request.args:
    #    return jsonify({'success': False, 'error': 'Missing UID'}), 400

    #uid = bleach.clean(request.args.get("uid"))
    role = db.session.execute(db.session.query(MissionRole).filter_by(clientUid=eud_uid, mission_name=mission_name)).first()

    if role:
        db.session.delete(role[0])
        db.session.commit()

    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()
    channel.queue_unbind(queue=eud_uid, exchange="missions", routing_key=f"missions.{mission_name}")

    return '', 200


@mission_marti_api.route('/Marti/api/missions/<mission_name>/changes', methods=['GET'])
def mission_changes(mission_name):
    permission_granted = check_permission(mission_name)
    if isinstance(permission_granted, flask.Response):
        return permission_granted

    squashed = request.args.get('squashed')
    if squashed:
        squashed = bleach.clean(squashed)

    response = {
        "version": "3", "type": "MissionChange", "data": [], "nodeId": app.config.get("OTS_NODE_ID")
    }

    changes = db.session.execute(db.session.query(MissionChange).filter_by(mission_name=mission_name)).all()
    for change in changes:
        response['data'].append(change[0].to_json())

    return jsonify(response)


@mission_marti_api.route('/Marti/api/missions/logs/entries', methods=['POST'])
def create_log_entry():
    permission_granted = check_permission(request.json['missionNames'][0])
    if isinstance(permission_granted, flask.Response):
        return permission_granted

    mission = db.session.execute(db.session.query(Mission).filter_by(name=request.json['missionNames'][0])).first()
    if not mission:
        return jsonify({'success': False, 'error': f"Mission not found: {request.json['missionNames'][0]}"}), 404

    log_entry = MissionLogEntry()
    log_entry.content = request.json.get('content')
    log_entry.creator_uid = request.json.get('creatorUid')
    log_entry.entry_uid = str(uuid.uuid4())
    log_entry.mission_name = request.json.get('missionNames')[0]
    log_entry.server_time = datetime.datetime.now()
    log_entry.dtg = datetime_from_iso8601_string(request.json.get('dtg'))
    log_entry.created = datetime.datetime.now()
    log_entry.keywords = request.json.get('keywords')

    db.session.add(log_entry)

    response = {
        'version': '3', 'type': '', 'messages': [], 'nodeId': app.config.get('OTS_NODE_ID'), 'data': [log_entry.to_json()]
    }

    mission_change = MissionChange()
    mission_change.content_uid = log_entry.entry_uid
    mission_change.isFederatedChange = False
    mission_change.change_type = MissionChange.CHANGE
    mission_change.timestamp = log_entry.dtg
    mission_change.creator_uid = log_entry.creator_uid
    mission_change.server_time = datetime.datetime.now()
    mission_change.mission_name = log_entry.mission_name

    db.session.add(mission_change)
    db.session.commit()

    change_cot = generate_mission_change_cot(log_entry.mission_name, mission[0], mission_change, cot_type='t-x-m-c-l')
    body = json.dumps({'uid': log_entry.creator_uid, 'cot': tostring(change_cot).decode('utf-8')})

    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()
    channel.basic_publish("missions", routing_key=f"missions.{log_entry.mission_name}", body=body)

    return jsonify(response), 201


@mission_marti_api.route('/Marti/api/missions/<mission_name>/log', methods=['GET'])
def mission_log(mission_name):
    permission_granted = check_permission(mission_name)
    if isinstance(permission_granted, flask.Response):
        return permission_granted

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': f"Mission {mission_name} not found"}), 404
    mission = mission[0]

    response = {
        "version": "3", "type": "com.bbn.marti.sync.model.LogEntry", "data": [],
        "nodeId": app.config.get("OTS_NODE_ID")
    }

    for log in mission.mission_logs:
        response['data'].append(log.to_json())

    return jsonify(response)


@mission_marti_api.route('/Marti/sync/upload', methods=['POST'])
def upload_content():
    """
    Used by the Data Sync plugin when adding files to a mission
    Also used to upload files and data packages

    :return: flask.Response
    """

    file_name = bleach.clean(request.args.get('name')) if 'name' in request.args else None
    keywords = request.args.getlist('keywords')

    if 'creatorUid' in request.args:
        creator_uid = request.args.get('creatorUid')
    # iTAK uses CreatorUid instead of creatorUid
    elif 'CreatorUid' in request.args:
        creator_uid = request.args.get('CreatorUid')
    else:
        creator_uid = None

    if not file_name:
        return jsonify({'success': False, 'error': 'File name cannot be blank'}), 400

    filename, extension = os.path.splitext(secure_filename(file_name))
    if extension.replace('.', '').lower() not in app.config.get("ALLOWED_EXTENSIONS"):
        logger.error(f"{extension} is not an allowed file extension")
        return jsonify({'success': False, 'error': f'{extension} is not an allowed file extension'}), 400

    file = request.data
    sha256 = hashlib.sha256()
    sha256.update(file)

    content = db.session.execute(db.session.query(MissionContent).filter_by(hash=sha256.hexdigest())).first()
    if not content:
        content = MissionContent()
        content.mime_type = request.content_type
        content.filename = file_name
        content.submission_time = datetime.datetime.now()
        content.submitter = current_user.username if current_user.is_authenticated else "anonymous"
        content.uid = str(uuid.uuid4())
        content.creator_uid = creator_uid
        content.size = request.content_length
        content.expiration = -1
        content.keywords = keywords if keywords else []
        content.hash = sha256.hexdigest()
        content_pk = db.session.execute(insert(MissionContent).values(**content.serialize()))
        content_pk = content_pk.inserted_primary_key[0]
        db.session.commit()
    else:
        content = content[0]
        content_pk = content.id

    # Save the content even if it exists in the database in case it was deleted from disk
    os.makedirs(os.path.join(app.config.get("OTS_DATA_FOLDER"), 'missions'), exist_ok=True)
    with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), 'missions', file_name), 'wb') as f:
        f.write(file)

    response = {
        "UID": content.uid, "SubmissionDateTime": iso8601_string_from_datetime(content.submission_time), "MIMEType": content.mime_type,
        "SubmissionUser": content.submitter, "PrimaryKey": content_pk, "Hash": content.hash, "CreatorUid": creator_uid,
        "Name": file_name
    }

    return jsonify(response)


@mission_marti_api.route('/Marti/api/sync/metadata/<content_hash>/keywords', methods=['PUT'])
def add_content_keywords(content_hash: str):
    # Not validating if the EUD is subscribed to the mission since we're not given the mission name or GUID
    # Instead, assume this EUD isn't malicious since we require a valid cert in order to get here

    keywords = request.json
    content = db.session.execute(db.session.query(MissionContent).filter_by(hash=content_hash)).first()
    if not content:
        return jsonify({'success': False, 'error': f"No content found with hash: {content_hash}"})
    content: MissionContent = content[0]
    current_keywords = content.keywords if content.keywords else []

    for keyword in keywords:
        if keyword not in current_keywords:
            current_keywords.append(keyword)
    db.session.execute(update(MissionContent).where(MissionContent.hash == content_hash).values(keywords=current_keywords))
    db.session.commit()

    return '', 200


@mission_marti_api.route('/Marti/api/missions/<mission_name>/contents', methods=['PUT'])
def mission_contents(mission_name: str):
    """ Associates content/files with a mission """
    permission_granted = check_permission(mission_name)
    if isinstance(permission_granted, flask.Response):
        return permission_granted

    body = request.json

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        logger.error(f"No such mission: {mission_name}")
        return jsonify({'success': False, 'error': f"No such mission: {mission_name}"}), 404

    mission = mission[0]

    if 'hashes' in body:
        for content_hash in body['hashes']:
            content = db.session.execute(db.session.query(MissionContent).filter_by(hash=content_hash)).first()
            if not content:
                logger.error(f"No such file with hash {content_hash}")
                return jsonify({'success': False, 'error': f"No such file with hash {content_hash}"}), 404

            content: MissionContent = content[0]

            mission_content_mission = db.session.execute(db.session.query(MissionContentMission).filter_by(mission_content_id=content.id, mission_name=mission_name)).first()
            if not mission_content_mission:
                mission_content_mission = MissionContentMission()
                mission_content_mission.mission_name = mission_name
                mission_content_mission.mission_content_id = content.id

                db.session.add(mission_content_mission)

                mission_change = MissionChange()
                mission_change.isFederatedChange = False
                mission_change.change_type = MissionChange.ADD_CONTENT
                mission_change.content_uid = content.uid
                mission_change.mission_name = mission_name
                mission_change.timestamp = datetime.datetime.now()
                mission_change.creator_uid = content.creator_uid
                mission_change.server_time = datetime.datetime.now()

                db.session.add(mission_change)

                event = generate_mission_change_cot(mission_name, mission, mission_change, content=content)

                body = json.dumps({'uid': mission_change.creator_uid, 'cot': tostring(event).decode('utf-8')})
                rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
                channel = rabbit_connection.channel()
                channel.basic_publish("missions", routing_key=f"missions.{mission_name}", body=body)

    if 'uids' in body:
        for uid in body['uids']:
            mission_uid = db.session.execute(db.session.query(MissionUID).filter_by(uid=uid)).first()
            if mission_uid:
                mission_uid = mission_uid[0]
                change_pk = mission_uid.mission_change_id
                mission_change = None
            else:
                mission_uid = MissionUID()

                mission_change = MissionChange()
                mission_change.isFederatedChange = False
                mission_change.change_type = MissionChange.ADD_CONTENT
                mission_change.mission_name = mission_name
                mission_change.timestamp = datetime.datetime.now()
                mission_change.creator_uid = request.args.get('creatorUid')
                mission_change.server_time = datetime.datetime.now()
                mission_change.mission_uid = uid

                change_pk = db.session.execute(insert(MissionChange).values(**mission_change.serialize()))
                db.session.commit()
                change_pk = change_pk.inserted_primary_key[0]

            mission_uid.uid = uid
            mission_uid.timestamp = datetime.datetime.now()
            mission_uid.creator_uid = request.args.get('creatorUid')
            mission_uid.mission_name = mission_name

            # iTAK sucks. It sends a CoT and makes a PUT to this endpoint rather than including a <dest mission="mission_name">
            # tag in the CoT. This endpoint finishes before the CoT can be parsed and inserted into the database. In that case
            # we insert a row in the mission_uids table with the CoT data missing, and the parse_point method in
            # cot_controller will fill it in
            cot = db.session.execute(db.session.query(CoT).filter_by(uid=uid)).first()
            if cot:
                cot = cot[0]

                mission_uid.cot_type = cot.type
                mission_uid.latitude = cot.point.latitude
                mission_uid.longitude = cot.point.longitude

                event = BeautifulSoup(cot.xml, 'xml')
                usericon = event.find('usericon')
                color = event.find('color')
                contact = event.find('contact')

                if usericon and 'iconsetpath' in usericon.attrs:
                    mission_uid.iconset_path = usericon.attrs['iconsetpath']
                elif usericon and 'iconsetPath' in usericon.attrs:
                    mission_uid.iconset_path = usericon.attrs['iconsetPath']

                if color and 'argb' in color.attrs:
                    mission_uid.color = color.attrs['argb']
                if color and 'value' in color.attrs:
                    mission_uid.color = color.attrs['value']

                if contact and 'callsign' in contact.attrs:
                    mission_uid.callsign = contact.attrs['callsign']

            try:
                db.session.add(mission_uid)
                db.session.commit()
            except sqlalchemy.exc.IntegrityError:
                db.session.rollback()
                db.session.execute(update(MissionUID).where(MissionUID.uid == mission_uid.uid).values(**mission_uid.serialize()))
                db.session.commit()

            if mission_change:
                event = generate_mission_change_cot(mission_name, mission, mission_change, mission_uid=mission_uid)

                body = json.dumps({'uid': mission_change.creator_uid, 'cot': tostring(event).decode('utf-8')})
                rabbit_connection = pika.BlockingConnection(
                    pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
                channel = rabbit_connection.channel()
                channel.basic_publish("missions", routing_key=f"missions.{mission_name}", body=body)

    db.session.commit()

    return jsonify({"version": "3", "type": "Mission", "data": [mission.to_json()], "nodeId": app.config.get("OTS_NODE_ID")})


@mission_marti_api.route('/Marti/api/missions/<mission_name>/contents', methods=['DELETE'])
def delete_content(mission_name: str):
    if "iTAK" not in request.user_agent.string:
        token = verify_token()
        if not token or token['MISSION_NAME'] != mission_name:
            return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401
        eud_uid = token['sub']
    else:
        # cert_is_valid will either be True or flask.Response. If it's flask.Response it indicates an error
        role = verify_itak_certificate(mission_name)
        if isinstance(role, flask.Response):
            return role
        eud_uid = role.clientUid

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': f'Mission {mission_name} not found'}), 404
    mission = mission[0]

    mission_change = MissionChange()
    mission_change.isFederatedChange = False
    mission_change.change_type = MissionChange.REMOVE_CONTENT
    mission_change.mission_name = mission_name
    mission_change.timestamp = datetime.datetime.now()
    mission_change.creator_uid = request.args.get('creatorUid')
    mission_change.server_time = datetime.datetime.now()

    mission_uid = None
    cot_event = None
    if 'uid' in request.args:
        mission_uid = db.session.execute(db.session.query(MissionUID).filter_by(uid=request.args.get('uid'))).first()
        if not mission_uid:
            return jsonify({'success': False, 'error': f"UID {request.args.get('uid')} not found"}), 404
        else:
            mission_uid = mission_uid[0]
            mission_uid.mission_name = None
            mission_change.mission_uid = mission_uid.uid
        cot_event = db.session.execute(db.session.query(CoT).filter_by(uid=request.args.get("uid"))).first()
        if cot_event:
            cot_event = cot_event[0]
            cot_event.mission_name = None
            db.session.add(cot_event)
            cot_event = BeautifulSoup(cot_event.xml, 'xml').find('event')

    # Files will be kept in the DB so the mission log is correct and on disk in case it gets added back to a mission
    content = None
    if 'hash' in request.args:
        content = db.session.execute(db.session.query(MissionContent).filter_by(hash=request.args.get('hash'))).first()
        if not content:
            return jsonify({'success': False, 'error': f"No content found with hash {request.args.get('hash')}"}), 404
        content = content[0]

        mission_change.content_uid = content.uid

        try:
            mission_content_mission = db.session.execute(db.session.query(MissionContentMission)
                                                         .filter_by(mission_name=mission_name, mission_content_id=content.uid)).first()
            if mission_content_mission:
                db.session.delete(mission_content_mission[0])
                db.session.commit()
        except BaseException as e:
            logger.error(f"Failed to delete content with hash {request.args.get('hash')}: {e}")
            logger.debug(traceback.format_exc())
            return jsonify({'success': False, 'error': f"Failed to delete content with hash {request.args.get('hash')}: {e}"}), 500

    event = generate_mission_change_cot(eud_uid, mission, mission_change, content=content, mission_uid=mission_uid, cot_event=cot_event)
    body = {'uid': app.config.get("OTS_NODE_ID"), 'cot': tostring(event).decode('utf-8')}

    rabbit_connection = pika.BlockingConnection(
        pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()
    channel.basic_publish(exchange="missions", routing_key=f"missions.{mission_name}", body=json.dumps(body))

    db.session.add(mission_change)
    db.session.commit()

    return jsonify({"version": "3", "type": "Mission", "data": [mission.to_json()], "nodeId": app.config.get("OTS_NODE_ID")})


@mission_marti_api.route('/Marti/api/missions/<mission_name>/contents/missionpackage', methods=['PUT'])
def add_content(mission_name):
    logger.info(request.headers)
    logger.info(request.args)
    logger.info(request.data)
    client_uid = request.args.get('clientUid')
    if 'Authorization' not in request.headers or not verify_token():
        return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401

    return '', 200


@mission_marti_api.route('/Marti/api/missions/<mission_name>/cot')
def get_mission_cots(mission_name: str):
    """
    Used by the Data Sync plugin to get all CoTs associated with a feed. Returns the CoTs encapsulated by an
    <events> tag
    """

    permission_granted = check_permission(mission_name)
    if isinstance(permission_granted, flask.Response):
        return permission_granted

    cots = db.session.execute(db.session.query(CoT).filter_by(mission_name=mission_name)).all()

    events = Element("events")

    for cot in cots:
        events.append(fromstring(cot[0].xml))

    return tostring(events).decode('utf-8'), 200
