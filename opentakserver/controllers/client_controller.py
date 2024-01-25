import json
import socket
import traceback
import uuid
from xml.etree.ElementTree import Element, SubElement, tostring, fromstring, ParseError
import datetime
from threading import Thread

from bs4 import BeautifulSoup
import pika


class ClientController(Thread):
    def __init__(self, address, port, sock, logger):
        Thread.__init__(self)
        self.address = address
        self.port = port
        self.sock = sock
        self.logger = logger
        self.shutdown = False
        self.sock.settimeout(1.0)

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

        # Location Attributes
        self.latitude = 0
        self.longitude = 0
        self.ce = 0
        self.hae = 0
        self.le = 0
        self.course = 0
        self.speed = 0
        self.location_source = None

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
                if event:
                    if self.pong(event):
                        continue

                    if not self.uid:
                        self.parse_device_info(event)

                    message = {'uid': self.uid, 'cot': str(soup)}
                    self.rabbit_channel.basic_publish(exchange='cot_controller', routing_key='',
                                                      body=json.dumps(message))

                else:
                    self.logger.error("{} sent unexpected CoT: {} {}".format(self.callsign, soup, event))
                    self.logger.error(data)
            else:
                self.send_disconnect_cot()
                break

    def stop(self):
        self.shutdown = True

    def pong(self, event):
        if 'uid' in event.attrs and event.attrs['uid'].endswith('ping'):
            now = datetime.datetime.now()
            stale = now + datetime.timedelta(seconds=10)
            pong = '<event how="h-g-i-g-o" stale="{}" start="{}" time="{}" type="t-x-c-t-r" uid="{}-pong" version="2.0"><point ce="9999999" hae="0.00000000" lat="0.00000000" le="9999999" lon="0.00000000"></point></event>'.format(
                stale.isoformat(), now.isoformat(), now.isoformat(), self.uid
            )
            self.sock.send(pong.encode())
            return True

        return False

    def parse_device_info(self, event):
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
        self.rabbit_connection.close()
