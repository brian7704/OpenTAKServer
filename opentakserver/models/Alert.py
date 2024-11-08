from datetime import datetime

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.functions import iso8601_string_from_datetime


class Alert(db.Model):
    __tablename__ = 'alerts'

    # type = ^b-a- (b-a-o-tbl, b-a-o-can)
    # how = ^m-g | ^h-e

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(255))
    sender_uid: Mapped[str] = mapped_column(String(255), ForeignKey("euds.uid", ondelete="CASCADE"))
    start_time: Mapped[datetime] = mapped_column(DateTime)
    cancel_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    alert_type: Mapped[str] = mapped_column(String(255))
    point_id: Mapped[int] = mapped_column(Integer, ForeignKey("points.id", ondelete="CASCADE"), nullable=True)
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id", ondelete="CASCADE"), nullable=True)
    cot = relationship("CoT", back_populates="alert")
    point = relationship("Point", back_populates="alert", foreign_keys=[point_id])
    eud = relationship("EUD", back_populates="alert")

    def serialize(self):
        return {
            'uid': self.uid,
            'sender_uid': self.sender_uid,
            'start_time': self.start_time,
            'cancel_time': self.cancel_time,
            'alert_type': self.alert_type,
            'point_id': self.point_id,
            'cot_id': self.cot_id
        }

    def to_json(self):
        return {
            'uid': self.uid,
            'sender_uid': self.sender_uid,
            'start_time': iso8601_string_from_datetime(self.start_time),
            'cancel_time': iso8601_string_from_datetime(self.cancel_time) if self.cancel_time else None,
            'alert_type': self.alert_type,
            'point': self.point.to_json() if self.point else None,
            'callsign': self.eud.callsign if self.eud else None,
        }
