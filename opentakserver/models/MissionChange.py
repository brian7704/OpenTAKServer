import datetime
from dataclasses import dataclass

from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.extensions import db
from sqlalchemy import Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship


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

        return json
