"""Federation v1 tests.

Unit coverage for the frame codec, the CoT <-> protobuf mapper, and the
federation truststore, plus an end-to-end integration test that federates two
in-process engines over real mutually-authenticated TLS sockets and asserts
SA events, contacts, group filtering, and certificate rejection behave like
TAK Server federation.

The engine's database and RabbitMQ touchpoints are injected (Directory and
bridge fakes), so these tests need no broker and no database.
"""

import datetime
import json
import socket
import ssl
import threading
import time
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from opentakserver.federation import mapper, truststore
from opentakserver.federation.codec import FrameDecoder, FrameTooLargeError, encode_frame
from opentakserver.federation.engine import FederationConnection, FederationManager
from opentakserver.federation.proto import fig_pb2

SA_COT = (
    '<event version="2.0" uid="ANDROID-deadbeef" type="a-f-G-U-C" how="m-g" '
    'time="2026-07-17T19:00:00.000Z" start="2026-07-17T19:00:00.000Z" '
    'stale="2026-07-17T19:06:15.000Z">'
    '<point lat="30.6187" lon="-96.3365" hae="102.3" ce="4.9" le="9999999.0"/>'
    '<detail><takv os="34" version="5.1.0" device="PIXEL 8" platform="ATAK-CIV"/>'
    '<contact endpoint="*:-1:stcp" callsign="HAVOC13"/>'
    '<precisionlocation altsrc="GPS" geopointsrc="GPS"/><status battery="79"/>'
    '<track course="221.5" speed="1.2"/><__group__ role="Team Member" name="Cyan"/>'
    "</detail></event>"
)

CHAT_COT = (
    '<event version="2.0" uid="GeoChat.ANDROID-deadbeef.S-1-5.1" type="b-t-f" '
    'how="h-g-i-g-o" time="2026-07-17T19:01:00.000Z" start="2026-07-17T19:01:00.000Z" '
    'stale="2026-07-18T19:01:00.000Z"><point lat="30.61" lon="-96.33" hae="0" '
    'ce="9999999" le="9999999"/><detail>'
    '<remarks source="BAO.F.ATAK.ANDROID-deadbeef" to="S-1-5" '
    'time="2026-07-17T19:01:00.000Z">on my way</remarks>'
    '<marti><dest callsign="JEEP1"/></marti></detail></event>'
)


# --------------------------------------------------------------------- codec


def test_codec_roundtrip_and_partial_frames():
    events = [
        mapper.cot_to_federated_event(SA_COT),
        mapper.contact_event("uid-1", "ALPHA"),
        mapper.cot_to_federated_event(CHAT_COT),
    ]
    stream = b"".join(encode_frame(event) for event in events)

    # Feed the stream in awkward 7-byte chunks to exercise partial-frame
    # buffering of both the length prefix and the payload
    decoder = FrameDecoder()
    decoded = []
    for i in range(0, len(stream), 7):
        decoded.extend(decoder.feed(stream[i : i + 7]))

    assert len(decoded) == 3
    assert decoded[0].event.uid == "ANDROID-deadbeef"
    assert decoded[1].contact.callsign == "ALPHA"
    assert decoded[2].event.uid == "GeoChat.ANDROID-deadbeef.S-1-5.1"


def test_codec_rejects_oversized_frames():
    decoder = FrameDecoder(max_frame_bytes=1024)
    with pytest.raises(FrameTooLargeError):
        decoder.feed((2048).to_bytes(4, "big") + b"x" * 10)


# -------------------------------------------------------------------- mapper


def test_mapper_extracts_fields_like_tak_server():
    fed_event = mapper.cot_to_federated_event(SA_COT)
    geo = fed_event.event

    assert geo.uid == "ANDROID-deadbeef"
    assert geo.type == "a-f-G-U-C"
    assert geo.coordSource == "m-g"
    assert geo.lat == pytest.approx(30.6187)
    assert geo.speed == pytest.approx(1.2)
    assert geo.course == pytest.approx(221.5)
    assert geo.battery == 79
    assert geo.ploc == "GPS" and geo.palt == "GPS"
    # 2026-07-17T19:00:00Z in epoch millis
    assert geo.sendTime == 1784314800000
    assert geo.staleTime - geo.startTime == 375000

    # Extracted elements must be gone from the opaque detail; the rest stays
    assert "track" not in geo.other
    assert "status" not in geo.other
    assert "precisionlocation" not in geo.other
    assert 'callsign="HAVOC13"' in geo.other
    assert "__group__" in geo.other


