from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, ForeignKey, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class GroupUser(db.Model):
    __tablename__ = "groups_users"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), primary_key=True)
    group_id: Mapped[Integer] = mapped_column(Integer, ForeignKey("groups.id"), primary_key=True)
    direction: Mapped[String] = mapped_column(String(255), primary_key=True)
    enabled: Mapped[Boolean] = mapped_column(Boolean, default=True)
    user = relationship("User", cascade="all, delete", viewonly=True)
    group = relationship("Group", cascade="all, delete", viewonly=True)

    def serialize(self):
        return {
            "user": self.user.serialize(),
            "group": self.group.serialize(),
            "direction": self.direction,
            "active": self.enabled
        }

    def to_marti_json(self):
        return {
            "name": self.group.name,
            "direction": self.direction,
            "created": int(self.group.created.timestamp()),
            "type": self.group.type,
            "bitpos": self.group.bitpos,
            "active": self.enabled
        }

    def to_json(self):
        return {
            "username": self.user.username,
            "group_name": self.group.name,
            "direction": self.direction,
            "active": self.enabled
        }
