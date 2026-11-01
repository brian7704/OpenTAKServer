import os
import pathlib
import traceback

import bleach
from flask import Blueprint
from flask import current_app as app
from flask import jsonify, request, send_from_directory
from flask_babel import gettext
from flask_security import auth_required, current_user

from opentakserver.blueprints.ots_api.api import paginate, search
from opentakserver.extensions import db, logger
from opentakserver.models.VideoRecording import VideoRecording
from opentakserver.models.VideoStream import VideoStream, user_can_access_video_stream

video_api_blueprint = Blueprint("video_api_blueprint", __name__)


def _allowed_video_paths(user) -> set[str]:
    streams = db.session.execute(db.select(VideoStream)).scalars().all()
    return {stream.path for stream in streams if user_can_access_video_stream(user, stream)}


@video_api_blueprint.route("/api/videos/thumbnail", methods=["GET"])
@auth_required()
def thumbnail():
    path = request.args.get("path")
    recording = request.args.get("recording")
    if not path:
        return jsonify({"success": False, "error": "Please specify a path"}), 400

    video_stream = db.session.query(VideoStream).filter(VideoStream.path == path).first()
    if not current_user.has_role("administrator") and not user_can_access_video_stream(
        current_user, video_stream
    ):
        return (
            jsonify(
                {
                    "success": False,
                    "error": gettext("You do not have permission to access this video stream"),
                }
            ),
            403,
        )

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

    if not current_user.has_role("administrator"):
        query = query.filter(VideoRecording.path.in_(_allowed_video_paths(current_user)))

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
        row = db.session.execute(
            db.session.query(VideoRecording).filter(VideoRecording.id == recording_id)
        ).first()
        if not row:
            return jsonify({"success": False, "error": gettext("Recording not found")}), 404
        recording = row[0]

        if not user_can_access_video_stream(current_user, recording.video_stream):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": gettext("You do not have permission to access this video stream"),
                    }
                ),
                403,
            )

        if request.method == "GET":
            filename = pathlib.Path(recording.segment_path)
            return send_from_directory(filename.parent, filename.name)
        elif request.method == "DELETE":
            db.session.delete(recording)
            db.session.commit()
            os.remove(recording.segment_path)
            return jsonify({"success": True})
        elif request.method == "HEAD":
            return "", 200
    except FileNotFoundError:
        return jsonify({"success": True})
    except BaseException as e:
        logger.error(traceback.format_exc())
        return (
            jsonify(
                {"success": False, "error": gettext("Failed to delete recording: %(e)s", str(e))}
            ),
            404,
        )


@video_api_blueprint.route("/api/video_streams")
@auth_required()
def get_video_streams():
    query = db.session.query(VideoStream)
    query = search(query, VideoStream, "username")
    query = search(query, VideoStream, "protocol")
    query = search(query, VideoStream, "path")
    query = search(query, VideoStream, "uid")

    if not current_user.has_role("administrator"):
        query = query.filter(VideoStream.path.in_(_allowed_video_paths(current_user)))

    return paginate(query, VideoStream)
