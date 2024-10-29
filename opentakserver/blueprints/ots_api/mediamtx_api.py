import datetime
import json
import os
import traceback
import uuid
from urllib.parse import urlparse

from ffmpeg import FFmpeg
from sqlalchemy import update
from werkzeug.datastructures import ImmutableMultiDict

import bleach
import requests
import sqlalchemy.exc
from flask import current_app as app, request, Blueprint, jsonify
from flask_security import auth_required, current_user, verify_password
from flask_security.utils import parse_auth_token

from opentakserver.extensions import logger, db
from opentakserver.models.VideoStream import VideoStream
from opentakserver.forms.MediaMTXPathConfig import MediaMTXPathConfig
from opentakserver.models.VideoRecording import VideoRecording

mediamtx_api_blueprint = Blueprint('mediamtx_api_blueprint', __name__)


def get_stream_protocol(source_type):
    protocol = "rtsp"
    if source_type.startswith('rtsps'):
        protocol = 'rtsps'
    if source_type.startswith('rtsp'):
        protocol = "rtsp"
    elif source_type == 'hlsSource':
        protocol = "hls"
    elif source_type == 'rpiCameraSource':
        protocol = "rpi_camera"
    elif source_type.startswith('rtmp'):
        protocol = 'rtmp'
    elif source_type.startswith('srt'):
        protocol = 'srt'
    elif source_type.startswith('udp'):
        protocol = 'udp'
    elif source_type.startswith('webRTC'):
        protocol = 'webrtc'

    return protocol


