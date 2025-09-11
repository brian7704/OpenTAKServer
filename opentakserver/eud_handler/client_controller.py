import base64
import json
import os
import random
import socket
import traceback
import typing
import uuid
from xml.etree.ElementTree import Element, SubElement, tostring, fromstring, ParseError
import datetime
from threading import Thread

import bleach
import sqlalchemy
from flask_security import verify_password
from flask_socketio import SocketIO

from bs4 import BeautifulSoup
import pika
from meshtastic import mesh_pb2, portnums_pb2, BROADCAST_NUM, mqtt_pb2
from pika.channel import Channel
from sqlalchemy import select, update

from opentakserver.extensions import db
from opentakserver.functions import datetime_from_iso8601_string, iso8601_string_from_datetime
from opentakserver.models.Chatrooms import Chatroom
from opentakserver.models.EUD import EUD
from opentakserver.models.Meshtastic import MeshtasticChannel
from opentakserver.models.Mission import Mission
from opentakserver.models.CasEvac import CasEvac
from opentakserver.models.GeoChat import GeoChat
from opentakserver.models.ChatroomsUids import ChatroomsUids
from opentakserver.models.Team import Team


class ClientController(Thread):
    def __init__(self, address, port, sock, logger, app, is_ssl):
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
        self.socketio = SocketIO(message_queue="amqp://" + app.config.get("OTS_RABBITMQ_SERVER_ADDRESS"))

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

        # In case the RabbitMQ channel or connection drops, cached_messages will hold message until the channel is open again
        self.cached_messages = []

        if self.is_ssl:
            try:
                self.sock.do_handshake()
                for c in self.sock.getpeercert()['subject']:
                    if c[0][0] == 'commonName':
                        self.common_name = c[0][1]
                        self.logger.debug("Got common name {}".format(self.common_name))
            except BaseException as e:
                logger.warning("Failed to do handshake: {}".format(e))
                self.close_connection()
                self.logger.error(traceback.format_exc())

        # RabbitMQ
        try:
            self.rabbit_connection = pika.SelectConnection(pika.ConnectionParameters(self.app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")),
                                                           self.on_connection_open)
            self.rabbit_channel: Channel | None = None
            # Start the pika ioloop in a thread or else it blocks and we can't receive any CoT messages
            self.iothread = Thread(target=self.rabbit_connection.ioloop.start, name="IOLOOP")
            self.iothread.daemon = True
            self.iothread.start()
            self.is_consuming = False
        except BaseException as e:
            self.logger.error("Failed to connect to rabbitmq: {}".format(e))
            return

    def on_connection_open(self, connection):
        self.rabbit_connection.channel(on_open_callback=self.on_channel_open)
        self.rabbit_connection.add_on_close_callback(self.on_close)

    def on_channel_open(self, channel: Channel):
        self.logger.debug(f"Opening RabbitMQ channel for {self.callsign or self.address}")
        self.rabbit_channel = channel
        # Remove the on_channel_close callback in case this channel is being reopened
        self.rabbit_channel.callbacks.clear()
        self.rabbit_channel.add_on_close_callback(self.on_channel_close)

        for message in self.cached_messages:
            self.logger.info(f"Publishing cached message: {message}")
            self.publish(**message)

        self.cached_messages.clear()

    def on_channel_close(self, channel: Channel, error):
        if self.rabbit_connection.is_open:
            self.logger.debug(f"RabbitMQ channel closed for {self.callsign}, attempting to re-open: {error}")
            channel.open()

    def on_close(self, connection, error):
        try:
            if self.rabbit_connection:
                self.rabbit_connection.ioloop.stop()
                self.rabbit_connection = None
        except BaseException as e:
            self.logger.error(f"Failed to close ioloop: {e}")
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

    # Yes this is super janky
    def run(self):
        while not self.shutdown:
            try:
                data = self.sock.recv(1)
                if not data:
                    self.logger.warning("No Data Closing connection to {}".format(self.address))
                    self.close_connection()
                    break
            except TimeoutError:
                if self.shutdown:
                    self.logger.warning("Timeout Closing connection to {}".format(self.address))
                    self.close_connection()
                    break
                else:
                    continue
            except OSError:
                self.logger.warning("OSError, stopping")
                # Client disconnected abruptly, either ATAK crashed, lost network connectivity, the battery died, etc
                return
            except (ConnectionError, ConnectionResetError) as e:
                self.close_connection()
                break

            if data:
                while True:
                    try:
                        if data.decode('utf-8').endswith(">"):
                            # fromstring will raise ParseError if the XML data isn't valid yet
                            fromstring(data)
                            break
                        else:
                            try:
                                received_byte = self.sock.recv(1)
                                if not received_byte:
                                    self.logger.info(f"{self.address} disconnected")
                                    self.close_connection()
                                    break
                                data += received_byte
                                continue
                            except (ConnectionError, TimeoutError, ConnectionResetError) as e:
                                break
                    except (ParseError, UnicodeDecodeError) as e:
                        try:
                            received_byte = self.sock.recv(1)
                            if not received_byte:
                                self.logger.info(f"{self.address} disconnected")
                                self.close_connection()
                                break
                            data += received_byte
                            continue
                        except (ConnectionError, TimeoutError, ConnectionResetError) as e:
                            break

                self.logger.debug(data)
                soup = BeautifulSoup(data, 'xml')

                event = soup.find('event')
                auth = soup.find('auth')

                if self.is_ssl and not self.is_authenticated and (auth or self.common_name):
                    with self.app.app_context():
                        if auth:
                            cot = auth.find('cot')
                            if cot:
                                username = cot.attrs['username']
                                password = cot.attrs['password']
                                uid = cot.attrs['uid']
                                user = self.app.security.datastore.find_user(username=username)
                        elif self.common_name:
                            user = self.app.security.datastore.find_user(username=self.common_name)

                        if not user:
                            self.logger.warning("User {} does not exist".format(self.common_name))
                            self.close_connection()
                            break
                        elif not user.active:
                            self.logger.warning("User {} is deactivated, disconnecting".format(username))
                            self.close_connection()
                            break
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
                            break

                if event:
                    # If this client is connected via ssl, make sure they're authenticated
                    # before accepting any data from them
                    if self.is_ssl and not self.is_authenticated:
                        self.logger.warning("EUD isn't authenticated, ignoring")
                        continue

                    if self.pong(event):
                        continue

                    if event and not self.uid:
                        self.parse_device_info(event)

                    message = {'uid': self.uid, 'cot': str(soup)}
                    self.publish(exchange='cot_controller', routing_key='', body=json.dumps(message),
                                 properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))
            else:
                self.unbind_rabbitmq_queues()
                self.send_disconnect_cot()
                break

    def close_connection(self):
        self.unbind_rabbitmq_queues()
        self.send_disconnect_cot()
        self.sock.shutdown(socket.SHUT_RDWR)
        self.sock.close()
        self.shutdown = True

    def stop(self):
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
            except BaseException as e:
                self.logger.error(e)
                self.logger.debug(traceback.format_exc())
            return True

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
        if takv and contact and uid and not uid.endswith('ping'):
            self.uid = uid
            device = takv.attrs['device'] if 'device' in takv.attrs else ""
            operating_system = takv.attrs['os'] if 'os' in takv.attrs else ""
            platform = takv.attrs['platform'] if 'platform' in takv.attrs else ""
            version = takv.attrs['version'] if 'version' in takv.attrs else ""

            if 'callsign' in contact.attrs:
                self.callsign = contact.attrs['callsign']

                # Declare a RabbitMQ Queue for this uid and join the 'dms' and 'cot' exchanges
                if self.rabbit_channel and self.rabbit_channel.is_open and platform != "OpenTAK ICU" and platform != "Meshtastic" and platform != "DMRCOT":
                    self.logger.debug(f"Declaring queue for {self.callsign}")
                    self.rabbit_channel.queue_declare(queue=self.callsign)
                    self.rabbit_channel.queue_bind(exchange='cot', queue=self.callsign)
                    self.rabbit_channel.queue_bind(exchange='missions', routing_key="missions", queue=self.callsign)
                    self.rabbit_channel.basic_consume(queue=self.callsign, on_message_callback=self.on_message, auto_ack=True)

                    self.logger.debug("Declaring queue {}".format(self.uid))
                    self.rabbit_channel.queue_declare(queue=self.uid)
                    self.rabbit_channel.queue_bind(exchange='cot', queue=self.uid)
                    self.rabbit_channel.queue_bind(exchange='missions', routing_key="missions", queue=self.uid)
                    self.rabbit_channel.basic_consume(queue=self.uid, on_message_callback=self.on_message, auto_ack=True)

                    self.rabbit_channel.queue_bind(exchange='dms', queue=self.uid, routing_key=self.uid)
                    self.rabbit_channel.queue_bind(exchange='dms', queue=self.callsign, routing_key=self.callsign)
                    self.rabbit_channel.queue_bind(exchange='chatrooms', queue=self.uid, routing_key='All Chat Rooms')

                    with self.app.app_context():
                        online_euds = self.db.session.execute(select(EUD).filter(EUD.last_status == 'Connected')).all()
                        for eud in online_euds:
                            eud = eud[0]
                            if len(eud.cots) > 0:
                                self.sock.send(eud.cots[-1].xml.encode())

            if 'phone' in contact.attrs and contact.attrs['phone']:
                self.phone_number = contact.attrs['phone']

            with self.app.app_context():
                group = event.find('__group')
                team = Team()

                if group:
                    # Declare an exchange for each group and bind the callsign's queue
                    if self.rabbit_channel.is_open and platform != "Meshtastic" and platform != "DMRCOT":
                        self.logger.debug("Declaring exchange {}".format(group.attrs['name']))
                        self.rabbit_channel.exchange_declare(exchange=group.attrs['name'])
                        self.rabbit_channel.queue_bind(queue=self.uid, exchange='chatrooms', routing_key=group.attrs['name'])

                    team.name = bleach.clean(group.attrs['name'])

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
                        team = self.db.session.execute(select(Team).filter(Team.name == group.attrs['name'])).first()[0]
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

                self.send_meshtastic_node_info(eud)
                self.socketio.emit('eud', eud.to_json(), namespace='/socket.io')

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
                self.publish(exchange='amq.topic', routing_key=routing_key,
                             body=service_envelope.SerializeToString(),
                             properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))
                self.logger.debug("Published message to " + routing_key)

    def unbind_rabbitmq_queues(self):
        if self.uid and self.rabbit_channel:
            self.rabbit_channel.queue_unbind(queue=self.uid, exchange="missions", routing_key="missions")
            self.rabbit_channel.queue_unbind(queue=self.uid, exchange="cot")
            with self.app.app_context():
                missions = db.session.execute(db.session.query(Mission)).all()
                for mission in missions:
                    self.rabbit_channel.queue_unbind(queue=self.uid, exchange="missions", routing_key=f"missions.{mission[0].name}")
                    self.logger.debug(f"Unbound {self.uid} from mission.{mission[0].name}")

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
            if self.rabbit_channel:
                self.publish(exchange='cot_controller', routing_key='', body=message,
                             properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))

            with self.app.app_context():
                self.db.session.execute(update(EUD).filter(EUD.uid == self.uid).values(last_status='Disconnected', last_event_time=now))
                self.db.session.commit()

        self.logger.info('{} disconnected'.format(self.address))
        if self.rabbit_connection:
            self.rabbit_connection.close()

    def publish(self, exchange: str, routing_key: str, body: typing.Any, properties: pika.BasicProperties):
        if not self.rabbit_channel or not self.rabbit_channel.is_open:
            self.cached_messages.append({'body': body, 'exchange': exchange, 'routing_key': routing_key, 'properties': properties})
            return

        try:
            self.rabbit_channel.basic_publish(exchange=exchange, routing_key=routing_key, body=body, properties=properties)
        except BaseException as e:
            self.logger.error(f"Failed to publish message, caching and trying again later: {e}")
            self.cached_messages.append({'exchange': exchange, 'routing_key': routing_key, 'body': body, 'properties': properties})
