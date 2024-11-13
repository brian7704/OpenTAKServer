import datetime
import json
import traceback
from xml.etree.ElementTree import tostring

import pika
from bs4 import BeautifulSoup
from flask import Blueprint
import adsbxcot
import aiscot
from flask import current_app as app
from sqlalchemy import delete

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
from opentakserver.models.Mission import Mission
from opentakserver.models.MissionChange import MissionChange
from opentakserver.models.MissionContentMission import MissionContentMission
from opentakserver.models.MissionRole import MissionRole
from opentakserver.models.MissionUID import MissionUID
from opentakserver.models.Point import Point
from opentakserver.models.RBLine import RBLine
from opentakserver.models.Team import Team
from opentakserver.models.VideoRecording import VideoRecording
from opentakserver.models.VideoStream import VideoStream
from opentakserver.models.ZMIST import ZMIST
from opentakserver.functions import iso8601_string_from_datetime, datetime_from_iso8601_string, generate_delete_cot, publish_cot

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
                        {'cot': str(BeautifulSoup(event, 'xml')), 'uid': app.config['OTS_NODE_ID']}),
                                          properties=pika.BasicProperties(expiration=app.config.get("OTS_RABBITMQ_TTL")))
                    # noinspection PyTypeChecker
                    channel.basic_publish(exchange='cot_controller', routing_key='', body=json.dumps(
                        {'cot': str(BeautifulSoup(event, 'xml')), 'uid': app.config['OTS_NODE_ID']}),
                                          properties=pika.BasicProperties(expiration=app.config.get("OTS_RABBITMQ_TTL")))

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
    # These are in a specific order to properly handle foreign key relationships
    delete_video_recordings()
    ZMIST.query.delete()
    VideoStream.query.delete()
    Alert.query.delete()
    CasEvac.query.delete()
    Certificate.query.delete()
    ChatroomsUids.query.delete()
    DataPackage.query.delete()
    Marker.query.delete()
    GeoChat.query.delete()
    Point.query.delete()
    RBLine.query.delete()
    Chatroom.query.delete()
    CoT.query.delete()
    MissionRole.query.delete()
    MissionContentMission.query.delete()
    MissionUID.query.delete()
    MissionChange.query.delete()
    Mission.query.delete()
    EUD.query.delete()
    Team.query.delete()
    db.session.commit()
    logger.info("Purged all data")


@apscheduler.task("interval", id="ais", name="AISHub.net", next_run_time=None)
def get_aishub_data():
    if not app.config.get("OTS_AISHUB_USERNAME"):
        logger.error("Please set your AISHub username")
        return

    with apscheduler.app.app_context():
        try:
            params = {"username": app.config.get("OTS_AISHUB_USERNAME"), "format": 1, "output": "json"}
            if app.config.get("OTS_AISHUB_SOUTH_LAT"):
                params['latmin'] = app.config.get("OTS_AISHUB_SOUTH_LAT")
            if app.config.get("OTS_AISHUB_WEST_LON"):
                params['lonmin'] = app.config.get("OTS_AISHUB_WEST_LON")
            if app.config.get("OTS_AISHUB_NORTH_LAT"):
                params['latmax'] = app.config.get("OTS_AISHUB_NORTH_LAT")
            if app.config.get("OTS_AISHUB_EAST_LON"):
                params['lonmax'] = app.config.get("OTS_AISHUB_EAST_LON")
            if app.config.get("OTS_AISHUB_MMSI_LIST"):
                params['mmsi'] = app.config.get("OTS_AISHUB_MMSI_LIST")
            if app.config.get("OTS_AISHUB_IMO_LIST"):
                params['imo'] = app.config.get("OTS_AISHUB_IMO_LIST")
            r = requests.get("https://data.aishub.net/ws.php", params=params)

            if r.status_code != 200:
                logger.error(f"Failed to get AIS data: {r.text}")
                return

            rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
            channel = rabbit_connection.channel()
            for vessel in r.json()[1]:
                event = aiscot.ais_to_cot(vessel, None, None)
                # noinspection PyTypeChecker
                channel.basic_publish(exchange='cot', routing_key='', body=json.dumps(
                    {'cot': str(BeautifulSoup(event, 'xml')), 'uid': app.config['OTS_NODE_ID']}),
                                      properties=pika.BasicProperties(expiration=app.config.get("OTS_RABBITMQ_TTL")))
                # noinspection PyTypeChecker
                channel.basic_publish(exchange='cot_controller', routing_key='', body=json.dumps(
                    {'cot': str(BeautifulSoup(event, 'xml')), 'uid': app.config['OTS_NODE_ID']}),
                                      properties=pika.BasicProperties(expiration=app.config.get("OTS_RABBITMQ_TTL")))

            channel.close()
            rabbit_connection.close()
        except BaseException as e:
            logger.error(f"Failed to get AIS data: {e}")
            logger.debug(traceback.format_exc())


@apscheduler.task('interval', name="Delete Old Data", id='delete_old_data', next_run_time=None)
def delete_old_data():
    timestamp = datetime.datetime.now() - datetime.timedelta(
        seconds=app.config.get("OTS_DELETE_OLD_DATA_SECONDS"),
        minutes=app.config.get("OTS_DELETE_OLD_DATA_MINUTES"),
        hours=app.config.get("OTS_DELETE_OLD_DATA_HOURS"),
        days=app.config.get("OTS_DELETE_OLD_DATA_DAYS"),
        weeks=app.config.get("OTS_DELETE_OLD_DATA_WEEKS"))

    rabbit_connection = pika.BlockingConnection(
        pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()

    # I wish I hadn't made the marker's timestamp field a string...
    markers = db.session.execute(db.session.query(Marker)).all()
    for marker in markers:
        marker = marker[0]
        if datetime_from_iso8601_string(marker.production_time) <= timestamp:
            cot = generate_delete_cot(marker.uid, marker.cot.type)
            channel.basic_publish(exchange='cot', routing_key='', body=json.dumps(
                {'cot': tostring(cot).decode('utf-8'), 'uid': app.config['OTS_NODE_ID']}),
                                  properties=pika.BasicProperties(expiration=app.config.get("OTS_RABBITMQ_TTL")))
            db.session.delete(marker)

    alerts = db.session.execute(db.session.query(Alert).where(Alert.start_time <= timestamp)).all()
    for alert in alerts:
        alert = alert[0]
        publish_cot(generate_delete_cot(alert.uid, alert.cot.type), channel)
        db.session.delete(alert)

    rb_lines = db.session.execute(db.session.query(RBLine).where(RBLine.timestamp <= timestamp)).all()
    for rb_line in rb_lines:
        rb_line = rb_line[0]
        publish_cot(generate_delete_cot(rb_line.uid, rb_line.cot.type), channel)
        db.session.delete(rb_line)

    db.session.execute(delete(Point).where(Point.timestamp <= timestamp))
    db.session.execute(delete(CoT).where(CoT.timestamp <= timestamp))
    db.session.execute(delete(EUD).where(EUD.last_event_time <= timestamp).where(EUD.last_status != 'Connected'))
    db.session.commit()

    channel.close()
    rabbit_connection.close()

    logger.info(f"Deleted data older than {iso8601_string_from_datetime(timestamp)}")