@mediamtx_api_blueprint.route('/api/mediamtx/webhook')
def mediamtx_webhook():
    token = request.args.get('token')
    if not token or bleach.clean(token) != app.config.get("OTS_MEDIAMTX_TOKEN"):
        logger.error('Invalid token')
        return jsonify({'success': False, 'error': 'Invalid token'}), 401

    event = bleach.clean(request.args.get('event'))
    if event == 'init':
        rtsp_port = bleach.clean(request.args.get("rtsp_port"))
        path = bleach.clean(request.args.get("path"))

        if path == 'startup':
            paths = VideoStream.query.all()
            for path in paths:
                r = requests.post(
                    "{}/v3/config/paths/add/{}".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), path.path),
                    json=json.loads(path.mediamtx_settings))
                logger.debug("Init added {} {}".format(path, r.status_code))

            # Get all paths from MediaMTX and make sure they're in OTS's database
            r = requests.get("{}/v3/paths/list".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS")))
            paths = r.json()
            for path in paths['items']:
                video_stream = db.session.query(VideoStream).where(VideoStream.path == path['name']).first()
                if not video_stream:
                    if not path['source']:
                        continue
                    video_stream = VideoStream()
                    video_stream.protocol = get_stream_protocol(path['source']['type'])

                    r = requests.get("{}/v3/config/global/get".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS")))
                    video_stream.port = r.json()['rtspAddress'].replace(":", "")

                    r = requests.get(
                        "{}/v3/config/paths/get/{}".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), path['name']))
                    video_stream.mediamtx_settings = json.dumps(r.json())

                    video_stream.path = path['name']
                    video_stream.alias = path['name']
                    video_stream.rtsp_reliable = 1
                    video_stream.ready = event == 'ready'
                    video_stream.rover_port = -1
                    video_stream.ignore_embedded_klv = False
                    video_stream.buffer_time = None
                    video_stream.network_timeout = 10000
                    video_stream.uid = str(uuid.uuid4())
                    video_stream.generate_xml(urlparse(request.url_root).hostname)

                    db.session.add(video_stream)
                    db.session.commit()

    elif event == 'connect':
        connection_type = bleach.clean(request.args.get("connection_type"))
        connection_id = bleach.clean(request.args.get("connection_id"))
        rtsp_port = bleach.clean(request.args.get("rtsp_port"))
    elif event == 'ready' or event == 'notready':
        rtsp_port = bleach.clean(request.args.get("rtsp_port"))
        path = bleach.clean(request.args.get("path"))
        query = bleach.clean(request.args.get("query"))
        source_type = bleach.clean(request.args.get("source_type"))
        source_id = bleach.clean(request.args.get("source_id"))

        video_stream = db.session.query(VideoStream).where(VideoStream.path == path).first()
        if video_stream:
            video_stream.ready = event == 'ready'
            db.session.add(video_stream)
            db.session.commit()
            r = requests.patch("{}/v3/config/paths/patch/{}".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), path),
                               json=json.loads(video_stream.mediamtx_settings))
            logger.debug("Ready Patched path {}: {} - {}".format(path, r.status_code, r.text))
        else:
            video_stream = VideoStream()
            if source_type.startswith('rtsps'):
                video_stream.protocol = 'rtsps'
            if source_type.startswith('rtsp'):
                video_stream.protocol = "rtsp"
            elif source_type == 'hlsSource':
                video_stream.protocol = "hls"
            elif source_type == 'rpiCameraSource':
                video_stream.protocol = "rpi_camera"
            elif source_type.startswith('rtmp'):
                video_stream.protocol = 'rtmp'
            elif source_type.startswith('srt'):
                video_stream.protocol = 'srt'
            elif source_type.startswith('udp'):
                video_stream.protocol = 'udp'
            elif source_type.startswith('webRTC'):
                video_stream.protocol = 'webrtc'

            # video_stream.query = query
            video_stream.port = rtsp_port
            video_stream.path = path
            video_stream.alias = path
            video_stream.rtsp_reliable = 1
            video_stream.ready = event == 'ready'
            video_stream.rover_port = -1
            video_stream.ignore_embedded_klv = False
            video_stream.buffer_time = None
            video_stream.network_timeout = 10000
            video_stream.uid = str(uuid.uuid4())
            video_stream.generate_xml(urlparse(request.url_root).hostname)
            mediamtx_settings = MediaMTXPathConfig(None)
            mediamtx_settings.sourceOnDemand.data = source_id is not None
            mediamtx_settings.record.data = False
            video_stream.mediamtx_settings = json.dumps(mediamtx_settings.serialize())

            db.session.add(video_stream)
            db.session.commit()

        if event == 'ready':
            os.makedirs(os.path.join(app.config.get('OTS_DATA_FOLDER'), "mediamtx", "recordings", video_stream.path),
                        exist_ok=True)

            try:
                (FFmpeg().input(
                    video_stream.to_json()['rtsp_link'] + "?token={}".format(token))
                 .option("y")
                 .output(os.path.join(app.config.get('OTS_DATA_FOLDER'), "mediamtx", "recordings", video_stream.path,
                                      "thumbnail.png"), {"frames:v": 1}).execute())
            except BaseException as e:
                logger.error(f"Failed to create thumbnail: {e}")
                logger.debug(traceback.format_exc())

    elif event == 'read':
        rtsp_port = bleach.clean(request.args.get("rtsp_port"))
        path = bleach.clean(request.args.get("path"))
        query = bleach.clean(request.args.get("query"))
        reader_type = bleach.clean(request.args.get("reader_type"))
        reader_id = bleach.clean(request.args.get("reader_id"))
    elif event == 'disconnect':
        connection_type = bleach.clean(request.args.get("connection_type"))
        connection_id = bleach.clean(request.args.get("connection_id"))
        rtsp_port = bleach.clean(request.args.get("rtsp_port"))
    elif event == 'segment_record':
        recording = VideoRecording()
        recording.segment_path = bleach.clean(request.args.get('segment_path'))
        recording.path = bleach.clean(request.args.get('path'))
        recording.in_progress = True
        recording.start_time = datetime.datetime.now()

        with (app.app_context()):
            try:
                db.session.add(recording)
                db.session.commit()
            except sqlalchemy.exc.IntegrityError:
                db.session.rollback()
                db.session.execute(update(VideoRecording).filter(VideoRecording.segment_path == recording.segment_path)
                                   .values(**recording.serialize()))
                db.session.commit()
    elif event == 'segment_record_complete':
        segment_path = bleach.clean(request.args.get("segment_path"))
        with app.app_context():
            recording = db.session.execute(db.session.query(VideoRecording)
                                           .filter(VideoRecording.segment_path == segment_path)).first()
            if recording and recording.count:
                recording = recording[0]
                recording.in_progress = False
                recording.stop_time = datetime.datetime.now()
                recording.duration = (recording.stop_time - recording.start_time).seconds
            else:
                recording = VideoRecording()
                recording.segment_path = bleach.clean(request.args.get('segment_path'))
                recording.path = bleach.clean(request.args.get('path'))
                recording.in_progress = False
                recording.stop_time = datetime.datetime.now()

            try:
                probe = json.loads(FFmpeg(executable="ffprobe").input(recording.segment_path, print_format="json", show_streams=None, show_format=None).execute())
                for stream in probe['streams']:
                    if stream['codec_type'].lower() == 'video':
                        recording.width = stream['width']
                        recording.height = stream['height']
                        recording.video_bitrate = stream['bit_rate']
                        recording.video_codec = stream['codec_name']
                        FFmpeg().input(recording.segment_path, ss="00:00:01").option("y").output(
                            recording.segment_path + ".png", {"frames:v": 1}).execute()
                    elif stream['codec_type'].lower() == 'audio':
                        recording.audio_codec = stream['codec_name']
                        recording.audio_samplerate = stream['sample_rate']
                        recording.audio_channels = stream['channels']
                        recording.audio_bitrate = stream['bit_rate']
                if 'format' in probe and 'size' in probe['format']:
                    recording.file_size = probe['format']['size']
            except BaseException as e:
                logger.error(f"Failed to run ffprobe: {e}")
                logger.debug(traceback.format_exc())

            db.session.add(recording)
            db.session.commit()
        pass

    return '', 200


