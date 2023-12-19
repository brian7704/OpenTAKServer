from dataclasses import dataclass

from extensions import db
from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class EUD(db.Model):
    __tablename__ = "eud"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    callsign: Mapped[str] = mapped_column(String, nullable=True)
    device: Mapped[str] = mapped_column(String, nullable=True)
    os: Mapped[str] = mapped_column(String, nullable=True)
    platform: Mapped[str] = mapped_column(String, nullable=True)
    version: Mapped[str] = mapped_column(String, nullable=True)
    phone_number: Mapped[int] = mapped_column(Integer, nullable=True)
    last_event_time: Mapped[str] = mapped_column(String, nullable=True)
    last_status: Mapped[str] = mapped_column(String, nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=True)
    points = relationship("Point", back_populates="eud")
    cots = relationship("CoT", back_populates="eud")
    casevacs = relationship("CasEvac", back_populates="eud")
    geochats = relationship("GeoChat", back_populates="eud")
    chatroom_uid = relationship("ChatroomsUids", back_populates="eud")
    user: Mapped["User"] = relationship(back_populates="euds")
    alert = relationship("Alert", back_populates="eud")
    # data_packages: Mapped[List["DataPackage"]] = relationship(back_populates="eud")

    def serialize(self):
        return {
            'eud': {
                'uid': self.uid,
                'callsign': self.callsign,
                'device': self.device,
                'os': self.os,
                'platform': self.platform,
                'version': self.version,
                'phone_number': self.phone_number,
                'last_event_time': self.last_event_time,
                'last_status': self.last_status,
                'username': self.user.username if self.user else None
            }
        }
