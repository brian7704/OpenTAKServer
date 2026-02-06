import os
import pathlib
import traceback

import bleach
from flask import Blueprint
from flask import current_app as app
from flask import jsonify, request, send_from_directory
from flask_babel import gettext
from flask_security import auth_required

from opentakserver.blueprints.ots_api.api import paginate, search
from opentakserver.extensions import db, logger
from opentakserver.models.VideoRecording import VideoRecording
from opentakserver.models.VideoStream import VideoStream

video_api_blueprint = Blueprint("video_api_blueprint", __name__)


@video_api_blueprint.route("/api/videos/thumbnail", methods=["GET"])
@auth_required()
def thumbnail():
    path = request.args.get("path")
    recording = request.args.get("recording")
    if not path:
        return jsonify({"success": False, "error": "Please specify a path"}), 400

    if recording and os.path.exists(
        os.path.join(
            app.config.get("OTS_DATA_FOLDER"), "mediamtx", "recordings", path, recording + ".png"
        )
    ):
        return send_from_directory(
            os.path.join(app.config.get("OTS_DATA_FOLDER"), "mediamtx", "recordings", path),
            recording + ".png",
        )

    elif os.path.exists(
        os.path.join(app.config.get("OTS_DATA_FOLDER"), "mediamtx", "recordings", path)
    ):
        return send_from_directory(
            os.path.join(app.config.get("OTS_DATA_FOLDER"), "mediamtx", "recordings", path),
            "thumbnail.png",
        )

    return jsonify({"success": False, "error": gettext("Please specify a valid path")}), 400


@video_api_blueprint.route("/api/videos/recordings")
@auth_required()
def video_recordings():
    query = db.session.query(VideoRecording)
    query = search(query, VideoRecording, "path")

    return paginate(query, VideoRecording)


@video_api_blueprint.route("/api/videos/recording", methods=["GET", "DELETE", "HEAD"])
@auth_required()
def download_recording():
    if not request.args.get("id"):
        return jsonify({"success": False, "error": "Please specify a recording ID"}), 400
    recording_id = bleach.clean(request.args.get("id"))

    if recording_id.isdigit():
        recording_id = int(recording_id)
    else:
        return (
            jsonify(
                {
                    "success": False,
                    "error": gettext(
                        "Invalid recording_id: %(recording_id)s", recording_id=recording_id
                    ),
                }
            ),
            400,
        )

    try:
        recording = db.session.execute(
            db.session.query(VideoRecording).filter(VideoRecording.id == recording_id)
        ).first()[0]

        if request.method == "GET":
            filename = pathlib.Path(recording.segment_path)
            return send_from_directory(filename.parent, filename.name)
        elif request.method == "DELETE":
            os.remove(recording.segment_path)
            db.session.delete(recording)
            db.session.commit()
            return jsonify({"success": True})
        elif request.method == "HEAD":
            return "", 200
    except Exception:
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "error": gettext("Recording not found")}), 404


@video_api_blueprint.route("/api/video_streams")
@auth_required()
def get_video_streams():
    query = db.session.query(VideoStream)
    query = search(query, VideoStream, "username")
    query = search(query, VideoStream, "protocol")
    query = search(query, VideoStream, "path")
    query = search(query, VideoStream, "uid")

    return paginate(query, VideoStream)
