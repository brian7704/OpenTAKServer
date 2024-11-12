import json
import socket
import traceback
import uuid
from xml.etree.ElementTree import Element, SubElement, tostring, fromstring, ParseError
import datetime
from threading import Thread

from flask_security import verify_password

from bs4 import BeautifulSoup
import pika
from pika.channel import Channel

from opentakserver.extensions import db
from opentakserver.models.EUD import EUD
from opentakserver.models.Mission import Mission


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

        if self.is_ssl:
            try:
                self.sock.do_handshake()
                for c in self.sock.getpeercert()['subject']:
                    if c[0][0] == 'commonName':
                        self.common_name = c[0][1]
                        self.logger.debug("Got common name {}".format(self.common_name))
            except BaseException as e:
                logger.warning("Failed to do handshake: {}".format(e))
                self.unbind_rabbitmq_queues()
                self.send_disconnect_cot()
                self.sock.shutdown(socket.SHUT_RDWR)
                self.sock.close()
                self.shutdown = True
                self.logger.error(traceback.format_exc())

        # RabbitMQ
        try:
            self.rabbit_connection = pika.SelectConnection(pika.ConnectionParameters(self.app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")),
                                                           self.on_connection_open)
            self.rabbit_channel: Channel | None = None
            self.iothread = Thread(target=self.rabbit_connection.ioloop.start)
            self.iothread.daemon = True
            self.iothread.start()
            self.is_consuming = False
        except BaseException as e:
            self.logger.error("Failed to connect to rabbitmq: {}".format(e))
            return

    def on_connection_open(self, connection):
        self.rabbit_connection.channel(on_open_callback=self.on_channel_open)
        self.rabbit_connection.add_on_close_callback(self.on_close)

    def on_channel_open(self, channel):
        self.rabbit_channel = channel
        self.rabbit_channel.add_on_close_callback(self.on_close)

    def on_close(self, channel, error):
        self.logger.info("Connection closed for {}: {}".format(self.address, error))

    def on_message(self, unused_channel, basic_deliver, properties, body):
        try:
            body = json.loads(body)
            if body['uid'] != self.uid:
                self.sock.send(body['cot'].encode())
        except BaseException as e:
            self.logger.error(f"{self.callsign}: {e}, closing socket")
            self.unbind_rabbitmq_queues()
            self.send_disconnect_cot()
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            self.shutdown = True
            self.logger.error(traceback.format_exc())

    def run(self):
        while not self.shutdown:
            try:
                data = self.sock.recv(1)
                if not data:
                    self.shutdown = True
                    self.logger.warning("Closing connection to {}".format(self.address))
                    self.unbind_rabbitmq_queues()
                    self.send_disconnect_cot()
                    self.sock.shutdown(socket.SHUT_RDWR)
                    self.sock.close()
                    break
            except (ConnectionError, ConnectionResetError) as e:
                self.unbind_rabbitmq_queues()
                self.send_disconnect_cot()
                self.sock.close()
                break
            except TimeoutError:
                if self.shutdown:
                    self.logger.warning("Closing connection to {}".format(self.address))
                    self.unbind_rabbitmq_queues()
                    self.send_disconnect_cot()
                    self.sock.shutdown(socket.SHUT_RDWR)
                    self.sock.close()
                    break
                else:
                    continue

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
                                    self.shutdown = True
                                    self.logger.info(f"{self.address} disconnected")
                                    self.unbind_rabbitmq_queues()
                                    self.send_disconnect_cot()
                                    self.sock.shutdown(socket.SHUT_RDWR)
                                    self.sock.close()
                                    break
                                data += received_byte
                                continue
                            except (ConnectionError, TimeoutError, ConnectionResetError) as e:
                                break
                    except ParseError as e:
                        try:
                            received_byte = self.sock.recv(1)
                            if not received_byte:
                                self.shutdown = True
                                self.logger.info(f"{self.address} disconnected")
                                self.unbind_rabbitmq_queues()
                                self.send_disconnect_cot()
                                self.sock.shutdown(socket.SHUT_RDWR)
                                self.sock.close()
                                break
                            data += received_byte
                            continue
                        except (ConnectionError, TimeoutError, ConnectionResetError) as e:
                            break
                    except UnicodeDecodeError:
                        self.sock.close()
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
                            self.logger.warning("User {} does not exist".format(username))
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
                    if self.rabbit_channel:
                        self.rabbit_channel.basic_publish(exchange='cot_controller', routing_key='',
                                                          body=json.dumps(message),
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

    def stop(self):
        self.shutdown = True

    def pong(self, event):
        if 'uid' in event.attrs and event.attrs['uid'].endswith('ping'):
            now = datetime.datetime.now()
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
        if not self.rabbit_channel:
            return

        contact = event.find('contact')
        takv = event.find('takv')
        if contact and takv:
            if 'callsign' in contact.attrs:
                self.uid = event.attrs['uid']
                self.callsign = contact.attrs['callsign']

                self.logger.debug("Declaring queue {}".format(self.uid))
                self.rabbit_channel.queue_declare(queue=self.uid)
                self.rabbit_channel.queue_bind(exchange='cot', queue=self.uid)
                self.rabbit_channel.queue_bind(exchange='missions', routing_key="missions", queue=self.uid)
                self.rabbit_channel.basic_consume(queue=self.uid, on_message_callback=self.on_message, auto_ack=True)
                self.logger.debug("{} is consuming".format(self.callsign))

                # Add the EUD if it doesn't exist and associate it with a user
                with self.app.app_context():
                    eud = self.db.session.execute(self.db.session.query(EUD).filter_by(uid=self.uid)).first()
                    if not eud:
                        eud = EUD()
                        eud.uid = self.uid
                        eud.callsign = self.callsign
                        eud.user_id = self.user.id

                        self.db.session.add(eud)
                        self.db.session.commit()

    def unbind_rabbitmq_queues(self):
        if self.uid:
            self.rabbit_channel.queue_unbind(queue=self.uid, exchange="missions", routing_key="missions")
            self.rabbit_channel.queue_unbind(queue=self.uid, exchange="cot")
            with self.app.app_context():
                missions = db.session.execute(db.session.query(Mission)).all()
                for mission in missions:
                    self.rabbit_channel.queue_unbind(queue=self.uid, exchange="missions", routing_key=f"missions.{mission[0].name}")
                    self.logger.debug(f"Unbound {self.uid} from mission.{mission[0].name}")

    def send_disconnect_cot(self):
        if self.uid:
            now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
            stale = (datetime.datetime.now() + datetime.timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")

            event = Element('event', {'how': 'h-g-i-g-o', 'type': 't-x-d-d', 'version': '2.0',
                                      'uid': str(uuid.uuid4()), 'start': now, 'time': now, 'stale': stale})
            point = SubElement(event, 'point', {'ce': '9999999', 'le': '9999999', 'hae': '0', 'lat': '0',
                                                'lon': '0'})
            detail = SubElement(event, 'detail')
            link = SubElement(detail, 'link', {'relation': 'p-p', 'uid': self.uid, 'type': 'a-f-G-U-C'})
            flow_tags = SubElement(detail, '_flow-tags_', {'TAK-Server-f1a8159ef7804f7a8a32d8efc4b773d0': now})

            message = json.dumps({'uid': self.uid, 'cot': tostring(event).decode('utf-8')})
            self.rabbit_channel.basic_publish(exchange='cot_controller', routing_key='', body=message,
                                              properties=pika.BasicProperties(expiration=self.app.config.get("OTS_RABBITMQ_TTL")))
        self.logger.info('{} disconnected'.format(self.address))
        if self.rabbit_connection:
            self.rabbit_connection.close()
