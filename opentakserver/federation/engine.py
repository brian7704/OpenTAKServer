"""Federation v1 engine: connections, RabbitMQ bridging, and supervision.

Data flow
---------

Outbound: each federation connection binds an exclusive queue to the
``firehose`` fanout exchange, which carries every CoT received from a local
EUD. Events pass the per-federate outbound group filter, are converted to
``FederatedEvent`` frames, and written to the TLS socket.

Inbound: frames from the peer are converted back to CoT XML and published to
the ``cot_parser`` exchange like any locally received event, tagged with the
per-federate inbound groups so the parser routes them into the right channels.

Loop prevention is structural: only EUD handlers publish to ``firehose``, and
federated traffic is injected via ``cot_parser`` only - so an event that
arrived over federation can never be read back off ``firehose`` and
re-federated. This matches TAK Server's point-to-point behavior (multi-hop
forwarding is the Federation Hub's job, not v1's).

Federates are identified by the SHA-256 fingerprint of their TLS certificate.
Unknown inbound federates (their CA is trusted, or the TLS handshake would
have failed) are auto-registered with empty group lists, so no traffic flows
until an administrator assigns groups - the same "nothing flows until groups
are configured" posture as TAK Server. Outbound fingerprints are pinned on
first connect.
"""

import json
import socket
import ssl
import threading
import time
import traceback
from datetime import datetime, timezone

import pika
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from opentakserver.federation import truststore
from opentakserver.federation.codec import DEFAULT_MAX_FRAME_BYTES, FrameDecoder, encode_frame
from opentakserver.federation.mapper import (
    EXCLUDED_COT_TYPES,
    contact_event,
    cot_to_federated_event,
    federated_event_to_cot,
    sender_identity,
)
from opentakserver.federation.proto import fig_pb2

ANON_GROUP = "__ANON__"
RECV_BYTES = 65536
HANDSHAKE_TIMEOUT_SECONDS = 15
DIALER_SCAN_SECONDS = 5
GROUP_CACHE_SECONDS = 30


