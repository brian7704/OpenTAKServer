from extensions import db
from sqlalchemy import Integer, String, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


class CoT(db.Model):
    __tablename__ = "cot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    how: Mapped[str] = mapped_column(String, nullable=True)
    type: Mapped[str] = mapped_column(String, nullable=True)
    sender_callsign: Mapped[str] = mapped_column(String)
    sender_device_name: Mapped[str] = mapped_column(String, nullable=True)
    sender_uid: Mapped[str] = mapped_column(String, ForeignKey("eud.uid"), nullable=True)
    recipients: Mapped[JSON] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[str] = mapped_column(String)
    xml: Mapped[str] = mapped_column(String)
    eud = relationship("EUD", back_populates="cots")
    alert = relationship("Alert", back_populates="cot")
    point = relationship("Point", back_populates="cot")
    casevac = relationship("CasEvac", back_populates="cot")
    video = relationship("Video", back_populates="cot")
    geochat = relationship("GeoChat", back_populates="cot")

    def serialize(self):
        return {
            'cot':{
                'how': self.how,
                'type': self.type,
                'sender_callsign': self.sender_callsign,
                'sender_uid': self.sender_uid,
                'recipients': self.recipients,
                'timestamp': self.timestamp,
                'xml': self.xml
            }
        }
