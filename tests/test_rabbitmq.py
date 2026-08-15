"""RabbitMQ topology upgrade behavior."""

from unittest.mock import Mock

import pika
import pytest

from opentakserver.rabbitmq import SOCKETIO_EXCHANGE, ensure_socketio_exchange


def test_existing_non_durable_socketio_exchange_is_left_in_place():
    connection = Mock()
    channel = Mock()

    returned = ensure_socketio_exchange(connection, channel, Mock())

    assert returned is channel
    channel.exchange_declare.assert_called_once_with(
        exchange=SOCKETIO_EXCHANGE,
        exchange_type="fanout",
        durable=False,
        auto_delete=False,
    )
    connection.channel.assert_not_called()


def test_legacy_durable_socketio_exchange_is_replaced():
    connection = Mock()
    original = Mock()
    repaired = Mock()
    connection.channel.return_value = repaired
    original.exchange_declare.side_effect = pika.exceptions.ChannelClosedByBroker(
        406,
        "PRECONDITION_FAILED - inequivalent arg 'durable' for exchange "
        "'flask-socketio': received 'false' but current is 'true'",
    )

    returned = ensure_socketio_exchange(connection, original, Mock())

    assert returned is repaired
    repaired.exchange_delete.assert_called_once_with(
        exchange=SOCKETIO_EXCHANGE,
        if_unused=False,
    )
    repaired.exchange_declare.assert_called_once_with(
        exchange=SOCKETIO_EXCHANGE,
        exchange_type="fanout",
        durable=False,
        auto_delete=False,
    )


def test_unrelated_broker_precondition_is_not_deleted():
    connection = Mock()
    channel = Mock()
    channel.exchange_declare.side_effect = pika.exceptions.ChannelClosedByBroker(
        406,
        "PRECONDITION_FAILED - inequivalent arg 'type' for exchange 'groups'",
    )

    with pytest.raises(pika.exceptions.ChannelClosedByBroker):
        ensure_socketio_exchange(connection, channel, Mock())

    connection.channel.assert_not_called()