class Directory:
    """Database lookups the engine needs, isolated for testability."""

    def __init__(self, app, logger):
        self.app = app
        self.logger = logger
        self._group_cache = {}

    def connected_contacts(self) -> dict[str, str]:
        from opentakserver.extensions import db
        from opentakserver.models.EUD import EUD

        with self.app.app_context():
            rows = db.session.execute(
                db.session.query(EUD).filter_by(last_status="Connected")
            ).all()
            return {row[0].uid: row[0].callsign or row[0].uid for row in rows}

    def sender_groups(self, uid: str) -> set[str]:
        """Groups the EUD with this uid publishes into (its user's IN groups).

        Mirrors cot_parser.route_cot: no user or no IN memberships means the
        __ANON__ group.
        """
        cached = self._group_cache.get(uid)
        if cached and time.monotonic() - cached[0] < GROUP_CACHE_SECONDS:
            return cached[1]

        from opentakserver.extensions import db
        from opentakserver.models.EUD import EUD
        from opentakserver.models.Group import Group
        from opentakserver.models.GroupUser import GroupUser

        groups = {ANON_GROUP}
        with self.app.app_context():
            eud = db.session.execute(db.session.query(EUD).filter_by(uid=uid)).first()
            if eud and eud[0].user_id:
                memberships = db.session.execute(
                    db.session.query(GroupUser).filter_by(
                        user_id=eud[0].user_id, direction=Group.IN, enabled=True
                    )
                ).all()
                if memberships:
                    groups = {m[0].group.name for m in memberships}

        self._group_cache[uid] = (time.monotonic(), groups)
        return groups

    def ensure_federated_eud(self, uid: str, callsign: str | None, federate_name: str) -> None:
        """Register a minimal EUD row for a federated entity.

        Federated tracks reference EUDs that live on the peer server, but the
        cot table's foreign key requires the sender to be a known local EUD.
        Registering a lightweight row (like TAK Server's federated contacts)
        lets federated CoT persist and route, and surfaces the remote unit in
        the EUD list. Idempotent; callsign is best-effort (it may collide with
        a local callsign, which is unique).
        """
        from opentakserver.extensions import db
        from opentakserver.models.EUD import EUD

        with self.app.app_context():
            existing = db.session.execute(db.session.query(EUD).filter_by(uid=uid)).first()
            now = datetime.now(timezone.utc)
            if existing:
                db.session.execute(
                    update(EUD)
                    .where(EUD.uid == uid)
                    .values(last_event_time=now, last_status=f"Federated ({federate_name})")
                )
                db.session.commit()
                return

            for attempt_callsign in (callsign, None):
                eud = EUD()
                eud.uid = uid
                eud.callsign = attempt_callsign
                eud.last_status = f"Federated ({federate_name})"
                eud.last_event_time = now
                try:
                    db.session.add(eud)
                    db.session.commit()
                    return
                except IntegrityError:
                    db.session.rollback()  # callsign collision or race; retry bare

    def remove_federated_eud(self, uid: str) -> None:
        from opentakserver.extensions import db
        from opentakserver.models.EUD import EUD

        with self.app.app_context():
            db.session.execute(
                update(EUD).where(EUD.uid == uid).values(last_status="Disconnected")
            )
            db.session.commit()

    def federate_config(self, federate_id: int) -> dict | None:
        from opentakserver.extensions import db
        from opentakserver.models.Federation import Federation

        with self.app.app_context():
            row = db.session.get(Federation, federate_id)
            return row.serialize() if row else None

    def outbound_federates(self) -> list[dict]:
        from opentakserver.extensions import db
        from opentakserver.models.Federation import Federation

        with self.app.app_context():
            rows = db.session.execute(
                db.session.query(Federation).filter_by(outbound=True, enabled=True)
            ).all()
            return [row[0].serialize() for row in rows]

    def find_or_create_inbound(self, fingerprint: str, common_name: str | None, address: str):
        from opentakserver.extensions import db
        from opentakserver.models.Federation import Federation

        with self.app.app_context():
            row = db.session.execute(
                db.session.query(Federation).filter_by(cert_fingerprint=fingerprint)
            ).first()
            if row:
                return row[0].serialize()

            row = Federation()
            row.name = common_name or f"federate-{fingerprint[:12]}"
            row.address = address
            row.outbound = False
            row.enabled = True
            row.cert_fingerprint = fingerprint
            row.cert_common_name = common_name
            row.inbound_groups = []
            row.outbound_groups = []
            db.session.add(row)
            db.session.commit()
            self.logger.info(
                f"Registered new inbound federate '{row.name}' ({fingerprint[:12]}) with no "
                "groups - assign groups to start the flow of data"
            )
            return row.serialize()

    def pin_fingerprint(self, federate_id: int, fingerprint: str, common_name: str | None):
        from opentakserver.extensions import db
        from opentakserver.models.Federation import Federation

        with self.app.app_context():
            row = db.session.get(Federation, federate_id)
            if row and not row.cert_fingerprint:
                row.cert_fingerprint = fingerprint
                row.cert_common_name = common_name
                db.session.commit()

    def record_state(self, federate_id: int, connected: bool, error: str | None = None):
        from opentakserver.extensions import db
        from opentakserver.models.Federation import Federation

        with self.app.app_context():
            row = db.session.get(Federation, federate_id)
            if not row:
                return
            now = datetime.now(timezone.utc)
            if connected:
                row.last_connected = now
                row.last_error = None
            else:
                row.last_disconnected = now
                if error:
                    row.last_error = error[:255]
            db.session.commit()


class RabbitBridge:
    """Per-connection RabbitMQ attachment.

    Uses two BlockingConnections because pika connections are not thread safe:
    one is driven by the consumer thread, the other is used by the socket
    reader thread to publish inbound events.
    """

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self._publish_lock = threading.Lock()

        credentials = pika.PlainCredentials(
            config.get("OTS_RABBITMQ_USERNAME"), config.get("OTS_RABBITMQ_PASSWORD")
        )
        params = pika.ConnectionParameters(
            host=config.get("OTS_RABBITMQ_SERVER_ADDRESS"), credentials=credentials
        )

        self._publisher = pika.BlockingConnection(params)
        self._publish_channel = self._publisher.channel()

        self._consumer = pika.BlockingConnection(params)
        self._consume_channel = self._consumer.channel()
        self._consume_channel.exchange_declare("firehose", durable=True, exchange_type="fanout")
        result = self._consume_channel.queue_declare(queue="", exclusive=True)
        self._queue = result.method.queue
        self._consume_channel.queue_bind(exchange="firehose", queue=self._queue)

    def publish_inbound(self, envelope: dict):
        with self._publish_lock:
            self._publish_channel.basic_publish(
                exchange="cot_parser",
                routing_key="cot_parser",
                body=json.dumps(envelope),
                properties=pika.BasicProperties(expiration=self.config.get("OTS_RABBITMQ_TTL")),
            )

    def consume_outbound(self, callback):
        """Deliver firehose envelopes to callback. Blocks until close()."""

        def on_message(channel, method, properties, body):
            callback(body)

        self._consume_channel.basic_consume(
            queue=self._queue, on_message_callback=on_message, auto_ack=True
        )
        self._consume_channel.start_consuming()

    def close(self):
        for connection in (self._consumer, self._publisher):
            try:
                connection.add_callback_threadsafe(connection.close)
            except Exception:
                pass


