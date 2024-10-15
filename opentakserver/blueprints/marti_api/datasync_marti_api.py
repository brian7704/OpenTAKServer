import datetime
import hashlib
import json
import os
import time
import traceback
import uuid

import flask
import jwt

import bleach
import sqlalchemy.exc
from flask import Blueprint, request, current_app as app, jsonify
from flask_security import current_user
from sqlalchemy import update, insert
from werkzeug.utils import secure_filename
import pika

from xml.etree.ElementTree import tostring, Element, fromstring, SubElement

from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.blueprints.marti_api.certificate_enrollment_api import basic_auth
from opentakserver.extensions import db, logger
from opentakserver.models.CoT import CoT
from opentakserver.models.EUD import EUD
from opentakserver.models.Group import Group
from opentakserver.models.Mission import Mission
from opentakserver.models.MissionChange import MissionChange, generate_mission_change_cot
from opentakserver.models.MissionContent import MissionContent
from opentakserver.models.MissionContentMission import MissionContentMission
from opentakserver.models.MissionInvitation import MissionInvitation
from opentakserver.models.MissionRole import MissionRole
from opentakserver.models.MissionUID import MissionUID
from opentakserver.models.Team import Team
from opentakserver.models.user import User

datasync_api = Blueprint('datasync_api', __name__)


def verify_token(token) -> dict | bool:
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


def generate_token(mission: Mission):
    payload = {'jti': mission.guid, 'iat': mission.create_time or time.time(), 'sub': 'SUBSCRIPTION', 'iss': '',
               'SUBSCRIPTION': mission.guid, 'MISSION_NAME': mission.name, 'MISSION_GUID': mission.guid}

    server_key = open(os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", "opentakserver",
                                   "opentakserver.nopass.key"), "r")

    token = jwt.encode(payload, server_key.read(), algorithm="RS256")
    server_key.close()

    return token


def generate_invitation_cot(mission: Mission):
    logger.info(mission.serialize())
    event = Element("event", {"type": "t-x-m-i", "how": "h-g-i-g-o", "version": "2.0", "uid": str(uuid.uuid4()),
                              "start": iso8601_string_from_datetime(datetime.datetime.now()),
                              "time": iso8601_string_from_datetime(datetime.datetime.now()),
                              "stale": iso8601_string_from_datetime(
                                  datetime.datetime.now() + datetime.timedelta(hours=1))})

    SubElement(event, "point", {"ce": "9999999", "le": "9999999", "hae": "0", "lat": "0", "lon": "0"})
    detail = SubElement(event, "detail")
    mission_tag = SubElement(detail, "mission", {"type": Mission.INVITE, "tool": "public", "name": mission.name,
                                                 "guid": mission.guid, "authorUid": "",
                                                 "token": generate_token(mission)})
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


@datasync_api.route('/Marti/api/missions')
def get_missions():
    password_protected = request.args.get('passwordProtected')
    if password_protected:
        password_protected = bleach.clean(password_protected).lower() == 'true'

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
        missions = db.session.execute(db.session.query(Mission).filter_by(tool=tool)).scalars()
        for mission in missions:
            response['data'].append(mission.to_json())

    except BaseException as e:
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify(response)


@datasync_api.route('/Marti/api/missions/all/invitations', methods=['GET'])
@datasync_api.route('/Marti/api/missions/invitations', methods=['GET'])
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
        response['data'].append(invitation[0].name)

    return jsonify(response)


@datasync_api.route('/Marti/api/missions/<mission_name>', methods=['PUT', 'POST'])
def put_mission(mission_name: str):
    """ Used by the Data Sync plugin to create a new feed """
    if not mission_name:
        return jsonify({'success': False, 'error': 'Invalid mission name'}), 400

    mission = Mission()
    mission.name = bleach.clean(mission_name)

    mission.creator_uid = bleach.clean(request.args.get('creatorUid')) if 'creatorUid' in request.args else None
    mission.description = bleach.clean(request.args.get('description')) if 'description' in request.args else None
    mission.tool = bleach.clean(request.args.get('tool')) if 'tool' in request.args else None
    mission.group = bleach.clean(request.args.get('group')) if 'group' in request.args else None
    mission.default_role = bleach.clean(request.args.get('defaultRole')) if 'defaultRole' in request.args else MissionRole.MISSION_SUBSCRIBER
    mission.password = request.args.get('password') if 'password' in request.args else None
    mission.guid = str(uuid.uuid4())

    mission.password_protected = False
    if mission.password:
        mission.password = bleach.clean(mission.password)
        mission.password_protected = True

    mission.uid = str(uuid.uuid4())
    mission.create_time = datetime.datetime.now()

    token = generate_token(mission)

    try:
        db.session.add(mission)
        db.session.commit()
    except BaseException as e:
        logger.error("Failed to add mission: {}".format(e))
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': "Failed to add mission: {}".format(e)}), 400

    mission_change = MissionChange()
    mission_change.isFederatedChange = False
    mission_change.change_type = MissionChange.CREATE_MISSION
    mission_change.mission_name = mission_name
    mission_change.timestamp = mission.create_time
    mission_change.creator_uid = mission.creator_uid
    mission_change.server_time = mission.create_time

    db.session.add(mission_change)
    db.session.commit()

    mission_json = mission.to_json()
    mission_json['token'] = token
    mission_json['ownerRole'] = MissionRole.OWNER_ROLE

    response = {'version': "3", 'type': 'Mission', 'data': [mission_json], 'nodeId': app.config.get("OTS_NODE_ID")}

    return jsonify(response), 201


