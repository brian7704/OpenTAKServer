from datetime import datetime

from opentakserver.extensions import db
from sqlalchemy import Integer, String, JSON, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.functions import iso8601_string_from_datetime


class CoT(db.Model):
    __tablename__ = "cot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    how: Mapped[str] = mapped_column(String, nullable=True)
    type: Mapped[str] = mapped_column(String, nullable=True)
    sender_callsign: Mapped[str] = mapped_column(String)
    sender_device_name: Mapped[str] = mapped_column(String, nullable=True)
    sender_uid: Mapped[str] = mapped_column(String, ForeignKey("euds.uid"), nullable=True)
    recipients: Mapped[JSON] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    start: Mapped[datetime] = mapped_column(DateTime)
    stale: Mapped[datetime] = mapped_column(DateTime)
    xml: Mapped[str] = mapped_column(String)
    eud = relationship("EUD", back_populates="cots", uselist=False)
    alert = relationship("Alert", back_populates="cot", uselist=False)
    point = relationship("Point", back_populates="cot", uselist=False)
    casevac = relationship("CasEvac", back_populates="cot", uselist=False)
    video = relationship("VideoStream", back_populates="cot", uselist=False)
    geochat = relationship("GeoChat", back_populates="cot", uselist=False)
    marker = relationship("Marker", back_populates="cot", uselist=False)
    rb_line = relationship("RBLine", back_populates="cot")

    def serialize(self):
        return {
            'how': self.how,
            'type': self.type,
            'sender_callsign': self.sender_callsign,
            'sender_uid': self.sender_uid,
            'recipients': self.recipients,
            'timestamp': self.timestamp,
            'start': self.start,
            'stale': self.stale,
            'xml': self.xml,
        }

    def to_json(self):
        return {
            'how': self.how,
            'type': self.type,
            'sender_callsign': self.sender_callsign,
            'sender_uid': self.sender_uid,
            'recipients': self.recipients,
            'timestamp': self.timestamp,
            'start': iso8601_string_from_datetime(self.start),
            'stale': iso8601_string_from_datetime(self.stale),
            'xml': self.xml,
            'eud': self.eud.to_json() if self.eud else None,
            'alert': self.alert.to_json() if self.alert else None,
            'point': self.point.to_json() if self.point else None,
            'casevac': self.casevac.to_json() if self.casevac else None,
            'video': self.video.to_json() if self.video else None,
            'geochat': self.geochat.to_json() if self.geochat else None,
        }
