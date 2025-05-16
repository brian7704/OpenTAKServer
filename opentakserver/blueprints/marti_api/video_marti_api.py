import json
import traceback
from urllib.parse import urlparse
from xml.etree.ElementTree import tostring, fromstring, Element

import sqlalchemy
from OpenSSL import crypto
from bs4 import BeautifulSoup
from flask import request, Blueprint, jsonify, current_app as app
from werkzeug.datastructures import ImmutableMultiDict

from opentakserver.blueprints.marti_api.marti_api import verify_client_cert
from opentakserver.extensions import logger, db
from opentakserver.forms.MediaMTXPathConfig import MediaMTXPathConfig
from opentakserver.functions import iso8601_string_from_datetime
from opentakserver import __version__ as version
from opentakserver.models.EUD import EUD
from opentakserver.models.VideoStream import VideoStream
from opentakserver.models.user import User

video_marti_api = Blueprint('video_marti_api', __name__)

@video_marti_api.route('/Marti/vcm', methods=['GET', 'POST'])
def video():
    if request.method == 'POST':
        soup = BeautifulSoup(request.data, 'xml')
        video_connections = soup.find('videoConnections')

        path = video_connections.find('path').text
        if path.startswith("/"):
            path = path[1:]

        if video_connections:
            v = VideoStream()
            v.protocol = video_connections.find('protocol').text
            v.alias = video_connections.find('alias').text
            v.uid = video_connections.find('uid').text
            v.port = video_connections.find('port').text
            v.rover_port = video_connections.find('roverPort').text
            v.ignore_embedded_klv = (video_connections.find('ignoreEmbeddedKLV').text.lower() == 'true')
            v.preferred_mac_address = video_connections.find('preferredMacAddress').text
            v.preferred_interface_address = video_connections.find('preferredInterfaceAddress').text
            v.path = path
            v.buffer_time = video_connections.find('buffer').text
            v.network_timeout = video_connections.find('timeout').text
            v.rtsp_reliable = video_connections.find('rtspReliable').text
            path_config = MediaMTXPathConfig(None).serialize()
            path_config['sourceOnDemand'] = False
            v.mediamtx_settings = json.dumps(path_config)

            # Discard username and password for security
            feed = soup.find('feed')
            address = feed.find('address').text
            feed.find('address').string.replace_with(address.split("@")[-1])

            v.xml = str(feed)

            with app.app_context():
                try:
                    db.session.add(v)
                    db.session.commit()
                    logger.debug("Inserted Video")
                except sqlalchemy.exc.IntegrityError as e:
                    db.session.rollback()
                    v = db.session.execute(db.select(VideoStream).filter_by(path=v.path)).scalar_one()
                    v.protocol = video_connections.find('protocol').text
                    v.alias = video_connections.find('alias').text
                    v.uid = video_connections.find('uid').text
                    v.port = video_connections.find('port').text
                    v.rover_port = video_connections.find('roverPort').text
                    v.ignore_embedded_klv = (video_connections.find('ignoreEmbeddedKLV').text.lower() == 'true')
                    v.preferred_mac_address = video_connections.find('preferredMacAddress').text
                    v.preferred_interface_address = video_connections.find('preferredInterfaceAddress').text
                    v.path = video_connections.find('path').text
                    v.buffer_time = video_connections.find('buffer').text
                    v.network_timeout = video_connections.find('timeout').text
                    v.rtsp_reliable = video_connections.find('rtspReliable').text
                    feed = soup.find('feed')
                    address = feed.find('address').text
                    feed.find('address').replace_with(address.split("@")[-1])

                    v.xml = str(feed)

                    db.session.commit()
                    logger.debug("Updated video")

        return '', 200

    elif request.method == 'GET':
        try:
            with app.app_context():
                videos = db.session.execute(db.select(VideoStream)).scalars()
                videoconnections = Element('videoConnections')

                for video in videos:
                    # Make sure videos have the correct address based off of the Flask request and not 127.0.0.1
                    # This also forces all streams to bounce through MediaMTX
                    feed = BeautifulSoup(video.xml, 'xml')

                    url = urlparse(request.url_root).hostname
                    path = feed.find('path').text
                    if not path.startswith("/"):
                        path = "/" + path

                    if 'iTAK' in request.user_agent.string:
                        url = feed.find('protocol').text + "://" + url + ":" + feed.find("port").text + path

                    if feed.find('address'):
                        feed.find('address').string.replace_with(url)
                    else:
                        address = feed.new_tag('address')
                        address.string = url
                        feed.feed.append(address)
                    videoconnections.append(fromstring(str(feed)))

            return tostring(videoconnections), 200
        except BaseException as e:
            logger.error(traceback.format_exc())
            return '', 500


@video_marti_api.route('/Marti/api/video')
def get_videos():
    cert = verify_client_cert()
    if not cert:
        # Shouldn't ever get here since nginx already verifies the cert
        return jsonify({'success': False, 'error': 'Invalid Certificate'}), 400
    username = None
    for a in cert.get_subject().get_components():
        if a[0].decode('UTF-8') == 'CN':
            username = a[1].decode('UTF-8')
            break

    user = app.security.datastore.find_user(username=username)
    videos = db.session.execute(db.select(VideoStream)).scalars()

    video_connections = {'videoConnections': []}
    for video in videos:
        video_connections['videoConnections'].append(video.to_marti_json(user))

    return jsonify(video_connections)


@video_marti_api.route('/Marti/api/video', methods=['POST'])
def add_video():
    cert = verify_client_cert()
    username = None
    for a in cert.get_subject().get_components():
        if a[0].decode('UTF-8') == 'CN':
            username = a[1].decode('UTF-8')
            break

    videos = request.json

    for video in videos['videoConnections']:
        feeds = video.get('feeds')

        for feed in feeds:
            data = ImmutableMultiDict(
                {
                    'path': feed['alias'],
                    'source': feed['url']
                }
            )
            mediamtx_config = MediaMTXPathConfig(formdata=data, csrf_enabled=False)

            video_stream = VideoStream()
            video_stream.path = feed['alias']
            video_stream.uid = video['uuid']
            video_stream.mediamtx_settings = json.dumps(mediamtx_config.serialize())
            video_stream.username = username
            video_stream.rover_port = -1
            video_stream.ignore_embedded_klv = False
            video_stream.buffer_time = None
            video_stream.rtsp_reliable = 1
            video_stream.network_timeout = 10000
            video_stream.generate_xml(urlparse(request.url_root).hostname)
            db.session.add(video_stream)
            db.session.commit()

    return '', 200


@video_marti_api.route('/Marti/api/video/<uid>')
def get_video(uid):
    cert = verify_client_cert()
    username = None
    for a in cert.get_subject().get_components():
        if a[0].decode('UTF-8') == 'CN':
            username = a[1].decode('UTF-8')
            break

    video = db.session.query(VideoStream).filter_by(uid=uid).scalar()
    if not video:
        return jsonify({'success': False, 'error': 'Video not found'}), 404
    user = db.session.execute(db.session.query(User).filter_by(username=username)).first()
    if not user:
        return jsonify({'success': False, 'error': f'User {username} not found'}), 401
    user = user[0]
    return video.to_marti_json(user), 200


@video_marti_api.route('/Marti/api/video/<uid>', methods=['DELETE'])
def delete_video(uid):
    video_stream = db.session.execute(db.session.query(VideoStream).filter_by(uid=uid))
    if not video_stream:
        return jsonify({'success': False, 'error': f'Video stream with uid {uid} not found'}), 404

    video_stream = video_stream[0]

    db.session.delete(video_stream)
    db.session.commit()

    return '', 200
