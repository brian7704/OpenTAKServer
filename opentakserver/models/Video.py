from extensions import db
from sqlalchemy import Integer, String, ForeignKey, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Video(db.Model):
    __tablename__ = 'video'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    network_timeout: Mapped[int] = mapped_column(Integer, nullable=True)
    uid: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    protocol: Mapped[str] = mapped_column(String, nullable=False, unique=False)
    path: Mapped[str] = mapped_column(String, nullable=True)
    buffer_time: Mapped[int] = mapped_column(Integer, nullable=True)
    address: Mapped[str] = mapped_column(String, nullable=True)
    port: Mapped[int] = mapped_column(Integer, nullable=True)
    rover_port: Mapped[int] = mapped_column(Integer, nullable=True)
    rtsp_reliable: Mapped[int] = mapped_column(Integer, nullable=True)
    ignore_embedded_klv: Mapped[bool] = mapped_column(Boolean, nullable=True)
    alias: Mapped[str] = mapped_column(String, nullable=True)
    preferred_mac_address: Mapped[str] = mapped_column(String, nullable=True)
    preferred_interface_address: Mapped[str] = mapped_column(String, nullable=True)
    xml: Mapped[str] = mapped_column(String, nullable=True)
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id"), nullable=True)
    cot = relationship("CoT", back_populates="video")

    def serialize(self):
        return {
            'video': {
                'network_timeout': self.network_timeout,
                'uid': self.uid,
                'protocol': self.protocol,
                'path': self.path,
                'buffer_time': self.buffer_time,
                'address': self.address,
                'port': self.port,
                'rover_port': self.rover_port,
                'rtsp_reliable': self.rtsp_reliable,
                'ignore_embedded_klv': self.ignore_embedded_klv,
                'alias': self.alias,
                'preferred_mac_address': self.preferred_mac_address,
                'preferred_interface_address': self.preferred_interface_address,
                'xml': self.xml
            }
        }

