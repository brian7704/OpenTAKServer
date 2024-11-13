import os
import traceback

import pathlib

import bleach
from flask import current_app as app, request, Blueprint, jsonify, send_from_directory
from flask_security import auth_required

from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.extensions import logger, db

from opentakserver.models.VideoStream import VideoStream
from opentakserver.models.VideoRecording import VideoRecording

video_api_blueprint = Blueprint('video_api_blueprint', __name__)


@video_api_blueprint.route('/api/videos/thumbnail', methods=['GET'])
@auth_required()
def thumbnail():
    path = request.args.get("path")
    recording = request.args.get("recording")
    if not path:
        return jsonify({"success": False, "error": "Please specify a path"}), 400

    if recording and os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "mediamtx", "recordings", path, recording + ".png")):
        return send_from_directory(os.path.join(app.config.get("OTS_DATA_FOLDER"), "mediamtx", "recordings", path),
                                   recording + ".png")

    elif os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "mediamtx", "recordings", path)):
        return send_from_directory(os.path.join(app.config.get("OTS_DATA_FOLDER"), "mediamtx", "recordings", path),
                                   "thumbnail.png")

    return jsonify({"success": False, "error": "Please specify a valid path"}), 400


@video_api_blueprint.route('/api/videos/recordings')
@auth_required()
def video_recordings():
    query = db.session.query(VideoRecording)
    query = search(query, VideoRecording, 'path')

    return paginate(query)


@video_api_blueprint.route('/api/videos/recording', methods=['GET', 'DELETE', 'HEAD'])
@auth_required()
def download_recording():
    if not request.args.get("id"):
        return jsonify({'success': False, 'error': 'Please specify a recording ID'}), 400
    recording_id = bleach.clean(request.args.get('id'))

    try:
        recording = \
            db.session.execute(db.session.query(VideoRecording).filter(VideoRecording.id == recording_id)).first()[0]

        if request.method == 'GET':
            filename = pathlib.Path(recording.segment_path)
            return send_from_directory(filename.parent, filename.name)
        elif request.method == 'DELETE':
            os.remove(recording.segment_path)
            db.session.delete(recording)
            db.session.commit()
            return jsonify({'success': True})
        elif request.method == 'HEAD':
            return '', 200
    except:
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'Recording not found'}), 404


@video_api_blueprint.route('/api/video_streams')
@auth_required()
def get_video_streams():
    query = db.session.query(VideoStream)
    query = search(query, VideoStream, 'username')
    query = search(query, VideoStream, 'protocol')
    query = search(query, VideoStream, 'path')
    query = search(query, VideoStream, 'uid')

    return paginate(query)
