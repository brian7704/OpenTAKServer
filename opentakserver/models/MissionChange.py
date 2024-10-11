import datetime
import uuid
from dataclasses import dataclass
from xml.etree.ElementTree import Element, SubElement

from bs4 import BeautifulSoup

from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.extensions import db
from sqlalchemy import Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.models.Mission import Mission
from opentakserver.models.MissionContent import MissionContent


@dataclass
class MissionChange(db.Model):
    __tablename__ = "mission_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    isFederatedChange: Mapped[bool] = mapped_column(Boolean)
    change_type: Mapped[str] = mapped_column(String)
    mission_name: Mapped[str] = mapped_column(String, ForeignKey('missions.name'))
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    creator_uid: Mapped[str] = mapped_column(String)
    server_time: Mapped[datetime] = mapped_column(DateTime)
    content_resource = relationship("MissionContent", secondary="mission_content_mission_changes", back_populates="mission_changes")
    mission = relationship("Mission", back_populates="mission_changes")
    uid = relationship("MissionUID", back_populates="mission_change", uselist=False)

    def serialize(self):
        return {
            "isFederatedChange": self.isFederatedChange,
            "change_type": self.change_type,
            "mission_name": self.mission_name,
            "timestamp": self.timestamp,
            "creator_uid": self.creator_uid,
            "server_time": self.server_time,
        }

    def to_json(self):
        json = {
            "isFederatedChange": self.isFederatedChange,
            "type": self.change_type,
            "missionName": self.mission_name,
            "timestamp": iso8601_string_from_datetime(self.timestamp),
            "creatorUid": self.creator_uid,
            "serverTime": iso8601_string_from_datetime(self.server_time),
        }

        if self.content_resource:
            json['contentResource'] = self.content_resource.mission_content.to_json()

        if self.uid:
            json['details'] = self.uid.to_json()

        return json


def generate_mission_change_cot(mission_name: str, mission: Mission, content: MissionContent | None,
                                cot_event: BeautifulSoup | None, mission_change: MissionChange) -> Element:
    if content:
        uid = content.uid
    elif cot_event:
        uid = cot_event.attrs['uid']
    else:
        uid = str(uuid.uuid4())

    event = Element("event", {"version": "2.0", "uid": uid, "type": "t-x-m-c", "how": "h-g-i-g-o",
                              "start": iso8601_string_from_datetime(mission_change.timestamp),
                              "time": iso8601_string_from_datetime(mission_change.timestamp),
                              "stale": iso8601_string_from_datetime(
                                  mission_change.timestamp + datetime.timedelta(minutes=2))})
    SubElement(event, "point", {"ce": "9999999", "le": "9999999", "hae": "0", "lat": "0", "lon": "0"})

    detail = SubElement(event, "detail")
    mission_element = SubElement(detail, "mission",
                                 {"type": mission_change.change_type, "tool": "public", "name": mission_name,
                                  "guid": mission[0].guid, "authorUid": mission_change.creator_uid})
    mission_changes_element = SubElement(mission_element, "MissionChanges")
    mission_change_element = SubElement(mission_changes_element, "MissionChange")

    if content:
        content_resource = SubElement(mission_change_element, "contentResource")
        SubElement(content_resource, "creatorUid").text = mission_change.creator_uid
        SubElement(content_resource, "expiration").text = "-1"
        SubElement(content_resource, "groupVector").text = "0"
        SubElement(content_resource, "hash").text = content.hash
        SubElement(content_resource, "mimeType").text = content.mime_type
        SubElement(content_resource, "name").text = content.filename
        SubElement(content_resource, "size").text = str(content.size)
        SubElement(content_resource, "submissionTime").text = iso8601_string_from_datetime(content.submission_time)
        SubElement(content_resource, "submitter").text = content.submitter
        SubElement(content_resource, "uid").text = content.uid

    if cot_event:
        details_tag = SubElement(mission_change_element, "details", {'type': cot_event.attrs['type']})

        point = cot_event.find("point")
        color = cot_event.find("color")
        callsign = cot_event.find("contact")
        icon = cot_event.find("usericon")

        if color:
            details_tag.set("color", color.attrs['argb'])
        if callsign:
            details_tag.set("callsign", callsign.attrs['callsign'])
        if icon:
            details_tag.set("iconsetPath", icon.attrs['iconsetpath'])

        SubElement(details_tag, "location", {'lon': point.attrs['lon'], 'lat': point.attrs['lat']})
        SubElement(mission_change_element, "contentUid").text = cot_event.attrs['uid']

    SubElement(mission_change_element, "creatorUid").text = mission_change.creator_uid
    SubElement(mission_change_element, "isFederatedChange").text = str(mission_change.isFederatedChange)
    SubElement(mission_change_element, "missionName").text = mission_name
    SubElement(mission_change_element, "timestamp").text = iso8601_string_from_datetime(mission_change.timestamp)
    SubElement(mission_change_element, "type").text = mission_change.change_type

    return event
