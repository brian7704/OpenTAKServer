from dataclasses import dataclass
from datetime import datetime

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.functions import iso8601_string_from_datetime


@dataclass
class Marker(db.Model):
    __tablename__ = "markers"

    # type = a-[a-z]-[A-Z]
    # how = h-g-i-g-o

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(255), unique=True)
    affiliation: Mapped[str] = mapped_column(String(255), nullable=True)
    battle_dimension: Mapped[str] = mapped_column(String(255), nullable=True)
    point_id: Mapped[int] = mapped_column(Integer, ForeignKey("points.id", ondelete="CASCADE"))
    callsign: Mapped[str] = mapped_column(String(255), nullable=True)
    readiness: Mapped[bool] = mapped_column(Boolean, nullable=True)
    argb: Mapped[int] = mapped_column(Integer, nullable=True)
    color_hex: Mapped[str] = mapped_column(String(255), nullable=True)
    iconset_path: Mapped[str] = mapped_column(String(255), nullable=True)
    parent_callsign: Mapped[str] = mapped_column(String(255), nullable=True)
    production_time: Mapped[str] = mapped_column(String(255), nullable=True)
    relation: Mapped[str] = mapped_column(String(255), nullable=True)
    relation_type: Mapped[str] = mapped_column(String(255), nullable=True)
    location_source: Mapped[str] = mapped_column(String(255), nullable=True)
    icon_id: Mapped[int] = mapped_column(Integer, ForeignKey("icons.id"), nullable=True)

    # Will either be the uid attribute in the <Link> tag or
    # if there's no <Link> tag it's assumed that the sender is the parent
    parent_uid: Mapped[str] = mapped_column(String(255), ForeignKey("euds.uid", ondelete="CASCADE"), nullable=True)
    remarks: Mapped[str] = mapped_column(String(255), nullable=True)
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id", ondelete="CASCADE"), nullable=True)
    mil_std_2525c: Mapped[str] = mapped_column(String(255), nullable=True)
    point = relationship("Point", cascade="all, delete", back_populates="marker")
    cot = relationship("CoT", back_populates="marker")
    eud = relationship("EUD", back_populates="markers")
    icon = relationship("Icon", back_populates="markers")

    def color_to_hex(self):
        if self.argb:
            return format(int(self.argb) & 0xFFFFFFFF, '08X')

    def serialize(self):
        return {
            'uid': self.uid,
            'affiliation': self.affiliation,
            'battle_dimension': self.battle_dimension,
            'callsign': self.callsign,
            'readiness': self.readiness,
            'argb': self.argb,
            'color_hex': self.color_hex,
            'iconset_path': self.iconset_path,
            'parent_callsign': self.parent_callsign,
            'relation': self.relation,
            'relation_type': self.relation_type,
            'production_time': self.production_time,
            'location_source': self.location_source,
            'mil_std_2525c': self.mil_std_2525c,
        }

    def to_json(self):
        return {
            'uid': self.uid,
            'affiliation': self.affiliation,
            'battle_dimension': self.battle_dimension,
            'callsign': self.callsign,
            'readiness': self.readiness,
            'argb': self.argb,
            'color_hex': self.color_hex,
            'iconset_path': self.iconset_path,
            'parent_callsign': self.parent_callsign,
            'relation': self.relation,
            'relation_type': self.relation_type,
            'production_time': self.production_time,
            'location_source': self.location_source,
            'icon': self.icon.to_json() if self.icon else None,
            'point': self.point.to_json() if self.point else None,
            'mil_std_2525c': self.mil_std_2525c,
            'type': self.cot.type if self.cot else None,
            'how': self.cot.how if self.cot else None,
            'start': iso8601_string_from_datetime(self.cot.start) if self.cot else None,
            'stale': iso8601_string_from_datetime(self.cot.stale) if self.cot else None,
        }
