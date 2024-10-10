import datetime
import hashlib
import os
import time
import traceback
import uuid
import jwt

import bleach
import sqlalchemy.exc
from flask import Blueprint, request, current_app as app, jsonify
from flask_security import current_user
from sqlalchemy import update, insert
from werkzeug.utils import secure_filename

from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.blueprints.marti import basic_auth
from opentakserver.extensions import db, logger
from opentakserver.models.Mission import Mission
from opentakserver.models.MissionContent import MissionContent
from opentakserver.models.MissionContentMission import MissionContentMission
from opentakserver.models.MissionInvitation import MissionInvitation
from opentakserver.models.MissionRole import MissionRole

datasync_api = Blueprint('datasync_api', __name__)


def verify_token(token) -> dict | bool:
    if "Bearer" not in token:
        return False

    token = token.replace("Bearer ", "")
    logger.info(token)

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


@datasync_api.route('/Marti/api/missions')
def get_missions():
    logger.warning(request.args)

    password_protected = request.args.get('passwordProtected')
    if password_protected:
        password_protected = bleach.clean(password_protected).lower() == 'true'

    tool = request.args.get('tool')
    if tool:
        tool = bleach.clean(tool)
    logger.error("Tool is " + tool)

    default_role = request.args.get('defaultRole')
    if default_role:
        default_role = bleach.clean(default_role).lower() == 'true'

    response = {
        'version': 3, 'type': 'Mission', 'data': [], 'nodeId': app.config.get('OTS_NODE_ID')
    }

    try:
        missions = db.session.execute(db.session.query(Mission).filter_by(tool=tool)).scalars()
        for mission in missions:
            mission = mission.serialize()
            mission['defaultRole'] = {'permissions': ["MISSION_WRITE", "MISSION_READ"], "type": "MISSION_SUBSCRIBER"}
            response['data'].append(mission)
    except BaseException as e:
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

    logger.warning(response)
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
        response['data'].append(invitation['name'])

    return jsonify(response)


@datasync_api.route('/Marti/api/missions/<mission_name>', methods=['PUT', 'POST'])
def put_mission(mission_name):
    if not mission_name:
        return jsonify({'success': False, 'error': 'Invalid mission name'}), 400

    mission = Mission()
    mission.name = bleach.clean(mission_name)

    mission.creator_uid = bleach.clean(request.args.get('creatorUid')) if 'creatorUid' in request.args else None
    mission.description = bleach.clean(request.args.get('description')) if 'description' in request.args else None
    mission.tool = bleach.clean(request.args.get('tool')) if 'tool' in request.args else None
    mission.group = bleach.clean(request.args.get('group')) if 'group' in request.args else None
    mission.default_role = bleach.clean(request.args.get('defaultRole')) if 'defaultRole' in request.args else None
    mission.password = request.args.get('password') if 'password' in request.args else None
    mission.guid = str(uuid.uuid4())

    mission.password_protected = False
    if mission.password:
        mission.password = bleach.clean(mission.password)
        mission.password_protected = True

    mission.uid = str(uuid.uuid4())
    mission.create_time = datetime.datetime.now()

    token = generate_token(mission)

    os.makedirs(os.path.join(app.config.get("OTS_DATA_FOLDER"), "missions", bleach.clean(mission_name)), exist_ok=True)

    try:
        db.session.add(mission)
        db.session.commit()
    except BaseException as e:
        logger.error("Failed to add mission: {}".format(e))
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': "Failed to add mission: {}".format(e)}), 400

    response = {
        'version': "3", 'type': 'Mission', 'data': [{
            'name': mission_name, 'description': mission.description, 'chatRoom': '', 'baseLayer': '', 'path': '',
            'classification': '', 'tool': mission.tool, 'keywords': [], 'creatorUid': mission.creator_uid, 'bbox': '',
            'createTime': mission.create_time, 'externalData': [], 'feeds': [], 'mapLayers': [], 'defaultRole': {
                'permissions': ["MISSION_WRITE", "MISSION_READ"], "type": "MISSION_SUBSCRIBER"},

            'ownerRole': {"permissions": ["MISSION_MANAGE_FEEDS", "MISSION_SET_PASSWORD", "MISSION_WRITE",
                                          "MISSION_MANAGE_LAYERS", "MISSION_UPDATE_GROUPS", "MISSION_SET_ROLE",
                                          "MISSION_READ", "MISSION_DELETE"], "type": "MISSION_OWNER"},
            'inviteOnly': False, 'expiration': -1, 'guid': mission.guid, 'uids': [], 'contents': [], 'token': token,
            'passwordProtected': mission.password_protected
        }],
        'nodeId': app.config.get("OTS_NODE_ID")
    }

    logger.warning(token)

    return jsonify(response), 201


