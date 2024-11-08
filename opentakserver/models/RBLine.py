import math
from dataclasses import dataclass
from datetime import datetime

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, Float, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pygc import great_circle

from opentakserver.functions import iso8601_string_from_datetime


@dataclass
class RBLine(db.Model):
    __tablename__ = "rb_lines"

    # type = u-rb-a
    # how = h-e

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_uid: Mapped[str] = mapped_column(String(255), ForeignKey("euds.uid", ondelete="CASCADE"))
    uid: Mapped[str] = mapped_column(String(255), unique=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)

    range: Mapped[float] = mapped_column(Float)
    bearing: Mapped[float] = mapped_column(Float)
    inclination: Mapped[float] = mapped_column(Float, nullable=True)
    anchor_uid: Mapped[str] = mapped_column(String(255), nullable=True)
    range_units: Mapped[int] = mapped_column(Integer, nullable=True)
    bearing_units: Mapped[int] = mapped_column(Integer, nullable=True)
    north_ref: Mapped[int] = mapped_column(Integer, nullable=True)
    color: Mapped[int] = mapped_column(Integer, nullable=True)
    color_hex: Mapped[str] = mapped_column(String(255), nullable=True)
    callsign: Mapped[str] = mapped_column(String(255), nullable=True)
    stroke_color: Mapped[int] = mapped_column(Integer, nullable=True)
    stroke_weight: Mapped[float] = mapped_column(Float, nullable=True)
    stroke_style: Mapped[str] = mapped_column(String(255), nullable=True)
    labels_on: Mapped[bool] = mapped_column(Boolean, nullable=True)
    point_id: Mapped[int] = mapped_column(Integer, ForeignKey("points.id", ondelete="CASCADE"), nullable=True)
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id", ondelete="CASCADE"), nullable=True)
    end_latitude: Mapped[float] = mapped_column(Float, nullable=True)
    end_longitude: Mapped[float] = mapped_column(Float, nullable=True)
    point = relationship("Point", back_populates="rb_line")
    cot = relationship("CoT", back_populates="rb_line")
    eud = relationship("EUD", back_populates="rb_lines")

    range_unit_names = ['standard', 'metric', 'nautical']
    bearing_unit_names = ['degrees', 'mils']
    north_ref_names = ['true', 'magnetic', 'grid']

    def color_to_hex(self):
        if self.color:
            return format(int(self.color) & 0xFFFFFFFF, '08X')

    def calc_end_point(self, start_point):
        if not int(self.bearing_units):
            azimuth = float(self.bearing)
        else:
            azimuth = math.degrees(float(self.bearing))

        return great_circle(distance=float(self.range), azimuth=azimuth, latitude=start_point.latitude,
                            longitude=start_point.longitude)

    def serialize(self):
        return {
            'uid': self.uid,
            'timestamp': self.timestamp,
            'range': self.range,
            'inclination': self.inclination,
            'anchor_uid': self.anchor_uid,
            'range_units': self.range_units,
            'bearing_units': self.bearing_units,
            'north_ref': self.north_ref,
            'color': self.color,
            'color_hex': self.color_hex,
            'stroke_weight': self.stroke_weight,
            'stroke_style': self.stroke_style,
            'labels_on': self.labels_on,
            'end_latitude': self.end_latitude,
            'end_longitude': self.end_longitude
        }

    def to_json(self):
        return {
            'uid': self.uid,
            'timestamp': iso8601_string_from_datetime(self.timestamp),
            'range': self.range,
            'inclination': self.inclination,
            'anchor_uid': self.anchor_uid,
            'range_units': self.range_units,
            'range_unit_name': self.range_unit_names[int(self.range_units)] if self.range_units else None,
            'bearing_units': self.bearing_units,
            'bearing_unit_name': self.bearing_unit_names[int(self.bearing_units)] if self.bearing else None,
            'north_ref': self.north_ref,
            'north_ref_name': self.north_ref_names[int(self.north_ref)] if self.north_ref else None,
            'color': self.color,
            'color_hex': self.color_hex,
            'stroke_weight': self.stroke_weight,
            'stroke_style': self.stroke_style,
            'labels_on': self.labels_on,
            'point': self.point.to_json() if self.point else None,
            'end_latitude': self.end_latitude,
            'end_longitude': self.end_longitude
        }
