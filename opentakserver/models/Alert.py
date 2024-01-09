from extensions import db
from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Alert(db.Model):
    __tablename__ = 'alerts'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String)
    sender_uid: Mapped[str] = mapped_column(String, ForeignKey("eud.uid"))
    start_time: Mapped[str] = mapped_column(String)
    cancel_time: Mapped[str] = mapped_column(String, nullable=True)
    alert_type: Mapped[str] = mapped_column(String)
    point_id: Mapped[int] = mapped_column(Integer, ForeignKey("points.id"), nullable=True)
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id"), nullable=True)
    cot = relationship("CoT", back_populates="alert")
    point = relationship("Point", back_populates="alert")
    eud = relationship("EUD", back_populates="alert")

    def serialize(self):
        return {
            'uid': self.uid,
            'sender_uid': self.sender_uid,
            'start_time': self.start_time,
            'cancel_time': self.cancel_time,
            'alert_type': self.alert_type,
            'eud': self.eud.serialize() if self.eud else None,
        }
