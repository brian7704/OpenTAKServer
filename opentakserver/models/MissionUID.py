import datetime
from dataclasses import dataclass

from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.extensions import db
from sqlalchemy import String, DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class MissionUID(db.Model):
    __tablename__ = "mission_uids"

    uid: Mapped[str] = mapped_column(String(255), primary_key=True)  # Equals the original CoT's UID
    mission_name: Mapped[str] = mapped_column(String(255), ForeignKey("missions.name"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    creator_uid: Mapped[str] = mapped_column(String(255), nullable=True)
    cot_type: Mapped[str] = mapped_column(String(255), nullable=True)
    callsign: Mapped[str] = mapped_column(String(255), nullable=True)
    iconset_path: Mapped[str] = mapped_column(String(255), nullable=True)
    color: Mapped[str] = mapped_column(String(255), nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=True)
    longitude: Mapped[float] = mapped_column(Float, nullable=True)
    mission = relationship("Mission", back_populates="uids")
    mission_change = relationship("MissionChange", back_populates="uid", uselist=False)

    def serialize(self):
        return {
            'timestamp': self.timestamp,
            'creator_uid': self.creator_uid,
            'cot_type': self.cot_type,
            'callsign': self.callsign,
            'iconset_path': self.iconset_path,
            'color': self.color,
            'latitude': self.latitude,
            'longitude': self.longitude
        }

    def to_json(self):
        return {
            'data': self.uid,
            'timestamp': iso8601_string_from_datetime(self.timestamp),
            'creatorUid': self.creator_uid if self.creator_uid else "",
            'details': {
                'type': self.cot_type,
                'callsign': self.callsign,
                'iconsetPath': self.iconset_path,
                'color': self.color,
                'location': {
                    'lat': self.latitude,
                    'lon': self.longitude
                }
            }
        }

    def to_details_json(self):
        return {
            'type': self.cot_type,
            'callsign': self.callsign,
            'iconsetPath': self.iconset_path,
            'color': self.color,
            'location': {
                'lat': self.latitude,
                'lon': self.longitude
            }
        }
