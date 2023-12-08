import datetime
import json
import traceback
from threading import Thread

from sqlalchemy import exc, insert, update
from bs4 import BeautifulSoup
import pika

from opentakserver.models.Alert import Alert
from opentakserver.models.CoT import CoT
from opentakserver.models.EUD import EUD
from opentakserver.models.point import Point


class CoTController(Thread):
    def __init__(self, context, logger, db):
        super().__init__()

        self.context = context
        self.logger = logger
        self.db = db

        self.online_euds = {}
        self.online_callsigns = {}
        self.exchanges = []

        # RabbitMQ
        try:
            self.rabbit_connection = pika.SelectConnection(pika.ConnectionParameters('localhost'),
                                                           self.on_connection_open)
            self.rabbit_channel = None
            self.iothread = Thread(target=self.rabbit_connection.ioloop.start)
            self.iothread.daemon = True
            self.iothread.start()
            self.is_consuming = False
        except BaseException as e:
            self.logger.error("cot_controller - Failed to connect to rabbitmq: {}".format(e))
            return

    def on_connection_open(self, connection):
        self.rabbit_connection.channel(on_open_callback=self.on_channel_open)

    def on_channel_open(self, channel):
        self.rabbit_channel = channel
        self.rabbit_channel.queue_declare(queue='cot_controller')
        self.rabbit_channel.exchange_declare(exchange='cot_controller', exchange_type='fanout')
        self.rabbit_channel.queue_bind(exchange='cot_controller', queue='cot_controller')
        self.rabbit_channel.basic_consume(queue='cot_controller', on_message_callback=self.on_message, auto_ack=True)

    def parse_point(self, event, uid):
        # hae = Height above the WGS ellipsoid in meters
        # ce = Circular 1-sigma or a circular area about the point in meters
        # le = Linear 1-sigma error or an altitude range about the point in meters
        point = event.find('point')
        if point:

            p = Point()
            p.device_uid = uid
            p.ce = point.attrs['ce']
            p.hae = point.attrs['hae']
            p.le = point.attrs['le']
            p.latitude = point.attrs['lat']
            p.longitude = point.attrs['lon']
            p.timestamp = datetime.datetime.now().isoformat() + "Z"

            # We only really care about the rest of the data if there's a valid lat/lon

            track = event.find('track')
            if track:
                p.course = track.attrs['course']
                p.speed = track.attrs['speed']

            precision_location = event.find('precisionlocation')
            if precision_location and 'geopointsrc' in precision_location.attrs:
                p.location_source = precision_location.attrs['geopointsrc']
            elif precision_location and 'altsrc' in precision_location.attrs:
                p.location_source = precision_location.attrs['altsrc']

            status = event.find('status')
            if status:
                if 'battery' in status.attrs:
                    p.battery = status.attrs['battery']

            with self.context:
                res = self.db.session.execute(insert(Point).values(
                    device_uid=uid, ce=point.attrs['ce'], hae=point.attrs['hae'], le=point.attrs['le'],
                    latitude=point.attrs['lat'], longitude=point.attrs['lon'],
                    timestamp=event.attrs['start'] + "Z")
                )
                pk = res.inserted_primary_key[0]
                self.logger.debug("Got point PK {}".format(pk))
                self.db.session.commit()
                return pk

    def parse_device_info(self, uid, soup, event):
        link = event.find('link')
        fileshare = event.find('fileshare')
        # uid = event.attrs['uid']
        callsign = None
        phone_number = None

        if uid not in self.online_euds and not uid.endswith('ping'):

            contact = event.find('contact')
            if contact:
                if 'callsign' in contact.attrs:
                    callsign = contact.attrs['callsign']

                    if callsign not in self.online_callsigns:
                        self.online_callsigns[callsign] = {'uid': uid, 'cot': soup}

                    # Declare a RabbitMQ Queue for this uid and join the 'dms' and 'cot' exchanges
                    if self.rabbit_channel and self.rabbit_channel.is_open:
                        self.rabbit_channel.queue_bind(exchange='dms', queue=uid, routing_key=uid)
                        self.rabbit_channel.queue_bind(exchange='chatrooms', queue=uid,
                                                       routing_key='All Chat Rooms')

                        for eud in self.online_euds:
                            self.rabbit_channel.basic_publish(exchange='dms', routing_key=uid,
                                                              body=str(self.online_euds[eud]['cot']))

                        self.online_euds[uid] = {'cot': soup, 'callsign': callsign}

                if 'phone' in contact.attrs:
                    phone_number = contact.attrs['phone']

            takv = event.find('takv')
            if takv:
                device = takv.attrs['device']
                os = takv.attrs['os']
                platform = takv.attrs['platform']
                version = takv.attrs['version']

                eud = EUD()
                eud.uid = uid
                eud.callsign = callsign
                eud.device = device
                eud.os = os
                eud.platform = platform
                eud.version = version
                eud.phone_number = phone_number
                eud.last_event_time = event.attrs['start']
                eud.last_status = 'Connected'

                with self.context:
                    try:
                        self.db.session.add(eud)
                        self.db.session.commit()
                    except exc.IntegrityError as e:
                        # This EUD/uid is already in the DB, update it in case anything changed like callsign or app version
                        self.db.session.rollback()
                        eud = self.db.session.execute(self.db.select(EUD).filter_by(uid=uid)).scalar_one()
                        eud.callsign = callsign
                        eud.os = os
                        eud.platform = platform
                        eud.version = version
                        eud.phone_number = phone_number
                        eud.last_event_time = event.attrs['start']
                        eud.last_status = 'Connected'
                        self.db.session.commit()
                        self.logger.debug("Updated {}".format(uid))

    def parse_groups(self, event, uid):
        groups = event.find_all('__group')

        for group in groups:
            # Declare an exchange for each group and bind the callsign's queue
            if self.rabbit_channel.is_open and group.attrs['name'] not in self.exchanges:
                self.logger.debug("Declaring exchange {}".format(group.attrs['name']))
                self.rabbit_channel.exchange_declare(exchange=group.attrs['name'])
                self.rabbit_channel.queue_bind(queue=uid, exchange='chatrooms', routing_key=group.attrs['name'])
                self.exchanges.append(group.attrs['name'])

    def rabbitmq_routing(self, event, data):
        # RabbitMQ Routing
        chat = event.find("__chat")
        destinations = event.find_all('dest')

        if chat and 'chatroom' in chat.attrs and chat.attrs['chatroom'] == 'All Chat Rooms':
            self.rabbit_channel.basic_publish(exchange='chatrooms', routing_key='All Chat Rooms', body=data)

        elif destinations:
            for destination in destinations:
                self.rabbit_channel.basic_publish(exchange='dms',
                                                  routing_key=self.online_callsigns[destination.attrs['callsign']]['uid'],
                                                  body=data)

        # If no destination or callsign is specified, broadcast to all TAK clients
        elif self.rabbit_channel and self.rabbit_channel.is_open:
            self.rabbit_channel.basic_publish(exchange='cot', routing_key="", body=data)

        # Do nothing because the RabbitMQ channel hasn't opened yet or has closed
        else:
            self.logger.debug("Not publishing, channel closed")

    def insert_cot(self, soup, event, uid):
        with self.context:
            self.db.session.execute(insert(CoT).values(
                how=event.attrs['how'], type=event.attrs['type'], sender_callsign=self.online_euds[uid]['callsign'],
                sender_uid=uid, timestamp=datetime.datetime.now().isoformat() + "Z", xml=str(soup)
            ))
            self.db.session.commit()

    def parse_alert(self, event, uid, point_pk):
        emergency = event.find('emergency')
        if emergency:
            if 'type' in emergency.attrs:
                emergency_type = emergency.attrs['type']
                alert = Alert()
                alert.uid = uid
                alert.start_time = event.attrs['start']
                alert.point_id = point_pk
                alert.alert_type = emergency_type

                with self.context:
                    self.db.session.add(alert)
                    self.db.session.commit()
            elif 'cancel' in emergency.attrs:
                with self.context:
                    self.db.session.execute(update(Alert).where(Alert.uid == uid and Alert.cancel_time is None)
                                            .values(cancel_time=event.attrs['start']))
                    self.db.session.commit()

    def on_message(self, unused_channel, basic_deliver, properties, body):
        try:
            body = json.loads(body)
            soup = BeautifulSoup(body['cot'], 'xml')
            self.logger.warning(soup)
            event = soup.find('event')
            if event:
                self.parse_device_info(body['uid'], soup, event)
                point_pk = self.parse_point(event, body['uid'])
                self.parse_groups(event, body['uid'])
                self.parse_alert(event, body['uid'], point_pk)
                self.insert_cot(soup, event, body['uid'])
                self.rabbitmq_routing(event, body['cot'])

                # EUD went offline
                if event.attrs['type'] == 't-x-d-d':
                    link = event.find('link')

                    try:
                        with self.context:
                            eud = self.db.session.execute(self.db.select(EUD).filter_by(uid=body['uid'])).scalar_one()
                            eud.last_event_time = event.attrs['start']
                            eud.last_status = 'Disconnected'
                            self.db.session.commit()
                            self.logger.debug("Updated {}".format(body['uid']))
                    except BaseException as e:
                        self.logger.error("Failed to update EUD: {}".format(e))

                    self.online_euds.pop(link.attrs['uid'])
        except BaseException as e:
            self.logger.error(traceback.format_exc())