@mediamtx_api_blueprint.route('/api/mediamtx/stream/add', methods=['POST'])
@mediamtx_api_blueprint.route('/api/mediamtx/stream/update', methods=['PATCH'])
@auth_required()
def add_update_stream():
    try:
        form = MediaMTXPathConfig(formdata=ImmutableMultiDict(request.json))
        if not form.validate():
            return jsonify({'success': False, 'errors': form.errors}), 400

        path = bleach.clean(request.json.get("path", ""))

        if not path:
            return jsonify({'success': False, 'error': 'Please specify a path name'}), 400

        if path.startswith("/"):
            return jsonify({'success': False, 'error': 'Path cannot begin with a slash'}), 400

        video = db.session.query(VideoStream).where(VideoStream.path == path).first()
        if not video and request.path.endswith('add'):
            video = VideoStream()
            video.path = path
            video.username = current_user.username
            video.mediamtx_settings = json.dumps(form.serialize())
            video.rover_port = -1
            video.ignore_embedded_klv = False
            video.buffer_time = None
            video.rtsp_reliable = 1
            video.network_timeout = 10000
            video.generate_xml(urlparse(request.url_root).hostname)
            db.session.add(video)
            db.session.commit()
        elif not video and request.path.endswith('update'):
            return jsonify({'success': False, 'error': 'Path {} not found'.format(path)}), 400

        settings = json.loads(video.mediamtx_settings)

        for setting in request.json:
            if setting == 'csrf_token' or setting == 'sourceOnDemand' or setting == 'path' or setting == 'source':
                continue
            key = bleach.clean(setting)
            value = request.json.get(setting)
            if isinstance(value, str):
                value = bleach.clean(value)
            if value is not None:
                settings[key] = value
                logger.debug("set {} to {}".format(key, value))

        if request.path.endswith('update'):
            r = requests.patch("{}/v3/config/paths/patch/{}".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), path),
                               json=settings)
        else:
            r = requests.post("{}/v3/config/paths/add/{}".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), path),
                              json=settings)

        if r.status_code == 200:
            logger.debug("Patched path {}: {}".format(path, r.status_code))
            video.mediamtx_settings = json.dumps(settings)
            db.session.add(video)
            db.session.commit()
            return jsonify({'success': True})

        else:
            action = 'add' if request.path.endswith('add') else 'update'
            logger.error("Failed to {} mediamtx path: {} - {}".format(action, r.status_code, r.json()['error']))
            return jsonify({'success': False, 'error': r.json()['error']}), 400

    except BaseException as e:
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500


