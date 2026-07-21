from datetime import datetime, timedelta, timezone
from xml.etree.ElementTree import Element, SubElement, tostring

from bs4 import BeautifulSoup
from sqlalchemy import select

from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.models.EUD import EUD
from opentakserver.models.Mission import Mission
from opentakserver.models.Point import Point


def build_disconnect_event(uid, latest_point=None, eud=None, now=None):
    """Build a stale SA event that expires the EUD's real map track."""
    now = now or datetime.now(timezone.utc)
    stale = now - timedelta(seconds=1)
    lat = lon = 0
    hae = 0
    ce = le = 9999999
    event_type = "a-f-G-U-C"
    how = "m-g"
    callsign = getattr(eud, "callsign", None) or uid
    team_name = "Cyan"
    team_role = getattr(eud, "team_role", None) or "Team Member"

    if latest_point:
        lat = latest_point.latitude or 0
        lon = latest_point.longitude or 0
        hae = latest_point.hae or 0
        ce = latest_point.ce or 9999999
        le = latest_point.le or 9999999
        if latest_point.cot:
            event_type = latest_point.cot.type or event_type
            how = latest_point.cot.how or how

    if eud and eud.team:
        team_name = eud.team.name or team_name

    event = Element(
        "event",
        {
            "how": how,
            "type": event_type,
            "version": "2.0",
            "uid": uid,
            "start": iso8601_string_from_datetime(now),
            "time": iso8601_string_from_datetime(now),
            "stale": iso8601_string_from_datetime(stale),
        },
    )
    SubElement(
        event,
        "point",
        {
            "ce": str(ce),
            "le": str(le),
            "hae": str(hae),
            "lat": str(lat),
            "lon": str(lon),
        },
    )
    detail = SubElement(event, "detail")
    SubElement(detail, "contact", {"callsign": callsign})
    SubElement(detail, "__group", {"name": team_name, "role": team_role})
    SubElement(
        detail,
        "_flow-tags_",
        {"OpenTAKServer": iso8601_string_from_datetime(now)},
    )
    return BeautifulSoup(tostring(event).decode("utf-8"), "xml").find("event")


def process_disconnect(controller, uid, user_id, now=None):
    """Expire, route, and persist one EUD disconnect through a CoT controller."""
    if not uid:
        return None

    now = now or datetime.now(timezone.utc)
    with controller.context:
        latest_point = (
            controller.db.session.query(Point)
            .filter(Point.device_uid == uid)
            .order_by(Point.timestamp.desc(), Point.id.desc())
            .first()
        )
        eud_result = controller.db.session.execute(
            select(EUD).filter_by(uid=uid)
        ).first()
        eud = eud_result[0] if eud_result else None
        event = build_disconnect_event(uid, latest_point=latest_point, eud=eud, now=now)

        if eud:
            eud.last_status = "Disconnected"
            eud.last_event_time = now
            controller.db.session.commit()
            controller.socketio.emit(
                "eud", eud.to_json(include_last_point=True), namespace="/socket.io"
            )

        missions = controller.db.session.execute(
            controller.db.session.query(Mission)
        ).all()

    channel = controller.rabbit_channel
    if channel and not channel.is_closed:
        controller.route_cot(event, uid, user_id)
        for mission in missions:
            channel.queue_unbind(
                queue=uid,
                exchange="missions",
                routing_key=f"missions.{mission[0].name}",
            )
            controller.logger.debug(f"Unbound {uid} from mission.{mission[0].name}")

    return event
