"""CoT XML <-> federation protobuf mapping.

Mirrors TAK Server's ProtoBufHelper (tak.server.federation.ProtoBufHelper) so
that events produced here are byte-compatible with what an official TAK Server
expects on a federation link, and events received from one reconstruct the
same CoT XML an official server would produce:

- ``time``/``start``/``stale`` become epoch milliseconds.
- ``<track speed course>``, ``<status battery>`` (without a ``readiness``
  attribute), ``<precisionlocation geopointsrc altsrc>`` and ``<image>`` data
  are lifted out of ``<detail>`` into dedicated fields.
- The remaining ``<detail>`` element is carried opaquely in ``other``.
- ``<marti><dest>`` routing intent maps to ``ptpCallsigns``/``ptpUids``/
  ``missionNames`` (TAK Server carries these in broker context rather than in
  the federated detail).
"""

import base64
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from opentakserver.federation.proto import fig_pb2

logger = logging.getLogger("OpenTAKServer")

# Control traffic that has no business crossing a federation link.
EXCLUDED_COT_TYPES = {"t-x-c-t", "t-x-c-t-r"}  # ping / pong


def millis_from_cot_time(value: str) -> int:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def cot_time_from_millis(millis: int) -> str:
    dt = datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _float_attr(tag, name: str, default: float) -> float:
    try:
        return float(tag.attrs[name])
    except (KeyError, TypeError, ValueError):
        return default


def cot_to_federated_event(cot: str) -> fig_pb2.FederatedEvent | None:
    """Convert a CoT ``<event>`` XML string to a FederatedEvent.

    Returns None for events that cannot be represented (no event element or
    missing mandatory attributes), mirroring TAK Server which drops events it
    cannot convert.
    """
    soup = BeautifulSoup(cot, "xml")
    event = soup.find("event")
    if not event:
        return None

    point = event.find("point")

    fed_event = fig_pb2.FederatedEvent()
    geo = fed_event.event

    try:
        geo.sendTime = millis_from_cot_time(event.attrs["time"])
        geo.startTime = millis_from_cot_time(event.attrs["start"])
        geo.staleTime = millis_from_cot_time(event.attrs["stale"])
        geo.uid = event.attrs["uid"]
        geo.type = event.attrs["type"]
    except (KeyError, ValueError) as e:
        logger.warning(f"Cannot federate CoT event, missing/invalid attribute: {e}")
        return None

    geo.coordSource = event.attrs.get("how", "")

    contact = event.find("contact")
    if contact and contact.attrs.get("callsign"):
        geo.screenName = contact.attrs["callsign"]

    if point:
        geo.lat = _float_attr(point, "lat", 0)
        geo.lon = _float_attr(point, "lon", 0)
        geo.hae = _float_attr(point, "hae", 0)
        geo.ce = _float_attr(point, "ce", 999999)
        geo.le = _float_attr(point, "le", 999999)
    else:
        geo.ce = 999999
        geo.le = 999999

    if "access" in event.attrs:
        geo.access = event.attrs["access"]
    if "caveat" in event.attrs:
        geo.caveat = event.attrs["caveat"]
    if "releasableTo" in event.attrs:
        geo.releaseableTo = event.attrs["releasableTo"]

    detail = event.find("detail")
    if detail:
        # Work on a copy so callers keep their original document intact.
        detail = BeautifulSoup(str(detail), "xml").find("detail")

        track = detail.find("track")
        if track and "speed" in track.attrs and "course" in track.attrs:
            geo.speed = _float_attr(track, "speed", 0)
            geo.course = _float_attr(track, "course", 0)
            track.decompose()

        status = detail.find("status")
        if status and "battery" in status.attrs and "readiness" not in status.attrs:
            try:
                geo.battery = int(status.attrs["battery"])
            except ValueError:
                pass
            status.decompose()

        ploc = detail.find("precisionlocation")
        if ploc and "geopointsrc" in ploc.attrs and "altsrc" in ploc.attrs:
            geo.ploc = ploc.attrs["geopointsrc"]
            geo.palt = ploc.attrs["altsrc"]
            ploc.decompose()

        image = detail.find("image")
        if image and image.text:
            try:
                geo.binary.type = fig_pb2.IMAGE
                geo.binary.data = base64.b64decode(image.text)
                image.string = ""
            except ValueError:
                logger.warning("Could not decode image data, sending as-is")

        # TAK Server strips <marti> destinations during ingest and carries the
        # routing intent alongside the event; reproduce that on the wire.
        marti = detail.find("marti")
        if marti:
            for dest in marti.find_all("dest"):
                if dest.attrs.get("callsign"):
                    geo.ptpCallsigns.append(dest.attrs["callsign"])
                elif dest.attrs.get("mission"):
                    geo.missionNames.append(dest.attrs["mission"])
                elif dest.attrs.get("uid"):
                    geo.ptpUids.append(dest.attrs["uid"])
            marti.decompose()

        geo.other = str(detail)

    return fed_event


