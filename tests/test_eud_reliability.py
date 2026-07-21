import datetime
import logging
import socketserver
from contextlib import nullcontext
from threading import Lock
from types import SimpleNamespace

from bs4 import BeautifulSoup

from opentakserver.cot_parser.disconnect import (
    build_disconnect_event,
    process_disconnect,
)
from opentakserver.eud_handler.EudHandler import EudHandler
from opentakserver.eud_handler.EudServer import EudServer
from opentakserver.extensions import db
from opentakserver.models.EUD import EUD
from opentakserver.models.Team import Team


class FakeRequest:
    def __init__(self):
        self.closed = False

    def shutdown(self, _how):
        self.closed = True

    def close(self):
        self.closed = True


class FakeChannel:
    def __init__(self, publish_error=None):
        self.is_open = True
        self.is_closed = False
        self.is_closing = False
        self.publish_error = publish_error
        self.declared = []
        self.bindings = []
        self.consumers = []
        self.published = []
        self.unbound = []

    def add_on_close_callback(self, callback):
        self.close_callback = callback

    def exchange_declare(self, **kwargs):
        self.exchange = kwargs

    def queue_declare(self, queue):
        self.declared.append(queue)

    def queue_bind(self, exchange, queue, routing_key):
        self.bindings.append((exchange, queue, routing_key))

    def queue_unbind(self, exchange, queue, routing_key=None):
        self.unbound.append((exchange, queue, routing_key))

    def basic_consume(self, queue, on_message_callback, auto_ack):
        self.consumers.append((queue, on_message_callback, auto_ack))

    def basic_publish(self, *args, **kwargs):
        if self.publish_error:
            raise self.publish_error
        self.published.append((args, kwargs))

    def close(self):
        self.is_open = False
        self.is_closed = True


class FakeConnection:
    def __init__(self):
        self.is_closing = False
        self.is_closed = False
        self.channel_requests = 0

    def channel(self, on_open_callback):
        self.channel_requests += 1
        self.on_open_callback = on_open_callback


def make_handler(monkeypatch):
    def base_init(instance, request, client_address, server):
        instance.request = request
        instance.client_address = client_address
        instance.server = server

    monkeypatch.setattr(socketserver.BaseRequestHandler, "__init__", base_init)
    server = SimpleNamespace()
    handler = EudHandler(FakeRequest(), ("127.0.0.1", 12345), server)
    handler.app = SimpleNamespace(config={"OTS_RABBITMQ_TTL": 60000})
    handler.app.app_context = nullcontext
    return handler


def make_server():
    server = object.__new__(EudServer)
    server.logger = logging.getLogger("test-eud-server")
    server._identity_lock = Lock()
    server._identity_handlers = {}
    return server


def test_per_connection_state_is_not_shared(monkeypatch):
    first = make_handler(monkeypatch)
    second = make_handler(monkeypatch)

    first.cached_messages.append("one")
    first.bound_queues.append({"queue": "one"})

    assert second.cached_messages == []
    assert second.bound_queues == []


def test_newest_identity_displaces_old_connection():
    server = make_server()
    old = SimpleNamespace(client_address=("10.0.0.1", 1), displaced=False)
    old.displace = lambda: setattr(old, "displaced", True)
    new = SimpleNamespace(client_address=("10.0.0.2", 2))

    server.claim_identity(old, "device-1")
    server.claim_identity(new, "device-1")

    assert old.displaced is True
    assert server.release_identity(old, "device-1") is False
    assert server.release_identity(new, "device-1") is True


def test_displaced_connection_does_not_publish_disconnect(monkeypatch):
    handler = make_handler(monkeypatch)
    handler.uid = "device-1"
    handler.displaced = True
    handler.rabbit_channel = FakeChannel()
    handler._close_lock = Lock()

    handler.close_connection()

    assert handler.rabbit_channel.published == []
    assert handler.rabbit_channel.unbound == []
    assert handler.request.closed is True


def test_shape_contact_cannot_claim_connection_identity(monkeypatch):
    handler = make_handler(monkeypatch)
    shape = BeautifulSoup(
        '<event type="u-d-r" uid="shape-1"><detail><contact callsign="SHAPE"/></detail></event>',
        "xml",
    ).find("event")

    handler.parse_device_info(shape)

    assert handler.uid is None
    assert handler.callsign is None


def test_channel_open_finishes_deferred_routing(monkeypatch):
    handler = make_handler(monkeypatch)
    handler.uid = "device-1"
    handler.callsign = "ALPHA"
    handler.platform = "ATAK"
    handler.socketio_publish_enabled = False
    channel = FakeChannel()

    handler.on_channel_open(channel)

    assert channel.declared == ["ALPHA", "device-1"]
    assert ("groups", "device-1", "__ANON__.OUT") in channel.bindings
    assert ("missions", "device-1", "missions") in channel.bindings
    assert ("dms", "device-1", "device-1") in channel.bindings
    assert ("dms", "ALPHA", "ALPHA") in channel.bindings
    assert [consumer[0] for consumer in channel.consumers] == ["ALPHA", "device-1"]


