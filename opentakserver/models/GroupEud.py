import datetime
from dataclasses import dataclass

from opentakserver.extensions import db
from opentakserver.functions import iso8601_string_from_datetime
from sqlalchemy import Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class GroupEud(db.Model):
    __tablename__ = "groups_euds"

    IN = "IN"
    OUT = "OUT"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("groups.id"))
    direction: Mapped[str] = mapped_column(String(255))  # IN, OUT
    active: Mapped[bool] = mapped_column(Boolean)
    description: Mapped[str] = mapped_column(String(255), nullable=True)
    eud_uid: Mapped[str] = mapped_column(String(255), ForeignKey("euds.uid", ondelete="CASCADE"))

    def serialize(self):
        return {
            'group_id': self.group_id,
            'direction': self.direction,
            'active': self.active,
            'description': self.description,
            'eud_uid': self.eud_uid
        }

    def to_json(self):
        return {
            "name": self.group.group_name,
            "direction": self.direction,
            "created": iso8601_string_from_datetime(self.group.created).split("T")[0],
            "type": self.group.group_type,
            "bitpos": self.group.bitpos,
            "active": self.active,
            "description": self.description if self.description else ""
        }