@datasync_api.route('/Marti/api/missions/<mission_name>', methods=['GET'])
def get_mission(mission_name: str):
    """ Used by the Data Sync plugin to get a feed's metadata """
    if 'Authorization' in request.headers:

        if 'Bearer' in request.headers.get('Authorization') and not verify_token(request.headers.get("Authorization")):
            return jsonify({'success': False, 'error': 'Invalid token'}), 401

        elif 'Basic' in request.headers.get('Authorization') and not basic_auth(request.headers.get('Authorization').replace("Basic ", "")):
            return jsonify({'success': False, 'error': 'Bad username or password'}), 401

    if not mission_name:
        return jsonify({'success': False, 'error': 'Invalid mission name'}), 400

    mission_name = bleach.clean(mission_name)

    try:
        mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
        if not mission:
            return jsonify({'success': False, 'error': f'Mission {mission_name} not found'}), 404

        return jsonify({'version': "3", 'type': 'Mission', 'data': [mission[0].to_json()], 'nodeId': app.config.get("OTS_NODE_ID")})
    except BaseException as e:
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 400


@datasync_api.route('/Marti/api/missions/<mission_name>', methods=['DELETE'])
def delete_mission(mission_name: str):
    """ Used by the Data Sync plugin to delete a feed """
    if 'creatorUid' not in request.args:
        return jsonify({'success': False, 'error': 'Invalid creator UID'}), 400

    creator_uid = request.args.get('creatorUid')

    mission = db.session.execute(db.session.query(Mission).filter_by(creator_uid=creator_uid, name=mission_name)).first()
    if mission:
        db.session.delete(mission[0])
        db.session.commit()
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': f'Mission {mission_name} not found'}), 404


@datasync_api.route('/Marti/api/mission/<mission_name>/password', methods=['PUT'])
def set_password(mission_name: str):
    """ Used by the Data Sync plugin to add a password to a feed """
    if 'creatorUid' not in request.args or 'password' not in request.args:
        return jsonify({'success': False, 'error': 'Please provide the creatorUid and password'}), 400

    creator_uid = request.args.get('creatorUid')
    password = request.args.get('password')

    db.session.execute(update(Mission).where(Mission.name == mission_name).where(Mission.creatorUid == creator_uid)
                       .values(password=password))

    return jsonify({'success': True})


@datasync_api.route('/Marti/api/missions/<mission_name>/invite/<invitation_type>/<invitee>', methods=['PUT'])
def invite(mission_name: str, invitation_type: str, invitee: str):
    invitation_types = ['clientUid', 'callsign', 'userName', 'group', 'team']

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

    event = generate_invitation_cot(mission)
    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()
    logger.warning(f"publishing messages to {invitee}")
    logger.error(tostring(event))
    channel.basic_publish(exchange="dms", routing_key=invitee, body=json.dumps({"uid": app.config.get("OTS_NODE_ID"),
                                                                                "cot": tostring(event).decode('utf-8')}))

    return '', 200


@datasync_api.route('/Marti/api/missions/<mission_name>/invite', methods=['POST'])
def invite_by_form(mission_name: str):
    creator_uid = request.args.get("creatorUid")
    contacts = request.form.getlist("contacts")

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': f"Mission not found: {mission_name}"}), 404
    mission = mission[0]

    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()

    for contact in contacts:
        invitation = MissionInvitation()
        invitation.mission_name = mission_name
        invitation.client_uid = contact

        db.session.add(invitation)
        db.session.commit()

        event = generate_invitation_cot(mission)

        channel.basic_publish(exchange="dms", routing_key=contact, body=json.dumps({'uid': app.config['OTS_NODE_ID'],
                                                                                    "cot": tostring(event).decode('utf-8')}))


