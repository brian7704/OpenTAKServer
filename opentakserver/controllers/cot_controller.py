import base64
import json
import os
import re
import time
import traceback

import random
from xml.etree.ElementTree import Element, tostring

import bleach
import pika
from pika.channel import Channel
import sqlalchemy.exc
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import exc, insert, update
from bs4 import BeautifulSoup
from meshtastic import mqtt_pb2, mesh_pb2, portnums_pb2, BROADCAST_NUM
import unishox2

from opentakserver.functions import *
from opentakserver.models.Mission import Mission
from opentakserver.models.MissionChange import MissionChange, generate_mission_change_cot
from opentakserver.models.MissionUID import MissionUID

from opentakserver.proto import atak_pb2
from opentakserver.controllers.rabbitmq_client import RabbitMQClient
from opentakserver.extensions import socketio
from opentakserver.functions import datetime_from_iso8601_string
from opentakserver.models.Chatrooms import Chatroom
from opentakserver.models.Alert import Alert
from opentakserver.models.CasEvac import CasEvac
from opentakserver.models.ChatroomsUids import ChatroomsUids
from opentakserver.models.CoT import CoT
from opentakserver.models.EUD import EUD
from opentakserver.models.GeoChat import GeoChat
from opentakserver.models.Icon import Icon
from opentakserver.models.RBLine import RBLine
from opentakserver.models.Team import Team
from opentakserver.models.VideoStream import VideoStream
from opentakserver.models.ZMIST import ZMIST
from opentakserver.models.Point import Point
from opentakserver.models.Marker import Marker


