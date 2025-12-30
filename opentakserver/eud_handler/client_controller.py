import base64
import json
import os
import random
import re
import socket
import traceback
import uuid
from xml.etree.ElementTree import Element, SubElement, tostring, fromstring, ParseError
import datetime
from threading import Thread

import bleach
import sqlalchemy
from flask import Flask
from flask_ldap3_login import AuthenticationResponseStatus
from flask_security import verify_password

from bs4 import BeautifulSoup
import pika
from meshtastic import mesh_pb2, portnums_pb2, BROADCAST_NUM, mqtt_pb2
from pika.channel import Channel
from sqlalchemy import select, update, insert

from opentakserver.extensions import db, ldap_manager, logger
from opentakserver.functions import datetime_from_iso8601_string, iso8601_string_from_datetime
from opentakserver.models.Chatrooms import Chatroom
from opentakserver.models.EUD import EUD
from opentakserver.models.Group import Group
from opentakserver.models.GroupUser import GroupUser
from opentakserver.models.Meshtastic import MeshtasticChannel
from opentakserver.models.Mission import Mission
from opentakserver.models.MissionChange import MissionChange, generate_mission_change_cot
from opentakserver.models.MissionUID import MissionUID
from opentakserver.models.Team import Team


class ClientController(Thread):
    def __init__(self, address: str, port: int, sock: socket, logger, app: Flask, is_ssl: bool):
        Thread.__init__(self)
        self.address = address
        self.port = port
        self.sock = sock
        self.logger = logger
        self.shutdown = False
        self.sock.settimeout(1.0)
        self.app = app
        self.db = db
        self.is_ssl = is_ssl
        self.bound_queues = []
        self.eud = None

        self.user = None

        # Device attributes
        self.uid = None
        self.device = None
        self.os = None
        self.platform = None
        self.version = None
        self.callsign = None
        self.phone_number = None
        self.battery = None
        self.groups = {}
        self.device_inserted = False
        self.is_authenticated = False

        # Location Attributes
        self.latitude = 0
        self.longitude = 0
        self.ce = 0
        self.hae = 0
        self.le = 0
        self.course = 0
        self.speed = 0
        self.location_source = None
        self.common_name = None
        self.user = None

        # In case the RabbitMQ channel or connection drops, cached_messages will hold message until the channel is open again
        self.cached_messages = []

        if self.is_ssl:
            try:
                self.sock.do_handshake()
                for c in self.sock.getpeercert()['subject']:
                    if c[0][0] == 'commonName':
                        self.common_name = c[0][1]
                        self.logger.debug("Got common name {}".format(self.common_name))

                        with self.app.app_context():
                            self.user = self.app.security.datastore.find_user(username=self.common_name)
            except BaseException as e:
                logger.warning("Failed to do handshake: {}".format(e))
                self.logger.error(traceback.format_exc())
                self.close_connection()

        # RabbitMQ
        try:
            rabbit_credentials = pika.PlainCredentials(self.app.config.get("OTS_RABBITMQ_USERNAME"), self.app.config.get("OTS_RABBITMQ_PASSWORD"))
            rabbit_host = self.app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")
            self.rabbit_connection = pika.SelectConnection(pika.ConnectionParameters(host=rabbit_host, credentials=rabbit_credentials), self.on_connection_open, on_close_callback=self.on_close)
            self.rabbit_channel: Channel | None = None
            # Start the pika ioloop in a thread or else it blocks and we can't receive any CoT messages
            self.iothread = Thread(target=self.rabbit_connection.ioloop.start, name="IOLOOP")
            self.iothread.daemon = True
            self.iothread.start()
            self.is_consuming = False
        except BaseException as e:
            self.logger.error("Failed to connect to rabbitmq: {}".format(e))
            return

    def on_connection_open(self, connection: pika.SelectConnection):
        self.rabbit_connection.channel(on_open_callback=self.on_channel_open)
        self.rabbit_connection.add_on_close_callback(self.on_close)

    def on_channel_open(self, channel: Channel):
        self.logger.debug(f"Opening RabbitMQ channel for {self.callsign or self.address}")
        self.rabbit_channel = channel
        self.rabbit_channel.add_on_close_callback(self.on_channel_close)

        for message in self.cached_messages:
            self.route_cot(message)

        self.cached_messages.clear()

        # Publish the EUD info to flask-socketio for the web UI map
        if self.eud:
            message = {'method': 'emit', 'event': "eud", 'data': self.eud.to_json(),
                       'namespace': "/socket.io", 'room': None,
                       'skip_sid': [], 'callback': None, 'binary': False,
                       'host_id': uuid.uuid4().hex}
            self.rabbit_channel.basic_publish("flask-socketio", "", json.dumps(message), properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))

    def on_channel_close(self, channel: Channel, error):
        self.logger.error(f"RabbitMQ channel closed for {self.callsign}, shut it down")
        if self.rabbit_connection and not self.rabbit_connection.is_closing and not self.rabbit_connection.is_closed:
            self.rabbit_connection.close()

        self.shutdown = True
        self.sock.shutdown(socket.SHUT_RDWR)
        self.sock.close()

    def on_close(self, connection, error):
        # Stop the ioloop using add_callback_threadsafe because ioloop.stop() isn't threadsafe
        connection.ioloop.add_callback_threadsafe(self.rabbit_connection.ioloop.stop)
        self.logger.info("Connection closed for {}: {}".format(self.address, error))

    def on_message(self, unused_channel, basic_deliver, properties, body):
        try:
            body = json.loads(body)
            if body['uid'] != self.uid:
                self.sock.send(body['cot'].encode())
        except BaseException as e:
            self.logger.error(f"{self.callsign}: {e}, closing socket")
            self.close_connection()
            self.logger.error(traceback.format_exc())

    def handle_auth(self, auth: str):
        self.logger.debug(auth)
        if auth:
            auth = BeautifulSoup(auth, 'xml')
        if self.is_ssl and not self.is_authenticated and (auth or self.common_name):
            user = None
            with self.app.app_context():
                if auth:
                    cot = auth.find('cot')
                    if cot:
                        username = cot.attrs['username']
                        password = cot.attrs['password']
                        uid = cot.attrs['uid']

                        if self.app.config.get("OTS_ENABLE_LDAP"):
                            result = ldap_manager.authenticate(username, password)

                            if result.status == AuthenticationResponseStatus.success:
                                # Keep this import here to avoid a circular import when OTS is started
                                from opentakserver.blueprints.ots_api.ldap_api import save_user

                                self.user = save_user(result.user_dn, result.user_id, result.user_info,
                                                      result.user_groups)

                                try:
                                    eud = self.db.session.execute(self.db.session.query(EUD).filter_by(uid=uid)).first()[0]
                                    self.logger.debug("Associating EUD uid {} to user {}".format(eud.uid, self.user.username))
                                    eud.user_id = self.user.id
                                    self.db.session.commit()
                                except:
                                    self.logger.debug("This is a new eud: {} {}".format(uid, self.user.username))
                                    eud = EUD()
                                    eud.uid = uid
                                    eud.user_id = self.user.id
                                    eud.callsign = self.callsign
                                    self.db.session.add(eud)
                                    self.db.session.commit()

                            else:
                                self.close_connection()
                                return

                        else:
                            user = self.app.security.datastore.find_user(username=username)
                elif self.common_name:
                    user = self.app.security.datastore.find_user(username=self.common_name)

                if not user:
                    self.logger.warning("User {} does not exist".format(self.common_name))
                    self.close_connection()
                    return
                elif not user.active:
                    self.logger.warning("User {} is deactivated, disconnecting".format(username))
                    self.close_connection()
                    return
                elif self.common_name:
                    self.logger.info("{} is ID'ed by cert".format(user.username))
                    self.is_authenticated = True
                    self.user = user
                elif verify_password(password, user.password):
                    self.logger.info("Successful login from {}".format(username))
                    self.is_authenticated = True
                    self.user = user
                    try:
                        eud = self.db.session.execute(self.db.session.query(EUD).filter_by(uid=uid)).first()[0]
                        self.logger.debug("Associating EUD uid {} to user {}".format(eud.uid, user.username))
                        eud.user_id = user.id
                        self.db.session.commit()
                    except:
                        self.logger.debug("This is a new eud: {} {}".format(uid, user.username))
                        eud = EUD()
                        eud.uid = uid
                        eud.user_id = user.id
                        self.db.session.add(eud)
                        self.db.session.commit()

                else:
                    self.logger.warning("Wrong password for user {}".format(username))
                    self.close_connection()
                    return

    def handle_cot(self, cot):
        self.logger.debug(cot)
        event = BeautifulSoup(cot, 'xml').find("event")

        # If this client is connected via ssl, make sure they're authenticated
        # before accepting any data from them
        if self.is_ssl and not self.is_authenticated:
            self.logger.warning("EUD isn't authenticated, ignoring")
            return

        if self.pong(event):
            return

        if event and not self.uid:
            self.parse_device_info(event)

        self.route_cot(event)

    # Yes this is super janky
    def run(self):
        cot = ""

        while not self.shutdown:
            try:
                if self.common_name and not self.is_authenticated:
                    self.handle_auth("")

                data = self.sock.recv(65536)
                if not data:
                    # Occurs when an EUD disconnects
                    self.logger.warning("No Data Closing connection to {}".format(self.address))
                    self.shutdown = True
                    self.close_connection()
                    break

                cot += data.decode("utf-8")
                cot_list = re.split("</event>|</auth>", cot)

                if len(cot_list) < 2:
                    continue

                for c in cot_list:
                    try:
                        if "<event" in c:
                            fromstring(c + "</event>")
                            self.handle_cot(c + "</event>")
                        elif "<auth>" in c:
                            fromstring(c + "</auth>")
                            self.handle_auth(c + "</auth>")
                    except ParseError as e:
                        self.logger.error(f"Failed to parse: {e}")
                        cot = c
                        break

                cot = ""

            except TimeoutError:
                if self.shutdown:
                    self.logger.warning("Timeout Closing connection to {}".format(self.address))
                    self.close_connection()
                    break
                else:
                    continue
            except OSError as e:
                self.logger.warning("OSError, stopping")
                self.logger.error(str(e))
                self.logger.error(traceback.format_exc())
                # Client disconnected abruptly, either ATAK crashed, lost network connectivity, the battery died, etc
                return
            except (ConnectionError, ConnectionResetError) as e:
                self.logger.info(f"Closing connection {e}")
                self.close_connection()
                break

    def close_connection(self):
        self.unbind_rabbitmq_queues()
        self.send_disconnect_cot()

        if self.rabbit_channel and not self.rabbit_channel.is_closing and not self.rabbit_channel.is_closed:
            self.rabbit_channel.close()

        if not self.shutdown:
            self.shutdown = True
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()

        # Close this thread's DB session. This doesn't affect other EUD's threads
        with self.app.app_context():
            self.db.session.close()
            self.db.engine.dispose()

    def stop(self):
        self.close_connection()
        self.shutdown = True

    def pong(self, event):
        if event.attrs.get('type') == 't-x-c-t':
            now = datetime.datetime.now(datetime.timezone.utc)
            stale = now + datetime.timedelta(seconds=10)

            cot = Element('event', {'how': 'h-g-i-g-o', 'type': 't-x-c-t-r', 'version': '2.0',
                                      'uid': "{}-pong".format(self.uid), 'start': now, 'time': now, 'stale': stale})
            SubElement(cot, 'point', {'ce': '9999999', 'le': '9999999', 'hae': '0', 'lat': '0',
                                                'lon': '0'})

            try:
                self.sock.send(event.encode())
                return True
            except BaseException as e:
                self.logger.error(e)
                self.logger.debug(traceback.format_exc())

        return False

    def parse_device_info(self, event):
        link = event.find('link')
        fileshare = event.find('fileshare')

        # EUDs running the Meshtastic and dmrcot plugins can relay messages from their RF networks to the server
        # so we want to use the UID of the "off grid" EUD, not the relay EUD
        takv = event.find('takv')
        if takv:
            uid = event.attrs.get('uid')
        else:
            return

        contact = event.find('contact')

        # Only assume it's an EUD if it's got a <takv> tag
        if takv and contact and uid and not uid.endswith('ping') and (self.user or not self.is_ssl):
            self.uid = uid
            device = takv.attrs['device'] if 'device' in takv.attrs else ""
            operating_system = takv.attrs['os'] if 'os' in takv.attrs else ""
            platform = takv.attrs['platform'] if 'platform' in takv.attrs else ""
            version = takv.attrs['version'] if 'version' in takv.attrs else ""

            if 'callsign' in contact.attrs:
                self.callsign = contact.attrs['callsign']

                # Declare a RabbitMQ Queue for this uid and join the 'dms' and 'cot' exchanges
                if self.rabbit_channel and self.rabbit_channel.is_open and platform != "OpenTAK ICU" and platform != "Meshtastic" and platform != "DMRCOT":

                    self.logger.debug(f"Declaring queue for {self.callsign} {self.uid}")
                    self.rabbit_channel.queue_declare(queue=self.callsign)
                    self.rabbit_channel.queue_declare(queue=self.uid)

                    with self.app.app_context():
                        if self.is_ssl:
                            group_memberships = db.session.execute(db.session.query(GroupUser).filter_by(user_id=self.user.id, direction=Group.OUT)).all()
                            if not group_memberships:
                                self.logger.debug(f"{self.callsign} doesn't belong to any groups, adding them to the __ANON__ group")
                                self.rabbit_channel.queue_bind(exchange="groups", queue=self.uid, routing_key="__ANON__.OUT")
                                if {"exchange": "groups", "routing_key": "__ANON__.OUT", "queue": self.uid} not in self.bound_queues:
                                    self.bound_queues.append({"exchange": "groups", "routing_key": "__ANON__.OUT", "queue": self.uid})

                            elif group_memberships and self.is_ssl:
                                for membership in group_memberships:
                                    membership = membership[0]
                                    self.rabbit_channel.queue_bind(exchange="groups", queue=self.uid, routing_key=f"{membership.group.name}.OUT")

                                    if {"exchange": "groups", "routing_key": f"{membership.group.name}.OUT", "queue": self.uid} not in self.bound_queues:
                                        self.bound_queues.append({"exchange": "groups", "routing_key": f"{membership.group.name}.OUT", "queue": self.uid})

                        self.rabbit_channel.queue_bind(exchange='missions', routing_key="missions", queue=self.uid)
                        if {"exchange": "missions", "routing_key": "missions", "queue": self.uid} not in self.bound_queues:
                            self.bound_queues.append({"exchange": "groups", "routing_key": "__ANON__.OUT", "queue": self.uid})

                        # The DMs queue also binds by callsign since the <dest> tag in CoT messages can be by callsign instead of UID
                        self.rabbit_channel.queue_bind(exchange='dms', queue=self.uid, routing_key=self.uid)
                        self.rabbit_channel.queue_bind(exchange='dms', queue=self.callsign, routing_key=self.callsign)

                        if {"exchange": "dms", "routing_key": self.uid, "queue": self.uid} not in self.bound_queues:
                            self.bound_queues.append({"exchange": "dms", "routing_key": self.uid, "queue": self.uid})

                        if {"exchange": "dms", "routing_key": self.callsign, "queue": self.callsign} not in self.bound_queues:
                            self.bound_queues.append({"exchange": "dms", "routing_key": self.callsign, "queue": self.callsign})

                        self.rabbit_channel.basic_consume(queue=self.callsign, on_message_callback=self.on_message, auto_ack=True)
                        self.rabbit_channel.basic_consume(queue=self.uid, on_message_callback=self.on_message, auto_ack=True)

            if 'phone' in contact.attrs and contact.attrs['phone']:
                self.phone_number = contact.attrs['phone']

            with self.app.app_context():
                __group = event.find('__group')
                team = Team()

                if __group:
                    team.name = bleach.clean(__group.attrs['name'])

                    try:
                        chatroom = self.db.session.execute(select(Chatroom).filter(Chatroom.name == team.name)).first()[0]
                        team.chatroom_id = chatroom.id
                    except TypeError:
                        chatroom = None

                    try:
                        self.db.session.add(team)
                        self.db.session.commit()
                    except sqlalchemy.exc.IntegrityError:
                        self.db.session.rollback()
                        team = self.db.session.execute(select(Team).filter(Team.name == __group.attrs['name'])).first()[0]
                        if not team.chatroom_id and chatroom:
                            team.chatroom_id = chatroom.id
                            self.db.session.execute(update(Team).filter(Team.name == chatroom.id).values(chatroom_id=chatroom.id))

                try:
                    eud = self.db.session.execute(select(EUD).filter_by(uid=uid)).first()[0]
                except:
                    eud = EUD()

                eud.uid = uid
                if self.callsign:
                    eud.callsign = self.callsign
                if device:
                    eud.device = device

                eud.os = operating_system
                eud.platform = platform
                eud.version = version
                eud.phone_number = self.phone_number
                eud.last_event_time = datetime_from_iso8601_string(event.attrs['start'])
                eud.last_status = 'Connected'
                eud.user_id = self.user.id if self.user else None

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

                if __group:
                    eud.team_id = team.id
                    eud.team_role = bleach.clean(__group.attrs['role'])

                try:
                    self.db.session.add(eud)
                    self.db.session.commit()
                except sqlalchemy.exc.IntegrityError:
                    self.db.session.rollback()
                    self.db.session.execute(update(EUD).where(EUD.uid == eud.uid).values(**eud.serialize()))
                    self.db.session.commit()

                self.send_meshtastic_node_info(eud)

                # If the RabbitMQ channel is open, publish the EUD info to socketio to be displayed on the web UI map.
                # Also save the EUD's info for on_channel_open to publish
                self.eud = eud
                if self.rabbit_channel:
                    message = {'method': 'emit', 'event': "eud", 'data': eud.to_json(),
                               'namespace': "/socket.io", 'room': None,
                               'skip_sid': None, 'callback': None, 'binary': False,
                               'host_id': uuid.uuid4().hex}
                    self.rabbit_channel.basic_publish(exchange="flask-socketio", routing_key="", body=json.dumps(message).encode(),
                                                      properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))

    def send_meshtastic_node_info(self, eud):
        if self.app.config.get("OTS_ENABLE_MESHTASTIC") and eud.platform != "Meshtastic":
            user_info = mesh_pb2.User()
            setattr(user_info, "id", "!{:x}".format(eud.meshtastic_id))
            user_info.long_name = eud.callsign
            # Use the last 4 characters of the UID as the short name
            user_info.short_name = eud.uid[-4:]
            user_info.hw_model = mesh_pb2.HardwareModel.PRIVATE_HW

            # Note to future self: The Meshtastic firmware expects a User payload when the Portnum is NodeInfo
            # DO NOT SEND A NODEINFO PAYLOAD!
            encoded_message = mesh_pb2.Data()
            encoded_message.portnum = portnums_pb2.NODEINFO_APP
            encoded_message.payload = user_info.SerializeToString()

            message_id = random.getrandbits(32)
            mesh_packet = mesh_pb2.MeshPacket()
            mesh_packet.id = message_id

            try:
                setattr(mesh_packet, "from", int(eud.meshtastic_id, 16))
            except BaseException as e:
                setattr(mesh_packet, "from", eud.meshtastic_id)
            mesh_packet.to = BROADCAST_NUM
            mesh_packet.want_ack = False
            mesh_packet.hop_limit = 3
            mesh_packet.decoded.CopyFrom(encoded_message)

            service_envelope = mqtt_pb2.ServiceEnvelope()
            service_envelope.packet.CopyFrom(mesh_packet)
            service_envelope.gateway_id = "OpenTAKServer"

            channels = self.db.session.execute(select(MeshtasticChannel).filter(MeshtasticChannel.uplink_enabled is True))
            for channel in channels:
                channel = channel[0]
                service_envelope.channel_id = channel
                routing_key = f"{self.app.config.get('OTS_MESHTASTIC_TOPIC')}.2.e.{channel.name}.outgoing"
                self.rabbit_channel.basic_publish(exchange='amq.topic', routing_key=routing_key, body=service_envelope.SerializeToString(),
                             properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))
                self.logger.debug("Published message to " + routing_key)

    def unbind_rabbitmq_queues(self):
        if self.uid and self.rabbit_channel and not self.rabbit_channel.is_closing and not self.rabbit_channel.is_closed:
            self.rabbit_channel.queue_unbind(queue=self.uid, exchange="missions", routing_key="missions")
            self.rabbit_channel.queue_unbind(queue=self.uid, exchange="groups")
            with self.app.app_context():
                missions = db.session.execute(db.session.query(Mission)).all()
                for mission in missions:
                    self.rabbit_channel.queue_unbind(queue=self.uid, exchange="missions", routing_key=f"missions.{mission[0].name}")
                    self.logger.debug(f"Unbound {self.uid} from mission.{mission[0].name}")

            for bind in self.bound_queues:
                self.rabbit_channel.queue_unbind(exchange=bind['exchange'], queue=bind['queue'], routing_key=bind['routing_key'])

    def send_disconnect_cot(self):
        if self.uid:
            now = datetime.datetime.now(datetime.timezone.utc)
            stale = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=10))

            event = Element('event', {'how': 'h-g-i-g-o', 'type': 't-x-d-d', 'version': '2.0',
                                      'uid': str(uuid.uuid4()), 'start': iso8601_string_from_datetime(now),
                                      'time': iso8601_string_from_datetime(now), 'stale': iso8601_string_from_datetime(stale)})
            point = SubElement(event, 'point', {'ce': '9999999', 'le': '9999999', 'hae': '0', 'lat': '0',
                                                'lon': '0'})
            detail = SubElement(event, 'detail')
            link = SubElement(detail, 'link', {'relation': 'p-p', 'uid': self.uid, 'type': 'a-f-G-U-C'})
            flow_tags = SubElement(detail, '_flow-tags_', {'TAK-Server-f1a8159ef7804f7a8a32d8efc4b773d0': iso8601_string_from_datetime(now)})

            message = json.dumps({'uid': self.uid, 'cot': tostring(event).decode('utf-8')})
            if self.rabbit_channel and not self.rabbit_channel.is_closing and not self.rabbit_channel.is_closed and self.user:
                with self.app.app_context():
                    group_query = self.db.session.query(GroupUser).filter_by(user_id=self.user.id, direction=Group.OUT, enabled=True)
                    groups = self.db.session.execute(group_query).all()
                    for group in groups:
                        group = group[0]
                        self.logger.debug(f"Publishing to group {group.group.name}.{group.direction}")
                        self.rabbit_channel.basic_publish(exchange="groups", routing_key=f"{group.group.name}.{group.direction}", body=message,
                                                          properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))
            elif self.rabbit_channel and not self.rabbit_channel.is_closing and not self.rabbit_channel.is_closed:
                self.rabbit_channel.basic_publish(exchange="groups", routing_key=f"__ANON__.{Group.OUT}", body=message,
                                                  properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))

            with self.app.app_context():
                self.db.session.execute(update(EUD).filter(EUD.uid == self.uid).values(last_status='Disconnected', last_event_time=now))
                self.db.session.commit()

        self.logger.info('{} disconnected'.format(self.address))

    def route_cot(self, event):
        if not event:
            return

        if not self.rabbit_channel or not self.rabbit_channel.is_open:
            self.cached_messages.append(event)
            self.logger.error("RabbitMQ channel is closed, not publishing cot")
            return

        # Route all CoTs to the firehose exchange for plugins and users that connect directly to RabbitMQ
        self.rabbit_channel.basic_publish(exchange='firehose', body=json.dumps({'uid': self.uid, 'cot': str(event)}), routing_key='',
                                          properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))

        # Route all cots to the cot_parser direct exchange to be processed by a pool of cot_parser processes
        self.rabbit_channel.basic_publish(exchange='cot_parser', body=json.dumps({'uid': self.uid, 'cot': str(event)}),
                                          routing_key='cot_parser',
                                          properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))

        mission_changes = []
        destinations = event.find_all('dest')
        if destinations:

            for destination in destinations:
                creator = event.find("creator")
                creator_uid = self.uid
                if creator and "uid" in creator.attrs:
                    creator_uid = creator.attrs['uid']

                # ATAK and WinTAK use callsign, iTAK uses uid
                if 'callsign' in destination.attrs and destination.attrs['callsign']:
                    self.rabbit_channel.basic_publish(exchange='dms', routing_key=destination.attrs['callsign'],
                                                      body=json.dumps({'uid': self.uid, 'cot': str(event)}),
                                                      properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))

                # iTAK uses its own UID in the <dest> tag when sending CoTs to a mission so we don't send those to the dms exchange
                elif 'uid' in destination.attrs and destination['uid'] != self.uid:
                    self.rabbit_channel.basic_publish(exchange='dms', routing_key=destination.attrs['uid'],
                                                      body=json.dumps({'uid': self.uid, 'cot': str(event)}),
                                                      properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))

                # For data sync missions
                elif 'mission' in destination.attrs:
                    with self.app.app_context():
                        mission = self.db.session.execute(
                            self.db.session.query(Mission).filter_by(name=destination.attrs['mission'])).first()

                        if not mission:
                            self.logger.error(f"No such mission found: {destination.attrs['mission']}")
                            return

                        mission = mission[0]
                        self.rabbit_channel.basic_publish("missions",
                                                          routing_key=f"missions.{destination.attrs['mission']}",
                                                          body=json.dumps({'uid': self.uid, 'cot': str(event)}),
                                                          properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))

                        mission_uid = self.db.session.execute(
                            self.db.session.query(MissionUID).filter_by(uid=event.attrs['uid'])).first()

                        if not mission_uid:
                            mission_uid = MissionUID()
                            mission_uid.uid = event.attrs['uid']
                            mission_uid.mission_name = destination.attrs['mission']
                            mission_uid.timestamp = datetime_from_iso8601_string(event.attrs['start'])
                            mission_uid.creator_uid = creator_uid
                            mission_uid.cot_type = event.attrs['type']

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

                            mission_change = MissionChange()
                            mission_change.isFederatedChange = False
                            mission_change.change_type = MissionChange.ADD_CONTENT
                            mission_change.mission_name = destination.attrs['mission']
                            mission_change.timestamp = datetime_from_iso8601_string(event.attrs['start'])
                            mission_change.creator_uid = creator_uid
                            mission_change.server_time = datetime_from_iso8601_string(event.attrs['start'])
                            mission_change.mission_uid = event.attrs['uid']

                            change_pk = self.db.session.execute(insert(MissionChange).values(**mission_change.serialize()))
                            self.db.session.commit()

                            body = {'uid': self.app.config.get("OTS_NODE_ID"), 'cot': tostring(generate_mission_change_cot(destination.attrs['mission'], mission, mission_change, cot_event=event)).decode('utf-8')}
                            mission_changes.append({"mission": mission.name, "message": body})
                            self.rabbit_channel.basic_publish("missions", routing_key=f"missions.{mission.name}", body=json.dumps(body))

        if not destinations and not self.is_ssl:
            # Publish all CoT messages received by TCP and that have no destination to the __ANON__ group
            self.rabbit_channel.basic_publish(exchange='groups', routing_key="__ANON__.OUT", body=json.dumps({'uid': self.uid, 'cot': str(event)}),
                                              properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))
            return

        if not destinations:
            with self.app.app_context():
                group_memberships = db.session.execute(db.session.query(GroupUser).filter_by(user_id=self.user.id, direction=Group.IN, enabled=True)).all()
                if not group_memberships:
                    # Default to the __ANON__ group if the user doesn't belong to any IN groups
                    self.rabbit_channel.basic_publish(exchange='groups', routing_key="__ANON__.OUT", body=json.dumps({'uid': self.uid, 'cot': str(event)}),
                                                      properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))

                for membership in group_memberships:
                    membership = membership[0]
                    self.rabbit_channel.basic_publish(exchange='groups', routing_key=f"{membership.group.name}.{Group.OUT}", body=json.dumps({'uid': self.uid, 'cot': str(event)}),
                                                      properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))

        if mission_changes:
            for change in mission_changes:
                self.rabbit_channel.basic_publish("missions", routing_key=f"missions.{change['mission']}",
                                                  body=json.dumps(change['message']), properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))
