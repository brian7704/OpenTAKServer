import os
import time
import traceback
import uuid
import jwt

import bleach
from flask import Blueprint, request, current_app as app, jsonify

from opentakserver.extensions import db, logger
from opentakserver.models.Mission import Mission

datasync_blueprint = Blueprint('datasync_blueprint', __name__)


def verify_token(token):
    token = token.replace("Bearer ", "")
    with open(os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", "opentakserver", "opentakserver.pub"), "r") as key:
        try:
            jwt.decode(token, key.read(), algorithms=["RS256"])
            return True
        except BaseException as e:
            logger.error("Failed to validate mission token: {}".format(e))
            logger.error(traceback.format_exc())
            return False


@datasync_blueprint.route('/Marti/api/missions')
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


@datasync_blueprint.route('/Marti/api/missions/all/invitations')
def all_invitations():
    clientUid = bleach.clean(request.args.get('clientUid'))
    logger.info(request.headers)
    logger.info(request.args)
    return '', 200


@datasync_blueprint.route('/Marti/api/missions/<mission_name>', methods=['PUT'])
def put_mission(mission_name):
    if not mission_name:
        return jsonify({'success': False, 'error': 'Invalid mission name'}), 400

    mission = Mission()
    mission.name = bleach.clean(mission_name)

    mission.creatorUid = bleach.clean(request.args.get('creatorUid')) if 'creatorUid' in request.args else None
    mission.description = bleach.clean(request.args.get('description')) if 'description' in request.args else None
    mission.tool = bleach.clean(request.args.get('tool')) if 'tool' in request.args else None
    mission.group = bleach.clean(request.args.get('group')) if 'group' in request.args else None
    mission.defaultRole = bleach.clean(request.args.get('defaultRole')) if 'defaultRole' in request.args else None
    mission.password = request.args.get('password') if 'password' in request.args else None
    mission.guid = str(uuid.uuid4())

    mission.passwordProtected = False
    if mission.password:
        mission.password = bleach.clean(mission.password)
        mission.passwordProtected = True

    mission.uid = str(uuid.uuid4())
    mission.creationTime = int(time.time())

    payload = {'jti': mission.uid, 'iat': mission.creationTime, 'sub': 'SUBSCRIPTION', 'iss': '',
               'SUBSCRIPTION': mission.uid, 'MISSION_NAME': mission.name}

    server_key = open(os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", "opentakserver",
                                   "opentakserver.nopass.key"), "r")

    token = jwt.encode(payload, server_key.read(), algorithm="RS256")
    server_key.close()

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
            'classification': '', 'tool': mission.tool, 'keywords': [], 'creatorUid': mission.creatorUid, 'bbox': '',
            'createTime': mission.creationTime, 'externalData': [], 'feeds': [], 'mapLayers': [], 'defaultRole': {
                'permissions': ["MISSION_WRITE", "MISSION_READ"], "type": "MISSION_SUBSCRIBER"},

            'ownerRole': {"permissions": ["MISSION_MANAGE_FEEDS", "MISSION_SET_PASSWORD", "MISSION_WRITE",
                                          "MISSION_MANAGE_LAYERS", "MISSION_UPDATE_GROUPS", "MISSION_SET_ROLE",
                                          "MISSION_READ", "MISSION_DELETE"], "type": "MISSION_OWNER"},
            'inviteOnly': False, 'expiration': -1, 'guid': mission.guid, 'uids': [], 'contents': [], 'token': token,
            'passwordProtected': mission.passwordProtected
        }],
        'nodeId': app.config.get("OTS_NODE_ID")
    }

    logger.warning(token)

    return jsonify(response), 201


@datasync_blueprint.route('/Marti/api/missions/<mission_name>', methods=['GET'])
def get_mission(mission_name):
    if 'Authorization' not in request.headers:
        return jsonify({'success': False, 'error': 'Missing token'}), 401
    elif not verify_token(request.headers.get("Authorization")):
        return jsonify({'success': False, 'error': 'Invalid token'}), 401

    if not mission_name:
        return jsonify({'success': False, 'error': 'Invalid mission name'}), 400

    mission_name = bleach.clean(mission_name)

    try:
        mission = db.session.execute(db.session.query(Mission).filter_by(name=mission_name)).first()[0]

        default_role = {'permissions': ["MISSION_WRITE", "MISSION_READ"], "type": "MISSION_SUBSCRIBER"}

        response = {
            'version': "3", 'type': 'Mission', 'data': [{
                'name': mission.name, 'description': mission.description, 'chatRoom': mission.chatRoom,
                'baseLayer': mission.baseLayer, 'path': mission.path, 'classification': mission.classification,
                'tool': mission.tool, 'keywords': [], 'creatorUid': mission.creatorUid, 'bbox': mission.bbox,
                'createTime': mission.creationTime, 'externalData': [], 'feeds': [], 'mapLayers': [], 'defaultRole': default_role,
                'inviteOnly': mission.inviteOnly, 'expiration': -1, 'guid': mission.guid, 'uids': [], 'contents': [],
                'passwordProtected': mission.passwordProtected
            }],
            'nodeId': app.config.get("OTS_NODE_ID")
        }

        return jsonify(response)
    except BaseException as e:
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 400


