import json
import os
import datetime
import traceback

import sqlalchemy
from flask import current_app as app, request, Blueprint, send_from_directory
from extensions import logger, db

from config import Config
from opentakserver.models.EUD import EUD
from opentakserver.models.DataPackage import DataPackage
from werkzeug.utils import secure_filename

marti_blueprint = Blueprint('marti_blueprint', __name__)


@marti_blueprint.route('/Marti/api/clientEndPoints', methods=['GET'])
def client_end_points():
    euds = db.session.execute(db.select(EUD)).scalars()
    return_value = {'version': 3, "type": "com.bbn.marti.remote.ClientEndpoint", 'data': [], 'nodeId': Config.NODE_ID}
    for eud in euds:
        return_value['data'].append({
            'callsign': eud.callsign,
            'uid': eud.uid,
            'username': 'anonymous',  # TODO: change this once auth is working
            'lastEventTime': eud.last_event_time,
            'lastStatus': eud.last_status
        })

    return return_value, 200, {'Content-Type': 'application/json'}


@marti_blueprint.route('/Marti/api/version/config', methods=['GET'])
def marti_config():
    return {"version": "3", "type": "ServerConfig",
            "data": {"version": Config.VERSION, "api": "3", "hostname": Config.SERVER_DOMAIN_OR_IP},
            "nodeId": Config.NODE_ID}, 200, {'Content-Type': 'application/json'}


@marti_blueprint.route('/Marti/sync/missionupload', methods=['POST'])
def data_package_share():
    if not len(request.files):
        return {'error': 'no file'}, 400, {'Content-Type': 'application/json'}
    for file in request.files:
        file = request.files[file]
        logger.debug("Got file: {} - {}".format(file.filename, request.args.get('hash')))
        if file:
            file_hash = request.args.get('hash')
            if file.content_type != 'application/x-zip-compressed':
                return {'error': 'Please only upload zip files'}, 415, {'Content-Type': 'application/json'}
            filename = secure_filename(file_hash + '.zip')
            file.save(os.path.join(Config.UPLOAD_FOLDER, filename))

            try:
                data_package = DataPackage()
                data_package.filename = file.filename
                data_package.hash = file_hash
                data_package.creator_uid = request.args.get('creatorUid')
                data_package.submission_time = datetime.datetime.now().isoformat() + "Z"
                data_package.mime_type = file.mimetype
                data_package.size = os.path.getsize(os.path.join(Config.UPLOAD_FOLDER, filename))
                db.session.add(data_package)
                db.session.commit()
            except sqlalchemy.exc.IntegrityError as e:
                db.session.rollback()
                logger.error("Failed to save data package: {}".format(e))

            return 'http://{}:{}/Marti/api/sync/metadata/{}/tool'.format(
                Config.SERVER_DOMAIN_OR_IP, Config.HTTP_PORT, file_hash), 200


@marti_blueprint.route('/Marti/api/sync/metadata/<file_hash>/tool', methods=['GET', 'PUT'])
def data_package_metadata(file_hash):
    if request.method == 'PUT':
        try:
            data_package = db.session.execute(db.select(DataPackage).filter_by(hash=file_hash)).scalar_one()
            if data_package:
                data_package.keywords = request.data
                db.session.add(data_package)
                db.session.commit()
                return '', 200
            else:
                return '', 404
        except BaseException as e:
            logger.error("Data package PUT failed: {}".format(e))
            logger.error(traceback.format_exc())
            return {'error': str(e)}, 500
    elif request.method == 'GET':
        data_package = db.session.execute(db.select(DataPackage).filter_by(hash=file_hash)).scalar_one()
        return send_from_directory(Config.UPLOAD_FOLDER, data_package.hash + ".zip",
                                   download_name=data_package.filename)


@marti_blueprint.route('/Marti/sync/missionquery')
def data_package_query():
    try:
        data_package = db.session.execute(db.select(DataPackage).filter_by(hash=request.args.get('hash'))).scalar_one()
        if data_package:
            return 'https://{}/Marti/api/sync/metadata/{}/tool'.format(
                request.headers.get('Host'), request.args.get('hash')), 200
        else:
            return {'error': '404'}, 404, {'Content-Type': 'application/json'}
    except sqlalchemy.exc.NoResultFound as e:
        logger.error("Failed to get dps: {}".format(e))
        return {'error': '404'}, 404, {'Content-Type': 'application/json'}


@marti_blueprint.route('/Marti/sync/search', methods=['GET'])
def data_package_search():
    data_packages = db.session.execute(db.select(DataPackage)).scalars()
    res = {'resultCount': 0, 'results': []}
    for dp in data_packages:
        res['results'].append(
            {'UID': dp.hash, 'Name': dp.filename, 'Hash': dp.hash, 'CreatorUid': dp.creator_uid,
             "SubmissionDateTime": dp.submission_time, "Expiration": -1, "Keywords": "[missionpackage]",
             "MIMEType": dp.mime_type, "Size": dp.size, "SubmissionUser": "anonymous", "PrimaryKey": dp.id,
             "Tool": "public"
             })
        res['resultCount'] += 1

    return json.dumps(res), 200, {'Content-Type': 'application/json'}


@marti_blueprint.route('/Marti/sync/content', methods=['GET'])
def download_data_package():
    file_hash = request.args.get('hash')
    data_package = db.session.execute(db.select(DataPackage).filter_by(hash=file_hash)).scalar_one()

    return send_from_directory(Config.UPLOAD_FOLDER, file_hash + ".zip", download_name=data_package.filename)
