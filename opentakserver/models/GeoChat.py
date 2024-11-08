from datetime import datetime

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship


class GeoChat(db.Model):
    __tablename__ = 'geochat'

    uid: Mapped[str] = mapped_column(String(255), primary_key=True)
    chatroom_id: Mapped[str] = mapped_column(String(255), ForeignKey("chatrooms.id"))
    sender_uid: Mapped[str] = mapped_column(String(255), ForeignKey("euds.uid", ondelete="CASCADE"))
    remarks: Mapped[str] = mapped_column(String(255))
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    point_id: Mapped[int] = mapped_column(Integer, ForeignKey("points.id"))
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id"))
    point = relationship("Point", cascade="all", back_populates="geochat", uselist=False)
    cot = relationship("CoT", cascade="all", back_populates="geochat")
    chatroom = relationship("Chatroom", back_populates="geochats")
    eud = relationship("EUD", back_populates="geochats")

    def serialize(self):
        return {
            'uid': self.uid,
            'sender_uid': self.sender_uid,
            'remarks': self.remarks,
            'timestamp': self.timestamp,
        }

    def to_json(self):
        return {
            'uid': self.uid,
            'sender_uid': self.sender_uid,
            'remarks': self.remarks,
            'timestamp': self.timestamp,
            'point': self.point.to_json() or None,
        }
