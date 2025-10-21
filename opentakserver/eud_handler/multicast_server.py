import json
import socket
import struct
import traceback
from threading import Thread
from xml.etree.ElementTree import fromstring, ParseError

import pika
from bs4 import BeautifulSoup


class MulticastServer(Thread):
    """
    UDP Multicast server for receiving CoT messages from multicast group.
    Listens on a multicast group and publishes received CoT messages to RabbitMQ.
    """

    def __init__(self, logger, app_context):
        Thread.__init__(self)
        self.logger = logger
        self.app_context = app_context
        self.shutdown = False
        self.daemon = True
        self.socket = None
        self.rabbit_connection = None
        self.rabbit_channel = None

        # Get configuration
        self.multicast_address = app_context.app.config.get("OTS_MULTICAST_ADDRESS")
        self.multicast_port = app_context.app.config.get("OTS_MULTICAST_PORT")
        self.enabled = app_context.app.config.get("OTS_ENABLE_MULTICAST")
        self.receive_enabled = app_context.app.config.get("OTS_MULTICAST_RECEIVE")

    def run(self):
        if not self.enabled or not self.receive_enabled:
            self.logger.info("Multicast receiver is disabled")
            return

        try:
            # Initialize RabbitMQ connection
            self.init_rabbitmq()

            # Create UDP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Bind to the multicast port
            self.socket.bind(('', self.multicast_port))

            # Join multicast group
            mreq = struct.pack("4sl", socket.inet_aton(self.multicast_address), socket.INADDR_ANY)
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            # Set socket timeout for graceful shutdown
            self.socket.settimeout(1.0)

            self.logger.info(f"Multicast receiver started on {self.multicast_address}:{self.multicast_port}")

            # Main receive loop
            while not self.shutdown:
                try:
                    data, addr = self.socket.recvfrom(65536)  # Max UDP packet size
                    self.logger.debug(f"Received multicast CoT from {addr[0]}:{addr[1]} ({len(data)} bytes)")
                    self.process_cot_message(data, addr)
                except socket.timeout:
                    continue
                except Exception as e:
                    if not self.shutdown:
                        self.logger.error(f"Error receiving multicast message: {e}")
                        self.logger.error(traceback.format_exc())

        except Exception as e:
            self.logger.error(f"Failed to start multicast receiver: {e}")
            self.logger.error(traceback.format_exc())
        finally:
            self.cleanup()

    def init_rabbitmq(self):
        """Initialize RabbitMQ connection for publishing received CoT messages"""
        try:
            rabbit_credentials = pika.PlainCredentials(
                self.app_context.app.config.get("OTS_RABBITMQ_USERNAME"),
                self.app_context.app.config.get("OTS_RABBITMQ_PASSWORD")
            )
            rabbit_host = self.app_context.app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")

            self.rabbit_connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=rabbit_host, credentials=rabbit_credentials)
            )
            self.rabbit_channel = self.rabbit_connection.channel()
            self.logger.info("Multicast receiver connected to RabbitMQ")
        except Exception as e:
            self.logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise

    def process_cot_message(self, data, addr):
        """
        Process received CoT message and publish to RabbitMQ

        Args:
            data: Raw CoT XML data
            addr: Source address tuple (ip, port)
        """
        try:
            # Decode the message
            cot_xml = data.decode('utf-8')

            # Validate XML structure
            soup = BeautifulSoup(cot_xml, 'xml')
            event = soup.find('event')

            if not event:
                self.logger.warning(f"Invalid CoT XML received from {addr[0]} - no event element")
                return

            # Extract UID from the event
            uid = event.get('uid', 'UNKNOWN')
            event_type = event.get('type', 'UNKNOWN')

            self.logger.info(f"Received multicast CoT: uid={uid}, type={event_type}, from={addr[0]}")

            # Publish to RabbitMQ cot_controller exchange (same as TCP/SSL connections)
            message = json.dumps({
                'uid': uid,
                'cot': cot_xml,
                'source': 'multicast',
                'source_ip': addr[0]
            })

            if self.rabbit_channel and self.rabbit_channel.is_open:
                self.rabbit_channel.basic_publish(
                    exchange='cot_controller',
                    routing_key='',
                    body=message,
                    properties=pika.BasicProperties(
                        expiration=self.app_context.app.config.get("OTS_RABBITMQ_TTL")
                    )
                )
                self.logger.debug(f"Published multicast CoT to RabbitMQ: {uid}")
            else:
                self.logger.warning("RabbitMQ channel not available, message dropped")

        except UnicodeDecodeError as e:
            self.logger.warning(f"Failed to decode multicast message from {addr[0]}: {e}")
        except ParseError as e:
            self.logger.warning(f"Invalid XML received from {addr[0]}: {e}")
        except Exception as e:
            self.logger.error(f"Error processing multicast CoT from {addr[0]}: {e}")
            self.logger.error(traceback.format_exc())

    def stop(self):
        """Stop the multicast receiver"""
        self.logger.info("Shutting down multicast receiver")
        self.shutdown = True

    def cleanup(self):
        """Clean up resources"""
        if self.socket:
            try:
                # Leave multicast group
                mreq = struct.pack("4sl", socket.inet_aton(self.multicast_address), socket.INADDR_ANY)
                self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                self.socket.close()
            except Exception as e:
                self.logger.error(f"Error closing multicast socket: {e}")

        if self.rabbit_connection:
            try:
                self.rabbit_connection.close()
            except Exception as e:
                self.logger.error(f"Error closing RabbitMQ connection: {e}")

        self.logger.info("Multicast receiver has shut down")
