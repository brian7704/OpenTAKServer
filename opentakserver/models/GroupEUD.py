from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, ForeignKey, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column


@dataclass
class GroupEUD(db.Model):
    __tablename__ = "groups_euds"

    group_name: Mapped[String] = mapped_column(Integer, ForeignKey("groups.name"), primary_key=True)
    eud_uid: Mapped[String] = mapped_column(Integer, ForeignKey("eud.uid"), primary_key=True)
    direction: Mapped[str] = mapped_column(String(255), primary_key=True)
    enabled: Mapped[Boolean] = mapped_column(Boolean, default=True)
