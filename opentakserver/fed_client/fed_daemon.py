import argparse
import logging
import os
import sys
import traceback
import uuid
from logging import Logger
from logging.handlers import TimedRotatingFileHandler

import colorlog
import grpc
import sqlalchemy
import yaml
from flask import Flask
from flask_security import SQLAlchemyUserDatastore
from flask_security.models import fsqla
from opentakserver.models.WebAuthn import WebAuthn

from opentakserver.defaultconfig import DefaultConfig

from opentakserver.proto import fig_pb2_grpc, fig_pb2
from pika.channel import Channel
from pika.spec import Basic, BasicProperties

from opentakserver.models.FederationConnection import FederationConnection
from opentakserver.models.Federate import Federate
from opentakserver.models.CoT import CoT
from opentakserver.models.CasEvac import CasEvac
from opentakserver.models.ZMIST import ZMIST
from opentakserver.models.Chatrooms import Chatroom
from opentakserver.models.ChatroomsUids import ChatroomsUids
from opentakserver.models.DataPackage import DataPackage
from opentakserver.models.Certificate import Certificate
from opentakserver.models.EUDStats import EUDStats
from opentakserver.models.DeviceProfiles import DeviceProfiles
from opentakserver.models.VideoStream import VideoStream
from opentakserver.models.VideoRecording import VideoRecording
from opentakserver.models.RBLine import RBLine
from opentakserver.models.Point import Point
from opentakserver.models.Marker import Marker
from opentakserver.models.EUD import EUD
from opentakserver.models.Alert import Alert
from opentakserver.models.Federate import Federate
from opentakserver.models.Mission import Mission
from opentakserver.models.MissionLogEntry import MissionLogEntry
from opentakserver.models.MissionContentMission import MissionContentMission
from opentakserver.models.MissionChange import MissionChange
from opentakserver.models.MissionInvitation import MissionInvitation
from opentakserver.models.GroupMission import GroupMission
from opentakserver.rabbitmq_client import RabbitMQClient
from opentakserver.extensions import db, logger


class FedDaemon(RabbitMQClient):
    connection: FederationConnection

    def __init__(self, context, connection_id: int, logger: Logger):
        super().__init__(context)
        self.connection_id = connection_id
        self.logger = logger

        self.logger.info("Initializing federation connection")

        with self.context:
            connection = db.session.execute(
                db.session.query(FederationConnection).where(
                    FederationConnection.id == connection_id
                )
            ).first()

            logger.warning(connection[0].to_json())

            self.connection = connection[0]

        self.channel_creds = grpc.ssl_channel_credentials(
            open(
                os.path.join(
                    self.context.app.config.get("OTS_DATA_FOLDER"),
                    "federation",
                    f"{connection[0].federate.certificate_file}",
                ),
                "rb",
            ).read(),
            open(
                os.path.join(
                    self.context.app.config.get("OTS_CA_FOLDER"),
                    "certs",
                    "federation",
                    "federation.nopass.key",
                ),
                "rb",
            ).read(),
            open(
                os.path.join(
                    self.context.app.config.get("OTS_CA_FOLDER"),
                    "certs",
                    "federation",
                    "federation.pem",
                ),
                "rb",
            ).read(),
        )

        try:
            self.federation_connect()
        except BaseException as e:
            logger.error(f"Failed to connect to federation server: {e}")
            logger.debug(traceback.format_exc())
            sys.exit(1)

        # https://github.com/grpc/grpc/blob/master/examples/python/hellostreamingworld/async_greeter_client.py

    def federation_connect(self):
        # TODO: get the CN of the federate's cert for the grpc.ssl_target_name_override option
        with grpc.secure_channel(
            f"{self.connection.address}:{self.connection.port}",
            self.channel_creds,
            options=(
                ("grpc.ssl_target_name_override", "federation"),
                ("grpc.grpclb_call_timeout_ms", 0),
            ),
            compression=grpc.Compression.Gzip,
        ) as channel:
            stub = fig_pb2_grpc.FederatedChannelStub(channel)
            identity = fig_pb2.Identity()
            identity.name = self.connection.display_name
            identity.uid = str(uuid.uuid4())
            identity.description = str(self.connection.description)
            identity.type = 3
            identity.serverId = self.connection.uid
            subscription = fig_pb2.Subscription()
            subscription.identity.CopyFrom(identity)

            for response in stub.ClientEventStream(subscription):
                self.logger.warning(f"ClientEventStream response {response}")

    def on_channel_open(self, channel):
        self.rabbitmq_channel = channel
        self.rabbitmq_channel.queue_bind(
            queue="fed_daemon",
            exchange="fed_daemon",
            routing_key=f"fed_daemon.{self.connection.display_name}.#",
        )
        self.rabbitmq_channel.basic_consume(
            queue="fed_daemon", on_message_callback=self.on_message, auto_ack=True
        )

    def on_message(
        self,
        unused_channel: Channel,
        basic_deliver: Basic.Deliver,
        properties: BasicProperties,
        body,
    ):
        try:
            topic = basic_deliver.routing_key.split(".")[-1]
        except IndexError:
            self.logger.error(f"Failed to parse topic: {basic_deliver.routing_key}")
            return

        if topic == "enable":
            print(topic)
        elif topic == "disable":
            print(topic)
        elif topic == "new_connection":
            print(topic)

    def enable_fed_connection(self, federation_id: int):
        print("")


