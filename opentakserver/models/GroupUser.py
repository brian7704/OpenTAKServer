from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column


@dataclass
class GroupUser(db.Model):
    __tablename__ = "groups_users"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), primary_key=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("groups.id"), primary_key=True)
