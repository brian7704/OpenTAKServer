import argparse
import asyncio
import functools
import json
import logging
import os
import signal
import sys
import traceback
from logging.handlers import TimedRotatingFileHandler

import colorlog
import grpc
import pika
import sqlalchemy
import yaml
from flask import Flask
from flask_login import current_user
from flask_security import SQLAlchemyUserDatastore
from flask_security.models import fsqla
from sqlalchemy import select
from collections.abc import AsyncIterable

import opentakserver
from opentakserver.fed_client.RabbitMQAsyncClient import RabbitMQAsyncClient
from opentakserver.fed_client.data_converter import federated_event2cot, cot2federated_event
from opentakserver.models.Group import Group
from opentakserver.models.GroupUser import GroupUser
from opentakserver.models.WebAuthn import WebAuthn

from opentakserver.defaultconfig import DefaultConfig

from opentakserver.proto import fig_pb2_grpc, fig_pb2
from opentakserver.proto.fig_pb2 import FederatedEvent
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
from opentakserver.extensions import db, logger, ldap_manager


class FedDaemon(RabbitMQAsyncClient):
    def __init__(self, connection_id: int):
        signal.signal(signal.SIGINT, self.sig_handler)
        self.shutdown = False
        self.connection = None
        self.federated_groups = []
        self.receive_queue = asyncio.Queue()
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
        self.stub = None
        self.grpc_channel = None

        self.create_app()

        self.db = db

        logger.debug("Initializing federation connection")

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

            self.local_groups = self.get_federated_groups()

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

        super().__init__(self.app.app_context())
        asyncio.run(self.federation_connect())

        self.bind_queue()

    def stop(self):
        self.shutdown = True
        super().stop()
        logger.warning(
            f"Federation connection {self.fed_connection.display_name} is shutting down..."
        )
        for stream in self.streams:
            stream.cancel()

        for task in self.background_tasks:
            task.cancel()

        asyncio.get_event_loop().call_soon(self.grpc_channel.close)

    def sig_handler(self, sig, frame):
        logger.warning(f"Caught CTRL+C, shutting down...")
        self.stop()

    async def federation_connect(self):
        asyncio.get_event_loop().add_signal_handler(
            signal.SIGINT, functools.partial(self.sig_handler, sig=signal.SIGINT, frame=None)
        )

        await self.connect()

        async with grpc.aio.secure_channel(
            f"{self.fed_connection.address}:{self.fed_connection.port}",
            self.channel_creds,
            options=(("grpc.ssl_target_name_override", self.fed_connection.federate.common_name),),
            compression=grpc.Compression.Gzip,
        ) as channel:
            self.stub = fig_pb2_grpc.FederatedChannelStub(channel)
            self.grpc_channel = channel
            identity = fig_pb2.Identity()
            identity.name = self.fed_connection.display_name
            identity.uid = self.app.config.get("OTS_NODE_ID")
            identity.description = str(self.fed_connection.description)
            identity.type = fig_pb2.Identity.FEDERATION_TAK_CLIENT
            identity.serverId = self.app.config.get("OTS_NODE_ID")

            subscription = fig_pb2.Subscription()
            subscription.identity.CopyFrom(identity)

            async with asyncio.TaskGroup() as tg:
                task = tg.create_task(self.server_fed_groups_stream(self.stub, subscription))
                self.background_tasks.add(task)
                task.add_done_callback(self.background_tasks.discard)

                client_task = tg.create_task(self.client_event_stream(self.stub, subscription))
                self.background_tasks.add(client_task)
                client_task.add_done_callback(self.background_tasks.discard)

                server_rol_task = tg.create_task(self.server_rol(self.stub))
                self.background_tasks.add(server_rol_task)
                server_rol_task.add_done_callback(self.background_tasks.discard)

                client_fed_group = tg.create_task(self.client_fed_group_stream(self.stub))
                self.background_tasks.add(client_fed_group)
                client_fed_group.add_done_callback(self.background_tasks.discard)

                client_health = fig_pb2.ClientHealth()
                client_health.status = fig_pb2.ClientHealth.ServingStatus.SERVING
                health_task = tg.create_task(self.check_health(self.stub))
                self.background_tasks.add(health_task)
                health_task.add_done_callback(self.background_tasks.discard)

                self.connected = True

    async def server_fed_groups_stream(self, stub, subscription):
        server_fed_groups = stub.ServerFederateGroupsStream(subscription)
        self.streams.append(server_fed_groups)

        try:
            async for group in server_fed_groups:
                self.federated_groups.append(group)
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
            async for federated_event in client_stream:
                logger.debug(federated_event)
                if (
                    federated_event.HasField("federateHops")
                    and self.fed_connection.federate.max_hops > 0
                    and federated_event.federateHops.currentHops
                    > self.fed_connection.federate.max_hops
                ):
                    continue

                if not federated_event.HasField("event"):
                    continue

                if not self.rabbitmq_channel:
                    continue

                if self.fed_connection.federate.automatic_group_matching:
                    for fed_group in federated_event.federateGroups:
                        for local_group in self.local_groups:
                            if fed_group == local_group:
                                string_event = federated_event2cot(federated_event)

                                self.rabbitmq_channel.basic_publish(
                                    exchange="groups",
                                    routing_key=f"{local_group}.OUT",
                                    body=json.dumps(
                                        {
                                            "cot": string_event,
                                            "uid": federated_event.event.uid,
                                        }
                                    ),
                                    properties=pika.BasicProperties(
                                        expiration=self.app.config.get("OTS_RABBITMQ_TTL")
                                    ),
                                )

                                self.rabbitmq_channel.basic_publish(
                                    exchange="firehose",
                                    body=json.dumps(
                                        {"uid": federated_event.event.uid, "cot": string_event}
                                    ),
                                    routing_key="",
                                    properties=pika.BasicProperties(
                                        expiration=self.app.config.get("OTS_RABBITMQ_TTL")
                                    ),
                                )

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
        fed_groups = fig_pb2.FederateGroups()
        nested_groups = fig_pb2.FederateGroups()

        if not len(self.local_groups):
            fed_groups.federateGroups.append("__ANON__")
            nested_groups.federateGroups.append("__ANON__")
        else:
            for local_group in self.local_groups:
                fed_groups.federateGroups.append(local_group)
                nested_groups.federateGroups.append(local_group)

        fed_hops = fig_pb2.FederateHops()
        fed_hops.maxHops = self.fed_connection.federate.max_hops
        fed_hops.currentHops = 1
        nested_groups.federateHops.CopyFrom(fed_hops)

        fed_provenance = fig_pb2.FederateProvenance()
        fed_provenance.federationServerId = self.app.config.get("OTS_NODE_ID")
        fed_provenance.federationServerName = self.app.config.get("OTS_NODE_ID")
        nested_groups.federateProvenance.append(fed_provenance)

        server_health = fig_pb2.ServerHealth()
        server_health.status = fig_pb2.ServerHealth.SERVING
        fed_groups.streamUpdate.CopyFrom(server_health)

        nested_groups.federateGroupHopLimits.CopyFrom(fig_pb2.FederateGroupHopLimits())

        fed_groups.nestedGroups.append(nested_groups)

        self.client_groups_queue.put_nowait(fed_groups)

        async def request_iterator():
            group = self.client_groups_queue.get_nowait()
            yield group

        groups = request_iterator()
        sub = await stub.ClientFederateGroupsStream(groups)

        logger.debug(f"{sub}")

    async def server_event_stream(self, stub, federated_event):
        self.send_queue.put_nowait(federated_event)

        async def request_iterator():
            message = self.send_queue.get_nowait()
            yield message

        messages = request_iterator()

        server_event = await stub.ServerEventStream(messages)
        logger.debug(f"server_response {server_event}")
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

    async def send_event(self, event):
        await self.stub.SendOneEvent(event)

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
            self.rabbitmq_channel.queue_bind(
                queue=self.fed_connection.display_name,
                exchange="federation",
                routing_key="outgoing_messages",
            )
            self.rabbitmq_channel.basic_consume(
                queue=self.fed_connection.display_name,
                on_message_callback=self.on_message,
                auto_ack=True,
            )
            self.queue_bound = True
            self._consuming = True

    def on_message(
        self,
        unused_channel: Channel,
        basic_deliver: Basic.Deliver,
        properties: BasicProperties,
        body,
    ):
        if basic_deliver.routing_key == "outgoing_messages" and self.stub:
            body = json.loads(body)
            federated_event = cot2federated_event(body.get("cot"))
            for group in self.local_groups:
                federated_event.federateGroups.append(group)

            federate_provenance = fig_pb2.FederateProvenance()
            federate_provenance.federationServerId = self.app.config.get("OTS_NODE_ID")
            federated_event.federateProvenance.append(federate_provenance)

            federated_event.federateHops.maxHops = self.fed_connection.federate.max_hops
            federated_event.federateHops.currentHops = 1

            federated_event.federateGroupHopLimits.CopyFrom(fig_pb2.FederateGroupHopLimits())

            server_event_stream = asyncio.create_task(
                self.server_event_stream(self.stub, federated_event)
            )
            self.background_tasks.add(server_event_stream)
            server_event_stream.add_done_callback(self.background_tasks.discard)

            return

        try:
            topic = basic_deliver.routing_key.split(".")[-1]
        except IndexError:
            self.logger.error(f"Failed to parse topic: {basic_deliver.routing_key}")
            return

        if topic == "enable":
            print(topic)
        elif topic == "disable":
            if self._consuming and self.stub:
                self.stop()
        elif topic == "new_connection":
            print(topic)

    def get_federated_groups(self):
        groups = []

        with self.app.app_context():
            federated_groups = self.db.session.execute(
                self.db.session.query(FederationGroups).filter_by(
                    federation_id=self.fed_connection.id, direction="OUT"
                )
            ).scalars()

            for group in federated_groups:
                groups.append(group.group.name)

        return groups

    def get_all_groups(self) -> list:
        if self.app.config.get("OTS_ENABLE_LDAP"):
            groups = ldap_manager.get_user_groups(self.app.config.get("LDAP_BIND_USER_DN"))
            for group in groups:
                if group["cn"].lower().startswith(
                    self.app.config.get("OTS_LDAP_GROUP_PREFIX").lower()
                ) and not (
                    group["cn"].lower().endswith("_read") or group["cn"].lower().endswith("_write")
                ):

                    g = Group()
                    g.id = group["entryuuid"]
                    g.name = group["cn"]
                    g.distinguishedName = group["dn"]
                    g.type = Group.LDAP

                    groups.append(g.to_json())
        else:
            if not current_user.has_role("administrator"):
                groups = self.db.session.execute(
                    self.db.session.query(GroupUser).filter_by(user_id=current_user.id)
                ).scalars()
                # Make sure a group is only added once, not twice for both IN and OUT
                group_names = []
                for group in groups:
                    if group.group.name not in group_names:
                        group_names.append(group.group.name)
                    else:
                        continue
                    groups.append(group.group.to_json())

            else:
                groups = self.db.session.execute(self.db.session.query(Group)).scalars()
                for group in groups:
                    groups.append(group.to_json())

        return groups

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
    parser.add_argument("--connection-id", type=int, default=None, required=True)
    return parser.parse_args()


def main():
    options = args()
    FedDaemon(options.connection_id)


if __name__ == "__main__":
    main()
