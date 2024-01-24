from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Point(db.Model):
    __tablename__ = "points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String)
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

    # Only populate this field of the CoT type matches ^a- and how matches either ^m-g or ^h-e
    eud = relationship("EUD", back_populates="points")
    casevac = relationship("CasEvac", back_populates="point")
    geochat = relationship("GeoChat", back_populates="point")
    alert = relationship("Alert", back_populates="point")
    marker: Mapped["Marker"] = relationship(back_populates="point")
    rb_line = relationship("RBLine", back_populates="point")

    def serialize(self):
        return {
            'uid': self.uid,
            'device_uid': self.device_uid,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'ce': self.ce,
            'hae': self.hae,
            'le': self.le,
            'course': self.course,
            'speed': self.speed,
            'location_source': self.location_source,
            'battery': self.battery,
            'timestamp': self.timestamp,
            'how': self.cot.how,
            'type': self.cot.type,
            'callsign': self.eud.callsign if self.eud else None
        }
