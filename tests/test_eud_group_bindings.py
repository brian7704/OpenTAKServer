from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pika.exceptions
import sqlalchemy.exc
from flask_security.models import fsqla_v3 as fsqla

from opentakserver.extensions import db

try:
    fsqla.FsModels.set_db_info(db)
except sqlalchemy.exc.InvalidRequestError:
    pass

from opentakserver.blueprints.ots_api.group_api import (  # noqa: E402
    _queue_exists as group_api_queue_exists,
)
from opentakserver.eud_handler.EudHandler import EudHandler  # noqa: E402
from opentakserver.models.Group import Group  # noqa: E402


def make_eud_handler(uid="ANDROID-1234", ldap_enabled=False):
    handler = EudHandler.__new__(EudHandler)
    handler.uid = uid
    handler.callsign = "kevopfor"
    handler.bound_queues = []
    handler.cached_messages = []
    handler.group_memberships = []
    handler.app = MagicMock()
    handler.app.config.get.side_effect = (
        lambda key, default=None: ldap_enabled if key == "OTS_ENABLE_LDAP" else default
    )
    handler.rabbit_channel = MagicMock()
    handler.rabbit_channel.is_closing = False
    handler.rabbit_channel.is_closed = False
    handler.logger = MagicMock()
    return handler


def test_reconcile_group_bindings_unbinds_stale_groups():
    handler = make_eud_handler(uid="ANDROID-8a0e13e6a5a4d3b1", ldap_enabled=False)
    fake_groups = [
        SimpleNamespace(name="__ANON__"),
        SimpleNamespace(name="1S"),
        SimpleNamespace(name="blufor"),
        SimpleNamespace(name="opfor"),
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = fake_groups

    with patch("opentakserver.eud_handler.EudHandler.db") as mock_db:
        mock_db.session.execute.return_value = mock_result
        handler._reconcile_group_bindings({f"opfor.{Group.OUT}", f"opfor.{Group.IN}"})

    expected_unbinds = [
        call(exchange="groups", queue="ANDROID-8a0e13e6a5a4d3b1", routing_key="1S.IN"),
        call(exchange="groups", queue="ANDROID-8a0e13e6a5a4d3b1", routing_key="1S.OUT"),
        call(exchange="groups", queue="ANDROID-8a0e13e6a5a4d3b1", routing_key="__ANON__.IN"),
        call(exchange="groups", queue="ANDROID-8a0e13e6a5a4d3b1", routing_key="__ANON__.OUT"),
        call(exchange="groups", queue="ANDROID-8a0e13e6a5a4d3b1", routing_key="blufor.IN"),
        call(exchange="groups", queue="ANDROID-8a0e13e6a5a4d3b1", routing_key="blufor.OUT"),
    ]
    assert handler.rabbit_channel.queue_unbind.call_args_list == expected_unbinds


def test_reconcile_group_bindings_skips_when_ldap_enabled():
    handler = make_eud_handler(ldap_enabled=True)

    with patch("opentakserver.eud_handler.EudHandler.db") as mock_db:
        handler._reconcile_group_bindings({"opfor.OUT"})
        mock_db.session.execute.assert_not_called()

    handler.rabbit_channel.queue_unbind.assert_not_called()


def test_record_and_unbind_rabbitmq_queues_deduplicates():
    handler = make_eud_handler(uid="EUD-1")
    handler._record_bound_queue("groups", "opfor.OUT", "EUD-1")
    handler._record_bound_queue("groups", "opfor.OUT", "EUD-1")
    handler._record_bound_queue("groups", "opfor.IN", "EUD-1")

    assert len(handler.bound_queues) == 2

    handler.unbind_rabbitmq_queues()
    assert handler.rabbit_channel.queue_unbind.call_args_list == [
        call(queue="EUD-1", exchange="missions", routing_key="missions"),
        call(exchange="groups", queue="EUD-1", routing_key="opfor.OUT"),
        call(exchange="groups", queue="EUD-1", routing_key="opfor.IN"),
    ]


def test_queue_exists_handles_missing_queue_gracefully():
    conn = MagicMock()
    check_channel = MagicMock()
    conn.channel.return_value = check_channel

    assert group_api_queue_exists(conn, "ANDROID-1") is True
    check_channel.queue_declare.assert_called_once_with(queue="ANDROID-1", passive=True)
    check_channel.close.assert_called_once()

    missing_channel = MagicMock()
    missing_channel.queue_declare.side_effect = pika.exceptions.ChannelClosedByBroker(
        404, "NOT_FOUND"
    )
    conn.channel.return_value = missing_channel

    assert group_api_queue_exists(conn, "CesiumViewer-missing") is False
