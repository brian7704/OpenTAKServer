import argparse
import asyncio
import logging
import os
import signal
import sys
import traceback
import uuid
from logging.handlers import TimedRotatingFileHandler

import colorlog
import grpc
import pika
import sqlalchemy
import yaml
from flask import Flask
from flask_security import SQLAlchemyUserDatastore
from flask_security.models import fsqla
from sqlalchemy import select

import opentakserver
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
from opentakserver.models.FederationGroups import FederationGroups
from opentakserver.models.CITrap import CITrap
from opentakserver.rabbitmq_client import RabbitMQClient
from opentakserver.extensions import db, logger


class FedDaemon(RabbitMQClient):
    def __init__(self, connection_id: int):
        signal.signal(signal.SIGINT, self.sig_handler)
        self.shutdown = False
        self.connection = None
        self.receive_queue = asyncio.Queue()
        self.federated_groups_queue = asyncio.Queue()
        self.server_rol_queue = asyncio.Queue()
        self.client_groups_queue = asyncio.Queue()
        self.send_queue = asyncio.Queue()
        self.background_tasks = set()
        self.client_event_stream_connected = False
        self.server_event_stream_connected = False
        self.queue_bound = False
        self.fed_connection: FederationConnection | None = None
        self.enabled = False
        self.connected = False
        self.rabbitmq_channel: pika.channel.Channel | None = None
        self.streams = []
        self.app = None

        self.create_app()

        logger.debug("Initializing federation connection")

        super().__init__(self.app.app_context())

        with self.app.app_context():
            query = select(FederationConnection).filter_by(id=connection_id)
            connection = self.db.session.execute(query).scalar()
            self.fed_connection = connection
            if not self.fed_connection.enabled:
                logger.warning(
                    f"Federation connection {self.fed_connection.display_name} is disabled"
                )
                return
            else:
                self.enabled = True
                logger.info(f"{self.fed_connection.display_name} {self.fed_connection.address}")

            self.channel_creds = grpc.ssl_channel_credentials(
                open(
                    os.path.join(
                        self.app.config.get("OTS_DATA_FOLDER"),
                        "federation",
                        f"{self.fed_connection.federate.serial_number}.pem",
                    ),
                    "rb",
                ).read(),
                open(
                    os.path.join(
                        self.app.config.get("OTS_CA_FOLDER"),
                        "certs",
                        "opentakserver",
                        "opentakserver.nopass.key",
                    ),
                    "rb",
                ).read(),
                open(
                    os.path.join(
                        self.app.config.get("OTS_CA_FOLDER"),
                        "certs",
                        "opentakserver",
                        "opentakserver.pem",
                    ),
                    "rb",
                ).read(),
            )

        self.bind_queue()

    def stop(self):
        self.shutdown = True
        logger.warning(
            f"Federation connection {self.fed_connection.display_name} is shutting down..."
        )
        for stream in self.streams:
            stream.cancel()

    def sig_handler(self, sig, frame):
        logger.warning(f"Caught CTRL+C, shutting down...")
        self.stop()

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
            identity.type = fig_pb2.Identity.FEDERATION_TAK_CLIENT
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

                self.connected = True

    async def server_fed_groups_stream(self, stub, subscription):
        server_fed_groups = stub.ServerFederateGroupsStream(subscription)
        self.streams.append(server_fed_groups)

        try:
            async for group in server_fed_groups:
                self.federated_groups_queue.put_nowait(group)
                logger.debug(group)
        except asyncio.CancelledError:
            logger.debug("Server group stream is cancelled")
        except BaseException as e:
            logger.error(f"Server Group Stream Error: {e}")
            logger.debug(traceback.format_exc())
            await asyncio.sleep(self.fed_connection.reconnect_interval)
            await self.client_event_stream(stub, subscription)

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
        self.streams.append(client_stream)
        self.client_event_stream_connected = True

        try:
            async for a in client_stream:
                self.receive_queue.put_nowait(a)
                logger.debug(a)
        except asyncio.CancelledError:
            logger.debug("Client event stream is cancelled")
        except BaseException as e:
            logger.error(f"Client Event Stream Error: {e}")
            logger.debug(traceback.format_exc())
            await asyncio.sleep(self.fed_connection.reconnect_interval)
            await self.client_event_stream(stub, subscription)

    async def server_rol(self, stub):
        server_rol = stub.ServerROLStream(self.server_rol_queue)

    async def client_fed_group_stream(self, stub):
        fed_group = fig_pb2.FederateGroups()
        fed_group.federateGroups.append("__ANON__")

        fed_hops = fig_pb2.FederateHops()
        fed_hops.maxHops = -1
        fed_hops.currentHops = 1
        fed_group.federateHops.CopyFrom(fed_hops)

        self.client_groups_queue.put_nowait(fed_group)

        stub.ClientFederateGroupsStream(self.client_groups_queue)

    async def server_event_stream(self, stub):
        server_event = stub.ServerEventStream(self.send_queue)
        self.server_event_stream_connected = True

    async def check_health(self, stub):
        client_health = fig_pb2.ClientHealth()
        client_health.status = fig_pb2.ClientHealth.ServingStatus.SERVING

        while not self.shutdown:
            # Do not remove this line. For whatever magic asyncio reason that I hope to understand one day,
            # this loop doesn't work if `await asyncio.sleep(5)` is the first line in the loop.
            logger.debug("Pinging federate server")
            await asyncio.sleep(5)
            health = await stub.HealthCheck(client_health)
            logger.debug(f"Server health is {health}")

    def event_deserializer(self, data: bytes):
        logger.warn(f"Got some bytes: {data.hex()}")

    def on_channel_open(self, channel):
        self.rabbitmq_channel = channel
        self.bind_queue()

    def bind_queue(self):
        if (
            self.fed_connection is not None
            and self.rabbitmq_channel is not None
            and not self.queue_bound
        ):
            logger.debug(f"binding queue {self.fed_connection.display_name}")
            self.rabbitmq_channel.queue_declare(queue=self.fed_connection.display_name)
            self.rabbitmq_channel.queue_bind(
                queue=self.fed_connection.display_name,
                exchange="federation",
                routing_key=f"{self.fed_connection.display_name}.#",
            )
            self.rabbitmq_channel.basic_consume(
                queue=self.fed_connection.display_name,
                on_message_callback=self.on_message,
                auto_ack=True,
            )
            self.queue_bound = True

    def on_message(
        self,
        unused_channel: Channel,
        basic_deliver: Basic.Deliver,
        properties: BasicProperties,
        body,
    ):
        logger.info(f"WTF {basic_deliver.routing_key}")
        try:
            topic = basic_deliver.routing_key.split(".")[-1]
        except IndexError:
            self.logger.error(f"Failed to parse topic: {basic_deliver.routing_key}")
            return

        if topic == "enable":
            print(topic)
        elif topic == "disable":
            self.stop()
        elif topic == "new_connection":
            print(topic)

    def enable_fed_connection(self, federation_id: int):
        print("")

    def setup_logging(self):
        level = logging.INFO
        if self.app.config.get("DEBUG"):
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

        os.makedirs(os.path.join(self.app.config.get("OTS_DATA_FOLDER"), "logs"), exist_ok=True)
        fh = TimedRotatingFileHandler(
            os.path.join(self.app.config.get("OTS_DATA_FOLDER"), "logs", "fed_client.log"),
            when=self.app.config.get("OTS_LOG_ROTATE_WHEN"),
            interval=self.app.config.get("OTS_LOG_ROTATE_INTERVAL"),
            backupCount=self.app.config.get("OTS_BACKUP_COUNT"),
        )
        fh.setFormatter(
            logging.Formatter(
                "[%(asctime)s] - fed_client[%(process)d] - %(module)s - %(funcName)s - %(lineno)d - %(levelname)s - %(message)s"
            )
        )
        logger.addHandler(fh)

    def create_app(self):
        self.app = Flask(__name__)
        self.app.config.from_object(DefaultConfig)

        # Load config.yml if it exists
        if os.path.exists(os.path.join(self.app.config.get("OTS_DATA_FOLDER"), "config.yml")):
            self.app.config.from_file(
                os.path.join(self.app.config.get("OTS_DATA_FOLDER"), "config.yml"),
                load=yaml.safe_load,
            )
        else:
            # First run, created config.yml based on default settings
            logger.info("Creating config.yml")
            with open(
                os.path.join(self.app.config.get("OTS_DATA_FOLDER"), "config.yml"), "w"
            ) as config:
                conf = {}
                for option in DefaultConfig.__dict__:
                    if option.isupper():
                        conf[option] = DefaultConfig.__dict__[option]
                config.write(yaml.safe_dump(conf))

        self.setup_logging()
        db.init_app(self.app)

        try:
            fsqla.FsModels.set_db_info(db)
        except sqlalchemy.exc.InvalidRequestError:
            pass

        from opentakserver.models.role import Role
        from opentakserver.models.user import User

        user_datastore = SQLAlchemyUserDatastore(db, User, Role, WebAuthn)


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


def main():
    options = args()
    daemon = FedDaemon(options.connection_id)
    if daemon.enabled:
        asyncio.run(daemon.federation_connect(), debug=True)


if __name__ == "__main__":
    main()