@datasync_api.route('/Marti/api/missions/<mission_name>', methods=['GET'])
@datasync_api.route('/api/missions/<mission_name>', methods=['GET'])
def get_mission(mission_name):
    if 'Authorization' not in request.headers:
        return jsonify({'success': False, 'error': 'Missing token'}), 401
    else:
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
        logger.warning(mission)

        response = {'version': "3", 'type': 'Mission', 'data': [mission[0].to_json()], 'nodeId': app.config.get("OTS_NODE_ID")}
        logger.info(response)
        return jsonify(response)
    except BaseException as e:
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 400


@datasync_api.route('/Marti/api/missions/<mission_name>', methods=['DELETE'])
def delete_mission(mission_name):
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
def set_password(mission_name):
    if 'creatorUid' not in request.args or 'password' not in request.args:
        return jsonify({'success': False, 'error': 'Please provide the creatorUid and password'}), 400

    creator_uid = request.args.get('creatorUid')
    password = request.args.get('password')

    db.session.execute(update(Mission).where(Mission.name == mission_name).where(Mission.creatorUid == creator_uid)
                       .values(password=password))

    return jsonify({'success': True})


#@datasync_api.route('/Marti/api/missions/<mission_name>/invite/<invitation_type>/<invitee>', methods=['PUT'])
#def invite(mission_name, invitation_type, invitee):


@datasync_api.route('/Marti/api/missions/<mission_name>/subscriptions/roles')
def mission_roles(mission_name):
    response = {"version": "3", "type": "MissionSubscription", "data": [], "nodeId": app.config.get("OTS_NODE_ID")}
    roles = db.session.execute(db.session.query(MissionRole).filter_by(mission_name=mission_name))
    for role in roles:
        response['data'].append(role.to_json())

    return jsonify(response)


@datasync_api.route('/Marti/api/missions/<mission_name>/keywords', methods=['PUT'])
def put_mission_keywords(mission_name):
    keywords = request.json()

    return '', 200


@datasync_api.route('/Marti/api/missions/<mission_name>/subscription', methods=['PUT'])
@datasync_api.route('/api/missions/<mission_name>/subscription', methods=['PUT'])
def mission_subscribe(mission_name):
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
        role.role_type = "MISSION_SUBSCRIBER"
        role.mission_name = mission.name

        db.session.add(role)
        db.session.commit()
    else:
        role = role[0]

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
    response = {
        "version": "3", "type": "com.bbn.marti.sync.model.MissionSubscription", "data": [],
        "nodeId": app.config.get("OTS_NODE_ID")
    }

    return jsonify(response)


@datasync_api.route('/Marti/sync/content', methods=['HEAD'])
def check_content_exists():
    content_hash = request.args.get('hash')
    if not content_hash:
        return jsonify({'success': False, 'error': 'Invalid hash'}), 400

    content_hash = bleach.clean(content_hash)
    logger.warning(f"hash is {content_hash}")
    content = db.session.execute(db.session.query(MissionContent).filter_by(hash=content_hash)).first()
    if not content:
        logger.error(f"no soup for {content_hash}")
        return '', 404
    elif not os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "missions", content[0].name)):
        logger.info(f"No file {content.serialize()}")
        return '', 404

    return '', 200