@datasync_api.route('/Marti/api/missions/<mission_name>/subscriptions/roles')
def mission_roles(mission_name: str):
    response = {"version": "3", "type": "MissionSubscription", "data": [], "nodeId": app.config.get("OTS_NODE_ID")}
    roles = db.session.execute(db.session.query(MissionRole).filter_by(mission_name=mission_name))
    for role in roles:
        response['data'].append(role.to_json())

    return jsonify(response)


@datasync_api.route('/Marti/api/missions/<mission_name>/subscriptions')
def get_subscriptions(mission_name: str):
    subscriptions = db.session.execute(db.session.query(MissionRole).filter_by(mission_name=mission_name)).all()
    response = {
        "version": "3", "type": "MissionSubscription", "data": [], "nodeId": app.config.get("OTS_NODE_ID")
    }

    for subscription in subscriptions:
        response['data'].append(subscription[0].clientUid)

    return jsonify(response)


@datasync_api.route('/Marti/api/missions/<mission_name>/keywords', methods=['PUT'])
def put_mission_keywords(mission_name):
    keywords = request.json()

    return '', 200


@datasync_api.route('/Marti/api/missions/<mission_name>/subscription', methods=['PUT'])
def mission_subscribe(mission_name: str) -> flask.Response:
    """ Used by the Data Sync plugin to subscribe to a feed """

    if "uid" not in request.args:
        return jsonify({'success': False, 'error': 'Missing UID'}), 400

    uid = bleach.clean(request.args.get("uid"))
    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': f"Cannot find mission {mission_name}"}), 404

    mission = mission[0]

    if not current_user.is_authenticated:
        username = "anonymous"
    else:
        username = current_user.username

    role = db.session.execute(db.session.query(MissionRole).filter_by(mission_name=mission_name, clientUid=uid)).first()
    if not role:
        role = MissionRole()
        role.clientUid = uid
        role.username = username
        role.createTime = datetime.datetime.now()
        role.role_type = MissionRole.MISSION_SUBSCRIBER
        role.mission_name = mission.name

        db.session.add(role)
        db.session.commit()
    else:
        role = role[0]

    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()
    channel.queue_bind(queue=uid, exchange="missions", routing_key=mission_name)

    response = {
        "version": "3", "type": "com.bbn.marti.sync.model.MissionSubscription", "data": {
            "token": generate_token(mission),
            "mission": mission.to_json(),
            "username": username,
            "createTime": role.createTime,
            "role": role.to_json(),
            "nodeId": app.config.get("OTS_NODE_ID")
        }
    }

    return jsonify(response), 201


@datasync_api.route('/Marti/api/missions/<mission_name>/subscription', methods=['DELETE'])
def mission_unsubscribe(mission_name: str) -> flask.Response:
    """ Used by the Data Sync plugin to unsubscribe to a feed """
    if "uid" not in request.args:
        return jsonify({'success': False, 'error': 'Missing UID'}), 400

    uid = bleach.clean(request.args.get("uid"))
    role = db.session.execute(db.session.query(MissionRole).filter_by(clientUid=uid, mission_name=mission_name)).first()

    if role:
        db.session.delete(role[0])
        db.session.commit()

    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()
    channel.queue_unbind(queue=uid, exchange="missions", routing_key=mission_name)

    return '', 200


@datasync_api.route('/Marti/api/missions/<mission_name>/changes', methods=['GET'])
def mission_changes(mission_name):
    # {"version":"3","type":"MissionChange","data":[{"isFederatedChange":false,"type":"CREATE_MISSION","missionName":"my_mission","timestamp":"2024-05-17T16:39:34.621Z","creatorUid":"ANDROID-e3a3c5d176263d80","serverTime":"2024-05-17T16:39:34.621Z"}],"nodeId":"a2efc4ca15a74ccd89c947d6b5e551bf"}
    squashed = request.args.get('squashed')
    if squashed:
        squashed = bleach.clean(squashed)

    response = {
        "version": "3", "type": "MissionChange", "data": [], "nodeId": app.config.get("OTS_NODE_ID")
    }

    return jsonify(response)


@datasync_api.route('/Marti/api/missions/<mission_name>/log', methods=['GET'])
def mission_log(mission_name):
    # ATAK makes queries for this path but the TAK.gov server doesn't seem to ever return anything in the data
    # list. Keeping the response as-is until I can find out what exactly what this API call is supposed to do

    response = {
        "version": "3", "type": "com.bbn.marti.sync.model.LogEntry", "data": [],
        "nodeId": app.config.get("OTS_NODE_ID")
    }

    return jsonify(response)


