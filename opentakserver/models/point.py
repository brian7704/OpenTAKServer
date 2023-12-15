from extensions import db
from sqlalchemy import Integer, String, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Point(db.Model):
    __tablename__ = "points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_uid: Mapped[str] = mapped_column(String, ForeignKey("eud.uid"))
    latitude: Mapped[float] = mapped_column(Float, nullable=True)
    longitude: Mapped[float] = mapped_column(Float, nullable=True)
    ce: Mapped[float] = mapped_column(Float, nullable=True)
    hae: Mapped[float] = mapped_column(Float, nullable=True)
    le: Mapped[float] = mapped_column(Float, nullable=True)
    course: Mapped[float] = mapped_column(Float, nullable=True)
    speed: Mapped[float] = mapped_column(Float, nullable=True)
    location_source: Mapped[str] = mapped_column(String, nullable=True)
    battery: Mapped[float] = mapped_column(Float, nullable=True)
    timestamp: Mapped[str] = mapped_column(String)
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id"), nullable=True)
    cot = relationship("CoT", back_populates="point")
    eud = relationship("EUD", back_populates="points")
    casevac = relationship("CasEvac", back_populates="point")
    geochat = relationship("GeoChat", back_populates="point")

    def serialize(self):
        return {
            'point': {
                'latitude': self.latitude,
                'longitude': self.longitude,
                'ce': self.ce,
                'hae': self.hae,
                'le': self.le,
                'course': self.course,
                'speed': self.speed,
                'location_source': self.location_source,
                'battery': self.battery,
                'timestamp': self.timestamp
            }
        }
