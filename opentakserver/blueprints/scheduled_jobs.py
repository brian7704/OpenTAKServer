import json
import os
import shutil
import traceback

import pika
from bs4 import BeautifulSoup
from flask import Blueprint
import adsbxcot
from flask import current_app as app

from opentakserver.extensions import apscheduler, logger, db
import requests

from opentakserver.models.VideoRecording import VideoRecording

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
                rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
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
            r = requests.get('http://localhost:9997/v3/recordings/list')
            if r.status_code == 200:
                recordings = r.json()
                for path in recordings['items']:
                    for recording in path['segments']:
                        r = requests.delete('http://localhost:9997/v3/recordings/deletesegment', params={'start': recording['start'], 'path': path['name']})
                        if r.status_code != 200:
                            logger.error("Failed to delete {} from {}: {}".format(recording['start'], path['name'], r.text))
        except BaseException as e:
            logger.error("Failed to delete recordings: {}".format(e))