import datetime
from dataclasses import dataclass

from opentakserver.extensions import db
from opentakserver.functions import iso8601_string_from_datetime
from sqlalchemy import Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class Group(db.Model):
    __tablename__ = "groups"

    SYSTEM = "SYSTEM"
    LDAP = "LDAP"
    IN = "IN"
    OUT = "OUT"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_name: Mapped[str] = mapped_column(String(255))
    direction: Mapped[str] = mapped_column(String(255))  # IN, OUT
    created: Mapped[datetime] = mapped_column(DateTime)
    group_type: Mapped[str] = mapped_column(String(255), default=SYSTEM)  # SYSTEM, LDAP
    bitpos: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean)
    description: Mapped[str] = mapped_column(String(255), nullable=True)
    eud_uid: Mapped[str] = mapped_column(String(255), ForeignKey("euds.uid"))
    eud = relationship("EUD", back_populates="groups")

    def serialize(self):
        return {
            'group_name': self.group_name,
            'direction': self.direction,
            'created': self.created,
            'group_type': self.group_type,
            'bitpos': self.bitpos,
            'active': self.active,
            'description': self.description
        }

    def to_json(self):
        return {
            "name": self.group_name,
            "direction": self.direction,
            "created": iso8601_string_from_datetime(self.created).split("T")[0],
            "type": self.group_type,
            "bitpos": self.bitpos,
            "active": self.active,
            "description": self.description if self.description else ""
        }