def setup_logging(app):
    level = logging.INFO
    if app.config.get("DEBUG"):
        level = logging.DEBUG
    logger.setLevel(level)

    if sys.stdout.isatty():
        color_log_handler = colorlog.StreamHandler()
        color_log_formatter = colorlog.ColoredFormatter(
            "%(log_color)s[%(asctime)s] - fed_client[%(process)d] - %(module)s - %(funcName)s - %(lineno)d - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S %Z",
        )
        color_log_handler.setFormatter(color_log_formatter)
        logger.addHandler(color_log_handler)
        logger.info("Added color logger")

    os.makedirs(os.path.join(app.config.get("OTS_DATA_FOLDER"), "logs"), exist_ok=True)
    fh = TimedRotatingFileHandler(
        os.path.join(app.config.get("OTS_DATA_FOLDER"), "logs", "fed_client.log"),
        when=app.config.get("OTS_LOG_ROTATE_WHEN"),
        interval=app.config.get("OTS_LOG_ROTATE_INTERVAL"),
        backupCount=app.config.get("OTS_BACKUP_COUNT"),
    )
    fh.setFormatter(
        logging.Formatter(
            "[%(asctime)s] - fed_client[%(process)d] - %(module)s - %(funcName)s - %(lineno)d - %(levelname)s - %(message)s"
        )
    )
    logger.addHandler(fh)


def create_app():
    app = Flask(__name__)
    app.config.from_object(DefaultConfig)

    # Load config.yml if it exists
    if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml")):
        app.config.from_file(
            os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), load=yaml.safe_load
        )
    else:
        # First run, created config.yml based on default settings
        logger.info("Creating config.yml")
        with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), "w") as config:
            conf = {}
            for option in DefaultConfig.__dict__:
                if option.isupper():
                    conf[option] = DefaultConfig.__dict__[option]
            config.write(yaml.safe_dump(conf))

    setup_logging(app)
    db.init_app(app)

    try:
        fsqla.FsModels.set_db_info(db)
    except sqlalchemy.exc.InvalidRequestError:
        pass

    from opentakserver.models.role import Role
    from opentakserver.models.user import User

    user_datastore = SQLAlchemyUserDatastore(db, User, Role, WebAuthn)

    return app


app = create_app()


def args():
    parser = argparse.ArgumentParser()
    """parser.add_argument(
        "--address",
        help=gettext("TAK Server or Fed Hub address to connect to"),
        default=None,
        type=str,
        required=True,
    )
    parser.add_argument("--port", type=int, default=9102)
    parser.add_argument("--reconnect-interval", type=int, default=30)
    parser.add_argument("--unlimited-retries", default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--fed-cert", type=str, default=None, required=True)"""
    parser.add_argument("--connection-id", type=int, default=None, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    options = args()
    daemon = FedDaemon(app.app_context(), options.connection_id, logger=logger)
