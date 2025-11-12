import datetime
import uuid
from dataclasses import dataclass
from xml.etree.ElementTree import Element, SubElement

from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.extensions import db
from sqlalchemy import Integer, String, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.models.MissionChange import MissionChange


@dataclass
class MissionLogEntry(db.Model):
    __tablename__ = "mission_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[str] = mapped_column(String(255))
    creator_uid: Mapped[str] = mapped_column(String(255))
    entry_uid: Mapped[str] = mapped_column(String(255), default=str(uuid.uuid4()))
    mission_name: Mapped[str] = mapped_column(String(255), ForeignKey("missions.name"))
    server_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.datetime.now(datetime.timezone.utc))
    dtg: Mapped[datetime] = mapped_column(DateTime, default=datetime.datetime.now(datetime.timezone.utc))
    created: Mapped[datetime] = mapped_column(DateTime, default=datetime.datetime.now(datetime.timezone.utc))
    # Leaving content_hash in order to not break existing DBs where this field is populated
    content_hash: Mapped[str] = mapped_column(String(255), nullable=True)
    content_hashes: Mapped[JSON] = mapped_column(JSON, default=[], nullable=True)
    keywords: Mapped[JSON] = mapped_column(JSON, default=[])
    mission = relationship("Mission", back_populates="mission_logs")

    def serialize(self):
        return {
            'content': self.content,
            'creator_uid': self.creator_uid,
            'entry_uid': self.entry_uid,
            'mission_names': self.mission_name,
            'server_time': self.server_time,
            'dtg': self.dtg,
            'created': self.created,
            'content_hashes': self.content_hashes,
            'keywords': self.keywords
        }

    def to_json(self):
        return {
            'id': self.entry_uid,
            'content': self.content,
            'creatorUid': self.creator_uid,
            'entryUid': self.entry_uid,
            'missionNames': [self.mission_name],
            'servertime': iso8601_string_from_datetime(self.server_time),
            'dtg': iso8601_string_from_datetime(self.dtg),
            'created': iso8601_string_from_datetime(self.created),
            'contentHashes': self.content_hashes if self.content_hash else [],
            'keywords': self.keywords if self.keywords is not None else []
        }

    def generate_cot(self) -> Element:
        event = Element("event", {"how": "h-g-i-g-o", "type": "t-x-m-c-l", "version": "2.0", "uid": str(uuid.uuid4()),
                                  "start": iso8601_string_from_datetime(self.dtg),
                                  "time": iso8601_string_from_datetime(self.server_time),
                                  "stale": iso8601_string_from_datetime(self.dtg + datetime.timedelta(minutes=2)),
                                  "access": "Undefined"})

        SubElement(event, "point", {"ce": "9999999", "le": "9999999", "hae": "0.0", "lat": "0.0", "lon": "0.0"})

        detail = SubElement(event, "detail")

        SubElement(detail, "mission", {"type": MissionChange.CHANGE, "tool": "public", "name": self.mission.name,
                                       "guid": self.mission.guid, "authorUid": self.creator_uid})

        return event
