import datetime
import json
import traceback
from threading import Thread
from xml.etree.ElementTree import Element, SubElement, tostring

import sqlalchemy.exc
from sqlalchemy import exc, insert, update
from bs4 import BeautifulSoup
import pika

from models.Chatrooms import Chatroom
from models.Alert import Alert
from models.CasEvac import CasEvac
from models.ChatroomsUids import ChatroomsUids
from models.CoT import CoT
from models.EUD import EUD
from models.GeoChat import GeoChat
from models.Video import Video
from models.ZMIST import ZMIST
from models.point import Point


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

    def parse_geochat(self, event, cot_id, point_id):
        chat = event.find('__chat')
        if chat:
            chat_group = event.find('chatgrp')
            remarks = event.find('remarks')

            chatroom = Chatroom()

            chatroom.name = chat.attrs['chatroom']
            chatroom.id = chat.attrs['id']
            chatroom.parent = chat.attrs['parent']

            with self.context:
                try:
                    self.db.session.add(chatroom)
                    self.db.session.commit()
                except sqlalchemy.exc.IntegrityError:
                    self.db.session.rollback()

            geochat = GeoChat()

            geochat.uid = event.attrs['uid']
            geochat.chatroom_id = chat.attrs['id']
            geochat.sender_uid = chat_group.attrs['uid0']
            geochat.remarks = remarks.text
            geochat.timestamp = remarks.attrs['time']
            geochat.point_id = point_id
            geochat.cot_id = cot_id

            with self.context:
                try:

                    self.db.session.add(geochat)
                    self.db.session.commit()
                except sqlalchemy.exc.IntegrityError:
                    # TODO: Check if remarks can be edited and if so do an update here
                    self.db.session.rollback()

            for attr in chat_group.attrs:
                if attr.startswith("uid") and attr != 'uid':

                    if chat.attrs['groupOwner'].lower() == 'true' and attr == 'uid0':
                        with self.context:
                            self.db.session.execute(update(Chatroom).where(Chatroom.id == chat.attrs['id'])
                                                    .values(group_owner=chat_group.attrs[attr]))
                            self.db.session.commit()

                    chatroom_uid = ChatroomsUids()
                    chatroom_uid.chatroom_id = chat.attrs['id']
                    chatroom_uid.uid = chat_group.attrs[attr]

                    with self.context:
                        try:
                            self.db.session.add(chatroom_uid)
                            self.db.session.commit()
                            self.logger.debug("add {} to chatroom {}".format(chatroom_uid.uid, chatroom_uid.chatroom_id))
                        except sqlalchemy.exc.IntegrityError:
                            self.db.session.rollback()

    def parse_point(self, event, uid, cot_id):
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
            p.cot_id = cot_id

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
                    device_uid=uid, ce=p.ce, hae=p.hae, le=p.le, latitude=p.latitude, longitude=p.longitude,
                    timestamp=event.attrs['start'] + "Z", cot_id=cot_id, location_source=p.location_source,
                    course=p.course, speed=p.speed, battery=p.battery)
                )

                self.db.session.commit()
                return res.inserted_primary_key[0]

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
                                                  routing_key=self.online_callsigns[destination.attrs['callsign']][
                                                      'uid'],
                                                  body=data)

        # If no destination or callsign is specified, broadcast to all TAK clients
        elif self.rabbit_channel and self.rabbit_channel.is_open:
            self.rabbit_channel.basic_publish(exchange='cot', routing_key="", body=data)

        # Do nothing because the RabbitMQ channel hasn't opened yet or has closed
        else:
            self.logger.debug("Not publishing, channel closed")

    def insert_cot(self, soup, event, uid):
        with self.context:
            res = self.db.session.execute(insert(CoT).values(
                how=event.attrs['how'], type=event.attrs['type'], sender_callsign=self.online_euds[uid]['callsign'],
                sender_uid=uid, timestamp=event.attrs['start'], xml=str(soup)
            ))

            self.db.session.commit()
            return res.inserted_primary_key[0]

    def parse_alert(self, event, uid, point_pk, cot_pk):
        emergency = event.find('emergency')
        if emergency:
            if 'type' in emergency.attrs:
                emergency_type = emergency.attrs['type']
                alert = Alert()
                alert.sender_uid = uid
                alert.uid = event.attrs['uid']
                alert.start_time = event.attrs['start']
                alert.point_id = point_pk
                alert.alert_type = emergency_type
                alert.cot_id = cot_pk

                with self.context:
                    self.db.session.add(alert)
                    self.db.session.commit()
            elif 'cancel' in emergency.attrs:
                with self.context:
                    self.db.session.execute(update(Alert).where(Alert.uid == event.attrs['uid'])
                                            .values(cancel_time=event.attrs['start']))
                    self.db.session.commit()

    def parse_casevac(self, event, uid, point_pk, cot_pk):
        medevac = event.find('_medevac_')
        if medevac:
            zmist = medevac.find('zMist')
            with self.context:
                for a in medevac.attrs:
                    if medevac.attrs[a].lower() == 'true':
                        medevac.attrs[a] = True
                    elif medevac.attrs[a].lower() == 'false':
                        medevac.attrs[a] = False

                try:
                    res = self.db.session.execute(insert(CasEvac).values(timestamp=event.attrs['start'], sender_uid=uid,
                                                                         uid=event.attrs['uid'], point_id=point_pk,
                                                                         cot_id=cot_pk, **medevac.attrs))
                    casevac_pk = res.inserted_primary_key[0]

                    if zmist:
                        self.db.session.execute(insert(ZMIST).values(casevac_uid=event.attrs['uid'], **zmist.attrs))
                except exc.IntegrityError as e:
                    self.db.session.rollback()
                    self.db.session.execute(update(CasEvac).where(CasEvac.uid == event.attrs['uid'])
                                            .values(**medevac.attrs))

                    self.db.session.execute(
                        update(ZMIST).where(CasEvac.uid == event.attrs['uid']).values(**zmist.attrs))
                self.db.session.commit()

    def parse_video(self, event, cot_pk):
        video = event.find("__video")
        if video:
            logger.warning(video)
            self.logger.debug("Got video stream")
            connection_entry = video.find('ConnectionEntry')

            v = Video()
            v.network_timeout = connection_entry.attrs['networkTimeout']
            v.uid = connection_entry.attrs['uid']
            v.path = connection_entry.attrs['path']
            v.protocol = connection_entry.attrs['protocol']
            v.buffer_time = connection_entry.attrs['bufferTime']
            v.address = connection_entry.attrs['address']
            v.port = connection_entry.attrs['port']
            v.rover_port = connection_entry.attrs['roverPort']
            v.rtsp_reliable = connection_entry.attrs['rtspReliable']
            v.ignore_embedded_klv = (connection_entry.attrs['ignoreEmbeddedKLV'].lower() == 'true')
            v.alias = connection_entry.attrs['alias']
            v.cot_id = cot_pk
            v.generate_xml()

            with self.context:
                try:
                    self.db.session.add(v)
                    self.db.session.commit()
                    self.logger.debug("Added video")
                except exc.IntegrityError as e:
                    self.db.session.rollback()
                    self.db.session.execute(update(Video).where(Video.uid == connection_entry.attrs['uid'])
                                            .values(network_timeout=connection_entry.attrs['networkTimeout'],
                                                    path=connection_entry.attrs['uid'],
                                                    protocol=connection_entry.attrs['protocol'],
                                                    buffer_time=connection_entry.attrs['bufferTime'],
                                                    address=connection_entry.attrs['address'],
                                                    port=connection_entry.attrs['port'],
                                                    rover_port=connection_entry.attrs['roverPort'],
                                                    rtsp_reliable=connection_entry.attrs['rtspReliable'],
                                                    ignore_embedded_klv=(connection_entry.attrs['ignoreEmbeddedKLV'].lower() == 'true'),
                                                    alias=connection_entry.attrs['alias'],
                                                    xml=v.xml))

                    self.db.session.commit()

    def on_message(self, unused_channel, basic_deliver, properties, body):
        try:
            body = json.loads(body)
            soup = BeautifulSoup(body['cot'], 'xml')
            event = soup.find('event')
            if event:
                self.parse_device_info(body['uid'], soup, event)
                cot_pk = self.insert_cot(soup, event, body['uid'])
                point_pk = self.parse_point(event, body['uid'], cot_pk)
                self.parse_geochat(event, cot_pk, point_pk)
                self.parse_video(event, cot_pk)
                self.parse_groups(event, body['uid'])
                self.parse_alert(event, body['uid'], point_pk, cot_pk)
                self.parse_casevac(event, body['uid'], point_pk, cot_pk)
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
