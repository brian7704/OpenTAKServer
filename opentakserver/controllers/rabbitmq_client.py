import logging
from threading import Thread
from pika.channel import Channel

import flask_sqlalchemy
import pika


class RabbitMQClient:
    def __init__(self, context, logger, db, socketio):
        self.context = context
        self.logger = logger
        self.db: flask_sqlalchemy.SQLAlchemy = db
        self.socketio = socketio

        self.online_euds = {}
        self.online_callsigns = {}
        self.exchanges = []

        try:
            self.rabbit_connection = pika.SelectConnection(pika.ConnectionParameters(self.context.app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")),
                                                           self.on_connection_open)
            self.rabbit_channel: Channel = None
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
        raise NotImplemented

    def on_close(self, channel, error):
        self.logger.error("cot_controller closing RabbitMQ connection: {}".format(error))

    def on_message(self, unused_channel, basic_deliver, properties, body):
        raise NotImplemented
