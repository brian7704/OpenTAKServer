import json
import traceback

import pika
from bs4 import BeautifulSoup
from flask import Blueprint
import adsbxcot
from flask import current_app as app

from opentakserver.config import Config
from opentakserver.extensions import apscheduler, logger
import requests

scheduler_blueprint = Blueprint('scheduler_blueprint', __name__)


@apscheduler.task('interval', id='get_airplanes_live_data', minutes=app.config.get("OTS_AIRPLANES_LIVE_MINUTES", 5),
                  seconds=app.config.get("OTS_AIRPLANES_LIVE_SECONDS", 0))
def get_airplanes_live_data():
    if not app.config.get("OTS_ENABLE_AIRPLANES_LIVE", False):
        return

    try:
        r = requests.get('https://api.airplanes.live/v2/point/{}/{}/{}'
                         .format(Config.OTS_AIRPLANES_LIVE_LAT,
                                 Config.OTS_AIRPLANES_LIVE_LON,
                                 Config.OTS_AIRPLANES_LIVE_RADIUS))
        if r.status_code == 200:
            rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
            channel = rabbit_connection.channel()

            for craft in r.json()['ac']:
                try:
                    event = adsbxcot.adsbx_to_cot(craft, known_craft=None)
                except ValueError:
                    continue

                channel.basic_publish(exchange='cot', routing_key='', body=json.dumps(
                    {'cot': str(BeautifulSoup(event, 'xml')), 'uid': Config.OTS_NODE_ID}))
                channel.basic_publish(exchange='cot_controller', routing_key='', body=json.dumps(
                        {'cot': str(BeautifulSoup(event, 'xml')), 'uid': Config.OTS_NODE_ID}))

            channel.close()
            rabbit_connection.close()
        else:
            logger.error('Failed to get airplanes.live: {}'.format(r.text))
    except BaseException as e:
        logger.error("Failed to get airplanes.live: {}".format(e))
        logger.error(traceback.format_exc())