class FederationConnection:
    """One established federation link (either direction)."""

    def __init__(self, sock: ssl.SSLSocket, federate: dict, directory, bridge, config, logger):
        self.sock = sock
        self.federate = federate
        self.directory = directory
        self.bridge = bridge
        self.config = config
        self.logger = logger

        self.node_id = config.get("OTS_NODE_ID")
        self.decoder = FrameDecoder(
            config.get("OTS_FEDERATION_MAX_FRAME_BYTES", DEFAULT_MAX_FRAME_BYTES)
        )
        self.remote_contacts: dict[str, str] = {}
        self._sent_contacts: dict[str, str] = {}
        self._send_lock = threading.Lock()
        self._closed = threading.Event()
        self.events_in = 0
        self.events_out = 0

    # ------------------------------------------------------------------ sending

    def _send(self, fed_event: fig_pb2.FederatedEvent):
        frame = encode_frame(fed_event)
        with self._send_lock:
            self.sock.sendall(frame)

    def _refresh_config(self):
        config = self.directory.federate_config(self.federate["id"])
        if config:
            self.federate = config

    def announce_contacts(self):
        """Send ContactListEntry create/delete for local EUD presence changes."""
        current = self.directory.connected_contacts()
        for uid, callsign in current.items():
            if self._sent_contacts.get(uid) != callsign:
                self._send(contact_event(uid, callsign, fig_pb2.CREATE))
        for uid, callsign in list(self._sent_contacts.items()):
            if uid not in current:
                self._send(contact_event(uid, callsign, fig_pb2.DELETE))
        self._sent_contacts = current

    def handle_outbound(self, body: bytes):
        """Firehose callback: filter by outbound groups, convert, and send."""
        try:
            envelope = json.loads(body)
            uid = envelope.get("uid")
            cot = envelope.get("cot")
            if not cot or not uid or uid == self.node_id:
                return

            allowed = set(self.federate.get("outbound_groups") or [])
            if not allowed:
                return

            groups = self.directory.sender_groups(uid) & allowed
            if not groups:
                return

            fed_event = cot_to_federated_event(cot)
            if not fed_event or fed_event.event.type in EXCLUDED_COT_TYPES:
                return

            fed_event.federateGroups.extend(sorted(groups))
            self._send(fed_event)
            self.events_out += 1
        except (OSError, ssl.SSLError):
            self.close()
        except Exception as e:
            self.logger.error(f"Federation outbound error for {self.federate['name']}: {e}")
            self.logger.debug(traceback.format_exc())

    # ---------------------------------------------------------------- receiving

    def handle_frame(self, fed_event: fig_pb2.FederatedEvent):
        name = self.federate["name"]

        if fed_event.HasField("contact"):
            contact = fed_event.contact
            if contact.operation == fig_pb2.DELETE:
                self.remote_contacts.pop(contact.uid, None)
                self.directory.remove_federated_eud(contact.uid)
            else:
                self.remote_contacts[contact.uid] = contact.callsign
                self.directory.ensure_federated_eud(contact.uid, contact.callsign, name)
            self.logger.debug(
                f"Federate {name} contact "
                f"{fig_pb2.CRUD.Name(contact.operation)}: {contact.callsign} ({contact.uid})"
            )

        if not fed_event.HasField("event"):
            return

        inbound_groups = self.federate.get("inbound_groups") or []
        if not inbound_groups:
            return

        cot = federated_event_to_cot(fed_event)
        if not cot:
            return

        # Attribute the CoT to its originating EUD and make sure that EUD exists
        # locally so the cot table's foreign key is satisfied and the remote unit
        # shows up like a federated contact.
        sender_uid, callsign = sender_identity(fed_event)
        if sender_uid:
            self.directory.ensure_federated_eud(sender_uid, callsign, name)

        self.bridge.publish_inbound(
            {
                "uid": sender_uid or fed_event.event.uid,
                "cot": cot,
                "user_id": None,
                "groups": inbound_groups,
                "federate": name,
            }
        )
        self.events_in += 1

    def run(self):
        """Serve the connection; returns when the link dies."""
        name = self.federate["name"]
        self.logger.info(f"Federation link established with '{name}'")
        self.directory.record_state(self.federate["id"], connected=True)

        consumer = threading.Thread(
            target=self._consume, name=f"fed-out-{name}", daemon=True
        )
        consumer.start()

        contact_thread = threading.Thread(
            target=self._contact_loop, name=f"fed-contacts-{name}", daemon=True
        )
        contact_thread.start()

        error = None
        try:
            while not self._closed.is_set():
                data = self.sock.recv(RECV_BYTES)
                if not data:
                    break
                for fed_event in self.decoder.feed(data):
                    self.handle_frame(fed_event)
        except (OSError, ssl.SSLError) as e:
            error = str(e)
        except Exception as e:
            error = str(e)
            self.logger.error(f"Federation receive error from '{name}': {e}")
            self.logger.debug(traceback.format_exc())
        finally:
            self.close()
            self.directory.record_state(self.federate["id"], connected=False, error=error)
            self.logger.info(
                f"Federation link with '{name}' closed "
                f"(in: {self.events_in} events, out: {self.events_out} events)"
            )

    def _consume(self):
        try:
            self.bridge.consume_outbound(self.handle_outbound)
        except Exception as e:
            if not self._closed.is_set():
                self.logger.error(
                    f"Federation outbound consumer for '{self.federate['name']}' died: {e}"
                )
                self.close()

    def _contact_loop(self):
        interval = self.config.get("OTS_FEDERATION_CONTACT_INTERVAL_SECONDS", 30)
        while not self._closed.is_set():
            try:
                self._refresh_config()
                self.announce_contacts()
            except (OSError, ssl.SSLError):
                self.close()
                break
            except Exception as e:
                self.logger.error(f"Federation contact announcement failed: {e}")
            self._closed.wait(interval)

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        self.bridge.close()


