import datetime
import uuid
from dataclasses import dataclass

from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.extensions import db
from sqlalchemy import Integer, String, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class MissionLogEntry(db.Model):
    __tablename__ = "mission_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[str] = mapped_column(String(255))
    creator_uid: Mapped[str] = mapped_column(String(255))
    entry_uid: Mapped[str] = mapped_column(String(255), default=str(uuid.uuid4()))
    mission_name: Mapped[str] = mapped_column(String(255), ForeignKey("missions.name"))
    server_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.datetime.now())
    dtg: Mapped[datetime] = mapped_column(DateTime, default=datetime.datetime.now())
    created: Mapped[datetime] = mapped_column(DateTime, default=datetime.datetime.now())
    content_hash: Mapped[str] = mapped_column(String(255), nullable=True)
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
            'content_hash': self.content_hash,
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
            'contentHashes': [self.content_hash] if self.content_hash else [],
            'keywords': self.keywords if self.keywords is not None else []
        }
