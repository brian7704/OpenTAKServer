from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class MissionContentMissionChange(db.Model):
    __tablename__ = "mission_content_mission_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_content_id: Mapped[int] = mapped_column(Integer, ForeignKey("mission_content.id"))
    mission_change_id: Mapped[int] = mapped_column(Integer, ForeignKey("mission_changes.id"))
    #mission_content = relationship("MissionContent", back_populates="mission_changes")
    #mission_change = relationship("MissionChange", back_populates="content_resource")

    def serialize(self):
        return {
            "mission_content_id": self.mission_content_id,
            "mission_change_id": self.mission_change_id
        }

    def to_json(self):
        return self.serialize()