@datasync_api.route('/Marti/sync/upload', methods=['POST'])
def upload_content() -> flask.Response:
    """
    Used by the Data Sync plugin when adding files to a mission

    :return: flask.Response
    """

    file_name = bleach.clean(request.args.get('name')) if 'name' in request.args else None
    creator_uid = bleach.clean(request.args.get('creatorUid')) if 'creatorUid' in request.args else None

    if not file_name:
        return jsonify({'success': False, 'error': 'File name cannot be blank'}), 400

    if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "missions", file_name)):
        return jsonify({'success': True})

    filename, extension = os.path.splitext(secure_filename(file_name))
    if extension.replace('.', '').lower() not in app.config.get("ALLOWED_EXTENSIONS"):
        logger.error(f"{extension} is not an allowed file extension")
        return jsonify({'success': False, 'error': f'{extension} is not an allowed file extension'}), 400

    content = MissionContent()
    content.mime_type = request.content_type
    content.filename = file_name
    content.submission_time = datetime.datetime.now()
    content.submitter = current_user.username if current_user.is_authenticated else "anonymous"
    content.uid = str(uuid.uuid4())
    content.creator_uid = creator_uid
    content.size = request.content_length
    content.expiration = -1

    file = request.data
    sha256 = hashlib.sha256()
    sha256.update(file)
    content.hash = sha256.hexdigest()

    try:
        content_pk = db.session.execute(insert(MissionContent).values(**content.serialize()))
        db.session.commit()
    except sqlalchemy.exc.IntegrityError as e:
        logger.error(f"Failed to save content to database: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({'success': False, 'error': f"Failed to save content to database: {e}"}), 400

    os.makedirs(os.path.join(app.config.get("OTS_DATA_FOLDER"), 'missions'), exist_ok=True)
    with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), 'missions', file_name), 'wb') as f:
        f.write(file)

    response = {
        "UID": content.uid, "SubmissionDateTime": iso8601_string_from_datetime(content.submission_time), "MIMEType": content.mime_type,
        "SubmissionUser": content.submitter, "PrimaryKey": content_pk.inserted_primary_key[0], "Hash": content.hash, "CreatorUid": creator_uid,
        "Name": file_name
    }

    return jsonify(response)


@datasync_api.route('/Marti/api/missions/<mission_name>/contents', methods=['PUT'])
def mission_contents(mission_name: str) -> flask.Response:
    """ Associates content/files with a mission """

    body = request.json

    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        logger.error(f"No such mission: {mission_name}")
        return jsonify({'success': False, 'error': f"No such mission: {mission_name}"}), 404

    mission = mission[0]

    for content_hash in body['hashes']:
        content = db.session.execute(db.session.query(MissionContent).filter_by(hash=content_hash)).first()
        if not content:
            logger.error(f"No such file with hash {content_hash}")
            return jsonify({'success': False, 'error': f"No such file with hash {content_hash}"}), 404

        content: MissionContent = content[0]

        mission_content_mission = MissionContentMission()
        mission_content_mission.mission_name = mission_name
        mission_content_mission.mission_content_id = content.id

        db.session.add(mission_content_mission)

        mission_change = MissionChange()
        mission_change.isFederatedChange = False
        mission_change.change_type = MissionChange.ADD_CONTENT
        mission_change.mission_name = mission_name
        mission_change.timestamp = datetime.datetime.now()
        mission_change.creator_uid = content.creator_uid
        mission_change.server_time = datetime.datetime.now()

        db.session.add(mission_change)

        event = generate_mission_change_cot(mission_name, mission, mission_change, content=content)

        body = json.dumps({'uid': mission_change.creator_uid, 'cot': tostring(event).decode('utf-8')})
        rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
        channel = rabbit_connection.channel()
        channel.basic_publish("missions", routing_key=mission_name, body=body)

    db.session.commit()

    return jsonify({"version": "3", "type": "Mission", "data": [mission.to_json()], "nodeId": app.config.get("OTS_NODE_ID")})


