import time
from datetime import datetime, timezone
from math import floor
from xml.etree.ElementTree import Element, SubElement
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from opentakserver.extensions import logger
from opentakserver.functions import (
    iso8601_string_from_datetime,
    iso8601_string_from_unix_timestamp,
    datetime_from_iso8601_string,
    unix_timestamp_from_iso8601_string,
)
from opentakserver.proto import fig_pb2
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


def cot2federated_event(cot: str, node_id: str):
    federated_event = FederatedEvent()

    soup = BeautifulSoup(cot, "lxml")
    event = soup.find("event")

    if not event:
        return None

    send_time = floor(time.time() * 1000)
    start_time = unix_timestamp_from_iso8601_string(str(event.attrs.get("start")))
    stale_time = unix_timestamp_from_iso8601_string(str(event.attrs.get("stale")))

    federated_event.event.sendTime = send_time
    federated_event.event.startTime = start_time
    federated_event.event.staleTime = stale_time
    federated_event.event.uid = str(event.attrs.get("uid"))
    federated_event.event.type = str(event.attrs.get("type"))
    federated_event.event.coordSource = str(event.attrs.get("how"))
    federated_event.event.access = str(event.attrs.get("access", "Undefined"))

    point = soup.find("point")
    if not point:
        return None

    federated_event.event.lat = float(point.attrs.get("lat", 9999999))
    federated_event.event.lon = float(point.attrs.get("lon", 9999999))
    federated_event.event.hae = float(point.attrs.get("hae", 9999999))
    federated_event.event.ce = float(point.attrs.get("ce", 9999999))
    federated_event.event.le = float(point.attrs.get("le", 9999999))

    detail = soup.find("detail")

    # Add the <_flow_tags_> tag
    flow_tag = soup.new_tag("_flow-tags_")
    flow_tag.attrs[f"TAK-Server-{node_id}"] = iso8601_string_from_datetime()
    detail.append(flow_tag)

    # BeautifulSoup does some wonky crap when parsing tags with underscores
    detail = (
        str(detail).replace("&lt;", "<").replace("&gt;", ">").replace("<!--__chat-->", "</__chat>")
    )

    federated_event.event.other = detail

    return federated_event
