from datetime import datetime, timezone
from math import floor
from xml.etree.ElementTree import Element, SubElement
from xml.etree import ElementTree

from opentakserver.extensions import logger
from opentakserver.functions import iso8601_string_from_datetime, iso8601_string_from_unix_timestamp
from opentakserver.proto.fig_pb2 import FederatedEvent


def federated_event2cot(federated_event) -> str | None:
    if not federated_event.HasField("event"):
        return None

    cot_event = federated_event.event

    event = Element(
        "event",
        {
            "how": cot_event.coordSource,
            "type": cot_event.type,
            "version": "2.0",
            "uid": cot_event.uid,
            "start": iso8601_string_from_unix_timestamp(floor(cot_event.startTime / 1000)),
            "time": iso8601_string_from_unix_timestamp(floor(cot_event.startTime / 1000)),
            "stale": iso8601_string_from_unix_timestamp(floor(cot_event.staleTime / 1000)),
        },
    )
    SubElement(
        event,
        "point",
        {
            "ce": str(cot_event.ce),
            "le": str(cot_event.le),
            "hae": str(cot_event.hae),
            "lat": str(cot_event.lat),
            "lon": str(cot_event.lon),
        },
    )

    # <detail> tag
    event.append(ElementTree.fromstring(federated_event.event.other))
    return ElementTree.tostring(event).decode("utf-8")
