from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class RBLine(db.Model):
    __tablename__ = "rb_lines"

    # type = u-rb-a
    # how = h-e

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_uid: Mapped[str] = mapped_column(String, ForeignKey("eud.uid"))
    uid: Mapped[str] = mapped_column(String, unique=True)
    timestamp: Mapped[str] = mapped_column(String)

    range: Mapped[float] = mapped_column(Float)
    bearing: Mapped[float] = mapped_column(Float)
    inclination: Mapped[float] = mapped_column(Float, nullable=True)
    anchor_uid: Mapped[str] = mapped_column(String, nullable=True)
    range_units: Mapped[int] = mapped_column(Integer, nullable=True)
    bearing_units: Mapped[int] = mapped_column(Integer, nullable=True)
    north_ref: Mapped[int] = mapped_column(Integer, nullable=True)
    color: Mapped[int] = mapped_column(Integer, nullable=True)
    callsign: Mapped[str] = mapped_column(String, nullable=True)
    stroke_color: Mapped[int] = mapped_column(Integer, nullable=True)
    stroke_weight: Mapped[float] = mapped_column(Float, nullable=True)
    stroke_style: Mapped[str] = mapped_column(String, nullable=True)
    labels_on: Mapped[bool] = mapped_column(Boolean, nullable=True)
    point_id: Mapped[int] = mapped_column(Integer, ForeignKey("points.id"), nullable=True)
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id"), nullable=True)
    point = relationship("Point", back_populates="rb_line")
    cot = relationship("CoT", back_populates="rb_line")
    eud = relationship("EUD", back_populates="rb_lines")

    range_unit_names = ['standard', 'metric', 'nautical']
    bearing_unit_names = ['degrees', 'mils']
    north_ref_names = ['true', 'magnetic', 'grid']

    def serialize(self):
        return {
            'uid': self.uid,
            'timestamp': self.timestamp,
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
            'stroke_weight': self.stroke_weight,
            'stroke_style': self.stroke_style,
            'labels_on': self.labels_on,
            'point': self.point.serialize() if self.point else None
        }
