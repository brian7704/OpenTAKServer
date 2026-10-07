import asyncio
import traceback

import flask_sqlalchemy
import pika
from flask import Flask
from pika.adapters.asyncio_connection import AsyncioConnection
from pika.channel import Channel

from opentakserver.extensions import socketio, db, logger


class RabbitMQAsyncClient:

    def __init__(self, context: Flask):
        self.context = context
        self.logger = logger
        self.db: flask_sqlalchemy.SQLAlchemy = db
        self.socketio = socketio
        self.rabbit_connection = None
        self.rabbitmq_channel: Channel = None
        self._consuming = False
        self._closing = False

    async def connect(self):
        try:
            logger.info("Connecting...")
            rabbit_credentials = pika.PlainCredentials(
                self.context.app.config.get("OTS_RABBITMQ_USERNAME"),
                self.context.app.config.get("OTS_RABBITMQ_PASSWORD"),
            )
            rabbit_host = self.context.app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")

            self.rabbit_connection = AsyncioConnection(
                parameters=pika.ConnectionParameters(
                    host=rabbit_host, credentials=rabbit_credentials
                ),
                on_open_callback=self.on_connection_open,
            )

            if not self.rabbit_connection.ioloop.is_running():
                self.rabbit_connection.ioloop.run_forever()

        except BaseException as e:
            self.logger.error("Failed to connect to rabbitmq: {}".format(e))
            logger.debug(traceback.format_exc())

    def on_connection_open(self, connection):
        self.rabbit_connection.channel(on_open_callback=self.on_channel_open)
        self.rabbit_connection.add_on_close_callback(self.on_close)
        logger.info("on_connection_open")

    def on_channel_open(self, channel):
        raise NotImplemented

    def on_close(self, channel, error):
        self.logger.error("Closing RabbitMQ connection: {}".format(error))

    def on_message(self, unused_channel, basic_deliver, properties, body):
        raise NotImplemented

    def stop_consuming(self):
        """Tell RabbitMQ that you would like to stop consuming by sending the Basic.Cancel RPC
        command.
        """
        if self.rabbitmq_channel:
            logger.info("Sending a Basic.Cancel RPC command to RabbitMQ")
            self.rabbitmq_channel.close()

    def stop(self, error: str | None):
        """
        Cleanly shutdown the connection to RabbitMQ by stopping the consumer with RabbitMQ.

        When RabbitMQ confirms the cancellation, on_cancelok will be invoked by pika, which will
        then closing the channel and connection. The IOLoop is started again because this method is
        invoked when CTRL-C is pressed raising a KeyboardInterrupt exception. This exception stops
        the IOLoop which needs to be running for pika to communicate with RabbitMQ. All of the
        commands issued prior to starting the IOLoop will be buffered but not processed.
        """
        if not self._closing:
            self._closing = True
            logger.info("Stopping")
            if self._consuming:
                self.stop_consuming()
                if not self.rabbit_connection.ioloop.is_running():
                    self.rabbit_connection.ioloop.run_forever()
            else:
                self.rabbit_connection.ioloop.stop()
            logger.info("Stopped")
