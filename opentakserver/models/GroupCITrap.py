from dataclasses import dataclass

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.extensions import db


@dataclass
class GroupCITrap(db.Model):
    __tablename__ = "groups_citrap"

    citrap_id: Mapped[str] = mapped_column(String(255), ForeignKey("citrap.id"), primary_key=True)
    group_id: Mapped[Integer] = mapped_column(Integer, ForeignKey("groups.id"), primary_key=True)
    group = relationship("Group", cascade="all, delete", viewonly=True)
    citrap = relationship("CITrap", cascade="all, delete", viewonly=True)

    def serialize(self):
        return {
            "citrap_id": self.citrap_id,
            "group_id": self.group_id,
        }
