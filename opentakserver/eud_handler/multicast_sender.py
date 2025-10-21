import json
import socket
import struct
import traceback
from threading import Thread

import pika


class MulticastSender(Thread):
    """
    UDP Multicast sender for broadcasting CoT messages to multicast group.
    Subscribes to RabbitMQ 'cot' fanout exchange and broadcasts to multicast.
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
        self.multicast_ttl = app_context.app.config.get("OTS_MULTICAST_TTL")
        self.enabled = app_context.app.config.get("OTS_ENABLE_MULTICAST")
        self.send_enabled = app_context.app.config.get("OTS_MULTICAST_SEND")

    def run(self):
        if not self.enabled or not self.send_enabled:
            self.logger.info("Multicast sender is disabled")
            return

        try:
            # Create UDP socket for multicast
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

            # Set multicast TTL (time to live)
            # TTL of 1 = local network only, higher values allow routing
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack('b', self.multicast_ttl))

            # Optional: set multicast loop (allow receiving own messages)
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)

            self.logger.info(f"Multicast sender initialized to {self.multicast_address}:{self.multicast_port} (TTL={self.multicast_ttl})")

            # Initialize RabbitMQ connection and subscribe to 'cot' exchange
            self.init_rabbitmq()

            # Start consuming messages from RabbitMQ
            self.logger.info("Multicast sender starting to consume RabbitMQ messages")
            self.rabbit_channel.start_consuming()

        except Exception as e:
            self.logger.error(f"Failed to start multicast sender: {e}")
            self.logger.error(traceback.format_exc())
        finally:
            self.cleanup()

    def init_rabbitmq(self):
        """Initialize RabbitMQ connection and subscribe to 'cot' fanout exchange"""
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

            # Declare a queue for this consumer (auto-delete when sender stops)
            result = self.rabbit_channel.queue_declare(queue='', exclusive=True, auto_delete=True)
            queue_name = result.method.queue

            # Bind to the 'cot' fanout exchange (where all CoT messages are broadcast)
            self.rabbit_channel.queue_bind(exchange='cot', queue=queue_name)

            # Set up consumer callback
            self.rabbit_channel.basic_consume(queue=queue_name, on_message_callback=self.on_message, auto_ack=True)

            self.logger.info("Multicast sender connected to RabbitMQ 'cot' exchange")

        except Exception as e:
            self.logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise

    def on_message(self, ch, method, properties, body):
        """
        Callback for RabbitMQ messages - broadcasts CoT to multicast group

        Args:
            ch: Channel
            method: Method
            properties: Properties
            body: Message body containing CoT data
        """
        try:
            # Parse the message
            message = json.loads(body)
            cot_xml = message.get('cot', '')
            uid = message.get('uid', 'UNKNOWN')

            if not cot_xml:
                self.logger.warning(f"Received message without CoT XML: {uid}")
                return

            # Check if this message came from multicast (avoid loops)
            source = message.get('source', '')
            if source == 'multicast':
                self.logger.debug(f"Skipping multicast send for message from multicast source: {uid}")
                return

            # Send to multicast group
            self.send_multicast(cot_xml, uid)

        except json.JSONDecodeError as e:
            self.logger.warning(f"Failed to decode RabbitMQ message: {e}")
        except Exception as e:
            self.logger.error(f"Error processing RabbitMQ message for multicast: {e}")
            self.logger.error(traceback.format_exc())

    def send_multicast(self, cot_xml, uid):
        """
        Send CoT XML message to multicast group

        Args:
            cot_xml: CoT XML string
            uid: UID of the CoT message
        """
        try:
            # Encode and send
            data = cot_xml.encode('utf-8')
            self.socket.sendto(data, (self.multicast_address, self.multicast_port))
            self.logger.debug(f"Sent CoT to multicast: {uid} ({len(data)} bytes)")

        except Exception as e:
            self.logger.error(f"Failed to send multicast message {uid}: {e}")
            self.logger.error(traceback.format_exc())

    def stop(self):
        """Stop the multicast sender"""
        self.logger.info("Shutting down multicast sender")
        self.shutdown = True

        if self.rabbit_channel:
            try:
                self.rabbit_channel.stop_consuming()
            except Exception as e:
                self.logger.error(f"Error stopping RabbitMQ consumer: {e}")

    def cleanup(self):
        """Clean up resources"""
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                self.logger.error(f"Error closing multicast socket: {e}")

        if self.rabbit_connection:
            try:
                self.rabbit_connection.close()
            except Exception as e:
                self.logger.error(f"Error closing RabbitMQ connection: {e}")

        self.logger.info("Multicast sender has shut down")
