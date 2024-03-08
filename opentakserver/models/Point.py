from datetime import datetime

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.functions import iso8601_string_from_datetime


class Point(db.Model):
    __tablename__ = "points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String)
    device_uid: Mapped[str] = mapped_column(String, ForeignKey("euds.uid"))
    latitude: Mapped[float] = mapped_column(Float, nullable=True)
    longitude: Mapped[float] = mapped_column(Float, nullable=True)
    ce: Mapped[float] = mapped_column(Float, nullable=True)
    hae: Mapped[float] = mapped_column(Float, nullable=True)
    le: Mapped[float] = mapped_column(Float, nullable=True)
    course: Mapped[float] = mapped_column(Float, nullable=True)
    speed: Mapped[float] = mapped_column(Float, nullable=True)
    location_source: Mapped[str] = mapped_column(String, nullable=True)
    battery: Mapped[float] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    azimuth: Mapped[float] = mapped_column(Float, nullable=True)
    # Camera field of view from TAK ICU and OpenTAK ICU
    fov: Mapped[float] = mapped_column(Float, nullable=True)
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
            'azimuth': self.azimuth,
            'fov': self.fov,
            'location_source': self.location_source,
            'battery': self.battery,
            'timestamp': self.timestamp,
        }

    def to_json(self):
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
            'azimuth': self.azimuth,
            'fov': self.fov,
            'location_source': self.location_source,
            'battery': self.battery,
            'timestamp': iso8601_string_from_datetime(self.timestamp),
            'how': self.cot.how,
            'type': self.cot.type,
            'callsign': self.eud.callsign if self.eud else None
        }
