from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, ForeignKey, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column


@dataclass
class GroupUser(db.Model):
    __tablename__ = "groups_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"))
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("groups.id"))
    direction: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[Boolean] = mapped_column(Boolean, default=True)
