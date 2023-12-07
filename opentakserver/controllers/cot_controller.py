import datetime
import traceback
from threading import Thread

import sqlalchemy
from bs4 import BeautifulSoup
import pika

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
                self.db.session.add(p)
                self.db.session.commit()

    def parse_device_info(self, soup, event):
        link = event.find('link')
        fileshare = event.find('fileshare')
        uid = event.attrs['uid']
        callsign = None
        phone_number = None

        if link:
            uid = link.attrs['uid']
        elif fileshare:
            uid = fileshare.attrs['senderUid']
        elif uid.startswith('GeoChat'):
            uid = uid.split('.')[1]

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

                with self.context:
                    try:
                        self.db.session.add(eud)
                        self.db.session.commit()
                    except sqlalchemy.exc.IntegrityError as e:
                        # This EUD/uid is already in the DB, update it in case anything changed like callsign or app version
                        self.db.session.rollback()
                        eud = self.db.session.execute(self.db.select(EUD).filter_by(uid=uid)).scalar_one()
                        eud.callsign = callsign
                        eud.os = os
                        eud.platform = platform
                        eud.version = version
                        eud.phone_number = phone_number
                        self.db.session.commit()
                        self.logger.debug("Updated {}".format(uid))

        return uid

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
        cot = CoT()
        cot.how = event.attrs['how']
        cot.type = event.attrs['type']
        cot.sender_callsign = self.online_euds[uid]['callsign']
        cot.sender_uid = uid
        cot.xml = str(soup)

        with self.context:
            self.db.session.add(cot)
            self.db.session.commit()

    def on_message(self, unused_channel, basic_deliver, properties, body):
        try:
            soup = BeautifulSoup(body, 'xml')
            event = soup.find('event')
            if event:
                uid = self.parse_device_info(soup, event)
                self.parse_point(event, uid)
                self.parse_groups(event, uid)
                self.insert_cot(soup, event, uid)
                self.rabbitmq_routing(event, body)

                if event.attrs['type'] == 't-x-d-d':
                    link = event.find('link')
                    self.online_euds.pop(link.attrs['uid'])
        except BaseException as e:
            self.logger.error(traceback.format_exc())
