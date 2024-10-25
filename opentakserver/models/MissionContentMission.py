from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class MissionContentMission(db.Model):
    __tablename__ = "mission_content_mission"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_content_id: Mapped[int] = mapped_column(Integer, ForeignKey("mission_content.id"))
    mission_name: Mapped[str] = mapped_column(String(255), ForeignKey("missions.name"))

    def serialize(self):
        return {
            "mission_content_id": self.mission_content_id,
            "mission_name": self.mission_name
        }

    def to_json(self):
        return self.serialize()
