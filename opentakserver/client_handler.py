import datetime
import threading
from threading import Thread
from bs4 import BeautifulSoup
import pika
from extensions import db

from opentakserver.models.CoT import CoT


class ClientHandler(Thread):
    def __init__(self, address, port, sock, lock, logger, context):
        Thread.__init__(self)
        self.address = address
        self.port = port
        self.sock = sock
        self.lock = lock
        self.logger = logger
        self.context = context

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
            self.rabbit_connection = pika.SelectConnection(pika.ConnectionParameters('localhost'), self.on_connection_open)
            self.rabbit_channel = None
            self.logger.debug("starting ioloop")
            self.iothread = threading.Thread(target=self.rabbit_connection.ioloop.start)
            self.iothread.start()
            self.is_consuming = False
            self.logger.debug("ioloop started!")
        except BaseException as e:
            self.logger.error("Failed to connect to rabbitmq: {}".format(e))
            return

    def on_connection_open(self, connection):
        self.logger.debug("on_connection_open")
        self.rabbit_connection.channel(on_open_callback=self.on_channel_open)
        self.rabbit_connection.add_on_close_callback(self.on_close)

    def on_channel_open(self, channel):
        self.logger.debug('on_channel_open')
        self.rabbit_channel = channel
        self.rabbit_channel.add_on_close_callback(self.on_close)

    def on_close(self, channel, error):
        self.logger.debug("error type is {}".format(type(error)))
        self.logger.info("Connection closed for {}: {}".format(self.address, error))

    def on_message(self, unused_channel, basic_deliver, properties, body):
        self.sock.send(body)

    def run(self):
        while True:
            try:
                data = self.sock.recv(4098)
            except ConnectionError as e:
                self.logger.error("{} disconnected: {}".format(self.address, e))
                break

            if data:
                soup = BeautifulSoup(data, 'xml')
                # self.logger.debug(soup)

                event = soup.find('event')
                if event:
                    # Ping/Pong
                    if 'uid' in event.attrs and event.attrs['uid'].endswith('ping'):
                        self.sock.send(self.pong(soup).encode())
                        continue

                    # Get the course if there is one
                    track = event.find('track')
                    if track:
                        self.course = track.attrs['course']
                        self.speed = track.attrs['speed']

                    # Get the battery status if there is one
                    status = event.find('status')
                    if status:
                        if 'battery' in status.attrs:
                            self.battery = status.attrs['battery']

                    # New Connection
                    if not self.uid and not event.attrs['uid'].endswith('ping'):
                        self.uid = event.attrs['uid']

                    takv = event.find('takv')
                    if takv:
                        self.device = takv.attrs['device']
                        self.os = takv.attrs['os']
                        self.platform = takv.attrs['platform']
                        self.version = takv.attrs['version']

                    contact = event.find('contact')
                    if contact:
                        if 'callsign' in contact.attrs:
                            self.callsign = contact.attrs['callsign']

                            # Declare a RabbitMQ Queue for this callsign and join the 'dms' and 'cot' exchanges
                            if self.rabbit_channel and self.rabbit_channel.is_open:
                                self.rabbit_channel.queue_declare(queue=self.callsign)
                                self.rabbit_channel.queue_bind(exchange='cot', queue=self.callsign)
                                self.rabbit_channel.queue_bind(exchange='dms', queue=self.callsign, routing_key=self.callsign)
                                if not self.is_consuming:
                                    self.rabbit_channel.basic_consume(queue=self.callsign, on_message_callback=self.on_message, auto_ack=True)
                                    self.is_consuming = True
                                    self.logger.info("Consuming! {}".format(self.callsign))

                        if 'phone' in contact.attrs:
                            self.phone_number = contact.attrs['phone']

                    groups = event.find_all('__group')
                    for group in groups:
                        self.groups[group.attrs['name']] = group.attrs['role']

                        # Declare an exchange for each group and bind the callsign's queue
                        if self.rabbit_channel and self.rabbit_channel.is_open:
                            self.rabbit_channel.exchange_declare(exchange=group.attrs['name'])
                            self.rabbit_channel.queue_bind(queue=self.callsign, exchange=group.attrs['name'], routing_key=group.attrs['name'])

                    # Location CoT
                    if 'how' in event.attrs and event.attrs['how'] == 'm-g':
                        # hae = Height above the WGS ellipsoid in meters
                        # ce = Circular 1-sigma or a circular area about the point in meters
                        # le = Linear 1-sigma error or an altitude range about the point in meters
                        point = event.find('point')
                        if point:
                            self.ce = point.attrs['ce']
                            self.hae = point.attrs['hae']
                            self.le = point.attrs['le']
                            self.latitude = point.attrs['lat']
                            self.longitude = point.attrs['lon']

                        precision_location = event.find('precisionlocation')
                        if precision_location:
                            self.location_source = precision_location.attrs['geopointsrc']

                    # RabbitMQ Routing
                    destinations = event.find_all('dest')
                    chat = event.find('__chat')

                    # Only send to specified callsigns and ignore the chatroom name
                    # This prevents all users from getting each other's DMs
                    for dest in destinations:
                        self.logger.debug("Destination: {}".format(dest))
                        if 'callsign' in dest.attrs and self.rabbit_channel and self.rabbit_channel.is_open:
                            self.rabbit_channel.basic_publish(exchange='dms', routing_key=dest.attrs['callsign'], body=data)

                    # If no callsign destinations are specified, send to the chatroom exchange
                    if len(destinations) == 0 and chat and self.rabbit_channel and self.rabbit_channel.is_open:
                        self.rabbit_channel.exchange_declare(exchange=chat.attrs['chatroom'])
                        self.rabbit_channel.queue_bind(queue=self.callsign, exchange='chatrooms', routing_key=chat.attrs['chatroom'])
                        self.rabbit_channel.basic_publish(exchange=chat.attrs['chatroom'], routing_key=chat.attrs['chatroom'], body=data)

                    # If no destination or callsign is specified, broadcast to all TAK clients
                    elif len(destinations) == 0 and self.rabbit_channel and self.rabbit_channel.is_open:
                        self.rabbit_channel.basic_publish(exchange='cot', routing_key="", body=data)

                    # Do nothing because the RabbitMQ channel hasn't opened yet or has closed
                    else:
                        self.logger.debug("Not publishing, channel closed")

                    # self.logger.info("publishing to DB")
                    # self.rabbit_channel.basic_publish(exchange='cot', routing_key='database', body=str(soup))

                    cot = CoT()
                    cot.how = event.attrs['how']
                    cot.type = event.attrs['type']
                    cot.sender_callsign = self.callsign
                    cot.sender_device_name = self.device
                    cot.xml = str(soup)
                    with self.context:
                        db.session.add(cot)
                        db.session.commit()
            else:
                self.logger.info('{} disconnected'.format(self.address))
                self.rabbit_connection.close()
                break

    def pong(self, data):
        now = datetime.datetime.now()
        stale = now + datetime.timedelta(seconds=10)
        response = '<event how="h-g-i-g-o" stale="{}" start="{}" time="{}" type="t-x-c-t-r" uid="{}-pong" version="2.0"><point ce="9999999" hae="0.00000000" lat="0.00000000" le="9999999" lon="0.00000000"></point></event>'.format(
            stale.isoformat(), now.isoformat(), now.isoformat(), self.uid
        )
        return response
