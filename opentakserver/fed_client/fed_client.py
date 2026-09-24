import asyncio
import logging
import os
import sys
import uuid
from logging.handlers import TimedRotatingFileHandler

from pika.channel import Channel
from pika.spec import Basic, BasicProperties

import colorlog
import grpc
import sqlalchemy
import yaml
from flask import Flask, jsonify
from flask_security import SQLAlchemyUserDatastore
from flask_security.models import fsqla

import opentakserver
from opentakserver.rabbitmq_client import RabbitMQClient

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
from opentakserver.models.CITrap import CITrap
from opentakserver.defaultconfig import DefaultConfig
from opentakserver.extensions import logger, db
from opentakserver.models.FederationConnection import FederationConnection
from opentakserver.models.WebAuthn import WebAuthn
from opentakserver.proto import fig_pb2_grpc, fig_pb2


class FedDaemon(RabbitMQClient):
    fed_connection = None

    def __init__(self, context, connection_id: int):
        self.connection_id = connection_id
        self.connection = None
        self.receive_queue = asyncio.Queue()
        self.federated_groups_queue = asyncio.Queue()
        self.server_rol_queue = asyncio.Queue()
        self.client_groups_queue = asyncio.Queue()
        self.send_queue = asyncio.Queue()
        self.background_tasks = set()
        self.client_event_stream_connected = False
        self.server_event_stream_connected = False

        self.rabbitmq_channel = None

        logger.debug("Initializing federation connection")

        connection = db.session.execute(
            db.session.query(FederationConnection).where(FederationConnection.id == connection_id)
        ).first()

        self.fed_connection = connection[0]

        logger.warn(self.fed_connection.to_json())

        super().__init__(context)

        self.channel_creds = grpc.ssl_channel_credentials(
            open(
                os.path.join(
                    self.context.app.config.get("OTS_DATA_FOLDER"),
                    "federation",
                    f"{connection[0].federate.serial_number}.pem",
                ),
                "rb",
            ).read(),
            open(
                os.path.join(
                    self.context.app.config.get("OTS_CA_FOLDER"),
                    "certs",
                    "opentakserver",
                    "opentakserver.nopass.key",
                ),
                "rb",
            ).read(),
            open(
                os.path.join(
                    self.context.app.config.get("OTS_CA_FOLDER"),
                    "certs",
                    "opentakserver",
                    "opentakserver.pem",
                ),
                "rb",
            ).read(),
        )

    async def federation_connect(self):
        async with grpc.aio.secure_channel(
            f"{self.fed_connection.address}:{self.fed_connection.port}",
            self.channel_creds,
            options=(("grpc.ssl_target_name_override", self.fed_connection.federate.common_name),),
            compression=grpc.Compression.Gzip,
        ) as channel:
            stub = fig_pb2_grpc.FederatedChannelStub(channel)
            identity = fig_pb2.Identity()
            identity.name = self.fed_connection.display_name
            identity.uid = str(uuid.uuid4())
            identity.description = str(self.fed_connection.description)
            identity.type = 3
            identity.serverId = self.fed_connection.uid

            subscription = fig_pb2.Subscription()
            subscription.identity.CopyFrom(identity)

            async with asyncio.TaskGroup() as tg:
                task = tg.create_task(self.server_fed_groups_stream(stub, subscription))
                self.background_tasks.add(task)
                task.add_done_callback(self.background_tasks.discard)

                client_task = tg.create_task(self.client_event_stream(stub, subscription))
                self.background_tasks.add(client_task)
                client_task.add_done_callback(self.background_tasks.discard)

                server_rol_task = tg.create_task(self.server_rol(stub))
                self.background_tasks.add(server_rol_task)
                server_rol_task.add_done_callback(self.background_tasks.discard)

                client_fed_group = tg.create_task(self.client_fed_group_stream(stub))
                self.background_tasks.add(client_fed_group)
                client_fed_group.add_done_callback(self.background_tasks.discard)

                server_event_stream = tg.create_task(self.server_event_stream(stub))
                self.background_tasks.add(server_event_stream)
                server_event_stream.add_done_callback(self.background_tasks.discard)

                client_health = fig_pb2.ClientHealth()
                client_health.status = fig_pb2.ClientHealth.ServingStatus.SERVING
                health_task = tg.create_task(self.check_health(stub))
                self.background_tasks.add(health_task)
                health_task.add_done_callback(self.background_tasks.discard)

    async def server_fed_groups_stream(self, stub, subscription):
        server_fed_groups = stub.ServerFederateGroupsStream(subscription)
        async for group in server_fed_groups:
            self.federated_groups_queue.put_nowait(group)
            logger.debug(group)

    async def client_event_stream(self, stub, subscription):
        ts_version = fig_pb2.TakServerVersion()
        ts_version.major = opentakserver.__version_tuple__[0]
        ts_version.minor = opentakserver.__version_tuple__[1]
        ts_version.patch = opentakserver.__version_tuple__[2]
        branch = ""
        for b in opentakserver.__version_tuple__[3:]:
            branch = branch + " " + str(b)
        ts_version.branch = branch.strip()
        ts_version.variant = "OpenTAKServer"

        subscription.version.CopyFrom(ts_version)

        logger.debug(subscription)

        client_stream = stub.ClientEventStream(subscription)
        self.client_event_stream_connected = True

        try:
            async for a in client_stream:
                self.receive_queue.put_nowait(a)
                logger.debug(a)
        except BaseException as e:
            logger.error(e)
            await self.client_event_stream(stub, subscription)

    async def server_rol(self, stub):
        logger.error("server_rol")
        server_rol = stub.ServerROLStream(self.server_rol_queue)

        # while True:
        #    server_rol = await self.server_rol_queue.get()
        #    logger.info(f"Received a server rol message: {server_rol}")

    async def client_fed_group_stream(self, stub):
        logger.error("client_fed_group_stream")

        fed_group = fig_pb2.FederateGroups()
        fed_group.federateGroups.append("__ANON__")

        fed_hops = fig_pb2.FederateHops()
        fed_hops.maxHops = -1
        fed_hops.currentHops = 1
        fed_hops.CopyFrom(fed_hops)

        self.client_groups_queue.put_nowait(fed_group)

        stub.ClientFederateGroupsStream(self.client_groups_queue)
        # while True:
        #    a = await self.client_groups_queue.get()
        #    logger.error(f"Received a client_fed_group_stream message: {a}")

    async def server_event_stream(self, stub):
        server_event = stub.ServerEventStream(self.send_queue)
        self.server_event_stream_connected = True

    async def check_health(self, stub):
        client_health = fig_pb2.ClientHealth()
        client_health.status = fig_pb2.ClientHealth.ServingStatus.SERVING

        # TODO: Have a proper exit condition
        while True:
            await asyncio.sleep(5)
            health = await stub.HealthCheck(client_health)

    def event_deserializer(self, data: bytes):
        logger.warn(f"Got some bytes: {data.hex()}")

    def on_channel_open(self, channel):
        self.rabbitmq_channel = channel
        self.rabbitmq_channel.queue_bind(
            queue="fed_daemon",
            exchange="fed_daemon",
            routing_key=f"fed_daemon.{self.fed_connection.display_name}.#",
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


def main():
    with app.app_context():
        connections = db.session.execute(db.session.query(FederationConnection)).scalars()

        for connection in connections:
            connection_id = connection.id
            # if os.fork() == 0:
            logger.info(f"Launching connection {connection.display_name}")
            daemon = FedDaemon(app.app_context(), connection_id)
            asyncio.run(daemon.federation_connect(), debug=app.config.get("DEBUG"))


if __name__ == "__main__":
    main()
