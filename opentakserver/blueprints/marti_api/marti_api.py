import json
import traceback
from urllib.parse import urlparse

from xml.etree.ElementTree import Element, tostring, fromstring

import bleach
import sqlalchemy
from bs4 import BeautifulSoup
from flask import request, Blueprint, jsonify, current_app as app
from flask_security import current_user

from opentakserver.extensions import logger, db
from opentakserver.forms.MediaMTXPathConfig import MediaMTXPathConfig
from opentakserver.functions import iso8601_string_from_datetime
from opentakserver import __version__ as version
from opentakserver.models.EUD import EUD
from opentakserver.models.VideoStream import VideoStream
from opentakserver.blueprints.marti_api.data_package_marti_api import data_package_marti_api
from opentakserver.blueprints.marti_api.datasync_marti_api import datasync_api
from opentakserver.blueprints.marti_api.cot_marti_api import cot_marti_api
from opentakserver.blueprints.marti_api.device_profile_marti_api import device_profile_marti_api_blueprint
from opentakserver.blueprints.marti_api.citrap_api import citrap_api_blueprint
from opentakserver.blueprints.marti_api.certificate_enrollment_api import certificate_authority_api_blueprint

marti_api = Blueprint('marti_api', __name__)

marti_api.register_blueprint(data_package_marti_api)
marti_api.register_blueprint(datasync_api)
marti_api.register_blueprint(cot_marti_api)
marti_api.register_blueprint(device_profile_marti_api_blueprint)
marti_api.register_blueprint(citrap_api_blueprint)
marti_api.register_blueprint(certificate_authority_api_blueprint)


@marti_api.route('/Marti/api/clientEndPoints', methods=['GET'])
def client_end_points():
    euds = db.session.execute(db.select(EUD)).scalars()
    return_value = {'version': 3, "type": "com.bbn.marti.remote.ClientEndpoint", 'data': [],
                    'nodeId': app.config.get("OTS_NODE_ID")}
    for eud in euds:
        return_value['data'].append({
            'callsign': eud.callsign,
            'uid': eud.uid,
            'username': current_user.username if current_user.is_authenticated else 'anonymous',
            'lastEventTime': iso8601_string_from_datetime(eud.last_event_time),
            'lastStatus': eud.last_status
        })

    return return_value, 200, {'Content-Type': 'application/json'}


@marti_api.route('/Marti/api/version/config', methods=['GET'])
def marti_config():
    url = urlparse(request.url_root)

    return {"version": "3", "type": "ServerConfig",
            "data": {"version": version, "api": "3", "hostname": url.hostname},
            "nodeId": app.config.get("OTS_NODE_ID")}, 200, {'Content-Type': 'application/json'}


@marti_api.route('/Marti/api/groups/all')
def groups():
    use_cache = bleach.clean(request.args.get('useCache'))  # bool

    response = {
        'version': 3, 'type': 'com.bbn.marti.remote.groups.Group', 'data': [{}], 'nodeId': app.config.get("OTS_NODE_ID")
    }

    return jsonify(response)


@marti_api.route('/Marti/vcm', methods=['GET', 'POST'])
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

