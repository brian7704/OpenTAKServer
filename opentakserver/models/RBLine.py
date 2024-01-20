from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class RBLine(db.Model):
    __table_name__ = "rb_lines"

    # type = u-rb-a
    # how = h-e

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_uid: Mapped[str] = mapped_column(String, ForeignKey("eud.uid"))
    uid: Mapped[str] = mapped_column(String, unique=True)
    timestamp: Mapped[str] = mapped_column(String)

    range: Mapped[float] = mapped_column(Float)
    bearing: Mapped[float] = mapped_column(Float)
    inclination: Mapped[float] = mapped_column(Float, nullable=True)
    anchorUID: Mapped[str] = mapped_column(String, nullable=True)
    range_units: mapped_column[int] = mapped_column(Integer, nullable=True)
    bearing_units: mapped_column[int] = mapped_column(Integer, nullable=True)
    north_ref: mapped_column[int] = mapped_column(Integer, nullable=True)
    color_value: mapped_column[int] = mapped_column(Integer, nullable=True)
    stroke_color: mapped_column[int] = mapped_column(Integer, nullable=True)
    stroke_weight: mapped_column[float] = mapped_column(Float, nullable=True)
    stroke_style: mapped_column[str] = mapped_column(String, nullable=True)
    labels_on: mapped_column[bool] = mapped_column(Boolean, nullable=True)
    point_id: Mapped[int] = mapped_column(Integer, ForeignKey("points.id"), nullable=True)
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id"), nullable=True)
    point = relationship("Point", back_populates="rb_line")
    cot = relationship("CoT", back_populates="rb_line")
    eud = relationship("EUD", back_populates="rb_lines")