def test_mapper_reconstructs_cot():
    cot = mapper.federated_event_to_cot(mapper.cot_to_federated_event(SA_COT))

    assert 'uid="ANDROID-deadbeef"' in cot
    assert 'time="2026-07-17T19:00:00.000Z"' in cot
    assert 'speed="1.2"' in cot and 'course="221.5"' in cot
    assert 'battery="79"' in cot
    assert 'geopointsrc="GPS"' in cot
    assert 'callsign="HAVOC13"' in cot


def test_mapper_maps_marti_dest_to_ptp_and_back():
    fed_event = mapper.cot_to_federated_event(CHAT_COT)

    assert list(fed_event.event.ptpCallsigns) == ["JEEP1"]
    assert "marti" not in fed_event.event.other

    cot = mapper.federated_event_to_cot(fed_event)
    assert "<marti>" in cot and 'dest callsign="JEEP1"' in cot


def test_mapper_rejects_eventless_cot():
    assert mapper.cot_to_federated_event("<auth/>") is None
    assert mapper.federated_event_to_cot(mapper.contact_event("u", "c")) is None


# ----------------------------------------------------------------- certs/PKI


def _make_ca(common_name):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _make_cert(common_name, ca_key, ca_cert):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM)


def _key_pem(key):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )


def _write_identity(tmp_path, name, key, cert, ca_cert):
    """Lay out an OTS_CA_FOLDER shaped directory for one server."""
    ca_folder = tmp_path / name
    cert_folder = ca_folder / "certs" / "opentakserver"
    cert_folder.mkdir(parents=True)
    # The server presents its full chain, like TAK Server federates do
    (cert_folder / "opentakserver.pem").write_bytes(_pem(cert) + _pem(ca_cert))
    (cert_folder / "opentakserver.nopass.key").write_bytes(_key_pem(key))
    (ca_folder / "federation").mkdir()
    return ca_folder


def _config(ca_folder, port, node_id, extra=None):
    config = {
        "OTS_CA_FOLDER": str(ca_folder),
        "OTS_FEDERATION_TRUSTSTORE_FOLDER": str(ca_folder / "federation"),
        "OTS_FEDERATION_INTERFACE": "127.0.0.1",
        "OTS_FEDERATION_V1_PORT": port,
        "OTS_FEDERATION_RECONNECT_SECONDS": 1,
        "OTS_FEDERATION_CONTACT_INTERVAL_SECONDS": 1,
        "OTS_FEDERATION_VERIFY_HOSTNAME": False,
        "OTS_NODE_ID": node_id,
    }
    config.update(extra or {})
    return config


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_truststore_ca_management(tmp_path):
    ca_key, ca_cert = _make_ca("Partner CA")
    config = {"OTS_CA_FOLDER": str(tmp_path), "OTS_FEDERATION_TRUSTSTORE_FOLDER": ""}

    with pytest.raises(ValueError):
        truststore.save_ca(config, "bad.pem", b"not a certificate")

    saved = truststore.save_ca(config, "../sneaky/partner ca", _pem(ca_cert))
    assert saved["filename"] == "partner_ca.pem"
    assert "Partner CA" in saved["subject"]

    cas = truststore.list_cas(config)
    assert len(cas) == 1 and cas[0]["filename"] == "partner_ca.pem"

    assert truststore.delete_ca(config, "partner_ca.pem")
    assert truststore.list_cas(config) == []


def test_ssl_context_requires_a_ca(tmp_path):
    key, ca_cert = _make_ca("Lonely CA")
    cert_key, cert = _make_cert("server", key, ca_cert)
    ca_folder = _write_identity(tmp_path, "lonely", cert_key, cert, ca_cert)
    config = _config(ca_folder, 0, "node")

    with pytest.raises(truststore.NoFederationCAsError):
        truststore.server_ssl_context(config)


# ------------------------------------------------------------- engine fakes