def federated_event_to_cot(fed_event: fig_pb2.FederatedEvent) -> str | None:
    """Convert a received FederatedEvent's GeoEvent back to CoT XML.

    Mirrors ProtoBufHelper.proto2cot, and additionally re-synthesizes
    ``<marti><dest>`` elements from the ptp/mission fields so the local router
    can honor the sender's addressing.
    """
    if not fed_event.HasField("event"):
        return None

    geo = fed_event.event

    event = ET.Element(
        "event",
        {
            "version": "2.0",
            "uid": geo.uid,
            "type": geo.type,
            "how": geo.coordSource,
            "time": cot_time_from_millis(geo.sendTime),
            "start": cot_time_from_millis(geo.startTime),
            "stale": cot_time_from_millis(geo.staleTime),
        },
    )

    if geo.access:
        event.set("access", geo.access)
    if geo.caveat:
        event.set("caveat", geo.caveat)
    if geo.releaseableTo:
        event.set("releasableTo", geo.releaseableTo)

    ET.SubElement(
        event,
        "point",
        {
            "lat": str(geo.lat),
            "lon": str(geo.lon),
            "hae": str(geo.hae),
            "ce": str(geo.ce),
            "le": str(geo.le),
        },
    )

    detail = None
    if geo.other:
        try:
            detail = ET.fromstring(geo.other)
        except ET.ParseError as e:
            logger.warning(f"Could not parse federated detail, dropping it: {e}")

    if detail is None and (geo.ptpCallsigns or geo.ptpUids or geo.missionNames):
        detail = ET.Element("detail")

    if detail is not None:
        ET.SubElement(
            detail, "track", {"speed": str(geo.speed), "course": str(geo.course)}
        )

        if detail.find("status") is None:
            ET.SubElement(detail, "status", {"battery": str(geo.battery)})

        if detail.find("precisionlocation") is None and (geo.ploc or geo.palt):
            ploc = ET.SubElement(detail, "precisionlocation")
            if geo.ploc:
                ploc.set("geopointsrc", geo.ploc)
            if geo.palt:
                ploc.set("altsrc", geo.palt)

        image = detail.find("image")
        if (
            geo.HasField("binary")
            and geo.binary.type == fig_pb2.IMAGE
            and image is not None
        ):
            image.text = base64.b64encode(geo.binary.data).decode()

        if geo.ptpCallsigns or geo.ptpUids or geo.missionNames:
            marti = detail.find("marti")
            if marti is None:
                marti = ET.SubElement(detail, "marti")
            for callsign in geo.ptpCallsigns:
                ET.SubElement(marti, "dest", {"callsign": callsign})
            for uid in geo.ptpUids:
                ET.SubElement(marti, "dest", {"uid": uid})
            for mission in geo.missionNames:
                ET.SubElement(marti, "dest", {"mission": mission})

        event.append(detail)

    return ET.tostring(event, encoding="unicode")


def sender_identity(fed_event: fig_pb2.FederatedEvent) -> tuple[str | None, str | None]:
    """Best-effort (uid, callsign) of the entity that originated an event.

    For situational-awareness the track uid is the sender. For GeoChat the
    track uid is the message id, so attribute to the sending EUD carried in
    the chat detail instead - this is the uid the receiving server should
    persist the CoT against.
    """
    geo = fed_event.event
    if geo.other:
        chat = BeautifulSoup(geo.other, "xml").find("__chat")
        if chat:
            chatgrp = chat.find("chatgrp")
            sender = chatgrp.attrs.get("uid0") if chatgrp else None
            if sender:
                return sender, chat.attrs.get("senderCallsign") or None
    return (geo.uid or None), (geo.screenName or None)


def contact_event(
    uid: str, callsign: str, operation: int = fig_pb2.CREATE
) -> fig_pb2.FederatedEvent:
    """Build a ContactListEntry announcement for a local EUD."""
    fed_event = fig_pb2.FederatedEvent()
    fed_event.contact.operation = operation
    fed_event.contact.uid = uid
    fed_event.contact.callsign = callsign
    return fed_event
