import datetime
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from xml.etree.ElementTree import fromstring

import sqlalchemy.exc
from flask import Flask
from flask_security.models import fsqla_v3 as fsqla

from opentakserver.defaultconfig import DefaultConfig
from opentakserver.extensions import db

try:
    fsqla.FsModels.set_db_info(db)
except sqlalchemy.exc.InvalidRequestError:
    pass

import opentakserver.app  # noqa: E402, F401
from opentakserver.controllers.meshtastic_controller import MeshtasticController  # noqa: E402
from opentakserver.functions import datetime_from_iso8601_string  # noqa: E402
from opentakserver.models.role import Role  # noqa: E402, F401
from opentakserver.models.user import User  # noqa: E402, F401


def _make_controller(stale_minutes=30, check_interval=60, group="Meshtastic"):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    app.config["OTS_NODE_ID"] = "test-node-id"
    app.config["OTS_RABBITMQ_SERVER_ADDRESS"] = "127.0.0.1"
    app.config["OTS_RABBITMQ_TTL"] = "86400000"
    app.config["OTS_MESHTASTIC_GROUP"] = group
    app.config["OTS_MESHTASTIC_STALE_MINUTES"] = stale_minutes
    app.config["OTS_MESHTASTIC_STALE_CHECK_INTERVAL"] = check_interval

    rmq_module = MeshtasticController.__bases__[0].__module__
    with (
        patch.object(MeshtasticController, "get_euds", return_value=None),
        patch.object(MeshtasticController, "get_channels", return_value=None),
        patch(f"{rmq_module}.pika.SelectConnection") as mock_conn_cls,
        patch(f"{rmq_module}.Thread"),
    ):
        mock_conn = MagicMock()
        mock_conn.is_closing = False
        mock_conn.is_closed = False
        mock_conn_cls.return_value = mock_conn

        ctrl = MeshtasticController(app.app_context())
        ctrl.rabbit_channel = MagicMock()
        ctrl.rabbit_channel.is_closed = False
        return ctrl


def _sample_device(uid="8d54d459", callsign="squad 6"):
    return {
        "hw_model": "TBEAM",
        "long_name": callsign,
        "short_name": "sqd6",
        "firmware_version": "2.7.24",
        "last_lat": "28.5495",
        "last_lon": "-81.3792",
        "battery": 85,
        "meshtastic_id": uid,
        "voltage": 4.1,
        "uptime": 1200,
        "last_alt": "30.0",
        "course": "0.0",
        "speed": "0.0",
        "team": "Cyan",
        "role": "Team Member",
        "uid": uid,
        "macaddr": "",
        "last_seen": None,
    }


def test_default_config_values():
    assert DefaultConfig.OTS_MESHTASTIC_STALE_MINUTES == 30
    assert DefaultConfig.OTS_MESHTASTIC_STALE_CHECK_INTERVAL == 60


def test_cot_uses_configurable_stale_minutes():
    ctrl30 = _make_controller(stale_minutes=30)
    ctrl30.meshtastic_devices["8d54d459"] = _sample_device()
    ev30 = ctrl30.cot(None, "8d54d459", "all", "POSITION_APP")
    delta30 = datetime_from_iso8601_string(ev30.attrib["stale"]) - datetime_from_iso8601_string(
        ev30.attrib["time"]
    )
    assert abs(delta30.total_seconds() - 1800) <= 2

    ctrl10 = _make_controller(stale_minutes=10)
    ctrl10.meshtastic_devices["8d54d459"] = _sample_device()
    ev10 = ctrl10.cot(None, "8d54d459", "all", "POSITION_APP")
    delta10 = datetime_from_iso8601_string(ev10.attrib["stale"]) - datetime_from_iso8601_string(
        ev10.attrib["time"]
    )
    assert abs(delta10.total_seconds() - 600) <= 2

    ctrl_disabled = _make_controller(stale_minutes=0)
    ctrl_disabled.meshtastic_devices["8d54d459"] = _sample_device()
    ev_disabled = ctrl_disabled.cot(None, "8d54d459", "all", "POSITION_APP")
    delta_disabled = datetime_from_iso8601_string(
        ev_disabled.attrib["stale"]
    ) - datetime_from_iso8601_string(ev_disabled.attrib["time"])
    assert abs(delta_disabled.total_seconds() - 86400) <= 2


