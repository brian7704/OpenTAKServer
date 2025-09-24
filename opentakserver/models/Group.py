import datetime
import enum
from dataclasses import dataclass

from opentakserver.extensions import db
from opentakserver.functions import iso8601_string_from_datetime
from sqlalchemy import Integer, String, Boolean, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship


class GroupTypeEnum(enum.Enum):
    SYSTEM = "SYSTEM"
    LDAP = "LDAP"


class GroupDirectionEnum(enum.Enum):
    IN = "IN"
    OUT = "OUT"


@dataclass
class Group(db.Model):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    distinguishedName: Mapped[str] = mapped_column(String(255), nullable=True)
    direction: Mapped[str] = mapped_column(Enum(GroupDirectionEnum))
    created: Mapped[datetime] = mapped_column(DateTime, default=datetime.datetime.now(datetime.timezone.utc))
    type: Mapped[str] = mapped_column(Enum(GroupTypeEnum), default=GroupTypeEnum.SYSTEM)
    bitpos: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    users = relationship("User", secondary="groups_users", back_populates="groups")

    def serialize(self):
        return {
            'name': self.name,
            'distinguishedName': self.distinguishedName,
            'direction': self.direction,
            'created': self.created,
            'type': self.type,
            'bitpos': self.bitpos,
            'description': self.description,
            'active': self.active
        }

    def to_json(self):
        return_value = self.serialize()
        return_value['bitpos'] = "{0:b}".format(self.bitpos)
        return return_value
