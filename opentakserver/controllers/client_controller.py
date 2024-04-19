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

from opentakserver.extensions import db
from opentakserver.models.EUD import EUD


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

        # RabbitMQ
        try:
            self.rabbit_connection = pika.SelectConnection(pika.ConnectionParameters(self.app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")),
                                                           self.on_connection_open)
            self.rabbit_channel = None
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
        except:
            self.logger.error(traceback.format_exc())

    def run(self):
        while not self.shutdown:
            try:
                data = self.sock.recv(4096)
            except (ConnectionError, ConnectionResetError) as e:
                self.send_disconnect_cot()
                break
            except TimeoutError:
                if self.shutdown:
                    self.logger.warning("Closing connection to {}".format(self.address))
                    self.send_disconnect_cot()
                    self.sock.shutdown(socket.SHUT_RDWR)
                    self.sock.close()
                    break
                else:
                    continue

            if data:
                # Sometimes recv() doesn't get all of the XML data in one go. Test if the XML is well-formed
                # and if not, call recv() until it is
                while True:
                    try:
                        fromstring(data)
                        break
                    except ParseError as e:
                        try:
                            data += self.sock.recv(4096)
                            break
                        except (ConnectionError, TimeoutError, ConnectionResetError) as e:
                            break

                soup = BeautifulSoup(data, 'xml')

                event = soup.find('event')
                auth = soup.find('auth')

                if not self.is_authenticated and (auth or self.common_name):
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
                        elif verify_password(password, user.password):
                            self.logger.info("Successful login from {}".format(username))
                            self.is_authenticated = True
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

                    if event and self.pong(event):
                        continue

                    if event and not self.uid:
                        self.parse_device_info(event)

                    message = {'uid': self.uid, 'cot': str(soup)}
                    if self.rabbit_channel:
                        self.rabbit_channel.basic_publish(exchange='cot_controller', routing_key='',
                                                          body=json.dumps(message))

            else:
                self.send_disconnect_cot()
                break

    def close_connection(self):
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

            self.sock.send(event.encode())
            return True

        return False

    def parse_device_info(self, event):
        if not self.rabbit_channel:
            return
        self.uid = event.attrs['uid']
        contact = event.find('contact')
        if contact:
            if 'callsign' in contact.attrs:
                self.callsign = contact.attrs['callsign']

                self.logger.debug("Declaring queue {}".format(self.uid))
                self.rabbit_channel.queue_declare(queue=self.uid)
                self.rabbit_channel.queue_bind(exchange='cot', queue=self.uid)
                self.rabbit_channel.basic_consume(queue=self.uid, on_message_callback=self.on_message, auto_ack=True)
                self.logger.debug("{} is consuming".format(self.callsign))

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
            self.rabbit_channel.basic_publish(exchange='cot_controller', routing_key='', body=message)
        self.logger.info('{} disconnected'.format(self.address))
        if self.rabbit_connection:
            self.rabbit_connection.close()
