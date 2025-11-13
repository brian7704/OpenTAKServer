from dataclasses import dataclass

from sqlalchemy import String, Integer, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.extensions import db


@dataclass
class GroupMission(db.Model):
    __tablename__ = "groups_missions"

    mission_name: Mapped[String] = mapped_column(String, ForeignKey("missions.name"), primary_key=True)
    group_id: Mapped[Integer] = mapped_column(Integer, ForeignKey("groups.id"), primary_key=True)
    mission = relationship("Mission", cascade="all, delete", viewonly=True)
    group = relationship("Group", cascade="all, delete", viewonly=True)

    def serialize(self):
        return {
            "mission_name": self.mission_name,
            "group_id": self.group_id,
            "mission": self.mission.serialize(),
            "group": self.group.serialize()
        }
