import base64
import datetime
import json
import logging
import os
import platform
import random
import re
import socketserver
import sys
import traceback
import uuid
from logging.handlers import TimedRotatingFileHandler
from socket import socket, SHUT_RDWR
from threading import Event, Lock, Thread, current_thread
from xml.etree.ElementTree import Element, SubElement, tostring, fromstring, ParseError

import bleach
import colorlog
import flask_wtf
import pika
import sqlalchemy
import yaml
from bs4 import BeautifulSoup
from flask import Flask
from flask_ldap3_login import AuthenticationResponseStatus
from flask_security import SQLAlchemyUserDatastore, Security, verify_password
from flask_security.models import fsqla
from pika.channel import Channel
from sqlalchemy import insert, update, select

from opentakserver.EmailValidator import EmailValidator
from opentakserver.PasswordValidator import PasswordValidator
from opentakserver.defaultconfig import DefaultConfig
from opentakserver.extensions import logger as ots_logger, db, ldap_manager
from opentakserver.functions import iso8601_string_from_datetime, datetime_from_iso8601_string

# These unused imports are required by SQLAlchemy, don't remove them
from opentakserver.models.Alert import Alert
from opentakserver.models.CasEvac import CasEvac
from opentakserver.models.Certificate import Certificate
from opentakserver.models.Chatrooms import Chatroom
from opentakserver.models.ChatroomsUids import ChatroomsUids
from opentakserver.models.CoT import CoT
from opentakserver.models.DataPackage import DataPackage
from opentakserver.models.DeviceProfiles import DeviceProfiles
from opentakserver.models.EUD import EUD
from opentakserver.models.EUDStats import EUDStats
from opentakserver.models.Group import Group
from opentakserver.models.GroupMission import GroupMission
from opentakserver.models.GroupUser import GroupUser
from opentakserver.models.Marker import Marker
from opentakserver.models.Mission import Mission
from opentakserver.models.MissionChange import MissionChange
from opentakserver.models.MissionContentMission import MissionContentMission
from opentakserver.models.MissionInvitation import MissionInvitation
from opentakserver.models.MissionLogEntry import MissionLogEntry
from opentakserver.models.MissionUID import MissionUID
from opentakserver.models.Point import Point
from opentakserver.models.RBLine import RBLine
from opentakserver.models.Team import Team
from opentakserver.models.VideoRecording import VideoRecording
from opentakserver.models.VideoStream import VideoStream
from opentakserver.models.WebAuthn import WebAuthn
from opentakserver.models.ZMIST import ZMIST