def test_check_stale_euds_marks_timed_out_nodes_disconnected_and_publishes_delete_cot():
    ctrl = _make_controller(stale_minutes=30, check_interval=45, group="Meshtastic")
    now_naive_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    stale_eud = SimpleNamespace(
        uid="8d54d459",
        callsign="squad 6",
        platform="Meshtastic",
        last_status="Connected",
        last_event_time=now_naive_utc - datetime.timedelta(minutes=31),
        to_json=lambda: {
            "uid": "8d54d459",
            "callsign": "squad 6",
            "platform": "Meshtastic",
            "last_status": stale_eud.last_status,
        },
    )
    fresh_eud = SimpleNamespace(
        uid="433a93b8",
        callsign="Kevin K Mesh Node",
        platform="Meshtastic",
        last_status="Connected",
        last_event_time=now_naive_utc - datetime.timedelta(minutes=5),
        to_json=lambda: {
            "uid": "433a93b8",
            "callsign": "Kevin K Mesh Node",
            "platform": "Meshtastic",
            "last_status": fresh_eud.last_status,
        },
    )

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [stale_eud, fresh_eud]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    with (
        patch("opentakserver.controllers.meshtastic_controller.db") as mock_db,
        patch("opentakserver.controllers.meshtastic_controller.socketio") as mock_sio,
    ):
        mock_db.session.execute.return_value = mock_result
        staled = ctrl.check_stale_euds()

    assert staled == ["8d54d459"]
    assert stale_eud.last_status == "Disconnected"
    assert fresh_eud.last_status == "Connected"

    mock_sio.emit.assert_called_once_with(
        "eud",
        {
            "uid": "8d54d459",
            "callsign": "squad 6",
            "platform": "Meshtastic",
            "last_status": "Disconnected",
        },
        namespace="/socket.io",
    )

    assert ctrl.rabbit_channel.basic_publish.call_count == 2
    exchanges = {
        (c.kwargs["exchange"], c.kwargs["routing_key"])
        for c in ctrl.rabbit_channel.basic_publish.call_args_list
    }
    assert exchanges == {("firehose", ""), ("groups", "Meshtastic.OUT")}

    raw_body = ctrl.rabbit_channel.basic_publish.call_args_list[0].kwargs["body"]
    published_payload = json.loads(raw_body)
    assert published_payload["uid"] == "8d54d459"
    cot_xml = fromstring(published_payload["cot"])
    assert cot_xml.attrib["type"] == "t-x-d-d"
    link = cot_xml.find("./detail/link")
    assert link is not None
    assert link.attrib["uid"] == "8d54d459"
    assert link.attrib["type"] == "a-f-G-U-C"

    ctrl.rabbit_connection.ioloop.call_later.assert_called_once_with(45.0, ctrl.check_stale_euds)


def test_legacy_eud_with_recent_point_backfills_connected_instead_of_staling():
    ctrl = _make_controller(stale_minutes=30)
    recent_point_ts = datetime.datetime.now(datetime.timezone.utc).replace(
        tzinfo=None
    ) - datetime.timedelta(minutes=10)

    legacy_eud = SimpleNamespace(
        uid="8d54d459",
        callsign="squad 6",
        platform="Meshtastic",
        last_status=None,
        last_event_time=None,
        to_json=lambda: {
            "uid": "8d54d459",
            "callsign": "squad 6",
            "last_status": legacy_eud.last_status,
        },
    )

    eud_scalars = MagicMock()
    eud_scalars.all.return_value = [legacy_eud]
    eud_query_res = MagicMock()
    eud_query_res.scalars.return_value = eud_scalars

    point_query_res = MagicMock()
    point_query_res.scalar.return_value = recent_point_ts

    with (
        patch("opentakserver.controllers.meshtastic_controller.db") as mock_db,
        patch("opentakserver.controllers.meshtastic_controller.socketio") as mock_sio,
    ):
        mock_db.session.execute.side_effect = [eud_query_res, point_query_res]
        staled = ctrl.check_stale_euds()

    assert staled == []
    assert legacy_eud.last_status == "Connected"
    assert legacy_eud.last_event_time == recent_point_ts
    ctrl.rabbit_channel.basic_publish.assert_not_called()
    mock_sio.emit.assert_called_once()


def test_insert_or_update_eud_updates_status_even_when_update_if_exists_false():
    ctrl = _make_controller(stale_minutes=30)
    ctrl.meshtastic_devices["8d54d459"] = _sample_device()

    persisted_eud = SimpleNamespace(
        uid="8d54d459",
        callsign="squad 6",
        last_status="Connected",
        to_json=lambda: {"uid": "8d54d459", "callsign": "squad 6", "last_status": "Connected"},
    )
    team_res = MagicMock()
    team_res.scalar.return_value = SimpleNamespace(id=1, name="Cyan")
    update_res = MagicMock()
    persisted_res = MagicMock()
    persisted_res.scalar.return_value = persisted_eud

    with (
        patch("opentakserver.controllers.meshtastic_controller.db") as mock_db,
        patch("opentakserver.controllers.meshtastic_controller.socketio") as mock_sio,
    ):
        mock_db.session.commit.side_effect = [
            sqlalchemy.exc.IntegrityError("stmt", "params", Exception("dup")),
            None,
        ]
        mock_db.session.execute.side_effect = [team_res, update_res, persisted_res]
        ctrl.insert_or_update_eud("8d54d459", "8d54d459", update_if_exists=False)

    assert ctrl.meshtastic_devices["8d54d459"]["last_seen"] is not None
    assert mock_db.session.execute.call_count == 3
    mock_sio.emit.assert_called_once_with(
        "eud",
        {"uid": "8d54d459", "callsign": "squad 6", "last_status": "Connected"},
        namespace="/socket.io",
    )


def test_record_node_activity_reconnects_disconnected_eud():
    ctrl = _make_controller(stale_minutes=30)
    ctrl.meshtastic_devices["8d54d459"] = _sample_device()

    eud = SimpleNamespace(
        uid="8d54d459",
        callsign="squad 6",
        platform="Meshtastic",
        last_status="Disconnected",
        last_event_time=None,
        to_json=lambda: {
            "uid": "8d54d459",
            "callsign": "squad 6",
            "last_status": eud.last_status,
        },
    )
    mock_result = MagicMock()
    mock_result.scalar.return_value = eud

    with (
        patch("opentakserver.controllers.meshtastic_controller.db") as mock_db,
        patch("opentakserver.controllers.meshtastic_controller.socketio") as mock_sio,
    ):
        mock_db.session.execute.return_value = mock_result
        ctrl.record_node_activity("8d54d459")

    assert eud.last_status == "Connected"
    assert eud.last_event_time is not None
    assert ctrl.meshtastic_devices["8d54d459"]["last_seen"] is not None
    mock_sio.emit.assert_called_once()