@mediamtx_api_blueprint.route('/api/mediamtx/stream/delete', methods=['DELETE'])
@auth_required()
def delete_stream():
    try:
        path = bleach.clean(request.args.get("path", ""))

        if not path:
            return jsonify({'success': False, 'error': 'Please specify a path name'}), 400

        r = requests.delete('{}/v3/config/paths/delete/{}'.format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), path))
        logger.debug("Delete status code: {}".format(r.status_code))
        video = db.session.query(VideoStream).filter(VideoStream.path == path)
        if not video:
            return jsonify({'success': False, 'error': 'Path {} not found'.format(path)}), 400

        video.delete()
        db.session.commit()
    except requests.exceptions.ConnectionError as e:
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'MediaMTX is not running'}), 500

    if r.status_code != 404:
        return r.text, r.status_code
    else:
        return "", 200


# This is mainly for mediamtx authentication
@mediamtx_api_blueprint.route('/api/external_auth', methods=['POST'])
def external_auth():
    username = bleach.clean(request.json.get('user'))
    password = bleach.clean(request.json.get('password'))
    action = bleach.clean(request.json.get('action'))
    query = bleach.clean(request.json.get('query'))

    # Token auth to prevent high CPU usage when reading HLS streams
    if 'jwt' in query or 'token' in query:
        query = query.split("&")
        for q in query:
            if "=" not in q:
                continue
            key, value = q.split("=")
            if key == 'jwt':
                try:
                    parse_auth_token(value)
                    return '', 200
                except BaseException as e:
                    logger.error(f"Invalid token: {e}")
                    return '', 401
            elif key == 'token':
                if value == app.config.get("OTS_MEDIAMTX_TOKEN"):
                    return '', 200
                else:
                    return '', 401

    user = app.security.datastore.find_user(username=username)
    if not user:
        return '', 401

    if user and verify_password(password, user.password):
        if action == 'publish':
            logger.debug("Publish {}".format(request.json.get('path')))
            v = VideoStream()
            v.uid = bleach.clean(request.json.get('id')) if request.json.get('id') else None
            v.rover_port = -1
            v.ignore_embedded_klv = False
            v.buffer_time = None
            v.network_timeout = 10000
            v.protocol = bleach.clean(request.json.get('protocol'))
            v.path = bleach.clean(request.json.get('path'))
            v.alias = v.path.split("/")[-1]
            v.username = bleach.clean(request.json.get('user'))
            path_config = MediaMTXPathConfig(None).serialize()
            path_config['sourceOnDemand'] = False
            v.mediamtx_settings = json.dumps(path_config)

            if v.protocol == 'rtsp':
                v.port = 8554
                v.rtsp_reliable = 1
            elif v.protocol == 'rtmp':
                v.port = 1935
                v.rtsp_reliable = 1
            else:
                v.rtsp_reliable = 0

            v.generate_xml(request.json.get("ip"))

            with app.app_context():
                try:

                    db.session.add(v)
                    db.session.commit()
                    r = requests.post(
                        "{}/v3/config/paths/add/{}".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), v.path),
                        json=path_config)
                    if r.status_code == 200:
                        logger.debug("Added path {} to mediamtx".format(v.path))
                    else:
                        logger.error(
                            "Failed to add path {} to mediamtx. Status code {} {}".format(v.path, r.status_code,
                                                                                          r.text))
                    logger.debug("Inserted video stream {}".format(v.uid))
                except sqlalchemy.exc.IntegrityError as e:
                    try:
                        db.session.rollback()
                        video = db.session.query(VideoStream).filter(VideoStream.path == v.path).first()
                        r = requests.post(
                            "{}/v3/config/paths/add/{}".format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"), v.path),
                            json=json.loads(video.mediamtx_settings))
                        if r.status_code == 200:
                            logger.debug("Added path {} to mediamtx".format(v.path))
                        else:
                            logger.error(
                                "Failed to add path {} to mediamtx. Status code {} {}".format(v.path, r.status_code,
                                                                                              r.text))
                    except:
                        logger.error(traceback.format_exc())

        logger.debug("external_auth returning 200")
        return '', 200
    elif query:
        for arg in query.split("&"):
            key, value = arg.split("=")
            if key == 'token' and value == app.config.get("OTS_MEDIAMTX_TOKEN"):
                return '', 200
    else:
        logger.debug("external_auth returning 401")
        return '', 401