@datasync_api.route('/Marti/sync/upload', methods=['POST'])
def upload_content():
    decoded_jwt = verify_token(request.headers.get('Authorization'))
    logger.error(decoded_jwt)

    if 'Authorization' not in request.headers or not decoded_jwt:
        return jsonify({'success': False, 'error': 'Missing or invalid token'}), 400

    file_name = bleach.clean(request.args.get('name')) if 'name' in request.args else None
    creator_uid = bleach.clean(request.args.get('creatorUid')) if 'creatorUid' in request.args else None

    if not file_name:
        return jsonify({'success': False, 'error': 'File name cannot be blank'}), 400

    if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "missions", file_name)):
        return jsonify({'success': False, 'error': f"File already exists: {file_name}"}), 400

    filename, extension = os.path.splitext(secure_filename(file_name))
    if extension.replace('.', '').lower() not in app.config.get("ALLOWED_EXTENSIONS"):
        logger.error(f"{extension} is not an allowed file extension")
        return jsonify({'success': False, 'error': f'{extension} is not an allowed file extension'}), 400

    content = MissionContent()
    content.mime_type = request.content_type
    content.name = file_name
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

    mission_content_mission = MissionContentMission()
    mission_content_mission.mission_name = decoded_jwt['MISSION_NAME']
    mission_content_mission.mission_content_id = content_pk.inserted_primary_key[0]

    db.session.add(mission_content_mission)
    db.session.commit()

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
def mission_contents(mission_name):
    # Body: {"hashes":["6277ed0d85fa6015b05fbc0b4656d3854a41281c83bb2a6b49b09010c1067baf"]}
    # {"version":"3","type":"Mission","data":[{"name":"my_mission","description":"hhb","chatRoom":"","baseLayer":"","bbox":"","path":"","classification":"","tool":"public","keywords":[],"creatorUid":"ANDROID-e3a3c5d176263d80","createTime":"2024-05-17T16:39:34.621Z","externalData":[],"feeds":[],"mapLayers":[],"defaultRole":{"permissions":["MISSION_WRITE","MISSION_READ"],"hibernateLazyInitializer":{},"type":"MISSION_SUBSCRIBER"},"inviteOnly":false,"missionChanges":[],"expiration":-1,"guid":"351961e9-0a9a-428e-a7bc-d56aa6e95f35","uids":[],"contents":[{"data":{"keywords":[],"mimeType":"application/pdf","name":"ATAK_TAK_GeoCam.pdf","submissionTime":"2024-05-17T16:45:55.517Z","submitter":"anonymous","uid":"a398db81-d0c0-48df-91ec-9b97f95d6fbc","creatorUid":"ANDROID-e3a3c5d176263d80","hash":"6277ed0d85fa6015b05fbc0b4656d3854a41281c83bb2a6b49b09010c1067baf","size":388745,"expiration":-1},"timestamp":"2024-05-17T16:45:55.630Z","creatorUid":"ANDROID-e3a3c5d176263d80"}],"passwordProtected":true}],"nodeId":"a2efc4ca15a74ccd89c947d6b5e551bf"}

    decoded_jwt = verify_token(request.headers.get('Authorization'))
    if 'Authorization' not in request.headers or not decoded_jwt:
        return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401

    mission = db.session.execute(db.session.query(Mission).filter_by(name=decoded_jwt['MISSION_NAME'])).first()
    if not mission:
        return jsonify({'success': False, 'error': f"Mission {decoded_jwt['MISSION_NAME']} not found"}), 404

    logger.info({"version": "3", "type": "Mission", "data": [mission[0].to_json()], "nodeId": app.config.get("OTS_NODE_ID")})
    return jsonify({"version": "3", "type": "Mission", "data": [mission[0].to_json()], "nodeId": app.config.get("OTS_NODE_ID")})


@datasync_api.route('/Marti/api/missions/<mission_name>/contents/missionpackage', methods=['PUT'])
def add_content(mission_name):
    client_uid = request.args.get('clientUid')
    if 'Authorization' not in request.headers or not verify_token(request.headers.get('Authorization')):
        return jsonify({'success': False, 'error': 'Missing or invalid token'}), 401

    return '', 200


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
    logger.debug("got sha256 {}".format(file_hash))
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

