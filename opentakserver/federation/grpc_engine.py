"""Federation v2 (gRPC) engine - situational awareness subset.

v2 carries the same FederatedEvent messages as v1, but over the official TAK
FederatedChannel gRPC service instead of length-prefixed TLS frames. This
implements the SA subset:

- getIdentity (when the peer serves it) / HealthCheck housekeeping
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
import ssl
import threading
import time
from concurrent import futures

import grpc

from opentakserver.federation import truststore
from opentakserver.federation.engine import (
    apply_inbound_event,
    build_outbound_event,
    contact_announcements,
    verify_peer_fingerprint,
)
from opentakserver.federation.mapper import contact_event
from opentakserver.federation.proto import fig_pb2, fig_pb2_grpc

STREAM_POLL_SECONDS = 1.0
OUTBOUND_QUEUE_MAX = 1000
DEFAULT_HEALTH_CHECK_INTERVAL_SECONDS = 5.0


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


def _optional_peer_name(stub, fallback):
    """Return the v2 peer name, tolerating TAK's optional identity RPC."""
    try:
        identity = stub.getIdentity(fig_pb2.Empty())
        return identity.name or fallback, True
    except grpc.RpcError as e:
        if e.code() != grpc.StatusCode.UNIMPLEMENTED:
            raise
        return fallback, False


def _health_check_loop(stub, stop, interval, logger, peer_name):
    """Keep a v2 event stream alive using the official FIG health contract.

    TAK Server and Federation Hub expire a client event stream when they do
    not receive a SERVING health report within their configured timeout.  A
    peer that does not implement the optional RPC remains usable; peers that
    do implement it receive the same periodic report as a stock TAK client.
    """
    interval = float(interval)
    if interval <= 0:
        logger.warning(f"Federation v2 health checks disabled for '{peer_name}'")
        return

    request = fig_pb2.ClientHealth(status=fig_pb2.ClientHealth.SERVING)
    # Hub 5.7 sends the unary response but does not call onCompleted(). Bound
    # each call so it cannot occupy this worker forever, while leaving enough
    # margin to refresh the Hub's default 15-second client timeout.
    rpc_timeout = max(1.0, min(interval / 2.0, 5.0))
    while not stop.wait(interval):
        try:
            response = stub.HealthCheck(request, timeout=rpc_timeout)
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.UNIMPLEMENTED:
                logger.debug(
                    f"Federation v2 peer '{peer_name}' does not serve optional HealthCheck"
                )
                return
            if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                # Federation Hub 5.7 updates the stream health and calls
                # onNext(SERVING), but omits onCompleted() from this unary RPC.
                # Python therefore reaches its local deadline even though the
                # heartbeat was accepted. Keep refreshing as stock TAK's
                # asynchronous client does.
                logger.debug(
                    f"Federation v2 health check to '{peer_name}' reached its "
                    "completion deadline; continuing"
                )
                continue
            else:
                logger.warning(
                    f"Federation v2 health check to '{peer_name}' failed: "
                    f"{e.code()} {e.details()}"
                )
                return

        if response.status != fig_pb2.ServerHealth.SERVING:
            logger.warning(
                f"Federation v2 peer '{peer_name}' reported unhealthy status "
                f"{fig_pb2.ServerHealth.ServingStatus.Name(response.status)}"
            )
            return


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
        federate = self.directory.find_or_create_inbound(fingerprint, cn, _peer_address(context))
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
            self.logger.info(f"Federation v2 inbound stream from '{name}' closed ({count} events)")
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
                federate = directory.federate_config(federate["id"]) or federate
                current = directory.connected_contacts(federate.get("outbound_groups") or [])
                for uid, callsign, operation in contact_announcements(current, sent_contacts):
                    yield contact_event(uid, callsign, operation)
                sent_contacts = current

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
                config = self.directory.federate_config(self.federate["id"]) or self.federate
                current = self.directory.connected_contacts(config.get("outbound_groups") or [])
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
            fingerprint, common_name = truststore.probe_grpc_peer_identity(
                self.config,
                config["address"],
                config["port"],
                authority,
            )
            verify_peer_fingerprint(config, fingerprint)
            self.directory.pin_fingerprint(config["id"], fingerprint, common_name)
        except (OSError, ssl.SSLError, truststore.NoFederationCAsError) as e:
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
            # Official TAK Server 5.5 declares getIdentity in fig.proto but
            # leaves the server-side method unimplemented.  Stock TAK clients
            # do not require it; identity is carried in the stream Subscription
            # instead.  Keep it as an optional diagnostic RPC so OTS remains
            # compatible with peers that do implement it.
            peer_name, serves_identity = _optional_peer_name(stub, name)
            if not serves_identity:
                self.logger.debug(
                    f"Federation v2 peer '{name}' does not serve optional getIdentity"
                )
            self.logger.info(
                f"Federation v2 link established with '{name}' (peer: {peer_name})"
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
            event_stream = stub.ClientEventStream(subscription)
            health = threading.Thread(
                target=_health_check_loop,
                args=(
                    stub,
                    self._stop,
                    self.config.get(
                        "OTS_FEDERATION_V2_HEALTH_CHECK_INTERVAL_SECONDS",
                        DEFAULT_HEALTH_CHECK_INTERVAL_SECONDS,
                    ),
                    self.logger,
                    name,
                ),
                name=f"fedv2c-health-{name}",
                daemon=True,
            )
            health.start()
            for fed_event in event_stream:
                if self._stop.is_set():
                    break
                current = self.directory.federate_config(config["id"]) or config
                apply_inbound_event(
                    fed_event, current, self.directory, bridge, self.logger, remote_contacts
                )
        except grpc.RpcError as e:
            self.logger.warning(f"Federation v2 dial to '{name}' failed: {e.code()} {e.details()}")
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