class EudHandler(socketserver.BaseRequestHandler):

    timeout = 1.0
    shutdown = False
    common_name = None
    user = None
    is_ssl = False
    logger = ots_logger
    app = None
    rabbit_connection = None
    rabbit_channel = None
    iothread = None
    is_consuming = False
    is_authenticated = False
    cached_messages = []
    eud = None
    callsign = None
    uid = None
    bound_queues = []
    phone_number = None
    group_memberships = []

    def __init__(self, request: socket, client_address, server):
        # BaseRequestHandler.__init__ immediately calls setup(), handle(), and
        # finish(), so every per-connection field must exist before super().
        self.logger = logging.getLogger()
        self.socket: socket = request
        self.shutdown = False
        self.common_name = None
        self.user = None
        self.rabbit_connection = None
        self.rabbit_channel = None
        self.iothread = None
        self.is_consuming = False
        self.is_authenticated = False
        self.cached_messages = []
        self.eud = None
        self.eud_payload = None
        self.callsign = None
        self.uid = None
        self.bound_queues = []
        self.phone_number = None
        self.group_memberships = []
        self.platform = None
        self.displaced = False
        self.socketio_publish_enabled = True
        self._closed = False
        self._close_lock = Lock()
        super().__init__(request, client_address, server)

    def handle(self):
        cot = ""

        while not self.shutdown:
            try:
                data = self.request.recv(65536)
            except Exception as e:
                self.logger.debug(f"recv failed: {e}")
                break
            if not data:
                self.logger.debug("no data")
                break

            cot += data.decode("utf-8")
            cot_list = re.split("</event>|</auth>", cot)

            if len(cot_list) < 2:
                continue

            for c in cot_list:
                try:
                    if "<event" in c:
                        fromstring(c + "</event>")
                        self.handle_cot(c + "</event>")
                    elif "<auth>" in c:
                        fromstring(c + "</auth>")
                        self.handle_auth(c + "</auth>")
                except ParseError as e:
                    self.logger.error(f"Failed to parse: {e}")
                    cot = c
                    break

            cot = ""

        self.close_connection()

    def pong(self, event):
        if event.attrs.get("type") == "t-x-c-t":
            now = datetime.datetime.now(datetime.timezone.utc)
            stale = now + datetime.timedelta(seconds=10)

            cot = Element(
                "event",
                {
                    "how": "h-g-i-g-o",
                    "type": "t-x-c-t-r",
                    "version": "2.0",
                    "uid": "{}-pong".format(event.attrs.get("uid")),
                    "start": iso8601_string_from_datetime(now),
                    "time": iso8601_string_from_datetime(now),
                    "stale": iso8601_string_from_datetime(stale),
                },
            )
            SubElement(
                cot, "point", {"ce": "9999999", "le": "9999999", "hae": "0", "lat": "0", "lon": "0"}
            )

            try:
                self.request.send(event.encode())
                return True
            except BaseException as e:
                self.logger.error(f"Pong error: {e}")

        return False

    def setup(self):
        self.create_app()
        self.socketio_publish_enabled = self.app.config.get("OTS_ENABLE_SOCKETIO", True)

        # RabbitMQ
        try:
            rabbit_credentials = pika.PlainCredentials(
                self.app.config.get("OTS_RABBITMQ_USERNAME"),
                self.app.config.get("OTS_RABBITMQ_PASSWORD"),
            )
            rabbit_host = self.app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")
            self.rabbit_connection = pika.SelectConnection(
                pika.ConnectionParameters(host=rabbit_host, credentials=rabbit_credentials),
                self.on_connection_open,
                on_close_callback=self.on_close,
            )
            self.rabbit_channel: Channel | None = None
            # Start the pika ioloop in a thread or else it blocks and we can't receive any CoT messages
            self.iothread = Thread(
                target=self.rabbit_connection.ioloop.start, name=f"IOLOOP_{self.common_name}"
            )
            self.iothread.daemon = True
            self.iothread.start()
            self.is_consuming = False
        except BaseException as e:
            self.logger.error("Failed to connect to rabbitmq: {}".format(e))
            return

    def finish(self):
        self.close_connection()

    def displace(self):
        """Stop this socket because a newer connection claimed its EUD UID."""
        self.displaced = True
        self.shutdown = True
        try:
            self.request.shutdown(SHUT_RDWR)
        except OSError:
            pass
        try:
            self.request.close()
        except OSError:
            pass

    def close_connection(self):
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self.shutdown = True

        owns_identity = not self.displaced
        release_identity = getattr(self.server, "release_identity", None)
        if release_identity:
            owns_identity = owns_identity and release_identity(self, self.uid)

        def close_rabbitmq():
            channel = self.rabbit_channel
            try:
                if owns_identity and channel and channel.is_open and self.uid:
                    channel.basic_publish(
                        exchange="cot_parser",
                        body=json.dumps(
                            {
                                "uid": self.uid,
                                "cot": None,
                                "disconnected": True,
                                "user_id": self.user.id if self.user else None,
                            }
                        ),
                        routing_key="cot_parser",
                        properties=pika.BasicProperties(
                            expiration=self.app.config.get("OTS_RABBITMQ_TTL")
                        ),
                    )
                    self.unbind_rabbitmq_queues(channel=channel)
            except BaseException as exc:
                self.logger.warning("RabbitMQ teardown failed for %s: %s", self.uid, exc)
                self.logger.debug(traceback.format_exc())
            finally:
                try:
                    if channel and channel.is_open:
                        channel.close()
                except BaseException:
                    self.logger.debug(traceback.format_exc())
                try:
                    if (
                        self.rabbit_connection
                        and not self.rabbit_connection.is_closing
                        and not self.rabbit_connection.is_closed
                    ):
                        self.rabbit_connection.close()
                except BaseException:
                    self.logger.debug(traceback.format_exc())

        connection = self.rabbit_connection
        if connection and self.iothread and self.iothread.is_alive():
            if current_thread() is self.iothread:
                close_rabbitmq()
            else:
                completed = Event()

                def callback():
                    try:
                        close_rabbitmq()
                    finally:
                        completed.set()

                try:
                    connection.ioloop.add_callback_threadsafe(callback)
                    completed.wait(timeout=2)
                except BaseException:
                    self.logger.debug(traceback.format_exc())
        else:
            close_rabbitmq()

        try:
            self.request.shutdown(SHUT_RDWR)
        except OSError:
            pass
        try:
            self.request.close()
        except OSError:
            pass

        if self.iothread and self.iothread.is_alive() and current_thread() is not self.iothread:
            self.iothread.join(timeout=2)

        self.logger.info(
            "%s disconnected%s",
            self.client_address[0],
            " (displaced)" if not owns_identity else "",
        )

    def create_app(self):
        app = Flask(__name__)
        app.config.from_object(DefaultConfig)

        # Load config.yml if it exists
        if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml")):
            app.config.from_file(
                os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), load=yaml.safe_load
            )
        else:
            # First run, created config.yml based on default settings
            self.logger.info("Creating config.yml")
            with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), "w") as config:
                conf = {}
                for option in DefaultConfig.__dict__:
                    # Fix the sqlite DB path on Windows
                    if (
                        option == "SQLALCHEMY_DATABASE_URI"
                        and platform.system() == "Windows"
                        and DefaultConfig.__dict__[option].startswith("sqlite")
                    ):
                        conf[option] = (
                            DefaultConfig.__dict__[option].replace("////", "///").replace("\\", "/")
                        )
                    elif option.isupper():
                        conf[option] = DefaultConfig.__dict__[option]
                config.write(yaml.safe_dump(conf))

        db.init_app(app)

        if app.config.get("OTS_ENABLE_LDAP"):
            self.logger.info("Enabling LDAP")
            ldap_manager.init_app(app)

        # The rest is required by flask, leave it in
        try:
            fsqla.FsModels.set_db_info(db)
        except sqlalchemy.exc.InvalidRequestError:
            pass

        from opentakserver.models.role import Role
        from opentakserver.models.user import User

        flask_wtf.CSRFProtect(app)
        user_datastore = SQLAlchemyUserDatastore(db, User, Role)
        app.security = Security(
            app, user_datastore, mail_util_cls=EmailValidator, password_util_cls=PasswordValidator
        )

        self.app = app
        return app

    def on_connection_open(self, connection: pika.SelectConnection):
        connection.channel(on_open_callback=self.on_channel_open)

    def _call_on_ioloop(self, callback, timeout=5):
        """Run a RabbitMQ operation on pika's I/O thread and return its result."""
        if not self.rabbit_connection or not self.iothread or current_thread() is self.iothread:
            return callback()

        completed = Event()
        result = {}

        def run_callback():
            try:
                result["value"] = callback()
            except BaseException as exc:
                result["error"] = exc
            finally:
                completed.set()

        self.rabbit_connection.ioloop.add_callback_threadsafe(run_callback)
        if not completed.wait(timeout=timeout):
            raise TimeoutError("RabbitMQ I/O operation timed out")
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def _queue_bind(self, channel, exchange, routing_key, queue):
        binding = {"exchange": exchange, "routing_key": routing_key, "queue": queue}
        channel.queue_bind(exchange=exchange, queue=queue, routing_key=routing_key)
        if binding not in self.bound_queues:
            self.bound_queues.append(binding)

    def _ensure_client_routing_bindings(self, channel=None):
        """Declare queues, bindings, and consumers once an EUD identity is known."""
        if not self.uid or not self.callsign:
            return False
        if self.platform in ("OpenTAK ICU", "Meshtastic", "DMRCOT"):
            return False

        def configure():
            active_channel = channel or self.rabbit_channel
            if not active_channel or not active_channel.is_open:
                return False

            self.logger.debug(f"Declaring queue for {self.callsign} {self.uid}")
            active_channel.queue_declare(queue=self.callsign)
            active_channel.queue_declare(queue=self.uid)

            group_routing_keys = []
            with self.app.app_context():
                if self.is_ssl and self.user:
                    memberships = db.session.execute(
                        db.session.query(GroupUser).filter_by(
                            user_id=self.user.id,
                            direction=Group.OUT,
                            enabled=True,
                        )
                    ).all()
                    self.group_memberships = [membership[0] for membership in memberships]
                    group_routing_keys = [
                        f"{membership.group.name}.OUT" for membership in self.group_memberships
                    ]

            if not group_routing_keys:
                group_routing_keys = ["__ANON__.OUT"]

            for routing_key in group_routing_keys:
                self._queue_bind(active_channel, "groups", routing_key, self.uid)

            self._queue_bind(active_channel, "missions", "missions", self.uid)
            self._queue_bind(active_channel, "dms", self.uid, self.uid)
            self._queue_bind(active_channel, "dms", self.callsign, self.callsign)

            if not self.is_consuming:
                active_channel.basic_consume(
                    queue=self.callsign,
                    on_message_callback=self.on_message,
                    auto_ack=True,
                )
                active_channel.basic_consume(
                    queue=self.uid,
                    on_message_callback=self.on_message,
                    auto_ack=True,
                )
                self.is_consuming = True
            return True

        return self._call_on_ioloop(configure)

    def _publish_socketio_eud(self, data):
        if not self.socketio_publish_enabled or not data:
            return

        def publish():
            channel = self.rabbit_channel
            if not channel or not channel.is_open:
                return
            message = {
                "method": "emit",
                "event": "eud",
                "data": data,
                "namespace": "/socket.io",
                "room": None,
                "skip_sid": [],
                "callback": None,
                "binary": False,
                "host_id": uuid.uuid4().hex,
            }
            channel.basic_publish(
                "flask-socketio",
                "",
                json.dumps(message),
                properties=pika.BasicProperties(
                    expiration=self.app.config.get("OTS_RABBITMQ_TTL")
                ),
            )

        self._call_on_ioloop(publish)

    def on_channel_open(self, channel: Channel):
        self.logger.debug(f"Opening RabbitMQ channel for {self.callsign or self.client_address[0]}")
        self.rabbit_channel = channel
        self.is_consuming = False
        self.rabbit_channel.add_on_close_callback(self.on_channel_close)

        if self.socketio_publish_enabled:
            self.rabbit_channel.exchange_declare(
                exchange="flask-socketio",
                durable=False,
                exchange_type="fanout",
                auto_delete=False,
            )

        if self.uid and self.callsign:
            try:
                self._ensure_client_routing_bindings(channel)
            except BaseException as exc:
                self.logger.warning("Failed to restore EUD routing for %s: %s", self.uid, exc)

        cached_messages = list(self.cached_messages)
        self.cached_messages.clear()
        for message in cached_messages:
            self.publish_cot(message)

        # Publish the EUD info to flask-socketio for the web UI map
        if self.eud_payload:
            self._publish_socketio_eud(self.eud_payload)

    def on_channel_close(self, channel: Channel, error):
        self.logger.error(
            f"RabbitMQ channel closed for {self.callsign or self.client_address[0]}: {error!r}"
        )
        if channel is self.rabbit_channel:
            self.rabbit_channel = None
        self.is_consuming = False

        err_text = str(error)
        if "flask-socketio" in err_text and ("NOT_FOUND" in err_text or "404" in err_text):
            self.socketio_publish_enabled = False

        if self.shutdown:
            return

        if (
            self.rabbit_connection
            and not self.rabbit_connection.is_closing
            and not self.rabbit_connection.is_closed
        ):
            try:
                self.rabbit_connection.channel(on_open_callback=self.on_channel_open)
                self.logger.warning(
                    "Attempting RabbitMQ channel recovery for %s",
                    self.callsign or self.client_address[0],
                )
                return
            except BaseException as exc:
                self.logger.error("RabbitMQ channel recovery failed: %s", exc)

        self.shutdown = True
        try:
            self.request.shutdown(SHUT_RDWR)
        except OSError:
            pass

    def on_close(self, connection, error):
        connection.ioloop.stop()
        self.logger.info("Connection closed for {}: {}".format(self.client_address[0], error))

    def on_message(self, unused_channel, basic_deliver, properties, body):
        try:
            body = json.loads(body)
            if body["uid"] != self.uid:
                self.request.send(body["cot"].encode())
        except BaseException as e:
            self.logger.error(f"{self.callsign}: {e}, closing socket")
            self.close_connection()
            self.logger.error(traceback.format_exc())

    def handle_auth(self, auth: str):
        self.logger.debug(auth)
        if auth:
            auth = BeautifulSoup(auth, "xml")
        if self.is_ssl and not self.is_authenticated and (auth or self.common_name):
            user = None
            with self.app.app_context():
                if auth:
                    cot = auth.find("cot")
                    if cot:
                        username = cot.attrs["username"]
                        password = cot.attrs["password"]
                        uid = cot.attrs["uid"]

                        if self.app.config.get("OTS_ENABLE_LDAP"):
                            result = ldap_manager.authenticate(username, password)

                            if result.status == AuthenticationResponseStatus.success:
                                # Keep this import here to avoid a circular import when OTS is started
                                from opentakserver.blueprints.ots_api.ldap_api import save_user

                                self.user = save_user(
                                    result.user_dn,
                                    result.user_id,
                                    result.user_info,
                                    result.user_groups,
                                )

                                try:
                                    eud = db.session.execute(
                                        db.session.query(EUD).filter_by(uid=uid)
                                    ).first()[0]
                                    self.logger.debug(
                                        "Associating EUD uid {} to user {}".format(
                                            eud.uid, self.user.username
                                        )
                                    )
                                    eud.user_id = self.user.id
                                    db.session.commit()
                                except:
                                    self.logger.debug(
                                        "This is a new eud: {} {}".format(uid, self.user.username)
                                    )
                                    eud = EUD()
                                    eud.uid = uid
                                    eud.user_id = self.user.id
                                    eud.callsign = self.callsign
                                    db.session.add(eud)
                                    db.session.commit()

                            else:
                                self.close_connection()
                                return

                        else:
                            user = self.app.security.datastore.find_user(username=username)
                elif self.common_name:
                    user = self.app.security.datastore.find_user(username=self.common_name)

                if not user:
                    self.logger.warning("User {} does not exist".format(self.common_name))
                    self.close_connection()
                    return
                elif not user.active:
                    self.logger.warning("User {} is deactivated, disconnecting".format(username))
                    self.close_connection()
                    return
                elif self.common_name:
                    self.logger.info("{} is ID'ed by cert".format(user.username))
                    self.is_authenticated = True
                    self.user = user
                elif verify_password(password, user.password):
                    self.logger.info("Successful login from {}".format(username))
                    self.is_authenticated = True
                    self.user = user
                    try:
                        eud = db.session.execute(db.session.query(EUD).filter_by(uid=uid)).first()[
                            0
                        ]
                        self.logger.debug(
                            "Associating EUD uid {} to user {}".format(eud.uid, user.username)
                        )
                        eud.user_id = user.id
                        db.session.commit()
                    except:
                        self.logger.debug("This is a new eud: {} {}".format(uid, user.username))
                        eud = EUD()
                        eud.uid = uid
                        eud.user_id = user.id
                        db.session.add(eud)
                        db.session.commit()

                else:
                    self.logger.warning("Wrong password for user {}".format(username))
                    self.close_connection()
                    return

    def handle_cot(self, cot):
        self.logger.debug(cot)
        event = BeautifulSoup(cot, "xml").find("event")

        # If this client is connected via ssl, make sure they're authenticated
        # before accepting any data from them
        if self.is_ssl and not self.is_authenticated:
            self.logger.warning("EUD isn't authenticated, ignoring")
            return

        if self.pong(event):
            return

        if event and not self.uid:
            self.parse_device_info(event)
            # Close the DB connection once the EUD is authenticated and identified
            with self.app.app_context():
                db.session.close()
                db.engine.dispose()

        self.publish_cot(event)

    def publish_cot(self, event):
        if not event:
            return

        channel = self.rabbit_channel
        if not channel or not channel.is_open:
            self.cached_messages.append(event)
            self.logger.error("RabbitMQ channel is closed, not publishing cot")
            return

        def publish():
            active_channel = self.rabbit_channel
            if not active_channel or not active_channel.is_open:
                raise RuntimeError("RabbitMQ channel is closed")

            body = json.dumps({"uid": self.uid, "cot": str(event)})
            active_channel.basic_publish(
                exchange="firehose",
                body=body,
                routing_key="",
                properties=pika.BasicProperties(
                    expiration=self.app.config.get("OTS_RABBITMQ_TTL")
                ),
            )
            active_channel.basic_publish(
                exchange="cot_parser",
                body=json.dumps(
                    {
                        "uid": self.uid,
                        "cot": str(event),
                        "user_id": self.user.id if self.user else None,
                    }
                ),
                routing_key="cot_parser",
                properties=pika.BasicProperties(
                    expiration=self.app.config.get("OTS_RABBITMQ_TTL")
                ),
            )

        try:
            self._call_on_ioloop(publish)
        except BaseException as exc:
            self.logger.error("CoT publish failed for %s: %s", self.uid, exc)
            self.cached_messages.append(event)

    def parse_device_info(self, event):
        # EUDs running the Meshtastic and dmrcot plugins can relay messages from their RF networks to the server
        # so we want to use the UID of the "off grid" EUD, not the relay EUD
        contact = event.find("contact")
        takv = event.find("takv")
        event_type = event.attrs.get("type", "")

        # Shapes and annotations can contain temporary contact identities.  A
        # connection identity must come from SA or explicit TAK client metadata.
        if not event_type.startswith("a-") and not takv:
            return

        if takv or contact:
            uid = event.attrs.get("uid")
        else:
            return

        contact = event.find("contact")

        # Only assume it's an EUD if it's got a <contact> tag
        if contact and uid and not uid.endswith("ping") and (self.user or not self.is_ssl):
            self.uid = uid
            device = operating_system = platform = version = None
            if takv:
                device = takv.attrs["device"] if "device" in takv.attrs else None
                operating_system = takv.attrs["os"] if "os" in takv.attrs else None
                platform = takv.attrs["platform"] if "platform" in takv.attrs else None
                version = takv.attrs["version"] if "version" in takv.attrs else None
            self.platform = platform

            if "callsign" in contact.attrs:
                self.callsign = contact.attrs["callsign"]

                claim_identity = getattr(self.server, "claim_identity", None)
                if claim_identity:
                    claim_identity(self, self.uid)

                if self.rabbit_channel and self.rabbit_channel.is_open:
                    try:
                        self._ensure_client_routing_bindings()
                    except BaseException as exc:
                        self.logger.warning(
                            "Deferring EUD routing setup for %s: %s", self.uid, exc
                        )

            if "phone" in contact.attrs and contact.attrs["phone"]:
                self.phone_number = contact.attrs["phone"]

            with self.app.app_context():
                __group = event.find("__group")
                team = Team()

                if __group:
                    team.name = bleach.clean(__group.attrs["name"])

                    try:
                        chatroom = db.session.execute(
                            select(Chatroom).filter(Chatroom.name == team.name)
                        ).first()[0]
                        team.chatroom_id = chatroom.id
                    except TypeError:
                        chatroom = None

                    try:
                        db.session.add(team)
                        db.session.commit()
                    except sqlalchemy.exc.IntegrityError:
                        db.session.rollback()
                        team = db.session.execute(
                            select(Team).filter(Team.name == __group.attrs["name"])
                        ).first()[0]
                        if not team.chatroom_id and chatroom:
                            team.chatroom_id = chatroom.id
                            db.session.execute(
                                update(Team)
                                .filter(Team.name == chatroom.id)
                                .values(chatroom_id=chatroom.id)
                            )

                try:
                    eud = db.session.execute(select(EUD).filter_by(uid=uid)).first()[0]
                except:
                    eud = EUD()

                eud.uid = uid
                if self.callsign:
                    eud.callsign = self.callsign
                if device:
                    eud.device = device

                eud.os = operating_system
                eud.platform = platform
                eud.version = version
                eud.phone_number = self.phone_number
                eud.last_event_time = datetime_from_iso8601_string(event.attrs["start"])
                eud.last_status = "Connected"
                eud.user_id = self.user.id if self.user else None

                # Set a Meshtastic ID for TAK EUDs to be identified by in the Meshtastic network
                if not eud.meshtastic_id and eud.platform != "Meshtastic":
                    meshtastic_id = "{:x}".format(int.from_bytes(os.urandom(4), "big"))
                    while len(meshtastic_id) < 8:
                        meshtastic_id = "0" + meshtastic_id
                    eud.meshtastic_id = int(meshtastic_id, 16)
                elif not eud.meshtastic_id and eud.platform == "Meshtastic":
                    try:
                        eud.meshtastic_id = int(takv.attrs["meshtastic_id"], 16)
                    except:
                        meshtastic_id = "{:x}".format(int.from_bytes(os.urandom(4), "big"))
                        while len(meshtastic_id) < 8:
                            meshtastic_id = "0" + meshtastic_id
                        eud.meshtastic_id = int(meshtastic_id, 16)

                # Get the Meshtastic device's mac address or generate a random one for TAK EUDs
                if takv and "macaddr" in takv.attrs:
                    eud.meshtastic_macaddr = takv.attrs["macaddr"]
                else:
                    eud.meshtastic_macaddr = base64.b64encode(os.urandom(6)).decode("ascii")

                if __group:
                    eud.team_id = team.id
                    eud.team_role = bleach.clean(__group.attrs["role"])

                try:
                    db.session.add(eud)
                    db.session.commit()
                except sqlalchemy.exc.IntegrityError:
                    db.session.rollback()
                    db.session.execute(
                        update(EUD).where(EUD.uid == eud.uid).values(**eud.serialize())
                    )
                    db.session.commit()

                # If the RabbitMQ channel is open, publish the EUD info to socketio to be displayed on the web UI map.
                # Also save the EUD's info for on_channel_open to publish
                self.eud = eud
                self.eud_payload = eud.to_json()
                if self.rabbit_channel and self.rabbit_channel.is_open:
                    try:
                        self._publish_socketio_eud(self.eud_payload)
                    except BaseException as exc:
                        self.logger.warning("SocketIO EUD publish failed: %s", exc)

    def unbind_rabbitmq_queues(self, channel=None):
        active_channel = channel or self.rabbit_channel
        if (
            self.uid
            and active_channel
            and not active_channel.is_closing
            and not active_channel.is_closed
        ):
            active_channel.queue_unbind(
                queue=self.uid, exchange="missions", routing_key="missions"
            )
            active_channel.queue_unbind(queue=self.uid, exchange="groups")

            for bind in self.bound_queues:
                active_channel.queue_unbind(
                    exchange=bind["exchange"], queue=bind["queue"], routing_key=bind["routing_key"]
                )