class FakeDirectory:
    """In-memory stand-in for the engine's database lookups."""

    def __init__(self, federates=None, contacts=None, groups=None):
        self.federates = {federate["id"]: dict(federate) for federate in (federates or [])}
        self.contacts = contacts or {}
        self.groups = groups or {}
        self.states = []
        self.auto_registered = []
        self.federated_euds = {}

    def connected_contacts(self):
        return dict(self.contacts)

    def ensure_federated_eud(self, uid, callsign, federate_name):
        self.federated_euds[uid] = callsign

    def remove_federated_eud(self, uid):
        self.federated_euds.pop(uid, None)

    def sender_groups(self, uid):
        return self.groups.get(uid, {"__ANON__"})

    def federate_config(self, federate_id):
        return self.federates.get(federate_id)

    def outbound_federates(self):
        return [
            federate
            for federate in self.federates.values()
            if federate.get("outbound") and federate.get("enabled")
        ]

    def find_or_create_inbound(self, fingerprint, common_name, address):
        for federate in self.federates.values():
            if federate.get("cert_fingerprint") in (None, fingerprint):
                federate["cert_fingerprint"] = fingerprint
                return federate
        federate = {
            "id": len(self.federates) + 100,
            "name": common_name or "unknown",
            "enabled": True,
            "outbound": False,
            "inbound_groups": [],
            "outbound_groups": [],
            "cert_fingerprint": fingerprint,
        }
        self.federates[federate["id"]] = federate
        self.auto_registered.append(federate)
        return federate

    def pin_fingerprint(self, federate_id, fingerprint, common_name):
        federate = self.federates.get(federate_id)
        if federate and not federate.get("cert_fingerprint"):
            federate["cert_fingerprint"] = fingerprint

    def record_state(self, federate_id, connected, error=None):
        self.states.append((federate_id, connected, error))


class FakeBridge:
    """In-memory stand-in for the RabbitMQ bridge."""

    def __init__(self):
        self.inbound = []
        self.inbound_event = threading.Event()
        self._callback = None
        self._closed = threading.Event()

    def publish_inbound(self, envelope):
        self.inbound.append(envelope)
        self.inbound_event.set()

    def consume_outbound(self, callback):
        self._callback = callback
        self._closed.wait()

    def inject(self, envelope: dict):
        deadline = time.monotonic() + 5
        while self._callback is None:
            if time.monotonic() > deadline:
                raise TimeoutError("outbound consumer never attached")
            time.sleep(0.01)
        self._callback(json.dumps(envelope).encode())

    def close(self):
        self._closed.set()


def _wait_for(predicate, timeout=5, message="condition"):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError(f"timed out waiting for {message}")
        time.sleep(0.02)


def _make_manager(config, directory, bridge_factory):
    app = SimpleNamespace(config=config)
    manager = FederationManager.__new__(FederationManager)
    manager.app = app
    manager.config = config
    manager.logger = __import__("logging").getLogger("OpenTAKServer")
    manager.directory = directory
    manager.bridge_factory = bridge_factory
    manager.connections = {}
    manager._lock = threading.Lock()
    manager._dialing = set()
    manager._stop = threading.Event()
    return manager


# -------------------------------------------------------------- integration


@pytest.fixture
def federated_pair(tmp_path):
    """Two engines, A listening and B dialing, mutually trusted."""
    ca_a_key, ca_a = _make_ca("Enclave A CA")
    ca_b_key, ca_b = _make_ca("Enclave B CA")
    key_a, cert_a = _make_cert("server-a", ca_a_key, ca_a)
    key_b, cert_b = _make_cert("server-b", ca_b_key, ca_b)

    folder_a = _write_identity(tmp_path, "a", key_a, cert_a, ca_a)
    folder_b = _write_identity(tmp_path, "b", key_b, cert_b, ca_b)
    # The out-of-band CA swap
    (folder_a / "federation" / "enclave-b.pem").write_bytes(_pem(ca_b))
    (folder_b / "federation" / "enclave-a.pem").write_bytes(_pem(ca_a))

    port_a = _free_port()
    config_a = _config(folder_a, port_a, "node-a")
    config_b = _config(folder_b, _free_port(), "node-b")

    directory_a = FakeDirectory(
        federates=[
            {
                "id": 1,
                "name": "enclave-b",
                "enabled": True,
                "outbound": False,
                "inbound_groups": ["__ANON__"],
                "outbound_groups": ["__ANON__"],
                "cert_fingerprint": None,
            }
        ],
        contacts={"uid-a1": "ALPHA"},
    )
    directory_b = FakeDirectory(
        federates=[
            {
                "id": 1,
                "name": "enclave-a",
                "address": "127.0.0.1",
                "port": port_a,
                "enabled": True,
                "outbound": True,
                "reconnect_interval": 1,
                "inbound_groups": ["__ANON__"],
                "outbound_groups": ["__ANON__"],
                "cert_fingerprint": None,
            }
        ],
        contacts={"uid-b1": "BRAVO"},
    )

    bridges_a, bridges_b = [], []

    def factory(bridges):
        def make():
            bridge = FakeBridge()
            bridges.append(bridge)
            return bridge

        return make

    manager_a = _make_manager(config_a, directory_a, factory(bridges_a))
    manager_b = _make_manager(config_b, directory_b, factory(bridges_b))

    listener = threading.Thread(target=manager_a._listen, daemon=True)
    listener.start()
    time.sleep(0.2)
    dialer = threading.Thread(target=manager_b._dialer_supervisor, daemon=True)
    dialer.start()

    try:
        _wait_for(
            lambda: manager_a.connections and manager_b.connections,
            message="federation link",
        )
        yield SimpleNamespace(
            manager_a=manager_a,
            manager_b=manager_b,
            bridges_a=bridges_a,
            bridges_b=bridges_b,
            directory_a=directory_a,
            directory_b=directory_b,
            config_a=config_a,
            folder_a=folder_a,
            port_a=port_a,
        )
    finally:
        manager_b._stop.set()
        manager_a._stop.set()
        manager_a.stop()
        manager_b.stop()
        # Unblock the accept() loop
        try:
            socket.create_connection(("127.0.0.1", port_a), timeout=1).close()
        except OSError:
            pass


