"""Federation v2 (gRPC) engine - situational awareness subset.

v2 carries the same FederatedEvent messages as v1, but over the official TAK
FederatedChannel gRPC service instead of length-prefixed TLS frames. This
implements the SA subset:

- getIdentity / HealthCheck housekeeping
- ClientEventStream: a federate subscribes and we stream our (group-filtered)
  events to it
- ServerEventStream: a federate streams its events to us and we route them in

The CoT mapping, group filtering, loop guard, and federated-EUD registration
are shared with v1 (engine.build_outbound_event / apply_inbound_event), so v2
is purely a different transport. ROL (mission federation) and group-mapping
RPCs are declared in the proto for wire compatibility but not served.

Trust uses the same federation truststore as v1: mutual TLS where peer server
certificates are validated against the peer-CA truststore. gRPC identifies the
connecting federate from its client certificate.
"""

import queue
import threading
import time
from concurrent import futures

import grpc

from opentakserver.federation import truststore
from opentakserver.federation.engine import (
    apply_inbound_event,
    build_outbound_event,
    contact_announcements,
)
from opentakserver.federation.mapper import contact_event
from opentakserver.federation.proto import fig_pb2, fig_pb2_grpc

STREAM_POLL_SECONDS = 1.0
OUTBOUND_QUEUE_MAX = 1000


def _channel_credentials(config):
    return grpc.ssl_channel_credentials(
        root_certificates=truststore.truststore_pem(config),
        private_key=truststore.server_key_pem(config),
        certificate_chain=truststore.server_cert_pem(config),
    )


def _server_credentials(config):
    return grpc.ssl_server_credentials(
        [(truststore.server_key_pem(config), truststore.server_cert_pem(config))],
        root_certificates=truststore.truststore_pem(config),
        require_client_auth=True,
    )


def _peer_identity(context):
    """(fingerprint, common_name) of the connecting federate's certificate."""
    auth = dict(context.auth_context())
    pem = auth.get("x509_pem_cert", [b""])[0]
    fingerprint = truststore.fingerprint_from_pem(pem)
    cn = auth.get("x509_common_name", [b""])[0]
    return fingerprint, (cn.decode() if cn else None)


def _peer_address(context):
    # grpc peer() looks like "ipv4:127.0.0.1:54321"
    peer = context.peer()
    parts = peer.split(":")
    return parts[1] if len(parts) >= 2 else peer


class FederationServicer(fig_pb2_grpc.FederatedChannelServicer):
    """Serves inbound federation v2 connections (we are the listener)."""

    def __init__(self, manager):
        self.manager = manager
        self.config = manager.config
        self.logger = manager.logger
        self.directory = manager.directory
        self.node_id = manager.config.get("OTS_NODE_ID")

    def _identity_message(self):
        return fig_pb2.Identity(
            name=self.node_id,
            uid=self.node_id,
            description="OpenTAKServer",
            type=fig_pb2.Identity.FEDERATION_TAK_SERVER,
            serverId=self.node_id,
        )

    def getIdentity(self, request, context):
        return self._identity_message()

    def HealthCheck(self, request, context):
        return fig_pb2.ServerHealth(status=fig_pb2.ServerHealth.SERVING)

    def _resolve_federate(self, context):
        fingerprint, cn = _peer_identity(context)
        federate = self.directory.find_or_create_inbound(
            fingerprint, cn, _peer_address(context)
        )
        return federate

    def ServerEventStream(self, request_iterator, context):
        """A federate streams its events to us; route them inbound."""
        federate = self._resolve_federate(context)
        name = federate["name"]
        if not federate.get("enabled"):
            context.abort(grpc.StatusCode.PERMISSION_DENIED, "federate disabled")

        bridge = self.manager.bridge_factory()
        remote_contacts = {}
        count = 0
        self.logger.info(f"Federation v2 inbound stream from '{name}' opened")
        self.directory.record_state(federate["id"], connected=True)
        try:
            for fed_event in request_iterator:
                current = self.directory.federate_config(federate["id"]) or federate
                if apply_inbound_event(
                    fed_event, current, self.directory, bridge, self.logger, remote_contacts
                ):
                    count += 1
        except Exception as e:  # noqa: BLE001 - report and end the stream cleanly
            self.logger.debug(f"Federation v2 inbound stream from '{name}' ended: {e}")
        finally:
            bridge.close()
            self.directory.record_state(federate["id"], connected=False)
            self.logger.info(
                f"Federation v2 inbound stream from '{name}' closed ({count} events)"
            )
        return fig_pb2.Subscription(identity=self._identity_message())

    def ClientEventStream(self, request, context):
        """A federate subscribes; stream our group-filtered events to it."""
        federate = self._resolve_federate(context)
        name = federate["name"]
        if not federate.get("enabled"):
            context.abort(grpc.StatusCode.PERMISSION_DENIED, "federate disabled")

        self.logger.info(f"Federation v2 outbound stream to '{name}' opened")
        yield from _outbound_event_stream(self.manager, federate, context)
        self.logger.info(f"Federation v2 outbound stream to '{name}' closed")


