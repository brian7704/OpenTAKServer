import json
import traceback

import pika
from bs4 import BeautifulSoup
from flask import Blueprint
import adsbxcot
from flask import current_app as app

from opentakserver.extensions import apscheduler, logger, db
import requests

from opentakserver.models.Chatrooms import Chatroom
from opentakserver.models.Alert import Alert
from opentakserver.models.CasEvac import CasEvac
from opentakserver.models.Certificate import Certificate
from opentakserver.models.ChatroomsUids import ChatroomsUids
from opentakserver.models.CoT import CoT
from opentakserver.models.DataPackage import DataPackage
from opentakserver.models.EUD import EUD
from opentakserver.models.GeoChat import GeoChat
from opentakserver.models.Marker import Marker
from opentakserver.models.Point import Point
from opentakserver.models.RBLine import RBLine
from opentakserver.models.Team import Team
from opentakserver.models.VideoRecording import VideoRecording
from opentakserver.models.VideoStream import VideoStream
from opentakserver.models.ZMIST import ZMIST

scheduler_blueprint = Blueprint('scheduler_blueprint', __name__)


@apscheduler.task("interval", name="Airplanes.live", id='get_airplanes_live_data', next_run_time=None)
def get_airplanes_live_data():
    with apscheduler.app.app_context():
        try:
            r = requests.get('https://api.airplanes.live/v2/point/{}/{}/{}'
                             .format(app.config["OTS_AIRPLANES_LIVE_LAT"],
                                     app.config["OTS_AIRPLANES_LIVE_LON"],
                                     app.config["OTS_AIRPLANES_LIVE_RADIUS"]))
            if r.status_code == 200:
                rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
                channel = rabbit_connection.channel()

                for craft in r.json()['ac']:
                    try:
                        event = adsbxcot.adsbx_to_cot(craft, known_craft=None)
                    except ValueError:
                        continue

                    # noinspection PyTypeChecker
                    channel.basic_publish(exchange='cot', routing_key='', body=json.dumps(
                        {'cot': str(BeautifulSoup(event, 'xml')), 'uid': app.config['OTS_NODE_ID']}))
                    # noinspection PyTypeChecker
                    channel.basic_publish(exchange='cot_controller', routing_key='', body=json.dumps(
                        {'cot': str(BeautifulSoup(event, 'xml')), 'uid': app.config['OTS_NODE_ID']}))

                channel.close()
                rabbit_connection.close()
            else:
                logger.error('Failed to get airplanes.live: {}'.format(r.text))
        except BaseException as e:
            logger.error("Failed to get airplanes.live: {}".format(e))
            logger.error(traceback.format_exc())


@apscheduler.task("interval", name="Delete Video Recordings", id="delete_video_recordings", next_run_time=None)
def delete_video_recordings():
    with apscheduler.app.app_context():
        VideoRecording.query.delete()
        db.session.commit()

        try:
            r = requests.get('{}/v3/recordings/list'.format(app.config.get("OTS_MEDIAMTX_API_ADDRESS")))
            if r.status_code == 200:
                recordings = r.json()
                for path in recordings['items']:
                    for recording in path['segments']:
                        r = requests.delete('{}/v3/recordings/deletesegment'.format(app.config.get("OTS_MEDIAMTX_API_ADDRESS"),),
                                            params={'start': recording['start'], 'path': path['name']})
                        if r.status_code != 200:
                            logger.error(
                                "Failed to delete {} from {}: {}".format(recording['start'], path['name'], r.text))
        except BaseException as e:
            logger.error("Failed to delete recordings: {}".format(e))


@apscheduler.task("cron", id="purge_data", name="Purge Data", day="*", hour=0, minute=0, next_run_time=None)
def purge_data():
    delete_video_recordings()
    Alert.query.delete()
    CasEvac.query.delete()
    Certificate.query.delete()
    Chatroom.query.delete()
    ChatroomsUids.query.delete()
    CoT.query.delete()
    DataPackage.query.delete()
    EUD.query.delete()
    GeoChat.query.delete()
    Marker.query.delete()
    Point.query.delete()
    RBLine.query.delete()
    Team.query.delete()
    VideoStream.query.delete()
    ZMIST.query.delete()
    db.session.commit()
    logger.info("Purged all data")
