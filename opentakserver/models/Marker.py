from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class Marker(db.Model):
    __tablename__ = "markers"

    # type = a-[a-z]-[A-Z]
    # how = h-g-i-g-o

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String, unique=True)
    affiliation: Mapped[str] = mapped_column(String)
    battle_dimension: Mapped[str] = mapped_column(String)
    point_id: Mapped[int] = mapped_column(Integer, ForeignKey("points.id"))
    callsign: Mapped[str] = mapped_column(String, nullable=True)
    readiness: Mapped[bool] = mapped_column(Boolean, nullable=True)
    argb: Mapped[int] = mapped_column(Integer, nullable=True)
    iconset_path: Mapped[str] = mapped_column(String, nullable=True)
    parent_callsign: Mapped[str] = mapped_column(String, nullable=True)
    production_time: Mapped[str] = mapped_column(String, nullable=True)
    relation: Mapped[str] = mapped_column(String, nullable=True)
    relation_type: Mapped[str] = mapped_column(String, nullable=True)
    location_source: Mapped[str] = mapped_column(String, nullable=True)

    # Will either be the uid attribute in the <Link> tag or
    # if there's no <Link> tag it's assumed that the sender is the parent
    parent_uid: Mapped[str] = mapped_column(String, ForeignKey("eud.uid"), nullable=True)
    remarks: Mapped[str] = mapped_column(String, nullable=True)
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id"), nullable=True)
    point = relationship("Point", back_populates="marker")
    cot = relationship("CoT", back_populates="marker")
    eud = relationship("EUD", back_populates="markers")

    def serialize(self):
        return {
            'uid': self.uid,
            'affiliation': self.affiliation,
            'battle_dimension': self.battle_dimension,
            'callsign': self.callsign,
            'readiness': self.readiness,
            'argb': self.argb,
            'iconset_path': self.iconset_path,
            'parent_callsign': self.parent_callsign,
            'relation': self.relation,
            'relation_type': self.relation_type,
            'production_time': self.production_time,
            'location_source': self.location_source
        }
