from datetime import datetime

from sqlalchemy import JSON, TEXT, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.extensions import db
from opentakserver.functions import iso8601_string_from_datetime


class CITrap(db.Model):
    __tablename__ = 'citrap'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(255), nullable=True)
    user_callsign: Mapped[str] = mapped_column(String(255), nullable=True)
    user_description: Mapped[str] = mapped_column(String(255), nullable=True)
    date_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    date_time_description: Mapped[str] = mapped_column(DateTime, nullable=True)
    location_description: Mapped[str] = mapped_column(String(255), nullable=True)
    event_scale: Mapped[str] = mapped_column(String(255), nullable=True)
    importance: Mapped[str] = mapped_column(String(255), nullable=True)
    uid: Mapped[str] = mapped_column(String, primary_key=True)
    location:
