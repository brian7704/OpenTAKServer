from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from geoalchemy2.shape import to_shape

from opentakserver.extensions import db
from opentakserver.functions import iso8601_string_from_datetime


class CITrap(db.Model):
    __tablename__ = "citrap"

    id: Mapped[str] = mapped_column(
        String(255), primary_key=True
    )  # UUID from the XML's id attribute
    type: Mapped[str] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=True)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=True)
    delimiter: Mapped[str] = mapped_column(String(255), nullable=True)
    user_callsign: Mapped[str] = mapped_column(String(255), nullable=True)
    user_description: Mapped[str] = mapped_column(String(255), nullable=True)
    date_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    date_time_description: Mapped[str] = mapped_column(String(255), nullable=True)
    point_id: Mapped[int] = mapped_column(Integer, ForeignKey("points.id", ondelete="CASCADE"))
    location_description: Mapped[str] = mapped_column(String(255), nullable=True)
    event_scale: Mapped[str] = mapped_column(String(255), nullable=True)
    importance: Mapped[str] = mapped_column(String(255), nullable=True)
    tags: Mapped[str] = mapped_column(String(255), nullable=True)
    scale_description: Mapped[str] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(255), nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=True)
    hash: Mapped[str] = mapped_column(String(255), nullable=True, unique=True)
    point = relationship("Point", cascade="all, delete", back_populates="citrap")

    def serialize(self):
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "visible": self.visible,
            "delimiter": self.delimiter,
            "user_callsign": self.user_callsign,
            "user_description": self.user_description,
            "date_time": self.date_time,
            "date_time_description": self.date_time_description,
            "location_description": self.location_description,
            "event_scale": self.event_scale,
            "importance": self.importance,
            "tags": self.tags,
            "scale_description": self.scale_description,
            "status": self.status,
            "file_name": self.file_name,
            "hash": self.hash,
        }

    def to_json(self):
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "visible": self.visible,
            "delimiter": self.delimiter,
            "user_callsign": self.user_callsign,
            "user_description": self.user_description,
            "date_time": iso8601_string_from_datetime(self.date_time) if self.date_time else None,
            "date_time_description": self.date_time_description,
            "location_description": self.location_description,
            "event_scale": self.event_scale,
            "importance": self.importance,
            "tags": self.tags,
            "scale_description": self.scale_description,
            "status": self.status,
            "file_name": self.file_name,
            "hash": self.hash,
            "point": self.point.to_json() if self.point else None,
        }

    def to_marti_json(self):
        return {
            "dateTime": iso8601_string_from_datetime(self.date_time),
            "userDescription": self.user_description,
            "importance": self.importance,
            "locationDescription": self.location_description,
            "userCallsign": self.user_callsign,
            "location": to_shape(self.point.point).wkt,
            "id": self.id,
            "eventScale": self.event_scale,
            "type": self.type,
            "title": self.title,
            "dateTimeDescription": self.date_time_description,
            "status": self.status,
        }