class CoTController(RabbitMQClient):

    def on_channel_open(self, channel: Channel):
        self.rabbit_channel = channel
        self.rabbit_channel.queue_declare(queue='cot_controller')
        self.rabbit_channel.exchange_declare(exchange='cot_controller', exchange_type='fanout')
        self.rabbit_channel.queue_bind(exchange='cot_controller', queue='cot_controller')
        self.rabbit_channel.basic_consume(queue='cot_controller', on_message_callback=self.on_message, auto_ack=False)
        self.rabbit_channel.add_on_close_callback(self.on_close)

    def parse_device_info(self, uid, soup, event):
        link = event.find('link')
        fileshare = event.find('fileshare')

        # Don't parse server generated messages
        with self.context:
            if uid == self.context.app.config.get("OTS_NODE_ID"):
                return

        callsign = None
        phone_number = None
        takv = event.find('takv')

        # Only assume it's an EUD if it's got a <takv> tag
        if takv and uid and uid not in self.online_euds and not uid.endswith('ping'):
            device = takv.attrs['device'] if 'device' in takv.attrs else ""
            operating_system = takv.attrs['os'] if 'os' in takv.attrs else ""
            platform = takv.attrs['platform'] if 'platform' in takv.attrs else ""
            version = takv.attrs['version'] if 'version' in takv.attrs else ""

            contact = event.find('contact')
            if contact:
                if 'callsign' in contact.attrs:
                    callsign = contact.attrs['callsign']

                    if uid not in self.online_euds:
                        self.online_euds[uid] = {'cot': str(soup), 'callsign': callsign, 'last_meshtastic_publish': 0}

                    if callsign not in self.online_callsigns:
                        self.online_callsigns[callsign] = {'uid': uid, 'cot': soup, 'last_meshtastic_publish': 0}

                    # Declare a RabbitMQ Queue for this uid and join the 'dms' and 'cot' exchanges
                    if self.rabbit_channel and self.rabbit_channel.is_open and platform != "OpenTAK ICU" and platform != "Meshtastic":
                        self.rabbit_channel.queue_bind(exchange='dms', queue=uid, routing_key=uid)
                        self.rabbit_channel.queue_bind(exchange='chatrooms', queue=uid,
                                                       routing_key='All Chat Rooms')

                        for eud in self.online_euds:
                            self.rabbit_channel.basic_publish(exchange='dms',
                                                              routing_key=uid,
                                                              body=json.dumps(
                                                                  {'cot': str(self.online_euds[eud]['cot']),
                                                                   'uid': None}),
                                                              properties=pika.BasicProperties(expiration=self.context.app.config.get("OTS_RABBITMQ_TTL")))

                if 'phone' in contact.attrs and contact.attrs['phone']:
                    phone_number = contact.attrs['phone']

            with self.context:
                group = event.find('__group')
                team = Team()

                if group:
                    # Declare an exchange for each group and bind the callsign's queue
                    if self.rabbit_channel.is_open and group.attrs['name'] not in self.exchanges and platform != "Meshtastic":
                        self.logger.debug("Declaring exchange {}".format(group.attrs['name']))
                        self.rabbit_channel.exchange_declare(exchange=group.attrs['name'])
                        self.rabbit_channel.queue_bind(queue=uid, exchange='chatrooms',
                                                       routing_key=group.attrs['name'])
                        self.exchanges.append(group.attrs['name'])

                    team.name = bleach.clean(group.attrs['name'])

                    try:
                        chatroom = self.db.session.execute(self.db.session.query(Chatroom)
                                                           .filter(Chatroom.name == team.name)).first()[0]
                        team.chatroom_id = chatroom.id
                    except TypeError:
                        chatroom = None

                    try:
                        self.db.session.add(team)
                        self.db.session.commit()
                    except sqlalchemy.exc.IntegrityError:
                        self.db.session.rollback()
                        team = self.db.session.execute(self.db.session.query(Team)
                                                       .filter(Team.name == group.attrs['name'])).first()[0]
                        if not team.chatroom_id and chatroom:
                            team.chatroom_id = chatroom.id
                            self.db.session.execute(update(Team).filter(Team.name).values(chatroom_id=chatroom.id))

                try:
                    eud = self.db.session.execute(self.db.session.query(EUD).filter_by(uid=uid)).first()[0]
                except:
                    eud = EUD()

                eud.uid = uid
                if callsign:
                    eud.callsign = callsign
                if device:
                    eud.device = device

                eud.os = operating_system
                eud.platform = platform
                eud.version = version
                eud.phone_number = phone_number
                eud.last_event_time = datetime_from_iso8601_string(event.attrs['start'])
                eud.last_status = 'Connected'

                # Set a Meshtastic ID for TAK EUDs to be identified by in the Meshtastic network
                if not eud.meshtastic_id and eud.platform != "Meshtastic":
                    meshtastic_id = '{:x}'.format(int.from_bytes(os.urandom(4), 'big'))
                    while len(meshtastic_id) < 8:
                        meshtastic_id = "0" + meshtastic_id
                    eud.meshtastic_id = int(meshtastic_id, 16)
                elif not eud.meshtastic_id and eud.platform == "Meshtastic":
                    try:
                        eud.meshtastic_id = int(takv.attrs['meshtastic_id'], 16)
                    except:
                        meshtastic_id = '{:x}'.format(int.from_bytes(os.urandom(4), 'big'))
                        while len(meshtastic_id) < 8:
                            meshtastic_id = "0" + meshtastic_id
                        eud.meshtastic_id = int(meshtastic_id, 16)

                # Get the Meshtastic device's mac address or generate a random one for TAK EUDs
                if takv and 'macaddr' in takv.attrs:
                    eud.meshtastic_macaddr = takv.attrs['macaddr']
                else:
                    eud.meshtastic_macaddr = base64.b64encode(os.urandom(6)).decode('ascii')

                if group:
                    eud.team_id = team.id
                    eud.team_role = bleach.clean(group.attrs['role'])

                try:
                    self.db.session.add(eud)
                    self.db.session.commit()
                except sqlalchemy.exc.IntegrityError:
                    self.db.session.rollback()
                    self.db.session.execute(update(EUD).where(EUD.uid == eud.uid).values(**eud.serialize()))
                    self.db.session.commit()

                if self.context.app.config.get("OTS_ENABLE_MESHTASTIC") and eud.platform != "Meshtastic":
                    user_info = mesh_pb2.User()
                    setattr(user_info, "id", "!{:x}".format(eud.meshtastic_id))
                    user_info.long_name = eud.callsign
                    # Use the last 4 characters of the UID as the short name
                    user_info.short_name = eud.uid[-4:]
                    user_info.hw_model = mesh_pb2.HardwareModel.PRIVATE_HW

                    node_info = mesh_pb2.NodeInfo()
                    node_info.user.CopyFrom(user_info)

                    encoded_message = mesh_pb2.Data()
                    encoded_message.portnum = portnums_pb2.NODEINFO_APP
                    user_info_bytes = user_info.SerializeToString()
                    encoded_message.payload = user_info_bytes

                    self.publish_to_meshtastic(self.get_protobuf(encoded_message, from_id=eud.meshtastic_id))

                socketio.emit('eud', eud.to_json(), namespace='/socket.io')

        # Update the CoT stored in memory which contains the new stale time
        elif takv:
            self.online_euds[uid]['cot'] = str(soup)

    def insert_cot(self, soup, event, uid):
        try:
            sender_callsign = self.online_euds[uid]['callsign']
            sender_uid = uid
        except:
            sender_callsign = 'server'
            sender_uid = None

        start = datetime_from_iso8601_string(event.attrs['start'])
        stale = datetime_from_iso8601_string(event.attrs['stale'])
        timestamp = datetime_from_iso8601_string(event.attrs['time'])

        # Assign CoT to a data sync mission
        dest = event.find("dest")
        mission_name = None
        if dest and 'mission' in dest.attrs:
            mission_name = dest.attrs['mission']

        with self.context:
            res = self.db.session.execute(insert(CoT).values(
                how=event.attrs['how'], type=event.attrs['type'], sender_callsign=sender_callsign,
                sender_uid=sender_uid, timestamp=timestamp, xml=str(soup), start=start, stale=stale, mission_name=mission_name,
                uid=event.attrs['uid']
            ))

            try:
                self.db.session.commit()
                return res.inserted_primary_key[0]
            except sqlalchemy.exc.IntegrityError:
                # When using MySQL it will raise IntegrityError when a new EUD connects and it doesn't exist yet in the EUDs table
                # We'll ignore this error and not insert this CoT so the EUD table can be populated
                return None

    def parse_point(self, event, uid, cot_id):
        # hae = Height above the WGS ellipsoid in meters
        # ce = Circular 1-sigma or a circular area about the location in meters
        # le = Linear 1-sigma error or an altitude range about the location in meters
        point = event.find('point')
        if point and not point.attrs['lat'].startswith('999'):
            p = Point()
            p.uid = event.attrs['uid']
            p.device_uid = uid
            p.ce = point.attrs['ce']
            p.hae = point.attrs['hae']
            p.le = point.attrs['le']
            p.latitude = float(point.attrs['lat'])
            p.longitude = float(point.attrs['lon'])
            p.timestamp = datetime_from_iso8601_string(event.attrs['time'])
            p.cot_id = cot_id

            # We only really care about the rest of the data if there's a valid lat/lon
            if p.latitude == 0 and p.longitude == 0:
                return None

            track = event.find('track')
            if track:
                if 'course' in track.attrs and track.attrs['course'] != "9999999.0":
                    p.course = track.attrs['course']
                else:
                    p.course = 0

                if 'speed' in track.attrs and track.attrs['speed'] != "9999999.0":
                    p.speed = track.attrs['speed']
                else:
                    p.speed = 0

            # For TAK ICU and OpenTAK ICU CoT's with bearing from the compass
            sensor = event.find('sensor')
            if sensor:
                if 'azimuth' in sensor.attrs:
                    p.azimuth = sensor.attrs['azimuth']
                # Camera's field of view
                if 'fov' in sensor.attrs:
                    p.fov = sensor.attrs['fov']

            precision_location = event.find('precisionlocation')
            if precision_location and 'geolocationsrc' in precision_location.attrs:
                p.location_source = precision_location.attrs['geolocationsrc']
            elif precision_location and 'altsrc' in precision_location.attrs:
                p.location_source = precision_location.attrs['altsrc']
            elif event.attrs['how'] == 'm-g':
                p.location_source = 'GPS'

            status = event.find('status')
            if status:
                if 'battery' in status.attrs:
                    p.battery = status.attrs['battery']

            with self.context:
                res = self.db.session.execute(insert(Point).values(
                    uid=p.uid, device_uid=p.device_uid, ce=p.ce, hae=p.hae, le=p.le, latitude=p.latitude,
                    longitude=p.longitude, timestamp=p.timestamp, cot_id=cot_id, location_source=p.location_source,
                    course=p.course, speed=p.speed, battery=p.battery, fov=p.fov, azimuth=p.azimuth)
                )

                # iTAK sucks. Instead of sending mission CoTs with a <dest mission="mission_name"> tag, it sends a normal CoT and
                # makes a POST to /Marti/api/missions/mission_name/contents. The POST happens faster than the CoT can be received and parsed,
                # so we're left with a row in the mission_uids table without most of the details that come from the CoT. Fortunately
                # the mission_uids.uid field corresponds to the CoT's event UID, so the row in mission_uids can be updated here.
                usericon = event.find('usericon')
                color = event.find('color')
                contact = event.find('contact')

                iconset_path = None
                if usericon and 'iconsetpath' in usericon.attrs:
                    iconset_path = usericon.attrs['iconsetpath']
                elif usericon and 'iconsetPath' in usericon.attrs:
                    iconset_path = usericon.attrs['iconsetPath']

                cot_color = None
                if color and 'argb' in color.attrs:
                    cot_color = color.attrs['argb']
                if color and 'value' in color.attrs:
                    cot_color = color.attrs['value']

                callsign = None
                if contact and 'callsign' in contact.attrs:
                    callsign = contact.attrs['callsign']

                self.db.session.execute(update(MissionUID).where(MissionUID.uid == event.attrs['uid']).values(
                    cot_type=event.attrs['type'], latitude=p.latitude, longitude=p.longitude, iconset_path=iconset_path,
                    color=cot_color, callsign=callsign
                ))

                self.db.session.commit()
                # Get the point from the DB with its related CoT
                p = self.db.session.execute(
                    self.db.session.query(Point).filter(Point.id == res.inserted_primary_key[0])).first()[0]

                # This CoT is a position update for an EUD. Send it to socketio clients so it can be seen on the UI map
                # OpenTAK ICU position updates don't include the <takv> tag, but we still want to send the updated position
                # to the UI's map
                if event.find('takv') or event.find("__video"):
                    socketio.emit('point', p.to_json(), namespace='/socket.io')

                now = time.time()
                if uid in self.online_euds:
                    can_transmit = (now - self.online_euds[uid]['last_meshtastic_publish'] >= self.context.app.config.get("OTS_MESHTASTIC_PUBLISH_INTERVAL"))
                else:
                    can_transmit = False

                if self.context.app.config.get("OTS_ENABLE_MESHTASTIC") and can_transmit:
                    self.logger.debug("publishing position to mesh")
                    try:
                        self.online_euds[uid]['last_meshtastic_publish'] = now
                        eud = self.db.session.execute(self.db.session.query(EUD).filter_by(uid=uid)).first()[0]

                        if eud.platform != "Meshtastic":
                            mesh_user = mesh_pb2.User()
                            setattr(mesh_user, "id", eud.uid)
                            mesh_user.hw_model = mesh_pb2.HardwareModel.PRIVATE_HW
                            mesh_user.short_name = p.device_uid[-4:]

                            contact = event.find('contact')
                            if contact:
                                mesh_user.long_name = contact.attrs['callsign']

                            position = mesh_pb2.Position()
                            position.latitude_i = int(p.latitude / .0000001)
                            position.longitude_i = int(p.longitude / .0000001)
                            position.altitude = int(p.hae)
                            position.time = int(time.mktime(p.timestamp.timetuple()))
                            position.ground_track = int(p.course) if p.course else 0
                            position.ground_speed = int(p.speed) if p.speed and p.speed >= 0 else 0
                            position.seq_number = 1
                            position.precision_bits = 32

                            node_info = mesh_pb2.NodeInfo()
                            node_info.user.CopyFrom(mesh_user)
                            node_info.position.CopyFrom(position)

                            encoded_message = mesh_pb2.Data()
                            encoded_message.portnum = portnums_pb2.POSITION_APP
                            encoded_message.payload = position.SerializeToString()

                            self.publish_to_meshtastic(self.get_protobuf(encoded_message, uid=p.device_uid))

                            tak_packet = atak_pb2.TAKPacket()
                            tak_packet.is_compressed = True
                            tak_packet.contact.device_callsign, size = unishox2.compress(eud.uid)
                            tak_packet.contact.callsign, size = unishox2.compress(eud.callsign)
                            tak_packet.group.team = eud.team.name.replace(" ", "_") if eud.team else "Cyan"
                            tak_packet.group.role = eud.team_role.replace(" ", "") if eud.team_role else "TeamMember"
                            tak_packet.status.battery = int(p.battery) if p.battery else 0
                            tak_packet.pli.latitude_i = int(p.latitude / .0000001)
                            tak_packet.pli.longitude_i = int(p.longitude / .0000001)
                            tak_packet.pli.altitude = int(p.hae) if p.hae else 0
                            tak_packet.pli.speed = int(p.speed) if p.speed else 0
                            tak_packet.pli.course = int(p.course) if p.course else 0

                            encoded_message = mesh_pb2.Data()
                            encoded_message.portnum = portnums_pb2.ATAK_PLUGIN
                            encoded_message.payload = tak_packet.SerializeToString()

                            self.publish_to_meshtastic(self.get_protobuf(encoded_message, uid=eud.uid))
                    except BaseException as e:
                        self.logger.error(f"Failed to send publish message to mesh: {e}")
                        self.logger.debug(traceback.format_exc())

                return res.inserted_primary_key[0]

    def get_protobuf(self, payload, uid=None, from_id=None, to_id=BROADCAST_NUM, channel_id="LongFast"):
        if uid and not from_id:
            try:
                eud = self.db.session.execute(self.db.session.query(EUD).filter_by(uid=uid)).first()[0]
                from_id = eud.meshtastic_id
            except:
                self.logger.error("Failed to find EUD {}, using random Meshtastic ID".format(uid))
                self.logger.debug(traceback.format_exc())
                from_id = random.getrandbits(32)

        message_id = random.getrandbits(32)
        mesh_packet = mesh_pb2.MeshPacket()
        mesh_packet.id = message_id

        try:
            setattr(mesh_packet, "from", int(from_id, 16))
        except BaseException as e:
            setattr(mesh_packet, "from", from_id)
        mesh_packet.to = to_id
        mesh_packet.want_ack = False
        mesh_packet.hop_limit = 3
        mesh_packet.decoded.CopyFrom(payload)

        service_envelope = mqtt_pb2.ServiceEnvelope()
        service_envelope.packet.CopyFrom(mesh_packet)
        service_envelope.channel_id = channel_id
        service_envelope.gateway_id = "OpenTAKServer"

        return service_envelope

    def parse_geochat(self, event, cot_id, point_pk):
        chat = event.find('__chat')
        if chat:
            chat_group = event.find('chatgrp')
            remarks = event.find('remarks')

            # Sometimes WinTAK seems to send GeoChat CoTs without remarks
            if not remarks:
                return

            sender_callsign = chat.attrs['senderCallsign']
            if sender_callsign not in self.online_callsigns:
                self.online_callsigns[sender_callsign] = {'uid': chat_group.attrs['uid0'], 'cot': "", 'last_meshtastic_publish': 0}
            if chat_group.attrs['uid0'] not in self.online_euds:
                self.online_euds[chat_group.attrs['uid0']] = {'cot': "", 'callsign': sender_callsign, 'last_meshtastic_publish': 0}

            chatroom = Chatroom()

            chatroom.name = chat.attrs['chatroom']
            chatroom.id = chat.attrs['id']
            chatroom.parent = chat.attrs['parent'] if 'parent' in chat.attrs else None

            with self.context:
                try:
                    self.db.session.add(chatroom)
                    self.db.session.commit()
                except exc.IntegrityError:
                    self.db.session.rollback()

            geochat = GeoChat()

            geochat.uid = event.attrs['uid']
            geochat.chatroom_id = chat.attrs['id']
            geochat.sender_uid = chat_group.attrs['uid0']
            geochat.remarks = remarks.text
            geochat.timestamp = datetime_from_iso8601_string(remarks.attrs['time'])
            geochat.point_id = point_pk
            geochat.cot_id = cot_id

            if self.context.app.config.get("OTS_ENABLE_MESHTASTIC"):
                try:
                    with self.context:
                        from_eud = self.db.session.execute(self.db.session.query(EUD).filter_by(uid=geochat.sender_uid)).first()[0]

                        tak_packet = atak_pb2.TAKPacket()
                        tak_packet.contact.device_callsign, size = unishox2.compress(geochat.sender_uid)
                        if geochat.sender_uid in self.online_euds:
                            tak_packet.contact.callsign, size = unishox2.compress(self.online_euds[geochat.sender_uid]['callsign'])
                        tak_packet.chat.message, size = unishox2.compress(remarks.text)
                        tak_packet.group.team = from_eud.team.name.replace(" ", "_")
                        tak_packet.group.role = from_eud.team_role.replace(" ", "")
                        tak_packet.is_compressed = True

                        send_meshtastic_text = False
                        if chat.attrs['chatroom'] in self.online_callsigns:
                            # This is a DM
                            to = self.online_callsigns[chat.attrs['chatroom']]['uid']
                            try:
                                # DM to a Meshtastic device
                                to_id = int(to, 16)
                                send_meshtastic_text = True
                            except:
                                # DM to an EUD running the Meshtastic ATAK Plugin
                                to_id = BROADCAST_NUM

                            tak_packet.chat.to, size = unishox2.compress(to)
                        else:
                            # This goes to a chat room
                            to = chat.attrs['chatroom']
                            to_id = BROADCAST_NUM
                            tak_packet.chat.to, size = unishox2.compress(to)

                            # By only sending a Meshtastic Data packet and not a TAK Packet, both the Meshtastic app
                            # and the Meshtastic ATAK plugin will receive the message
                            send_meshtastic_text = (to == "All Chat Rooms")

                        if send_meshtastic_text:
                            self.logger.debug("Publishing text to Meshtastic devices")
                            # Publish again for Meshtastic devices without the ATAK Plugin
                            encoded_message = mesh_pb2.Data()
                            encoded_message.portnum = portnums_pb2.TEXT_MESSAGE_APP
                            encoded_message.payload = remarks.text.encode("utf-8")
                            self.publish_to_meshtastic(self.get_protobuf(encoded_message, to_id=to_id, from_id=from_eud.meshtastic_id))
                        else:
                            # Publish once for EUDs using the Meshtastic ATAK Plugin
                            encoded_message = mesh_pb2.Data()
                            encoded_message.portnum = portnums_pb2.ATAK_PLUGIN
                            encoded_message.payload = tak_packet.SerializeToString()

                            self.publish_to_meshtastic(
                                self.get_protobuf(encoded_message, from_id=from_eud.meshtastic_id, to_id=to_id))

                except BaseException as e:
                    self.logger.error("Failed to publish MQTT message: {}".format(e))
                    self.logger.debug(traceback.format_exc())

            with self.context:
                try:

                    self.db.session.add(geochat)
                    self.db.session.commit()
                except exc.IntegrityError:
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
                            self.logger.debug(
                                "add {} to chatroom {}".format(chatroom_uid.uid, chatroom_uid.chatroom_id))
                        except exc.IntegrityError:
                            self.db.session.rollback()

    def parse_video(self, event, cot_pk):
        video = event.find("__video")
        if video:
            self.logger.debug("Got video stream")
            connection_entry = video.find('ConnectionEntry')
            if not connection_entry:
                return

            path = connection_entry.attrs['path']
            if path.startswith("/"):
                path = path[1:]

            v = VideoStream()
            v.network_timeout = connection_entry.attrs['networkTimeout']
            v.uid = connection_entry.attrs['uid']
            v.path = path
            v.protocol = connection_entry.attrs['protocol']
            v.buffer_time = connection_entry.attrs['bufferTime']
            v.port = connection_entry.attrs['port']
            v.rover_port = connection_entry.attrs['roverPort']
            v.rtsp_reliable = connection_entry.attrs['rtspReliable']
            v.ignore_embedded_klv = (connection_entry.attrs['ignoreEmbeddedKLV'].lower() == 'true')
            v.alias = connection_entry.attrs['alias']
            v.cot_id = cot_pk
            v.generate_xml(connection_entry.attrs['address'])

            with self.context:
                try:
                    self.db.session.add(v)
                    self.db.session.commit()
                    self.logger.debug("Added video")
                except exc.IntegrityError as e:
                    self.db.session.rollback()
                    self.db.session.execute(update(VideoStream).where(VideoStream.uid == connection_entry.attrs['uid'])
                                            .values(network_timeout=connection_entry.attrs['networkTimeout'],
                                                    protocol=connection_entry.attrs['protocol'],
                                                    buffer_time=connection_entry.attrs['bufferTime'],
                                                    # address=connection_entry.attrs['address'],
                                                    port=connection_entry.attrs['port'],
                                                    rover_port=connection_entry.attrs['roverPort'],
                                                    rtsp_reliable=connection_entry.attrs['rtspReliable'],
                                                    ignore_embedded_klv=(connection_entry.attrs[
                                                                             'ignoreEmbeddedKLV'].lower() == 'true'),
                                                    alias=connection_entry.attrs['alias'],
                                                    xml=v.xml))

                    self.db.session.commit()

    def parse_alert(self, event, uid, point_pk, cot_pk):
        emergency = event.find('emergency')
        if emergency:
            if 'type' in emergency.attrs:
                emergency_type = emergency.attrs['type']
                alert = Alert()
                alert.sender_uid = uid
                alert.uid = event.attrs['uid']
                alert.start_time = datetime_from_iso8601_string(event.attrs['start'])
                alert.point_id = point_pk
                alert.alert_type = emergency_type
                alert.cot_id = cot_pk

                with self.context:
                    self.db.session.add(alert)
                    self.db.session.commit()
                    socketio.emit('alert', alert.to_json(), namespace='/socket.io')
            elif 'cancel' in emergency.attrs:
                with self.context:
                    try:
                        alert = self.db.session.execute(
                            Alert.query.filter(Alert.cancel_time == None, Alert.sender_uid == uid).order_by(
                                Alert.start_time.desc())).first()[0]
                        alert.cancel_time = datetime_from_iso8601_string(event.attrs['start'])
                        self.db.session.commit()
                        socketio.emit('alert', alert.to_json(), namespace='/socket.io')
                    except BaseException as e:
                        self.logger.error("Failed to set alert cancel time: {}".format(e))
                        self.logger.debug(traceback.format_exc())

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
                    self.db.session.execute(
                        insert(CasEvac).values(timestamp=datetime_from_iso8601_string(event.attrs['start']),
                                               sender_uid=uid, uid=event.attrs['uid'],
                                               point_id=point_pk, cot_id=cot_pk,
                                               **medevac.attrs))

                    if zmist:
                        self.db.session.execute(insert(ZMIST).values(casevac_uid=event.attrs['uid'], **zmist.attrs))
                except exc.IntegrityError as e:
                    self.db.session.rollback()
                    self.db.session.execute(update(CasEvac).where(CasEvac.uid == event.attrs['uid'])
                                            .values(**medevac.attrs))

                    if zmist:
                        self.db.session.execute(
                            update(ZMIST).where(CasEvac.uid == event.attrs['uid']).values(**zmist.attrs))
                self.db.session.commit()

                try:
                    casevac: CasEvac = self.db.session.execute(self.db.session.query(CasEvac).filter_by(uid=event.attrs['uid'])).first()[0]
                    socketio.emit('casevac', casevac.to_json(), namespace='/socket.io')
                except BaseException as e:
                    self.logger.error(f"Failed to emit CasEvac: {e}")
                    self.logger.debug(traceback.format_exc())

    def parse_marker(self, event, uid, point_pk, cot_pk):
        if ((re.match("^a-[f|h|u|p|a|n|s|j|k]-[Z|P|A|G|S|U|F]", event.attrs['type']) or
             # Spot map
             re.match("^b-m-p", event.attrs['type'])) and
                # Don't worry about EUD location updates
                not event.find('takv') and
                # Ignore video streams from sources like OpenTAK ICU
                event.attrs['type'] != 'b-m-p-s-p-loc'):

            try:
                marker = Marker()
                marker.uid = event.attrs['uid']
                marker.affiliation = get_affiliation(event.attrs['type'])
                marker.battle_dimension = get_battle_dimension(event.attrs['type'])
                marker.mil_std_2525c = cot_type_to_2525c(event.attrs['type'])

                detail = event.find('detail')
                icon = None

                if detail:
                    for tag in detail.find_all():
                        if 'readiness' in tag.attrs:
                            marker.readiness = tag.attrs['readiness'] == "true"
                        if 'argb' in tag.attrs:
                            marker.argb = tag.attrs['argb']
                            marker.color_hex = marker.color_to_hex()
                        if 'callsign' in tag.attrs:
                            marker.callsign = tag.attrs['callsign']
                        if 'iconsetpath' in tag.attrs:
                            marker.iconset_path = tag.attrs['iconsetpath']
                            if marker.iconset_path.lower().endswith('.png'):
                                with self.context:
                                    filename = marker.iconset_path.split("/")[-1]

                                    try:
                                        icon = self.db.session.execute(self.db.session.query(Icon)
                                                                       .filter(Icon.filename == filename)).first()[0]
                                        marker.icon_id = icon.id
                                    except:
                                        icon = self.db.session.execute(self.db.session.query(Icon)
                                        .filter(
                                            Icon.filename == 'marker-icon.png')).first()[0]
                                        marker.icon_id = icon.id
                            elif not marker.mil_std_2525c:
                                with self.context:
                                    icon = self.db.session.execute(self.db.session.query(Icon)
                                                                   .filter(Icon.filename == 'marker-icon.png')).first()[
                                        0]
                                    marker.icon_id = icon.id

                        if 'altsrc' in tag.attrs:
                            marker.location_source = tag.attrs['altsrc']

                link = event.find('link')
                if link:
                    marker.parent_callsign = link.attrs['parent_callsign'] if 'parent_callsign' in link.attrs else None
                    marker.production_time = link.attrs['production_time'] if 'production_time' in link.attrs else iso8601_string_from_datetime(datetime.now())
                    marker.relation = link.attrs['relation'] if 'relation' in link.attrs else None
                    marker.relation_type = link.attrs['relation_type'] if 'relation_type' in link.attrs else None
                    marker.parent_uid = link.attrs['uid'] if 'uid' in link.attrs else None
                else:
                    marker.production_time = iso8601_string_from_datetime(datetime.now())

                marker.point_id = point_pk
                marker.cot_id = cot_pk

                with self.context:
                    try:
                        self.db.session.add(marker)
                        self.db.session.commit()
                        self.logger.debug('added marker')
                    except exc.IntegrityError:
                        self.db.session.rollback()
                        self.db.session.execute(
                            update(Marker).where(Marker.uid == marker.uid).values(point_id=marker.point_id,
                                                                                  icon_id=marker.icon_id,
                                                                                  **marker.serialize()))
                        self.db.session.commit()
                        self.logger.debug('updated marker')
                        marker = self.db.session.execute(self.db.session.query(Marker)
                                                         .filter(Marker.uid == marker.uid)).first()[0]

                    socketio.emit('marker', marker.to_json(), namespace='/socket.io')

            except BaseException as e:
                self.logger.error("Failed to parse marker: {}".format(e))
                self.logger.debug(traceback.format_exc())

    def parse_rbline(self, event, uid, point_pk, cot_pk):
        if re.match("^u-rb", event.attrs['type']):
            self.logger.debug("Got an R&B line")
            rb_line = RBLine()

            detail = event.find('detail')
            if detail:
                rb_line.uid = event.attrs['uid']
                rb_line.sender_uid = uid
                rb_line.timestamp = datetime_from_iso8601_string(event.attrs['start'])
                rb_line.point_id = point_pk
                rb_line.cot_id = cot_pk

                for tag in detail:
                    if tag.name == 'range':
                        rb_line.range = tag.attrs['value']
                    if tag.name == 'bearing':
                        rb_line.bearing = tag.attrs['value']
                    if tag.name == 'inclination':
                        rb_line.inclination = tag.attrs['value']
                    if tag.name == 'anchorUID':
                        rb_line.anchor_uid = tag.attrs['value']
                    if tag.name == 'rangeUnits':
                        rb_line.range_units = tag.attrs['value']
                    if tag.name == 'bearingUnits':
                        rb_line.bearing_units = tag.attrs['value']
                    if tag.name == 'northRef':
                        rb_line.north_ref = tag.attrs['value']
                    if tag.name == 'color':
                        rb_line.color = tag.attrs['value']
                        rb_line.color_hex = rb_line.color_to_hex()
                    if tag.name == 'contact':
                        rb_line.callsign = tag.attrs['callsign']
                    if tag.name == 'strokeColor':
                        rb_line.stroke_color = tag.attrs['value']
                    if tag.name == 'strokeWeight':
                        rb_line.stroke_weight = tag.attrs['value']
                    if tag.name == 'labels_on':
                        rb_line.labels_on = (tag.attrs['value'] == 'true')

                with self.context:

                    start_point = \
                        self.db.session.execute(self.db.session.query(Point).filter(Point.id == point_pk)).first()[0]
                    end_point = rb_line.calc_end_point(start_point)
                    rb_line.end_latitude = end_point['latitude']
                    rb_line.end_longitude = end_point['longitude']

                    try:
                        self.db.session.add(rb_line)
                        self.db.session.commit()
                        self.logger.debug("Inserted new R&B line: {}".format(rb_line.uid))
                    except exc.IntegrityError:
                        self.db.session.rollback()
                        self.db.session.execute(update(RBLine).where(RBLine.uid == rb_line.uid)
                                                .values(**rb_line.serialize()))
                        self.db.session.commit()
                        self.logger.debug('Updated R&B line: {}'.format(rb_line.uid))

                    rb_line.point = start_point
                    socketio.emit("rb_line", rb_line.to_json(), namespace='/socket.io')

    def rabbitmq_routing(self, event, data):
        # RabbitMQ Routing
        chat = event.find("__chat")
        destinations = event.find_all('dest')

        if chat and 'chatroom' in chat.attrs and chat.attrs['chatroom'] == 'All Chat Rooms':
            self.rabbit_channel.basic_publish(exchange='chatrooms', routing_key='All Chat Rooms', body=json.dumps(data))

        elif destinations:
            for destination in destinations:
                uid = None
                # ATAK and WinTAK use callsign, iTAK uses uid
                if 'callsign' in destination.attrs and destination.attrs['callsign'] in self.online_callsigns:
                    uid = self.online_callsigns[destination.attrs['callsign']]['uid']
                elif 'uid' in destination.attrs:
                    uid = destination.attrs['uid']

                if uid:
                    self.rabbit_channel.basic_publish(exchange='dms',
                                                      routing_key=uid,
                                                      body=json.dumps(data))

                # For data sync missions
                if 'mission' in destination.attrs:
                    with self.context:
                        mission = self.db.session.execute(
                            self.db.session.query(Mission).filter_by(name=destination.attrs['mission'])).first()

                        if not mission:
                            self.logger.error(f"No such mission found: {destination.attrs['mission']}")
                            return

                        mission = mission[0]
                        self.rabbit_channel.basic_publish("missions", routing_key=f"missions.{destination.attrs['mission']}", body=json.dumps(data))

                        mission_uid = self.db.session.execute(self.db.session.query(MissionUID).filter_by(uid=event.attrs['uid'])).first()

                        if not mission_uid:
                            mission_change = MissionChange()
                            mission_change.isFederatedChange = False
                            mission_change.change_type = MissionChange.ADD_CONTENT
                            mission_change.mission_name = destination.attrs['mission']
                            mission_change.timestamp = datetime_from_iso8601_string(event.attrs['start'])
                            mission_change.creator_uid = data['uid']
                            mission_change.server_time = datetime_from_iso8601_string(event.attrs['start'])
                            mission_change.mission_uid = event.attrs['uid']

                            change_pk = self.db.session.execute(insert(MissionChange).values(**mission_change.serialize()))
                            self.db.session.commit()

                            body = {'uid': uid, 'cot': tostring(generate_mission_change_cot(destination.attrs['mission'], mission, mission_change, cot_event=event)).decode('utf-8')}
                            self.rabbit_channel.basic_publish("missions", routing_key=f"missions.{mission.name}", body=json.dumps(body))

                            mission_uid = MissionUID()
                            mission_uid.uid = event.attrs['uid']
                            mission_uid.mission_name = destination.attrs['mission']
                            mission_uid.timestamp = datetime_from_iso8601_string(event.attrs['start'])
                            mission_uid.creator_uid = uid
                            mission_uid.cot_type = event.attrs['type']
                            mission_uid.mission_change_id = change_pk.inserted_primary_key[0]

                            color = event.find('color')
                            icon = event.find('usericon')
                            point = event.find('point')
                            contact = event.find('contact')

                            if color and 'argb' in color.attrs:
                                mission_uid.color = color.attrs['argb']
                            elif color and 'value' in color.attrs:
                                mission_uid.color = color.attrs['value']
                            if icon:
                                mission_uid.iconset_path = icon['iconsetpath']
                            if point:
                                mission_uid.latitude = float(point.attrs['lat'])
                                mission_uid.longitude = float(point.attrs['lon'])
                            if contact:
                                mission_uid.callsign = contact.attrs['callsign']

                            try:
                                self.db.session.add(mission_uid)
                                self.db.session.commit()
                            except sqlalchemy.exc.IntegrityError:
                                self.db.session.rollback()
                                self.db.session.execute(update(MissionUID).values(**mission_uid.serialize()))

        # If no destination or callsign is specified, broadcast to all TAK clients
        elif self.rabbit_channel and self.rabbit_channel.is_open:
            self.rabbit_channel.basic_publish(exchange='cot', routing_key="", body=json.dumps(data),
                                              properties=pika.BasicProperties(expiration=self.context.app.config.get("OTS_RABBITMQ_TTL")))

        # Do nothing because the RabbitMQ channel hasn't opened yet or has closed
        else:
            self.logger.debug("Not publishing, channel closed")

    def publish_to_meshtastic(self, body):
        for channel in self.context.app.config.get("OTS_MESHTASTIC_DOWNLINK_CHANNELS"):
            body.channel_id = channel
            routing_key = "{}.2.e.{}.outgoing".format(self.context.app.config.get("OTS_MESHTASTIC_TOPIC"), channel)
            self.rabbit_channel.basic_publish(exchange='amq.topic', routing_key=routing_key, body=body.SerializeToString(),
                                              properties=pika.BasicProperties(expiration=self.context.app.config.get("OTS_RABBITMQ_TTL")))
            self.logger.debug("Published message to " + routing_key)

    def on_message(self, unused_channel, basic_deliver, properties, body):
        try:
            body = json.loads(body)
            soup = BeautifulSoup(body['cot'], 'xml')
            event: BeautifulSoup = soup.find('event')

            uid = body['uid'] or event.attrs['uid']
            if uid == self.context.app.config['OTS_NODE_ID']:
                uid = None

            if event:
                self.parse_device_info(uid, soup, event)
                cot_pk = self.insert_cot(soup, event, uid)
                point_pk = self.parse_point(event, uid, cot_pk)
                self.parse_geochat(event, cot_pk, point_pk)
                self.parse_video(event, cot_pk)
                self.parse_alert(event, uid, point_pk, cot_pk)
                self.parse_casevac(event, uid, point_pk, cot_pk)
                self.parse_marker(event, uid, point_pk, cot_pk)
                self.parse_rbline(event, uid, point_pk, cot_pk)
                self.rabbit_channel.basic_ack(delivery_tag=basic_deliver.delivery_tag)
                self.rabbitmq_routing(event, body)

                # EUD went offline
                if event.attrs['type'] == 't-x-d-d':

                    try:
                        with self.context:
                            eud = self.db.session.execute(self.db.session.query(EUD).filter_by(uid=uid)).first()
                            if eud:
                                eud = eud[0]
                                eud.last_event_time = datetime_from_iso8601_string(event.attrs['start'])
                                eud.last_status = 'Disconnected'
                                self.db.session.commit()
                                self.logger.debug("Updated {}".format(uid))
                                eud_json = eud.to_json()
                                # The first time an EUD connects but doesn't have a location.
                                # Tells the UI what kind of EUD this is, ie ATAK/WinTAK/iTAK or OpenTAK ICU
                                if not eud_json['last_point']:
                                    eud_json['type'] = event.attrs['type']
                                socketio.emit('eud', eud.to_json(), namespace='/socket.io')
                    except BaseException as e:
                        self.logger.error("Failed to update EUD: {}".format(e))
                        self.logger.debug(traceback.format_exc())

                    if uid in self.online_euds.keys():
                        self.online_euds.pop(uid)
        except BaseException as e:
            self.logger.error(f"Failed to parse CoT: {e}")
            self.logger.debug(traceback.format_exc())
            self.rabbit_channel.basic_nack(delivery_tag=basic_deliver.delivery_tag, requeue=False)
