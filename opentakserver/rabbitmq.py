"""RabbitMQ topology helpers shared by OpenTAKServer processes."""

from __future__ import annotations

import logging

import pika

SOCKETIO_EXCHANGE = "flask-socketio"


def ensure_socketio_exchange(connection, channel, logger: logging.Logger):
    """Declare the transient Socket.IO fanout exchange, repairing old installs.

    OpenTAKServer 1.7.7 allowed the Socket.IO transport to create this exchange
    as durable. Newer OTS releases declare it explicitly as non-durable. AMQP
    closes the channel when a declaration disagrees with an existing exchange,
    so an in-place upgrade otherwise fails before the web application starts.

    The exchange carries ephemeral browser notifications, not persisted CoT.
    When the only conflict is its durability, replace it with the current
    topology and return the new open channel. Other broker failures propagate.
    """
    try:
        channel.exchange_declare(
            exchange=SOCKETIO_EXCHANGE,
            exchange_type="fanout",
            durable=False,
            auto_delete=False,
        )
        return channel
    except pika.exceptions.ChannelClosedByBroker as exc:
        message = str(getattr(exc, "reply_text", exc))
        is_upgrade_conflict = (
            getattr(exc, "reply_code", None) == 406
            and SOCKETIO_EXCHANGE in message
            and "durable" in message
        )
        if not is_upgrade_conflict:
            raise

        logger.warning(
            "Replacing legacy durable RabbitMQ exchange '%s' with the current "
            "non-durable Socket.IO topology",
            SOCKETIO_EXCHANGE,
        )
        repaired = connection.channel()
        repaired.exchange_delete(exchange=SOCKETIO_EXCHANGE, if_unused=False)
        repaired.exchange_declare(
            exchange=SOCKETIO_EXCHANGE,
            exchange_type="fanout",
            durable=False,
            auto_delete=False,
        )
        return repaired
