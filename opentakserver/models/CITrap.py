from datetime import datetime

from sqlalchemy import JSON, TEXT, DateTime, ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.extensions import db
from opentakserver.functions import iso8601_string_from_datetime


class CITrap(db.Model):
    __tablename__ = 'citrap'

    id: Mapped[str] = mapped_column(String(255), primary_key=True) # UUID from the XML's id attribute
    type: Mapped[str] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=True)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=True)
    delimiter: Mapped[str] = mapped_column(String(255), nullable=True)
    user_callsign: Mapped[str] = mapped_column(String(255), nullable=True)
    user_description: Mapped[str] = mapped_column(String(255), nullable=True)
    date_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    date_time_description: Mapped[str] = mapped_column(DateTime, nullable=True)
    location_description: Mapped[str] = mapped_column(String(255), nullable=True)
    event_scale: Mapped[str] = mapped_column(String(255), nullable=True)
    importance: Mapped[str] = mapped_column(String(255), nullable=True)
    tags: Mapped[str] = mapped_column(String(255), primary_key=True)
    scale_description: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[str] = mapped_column(String(255), primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    hash: Mapped[str] = mapped_column(String(255), primary_key=True)