def _outbound_event_stream(manager, federate, context):
    """Generator of FederatedEvents to send to a subscribed federate.

    Bridges the firehose exchange into a bounded queue on a worker thread and
    yields converted, group-filtered events plus periodic contact
    announcements until the peer goes away.
    """
    node_id = manager.config.get("OTS_NODE_ID")
    directory = manager.directory
    logger = manager.logger
    outbound = queue.Queue(maxsize=OUTBOUND_QUEUE_MAX)
    bridge = manager.bridge_factory()

    def pump():
        def on_body(body):
            try:
                outbound.put_nowait(body)
            except queue.Full:
                pass  # drop under backpressure; SA is live state

        try:
            bridge.consume_outbound(on_body)
        except Exception:  # noqa: BLE001 - bridge closed on teardown
            pass

    pump_thread = threading.Thread(target=pump, name=f"fedv2-out-{federate['name']}", daemon=True)
    pump_thread.start()

    sent_contacts = {}
    last_contacts = 0.0
    contact_interval = manager.config.get("OTS_FEDERATION_CONTACT_INTERVAL_SECONDS", 30)

    try:
        while context.is_active():
            # Contact announcements
            now = time.monotonic()
            if now - last_contacts >= contact_interval:
                last_contacts = now
                current = directory.connected_contacts()
                for uid, callsign, operation in contact_announcements(current, sent_contacts):
                    yield contact_event(uid, callsign, operation)
                sent_contacts = current
                federate = directory.federate_config(federate["id"]) or federate

            try:
                body = outbound.get(timeout=STREAM_POLL_SECONDS)
            except queue.Empty:
                continue

            import json

            fed_event = build_outbound_event(json.loads(body), federate, directory, node_id)
            if fed_event is not None:
                yield fed_event
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Federation v2 outbound stream error for '{federate['name']}': {e}")
    finally:
        bridge.close()


class GrpcClient:
    """Dials a federation v2 peer (we are the outgoing connection)."""

    def __init__(self, manager, federate):
        self.manager = manager
        self.config = manager.config
        self.logger = manager.logger
        self.directory = manager.directory
        self.node_id = manager.config.get("OTS_NODE_ID")
        self.federate = federate
        self._stop = threading.Event()

    def _identity_message(self):
        return fig_pb2.Identity(
            name=self.node_id,
            uid=self.node_id,
            type=fig_pb2.Identity.FEDERATION_TAK_CLIENT,
            serverId=self.node_id,
        )

    def _outbound_generator(self, bridge):
        outbound = queue.Queue(maxsize=OUTBOUND_QUEUE_MAX)

        def on_body(body):
            try:
                outbound.put_nowait(body)
            except queue.Full:
                pass

        threading.Thread(
            target=lambda: self._safe_consume(bridge, on_body),
            name=f"fedv2c-out-{self.federate['name']}",
            daemon=True,
        ).start()

        import json

        sent_contacts = {}
        last_contacts = 0.0
        contact_interval = self.config.get("OTS_FEDERATION_CONTACT_INTERVAL_SECONDS", 30)

        while not self._stop.is_set():
            now = time.monotonic()
            if now - last_contacts >= contact_interval:
                last_contacts = now
                current = self.directory.connected_contacts()
                for uid, callsign, operation in contact_announcements(current, sent_contacts):
                    yield contact_event(uid, callsign, operation)
                sent_contacts = current

            try:
                body = outbound.get(timeout=STREAM_POLL_SECONDS)
            except queue.Empty:
                continue

            config = self.directory.federate_config(self.federate["id"]) or self.federate
            fed_event = build_outbound_event(json.loads(body), config, self.directory, self.node_id)
            if fed_event is not None:
                yield fed_event

    def _safe_consume(self, bridge, on_body):
        try:
            bridge.consume_outbound(on_body)
        except Exception:  # noqa: BLE001
            pass

    def run(self):
        config = self.federate
        target = f"{config['address']}:{config['port']}"
        authority = self.config.get("OTS_FEDERATION_V2_AUTHORITY", "opentakserver")
        options = [("grpc.ssl_target_name_override", authority)]

        try:
            credentials = _channel_credentials(self.config)
        except truststore.NoFederationCAsError as e:
            self.logger.warning(f"Federation v2 dial to '{config['name']}' failed: {e}")
            self.directory.record_state(config["id"], connected=False, error=str(e))
            return

        channel = grpc.secure_channel(target, credentials, options=options)
        stub = fig_pb2_grpc.FederatedChannelStub(channel)
        bridge = self.manager.bridge_factory()
        remote_contacts = {}
        name = config["name"]

        try:
            grpc.channel_ready_future(channel).result(timeout=15)
            identity = stub.getIdentity(fig_pb2.Empty())
            self.logger.info(
                f"Federation v2 link established with '{name}' (peer: {identity.name})"
            )
            self.directory.record_state(config["id"], connected=True)

            # Send our events to the peer on a worker thread
            def send():
                try:
                    stub.ServerEventStream(self._outbound_generator(bridge))
                except grpc.RpcError as e:
                    self.logger.debug(f"Federation v2 send stream to '{name}' ended: {e.code()}")

            sender = threading.Thread(target=send, name=f"fedv2c-send-{name}", daemon=True)
            sender.start()

            # Receive the peer's events on this thread
            subscription = fig_pb2.Subscription(identity=self._identity_message())
            for fed_event in stub.ClientEventStream(subscription):
                if self._stop.is_set():
                    break
                current = self.directory.federate_config(config["id"]) or config
                apply_inbound_event(
                    fed_event, current, self.directory, bridge, self.logger, remote_contacts
                )
        except grpc.RpcError as e:
            self.logger.warning(
                f"Federation v2 dial to '{name}' failed: {e.code()} {e.details()}"
            )
            self.directory.record_state(config["id"], connected=False, error=str(e.code()))
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"Federation v2 client error for '{name}': {e}")
            self.directory.record_state(config["id"], connected=False, error=str(e))
        finally:
            self._stop.set()
            bridge.close()
            channel.close()
            self.logger.info(f"Federation v2 link with '{name}' closed")

    def stop(self):
        self._stop.set()

    # The manager's connection registry closes replaced links via close()
    close = stop


def build_server(manager):
    """Create (but do not start) the gRPC federation server."""
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=manager.config.get("OTS_FEDERATION_V2_WORKERS", 16))
    )
    fig_pb2_grpc.add_FederatedChannelServicer_to_server(FederationServicer(manager), server)
    interface = manager.config.get("OTS_FEDERATION_INTERFACE", "0.0.0.0")
    port = manager.config.get("OTS_FEDERATION_V2_PORT", 9001)
    server.add_secure_port(f"{interface}:{port}", _server_credentials(manager.config))
    return server, port