@datasync_blueprint.route('/Marti/api/missions/<mission_name>/subscriptions/roles')
def mission_roles(mission_name):
    # {"version":"3","type":"MissionSubscription","data":[{"clientUid":"ANDROID-11e3b01b9d6a39b0","username":"anonymous","createTime":"2024-05-15T21:16:24.84Z","role":{"permissions":["MISSION_MANAGE_FEEDS","MISSION_SET_PASSWORD","MISSION_MANAGE_LAYERS","MISSION_WRITE","MISSION_UPDATE_GROUPS","MISSION_SET_ROLE","MISSION_READ","MISSION_DELETE"],"hibernateLazyInitializer":{},"type":"MISSION_OWNER"}},{"clientUid":"ANDROID-e3a3c5d176263d80","username":"anonymous","createTime":"2024-05-15T21:23:14.632Z","role":{"permissions":["MISSION_WRITE","MISSION_READ"],"hibernateLazyInitializer":{},"type":"MISSION_SUBSCRIBER"}}],"nodeId":"a2efc4ca15a74ccd89c947d6b5e551bf"}
    logger.warning(request.args)
    logger.warning(request.headers)
    return '', 200


@datasync_blueprint.route('/Marti/api/missions/<mission_name>/keywords', methods=['PUT'])
def put_mission_keywords(mission_name):
    keywords = request.json()

    return '', 200


@datasync_blueprint.route('/Marti/api/missions/<mission_name>/subscription', methods=['PUT'])
def mission_subscribe(mission_name):
    uid = bleach.clean(request.args.get("uid"))

    return '', 200


@datasync_blueprint.route('/Marti/api/missions/<mission_name>/changes', methods=['GET'])
def mission_changes(mission_name):
    # {"version":"3","type":"MissionChange","data":[{"isFederatedChange":false,"type":"CREATE_MISSION","missionName":"my_mission","timestamp":"2024-05-17T16:39:34.621Z","creatorUid":"ANDROID-e3a3c5d176263d80","serverTime":"2024-05-17T16:39:34.621Z"}],"nodeId":"a2efc4ca15a74ccd89c947d6b5e551bf"}
    squashed = request.args.get('squashed')
    if squashed:
        squashed = bleach.clean(squashed)

    return '', 200


@datasync_blueprint.route('/Marti/api/missions/<mission_name>/log', methods=['GET'])
def mission_log(mission_name):
    # {"version":"3","type":"com.bbn.marti.sync.model.LogEntry","data":[],"nodeId":"a2efc4ca15a74ccd89c947d6b5e551bf"}
    return '', 200


@datasync_blueprint.route('/Marti/sync/content', methods=['HEAD'])
def check_content_exists():
    content_hash = request.args.get('hash')
    if not content_hash:
        return jsonify({'success': False, 'error': 'Invalid hash'}), 400

    content_hash = bleach.clean(content_hash)

    # Check for hash and return 404 or 200

    return '', 404


@datasync_blueprint.route('/Marti/sync/upload')
def upload_content():
    file_name = bleach.clean(request.args.get('name')) if 'name' in request.args else None
    creator_uid = bleach.clean(request.args.get('creatorUid')) if 'creatorUid' in request.args else None

    # {"UID":"ff15425a-7c2d-4e44-9e8f-82603cca1843","SubmissionDateTime":"2024-05-17T16:40:13.887Z","MIMEType":"image\/png","SubmissionUser":"anonymous","PrimaryKey":"3","Hash":"759183fbdb43af3948eed87e9bd418b2a7e34b455112b243cfb1b6a982ab5713","CreatorUid":"ANDROID-e3a3c5d176263d80","Name":"OpenTAKICU_1712677219279.png"}
    return '', 200


@datasync_blueprint.route('/Marti/api/missions/<mission_name>/contents')
def mission_contents(mission_name):
    # Body: {"hashes":["6277ed0d85fa6015b05fbc0b4656d3854a41281c83bb2a6b49b09010c1067baf"]}
    # {"version":"3","type":"Mission","data":[{"name":"my_mission","description":"hhb","chatRoom":"","baseLayer":"","bbox":"","path":"","classification":"","tool":"public","keywords":[],"creatorUid":"ANDROID-e3a3c5d176263d80","createTime":"2024-05-17T16:39:34.621Z","externalData":[],"feeds":[],"mapLayers":[],"defaultRole":{"permissions":["MISSION_WRITE","MISSION_READ"],"hibernateLazyInitializer":{},"type":"MISSION_SUBSCRIBER"},"inviteOnly":false,"missionChanges":[],"expiration":-1,"guid":"351961e9-0a9a-428e-a7bc-d56aa6e95f35","uids":[],"contents":[{"data":{"keywords":[],"mimeType":"application/pdf","name":"ATAK_TAK_GeoCam.pdf","submissionTime":"2024-05-17T16:45:55.517Z","submitter":"anonymous","uid":"a398db81-d0c0-48df-91ec-9b97f95d6fbc","creatorUid":"ANDROID-e3a3c5d176263d80","hash":"6277ed0d85fa6015b05fbc0b4656d3854a41281c83bb2a6b49b09010c1067baf","size":388745,"expiration":-1},"timestamp":"2024-05-17T16:45:55.630Z","creatorUid":"ANDROID-e3a3c5d176263d80"}],"passwordProtected":true}],"nodeId":"a2efc4ca15a74ccd89c947d6b5e551bf"}
    body = request.json()

    return '', 200