def test_federation_end_to_end(federated_pair):
    pair = federated_pair
    connection_a = next(iter(pair.manager_a.connections.values()))
    connection_b = next(iter(pair.manager_b.connections.values()))

    # Contact announcements flow both ways
    _wait_for(lambda: "uid-b1" in connection_a.remote_contacts, message="B's contacts on A")
    _wait_for(lambda: "uid-a1" in connection_b.remote_contacts, message="A's contacts on B")
    assert connection_a.remote_contacts["uid-b1"] == "BRAVO"

    # SA from a local EUD on B reaches A tagged with A's inbound groups
    pair.bridges_b[0].inject({"uid": "ANDROID-deadbeef", "cot": SA_COT})
    _wait_for(lambda: pair.bridges_a[0].inbound, message="SA event on A")
    envelope = pair.bridges_a[0].inbound[0]
    assert envelope["uid"] == "ANDROID-deadbeef"
    assert envelope["groups"] == ["__ANON__"]
    assert envelope["user_id"] is None
    assert 'callsign="HAVOC13"' in envelope["cot"]

    # And the reverse direction
    pair.bridges_a[0].inject({"uid": "ANDROID-cafef00d", "cot": SA_COT.replace("deadbeef", "cafef00d")})
    _wait_for(lambda: pair.bridges_b[0].inbound, message="SA event on B")
    assert pair.bridges_b[0].inbound[0]["uid"] == "ANDROID-cafef00d"

    # The remote sender was registered locally as a federated EUD, so its CoT
    # can satisfy the cot->eud foreign key and it surfaces like a contact
    assert "ANDROID-deadbeef" in pair.directory_a.federated_euds
    assert pair.directory_a.federated_euds["ANDROID-deadbeef"] == "HAVOC13"

    # Fingerprints were learned/pinned
    assert pair.directory_b.federates[1]["cert_fingerprint"]


def test_outbound_group_filter_blocks_unshared_groups(federated_pair):
    pair = federated_pair
    connection_b = next(iter(pair.manager_b.connections.values()))

    # Sender publishes into a group this federate is not allowed to see
    pair.directory_b.groups["ANDROID-deadbeef"] = {"Secret Squirrels"}
    before = connection_b.events_out
    pair.bridges_b[0].inject({"uid": "ANDROID-deadbeef", "cot": SA_COT})

    # Give the (filtered) event a moment, then confirm nothing was sent
    time.sleep(0.5)
    assert connection_b.events_out == before


def test_federate_with_no_outbound_groups_sends_nothing(federated_pair):
    pair = federated_pair
    connection_b = next(iter(pair.manager_b.connections.values()))

    pair.directory_b.federates[1]["outbound_groups"] = []
    connection_b.federate["outbound_groups"] = []
    before = connection_b.events_out
    pair.bridges_b[0].inject({"uid": "ANDROID-deadbeef", "cot": SA_COT})
    time.sleep(0.5)
    assert connection_b.events_out == before


def test_untrusted_ca_is_rejected(federated_pair, tmp_path):
    pair = federated_pair

    ca_key, ca_cert = _make_ca("Interloper CA")
    key, cert = _make_cert("interloper", ca_key, ca_cert)
    folder = _write_identity(tmp_path, "interloper", key, cert, ca_cert)
    # The interloper trusts A, but A does not trust the interloper
    (folder / "federation" / "enclave-a.pem").write_bytes(
        (pair.folder_a / "certs" / "opentakserver" / "opentakserver.pem").read_bytes()
    )
    config = _config(folder, 0, "interloper")

    raw = socket.create_connection(("127.0.0.1", pair.port_a), timeout=5)
    context = truststore.client_ssl_context(config)
    with pytest.raises(ssl.SSLError):
        with context.wrap_socket(raw, server_hostname="127.0.0.1") as tls:
            # Force the handshake failure to surface
            tls.recv(1)
    raw.close()