@datasync_api.route('/Marti/api/missions/<mission_name>/contents', methods=['DELETE'])
def delete_content(mission_name: str):
    mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()
    if not mission:
        return jsonify({'success': False, 'error': f'Mission {mission_name} not found'}), 404

    if 'uid' in request.args:
        mission_uid = db.session.execute(db.session.query(MissionUID).filter_by(uid=request.args.get('uid'))).first()
        if not mission_uid:
            return jsonify({'success': False, 'error': f"UID {request.args.get('uid')} not found"}), 404
        else:
            db.session.delete(mission_uid[0])
            db.session.commit()

    if 'hash' in request.args:
        content = db.session.execute(db.session.query(MissionContent).filter_by(hash=request.args.get('hash'))).first()
        if not content:
            return jsonify({'success': False, 'error': f"No content found with hash {request.args.get('hash')}"}), 404

        try:
            os.remove(os.path.join(app.config.get("OTS_DATA_FOLDER"), "missions", content[0].filename))
            db.session.delete(content[0])
            db.session.commit()
        except BaseException as e:
            logger.error(f"Failed to delete content with hash {request.args.get('hash')}: {e}")
            logger.debug(traceback.format_exc())
            return jsonify({'success': False, 'error': f"Failed to delete content with hash {request.args.get('hash')}: {e}"}), 500

    mission_change = MissionChange()
    mission_change.isFederatedChange = False
    mission_change.change_type = MissionChange.REMOVE_CONTENT
    mission_change.mission_name = mission_name
    mission_change.timestamp = datetime.datetime.now()
    mission_change.creator_uid = request.args.get('creatorUid')
    mission_change.server_time = datetime.datetime.now()

    cot = generate_mission_change_cot(mission_name, mission, mission_change, content_uid=request.args.get('uid'))
    body = {'uid': 'server', 'cot': tostring(cot).decode('utf-8')}
    logger.warning(tostring(cot).decode('utf-8'))

    rabbit_connection = pika.BlockingConnection(
        pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()
    channel.basic_publish(exchange="missions", routing_key=mission_name, body=json.dumps(body))

    return jsonify({'success': True})


@datasync_api.route('/Marti/api/missions/<mission_name>/contents/missionpackage', methods=['PUT'])
def add_content(mission_name):
    client_uid = request.args.get('clientUid')
    if 'Authorization' not in request.headers or not verify_token(request.headers.get('Authorization')):
        return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401

    return '', 200


@datasync_api.route('/Marti/api/missions/<mission_name>/cot')
def get_mission_cots(mission_name: str):
    """
    Used by the Data Sync plugin to get all CoTs associated with a feed. Returns the CoTs encapsulated by an
    <events> tag
    """

    cots = db.session.execute(db.session.query(CoT).filter_by(mission_name=mission_name)).all()

    events = Element("events")

    for cot in cots:
        events.append(fromstring(cot[0].xml))

    return tostring(events).decode('utf-8'), 200


#@datasync_api.route('/Marti/sync/upload', methods=['POST'])
def content_upload():
    if not request.content_length:
        return jsonify({'success': False, 'error': 'no file'}), 400

    filename, extension = os.path.splitext(secure_filename(request.args.get('name')))
    if extension.replace('.', '').lower() not in app.config.get("ALLOWED_EXTENSIONS"):
        logger.error(f"{extension} is not an allowed file extension")
        return jsonify({'success': False, 'error': f'{extension} is not an allowed file extension'}), 415

    file = request.data
    sha256 = hashlib.sha256()
    sha256.update(file)
    file_hash = sha256.hexdigest()
    hash_filename = secure_filename(f"{file_hash}{extension}")

    with open(os.path.join(app.config.get("UPLOAD_FOLDER"), hash_filename), "wb") as f:
        f.write(file)

    try:
        data_package = DataPackage()
        data_package.filename = request.args.get('name')
        data_package.hash = file_hash
        data_package.creator_uid = request.args.get('CreatorUid') if request.args.get('CreatorUid') else str(
            uuid.uuid4())
        data_package.submission_user = current_user.id if current_user.is_authenticated else None
        data_package.submission_time = datetime.now()
        data_package.mime_type = request.content_type
        data_package.size = os.path.getsize(os.path.join(app.config.get("UPLOAD_FOLDER"), hash_filename))
        db.session.add(data_package)
        db.session.commit()
    except sqlalchemy.exc.IntegrityError as e:
        db.session.rollback()
        logger.error("Failed to save data package: {}".format(e))
        return jsonify({'success': False, 'error': 'This data package has already been uploaded'}), 400

    return_value = {"UID": data_package.hash, "SubmissionDateTime": data_package.submission_time,
                    "Keywords": ["missionpackage"],
                    "MIMEType": data_package.mime_type, "SubmissionUser": "anonymous", "PrimaryKey": "1",
                    "Hash": data_package.hash, "CreatorUid": data_package.creator_uid, "Name": data_package.filename}

    return jsonify(return_value)