def test_closed_channel_requests_recovery(monkeypatch):
    handler = make_handler(monkeypatch)
    channel = FakeChannel()
    connection = FakeConnection()
    handler.rabbit_channel = channel
    handler.rabbit_connection = connection

    handler.on_channel_close(channel, RuntimeError("broker reset"))

    assert handler.rabbit_channel is None
    assert handler.shutdown is False
    assert connection.channel_requests == 1


def test_publish_race_caches_event(monkeypatch):
    handler = make_handler(monkeypatch)
    handler.uid = "device-1"
    handler.rabbit_channel = FakeChannel(publish_error=RuntimeError("channel closed"))
    event = BeautifulSoup('<event type="a-f-G" uid="device-1"/>', "xml").find("event")

    handler.publish_cot(event)

    assert handler.cached_messages == [event]


def test_disconnect_event_expires_original_track_at_last_point():
    now = datetime.datetime(2026, 7, 21, 12, 0, tzinfo=datetime.timezone.utc)
    cot = SimpleNamespace(type="a-f-G-U-C", how="m-g")
    point = SimpleNamespace(
        latitude=41.1,
        longitude=-87.2,
        hae=190.0,
        ce=4.0,
        le=7.0,
        cot=cot,
    )
    eud = SimpleNamespace(
        callsign="ALPHA",
        team_role="Team Lead",
        team=SimpleNamespace(name="Blue"),
    )

    event = build_disconnect_event("device-1", latest_point=point, eud=eud, now=now)

    assert event["uid"] == "device-1"
    assert event["type"] == "a-f-G-U-C"
    assert event.find("point")["lat"] == "41.1"
    assert event.find("point")["lon"] == "-87.2"
    assert event.find("contact")["callsign"] == "ALPHA"
    assert event.find("__group")["name"] == "Blue"
    assert event.find("__group")["role"] == "Team Lead"
    assert event["stale"] < event["time"]


def test_disconnect_controller_routes_stale_sa_and_updates_status():
    now_point = SimpleNamespace(
        latitude=41.1,
        longitude=-87.2,
        hae=190.0,
        ce=4.0,
        le=7.0,
        cot=SimpleNamespace(type="a-f-G-U-C", how="m-g"),
    )

    class FakeEud:
        callsign = "ALPHA"
        team_role = "Team Member"
        team = SimpleNamespace(name="Cyan")
        last_status = "Connected"
        last_event_time = None

        def to_json(self, include_last_point=False):
            return {"uid": "device-1", "last_point": include_last_point}

    eud = FakeEud()

    class Query:
        def __init__(self, model):
            self.model = model

        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def first(self):
            return now_point

    class Result:
        def __init__(self, value, many=False):
            self.value = value
            self.many = many

        def first(self):
            return (self.value,) if self.value else None

        def all(self):
            return self.value if self.many else []

    class Session:
        def __init__(self):
            self.execute_count = 0
            self.commits = 0

        def query(self, model):
            return Query(model)

        def execute(self, _statement):
            self.execute_count += 1
            if self.execute_count == 1:
                return Result(eud)
            return Result([], many=True)

        def commit(self):
            self.commits += 1

    session = Session()
    controller = SimpleNamespace(
        context=nullcontext(),
        logger=logging.getLogger("test-cot-controller"),
        db=SimpleNamespace(session=session),
        socketio=SimpleNamespace(events=[]),
    )
    controller.socketio.emit = (
        lambda *args, **kwargs: controller.socketio.events.append((args, kwargs))
    )
    controller.rabbit_channel = FakeChannel()
    routed = []
    controller.route_cot = lambda event, uid, user_id: routed.append(
        (event, uid, user_id)
    )

    process_disconnect(controller, "device-1", 7)

    assert eud.last_status == "Disconnected"
    assert session.commits == 1
    assert routed[0][0]["uid"] == "device-1"
    assert routed[0][1:] == ("device-1", 7)
    assert controller.socketio.events[0][0][0] == "eud"


def test_map_json_can_include_only_latest_point(monkeypatch):
    point = SimpleNamespace(to_json=lambda: {"uid": "point-latest"})

    class Query:
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def first(self):
            return point

    monkeypatch.setattr(db.session, "query", lambda model: Query())
    eud = SimpleNamespace(
        uid="device-1",
        callsign="ALPHA",
        certificate=None,
        device=None,
        os=None,
        platform=None,
        version=None,
        phone_number=None,
        last_event_time=None,
        last_status=None,
        user=None,
        team=None,
        team_role=None,
        data_packages=None,
    )

    payload = EUD.to_json(eud, include_last_point=True)

    assert payload["last_point"] == {"uid": "point-latest"}


def test_unknown_team_uses_gray_fallback():
    team = SimpleNamespace(
        name="Custom Team",
        colors=Team.colors,
        fallback_color=Team.fallback_color,
        chatroom=None,
        euds=None,
    )

    assert Team.get_team_color(team) == "#808080"
    assert Team.to_json(team)["color"] == "#808080"