class FederationManager:
    """Owns the listener, dialers, and the registry of live connections."""

    def __init__(self, app, logger, bridge_factory=None):
        self.app = app
        self.config = app.config
        self.logger = logger
        self.directory = Directory(app, logger)
        self.bridge_factory = bridge_factory or (lambda: RabbitBridge(self.config, logger))
        self.connections: dict[int, FederationConnection] = {}
        self._lock = threading.Lock()
        self._dialing: set[int] = set()
        self._stop = threading.Event()

    # ----------------------------------------------------------------- registry

    def _register(self, connection: FederationConnection) -> None:
        with self._lock:
            previous = self.connections.get(connection.federate["id"])
            if previous:
                self.logger.info(
                    f"Replacing existing federation connection for '{connection.federate['name']}'"
                )
                previous.close()
            self.connections[connection.federate["id"]] = connection

    def _unregister(self, connection: FederationConnection) -> None:
        with self._lock:
            if self.connections.get(connection.federate["id"]) is connection:
                del self.connections[connection.federate["id"]]

    def is_connected(self, federate_id: int) -> bool:
        with self._lock:
            return federate_id in self.connections

    # ----------------------------------------------------------------- inbound

    def serve_inbound(self, raw_socket: socket.socket, address):
        try:
            raw_socket.settimeout(HANDSHAKE_TIMEOUT_SECONDS)
            context = truststore.server_ssl_context(self.config)
            sock = context.wrap_socket(raw_socket, server_side=True)
            sock.settimeout(None)
        except (OSError, ssl.SSLError, truststore.NoFederationCAsError) as e:
            self.logger.warning(f"Federation handshake with {address[0]} failed: {e}")
            try:
                raw_socket.close()
            except OSError:
                pass
            return

        fingerprint, common_name = truststore.peer_identity(sock)
        federate = self.directory.find_or_create_inbound(fingerprint, common_name, address[0])

        if not federate.get("enabled"):
            self.logger.warning(
                f"Rejecting federation connection from disabled federate '{federate['name']}'"
            )
            sock.close()
            return

        self._run_connection(sock, federate)

    def _listen(self):
        interface = self.config.get("OTS_FEDERATION_INTERFACE", "0.0.0.0")
        port = self.config.get("OTS_FEDERATION_V1_PORT", 9000)

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((interface, port))
        server.listen(5)
        self.logger.info(f"Federation v1 listening on {interface}:{port}")

        while not self._stop.is_set():
            try:
                raw_socket, address = server.accept()
            except OSError:
                break
            self.logger.info(f"Federation connection attempt from {address[0]}")
            threading.Thread(
                target=self.serve_inbound,
                args=(raw_socket, address),
                name=f"fed-in-{address[0]}",
                daemon=True,
            ).start()

        server.close()

    # ---------------------------------------------------------------- outbound

    def _dial(self, federate: dict):
        federate_id = federate["id"]
        try:
            while not self._stop.is_set():
                config = self.directory.federate_config(federate_id)
                if not config or not config.get("enabled") or not config.get("outbound"):
                    return

                try:
                    raw_socket = socket.create_connection(
                        (config["address"], config["port"]), timeout=HANDSHAKE_TIMEOUT_SECONDS
                    )
                    context = truststore.client_ssl_context(self.config)
                    sock = context.wrap_socket(raw_socket, server_hostname=config["address"])
                    sock.settimeout(None)

                    fingerprint, common_name = truststore.peer_identity(sock)
                    if (
                        config.get("cert_fingerprint")
                        and config["cert_fingerprint"] != fingerprint
                    ):
                        sock.close()
                        raise ssl.SSLError(
                            f"Federate '{config['name']}' presented certificate {fingerprint[:12]} "
                            f"but {config['cert_fingerprint'][:12]} is pinned"
                        )
                    self.directory.pin_fingerprint(federate_id, fingerprint, common_name)

                    self._run_connection(sock, config)
                except (OSError, ssl.SSLError, truststore.NoFederationCAsError) as e:
                    self.logger.warning(f"Federation dial to '{config['name']}' failed: {e}")
                    self.directory.record_state(federate_id, connected=False, error=str(e))

                interval = config.get("reconnect_interval") or self.config.get(
                    "OTS_FEDERATION_RECONNECT_SECONDS", 30
                )
                self._stop.wait(interval)
        finally:
            with self._lock:
                self._dialing.discard(federate_id)

    def _dialer_supervisor(self):
        while not self._stop.is_set():
            try:
                for federate in self.directory.outbound_federates():
                    with self._lock:
                        already = federate["id"] in self._dialing or federate["id"] in self.connections
                        if not already:
                            self._dialing.add(federate["id"])
                        else:
                            continue
                    threading.Thread(
                        target=self._dial,
                        args=(federate,),
                        name=f"fed-dial-{federate['name']}",
                        daemon=True,
                    ).start()
            except Exception as e:
                self.logger.error(f"Federation dialer supervisor error: {e}")
                self.logger.debug(traceback.format_exc())
            self._stop.wait(DIALER_SCAN_SECONDS)

    # ------------------------------------------------------------------ common

    def _run_connection(self, sock: ssl.SSLSocket, federate: dict):
        try:
            bridge = self.bridge_factory()
        except Exception as e:
            self.logger.error(f"Could not attach to RabbitMQ for federation: {e}")
            sock.close()
            return

        connection = FederationConnection(
            sock, federate, self.directory, bridge, self.config, self.logger
        )
        self._register(connection)
        try:
            connection.run()
        finally:
            self._unregister(connection)

    def run(self):
        listener = threading.Thread(target=self._listen, name="fed-listener", daemon=True)
        listener.start()

        supervisor = threading.Thread(
            target=self._dialer_supervisor, name="fed-dialer", daemon=True
        )
        supervisor.start()

        try:
            while not self._stop.is_set():
                self._stop.wait(3600)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self._stop.set()
        with self._lock:
            connections = list(self.connections.values())
        for connection in connections:
            connection.close()
