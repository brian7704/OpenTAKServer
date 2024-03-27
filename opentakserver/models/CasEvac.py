from datetime import datetime

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, Boolean, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.models.Icon import Icon


class CasEvac(db.Model):
    __tablename__ = 'casevac'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_uid: Mapped[str] = mapped_column(String, ForeignKey("euds.uid"))
    uid: Mapped[str] = mapped_column(String, unique=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)

    # The following are taken from CoT attributes generated from ATAK
    ambulatory: Mapped[int] = mapped_column(Integer, nullable=True)
    casevac: Mapped[bool] = mapped_column(Boolean, nullable=True)
    child: Mapped[int] = mapped_column(Integer, nullable=True)
    enemy: Mapped[str] = mapped_column(String, nullable=True)
    epw: Mapped[int] = mapped_column(Integer, nullable=True)
    equipment_detail: Mapped[str] = mapped_column(String, nullable=True)
    equipment_none: Mapped[bool] = mapped_column(Boolean, nullable=True)
    equipment_other: Mapped[bool] = mapped_column(Boolean, nullable=True)
    extraction_equipment: Mapped[bool] = mapped_column(Boolean, nullable=True)
    freq: Mapped[float] = mapped_column(Float, nullable=True)
    friendlies: Mapped[str] = mapped_column(String, nullable=True)
    hlz_marking: Mapped[int] = mapped_column(Integer, nullable=True)
    hlz_remarks: Mapped[str] = mapped_column(String, nullable=True)
    hoist: Mapped[bool] = mapped_column(Boolean, nullable=True)
    litter: Mapped[int] = mapped_column(Integer, nullable=True)
    marked_by: Mapped[str] = mapped_column(String, nullable=True)
    medline_remarks: Mapped[str] = mapped_column(String, nullable=True)
    nonus_civilian: Mapped[int] = mapped_column(Integer, nullable=True)
    nonus_military: Mapped[int] = mapped_column(Integer, nullable=True)
    obstacles: Mapped[str] = mapped_column(String, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=True)
    routine: Mapped[int] = mapped_column(Integer, nullable=True)
    security: Mapped[int] = mapped_column(Integer, nullable=True)
    terrain_loose: Mapped[bool] = mapped_column(Boolean, nullable=True)
    terrain_other: Mapped[bool] = mapped_column(Boolean, nullable=True)
    terrain_other_detail: Mapped[bool] = mapped_column(String, nullable=True)
    terrain_detail: Mapped[str] = mapped_column(String, nullable=True)
    terrain_none: Mapped[bool] = mapped_column(Boolean, nullable=True)
    terrain_rough: Mapped[bool] = mapped_column(Boolean, nullable=True)
    terrain_slope: Mapped[bool] = mapped_column(Boolean, nullable=True)
    terrain_slope_dir: Mapped[str] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String)
    urgent: Mapped[int] = mapped_column(Integer, nullable=True)
    us_civilian: Mapped[int] = mapped_column(Integer, nullable=True)
    us_military: Mapped[int] = mapped_column(Integer, nullable=True)
    ventilator: Mapped[bool] = mapped_column(Boolean, nullable=True)
    winds_are_from: Mapped[str] = mapped_column(String, nullable=True)
    zone_prot_selection: Mapped[int] = mapped_column(Integer, nullable=True)
    point_id: Mapped[int] = mapped_column(Integer, ForeignKey("points.id"), nullable=True)
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id"), nullable=True)
    point = relationship("Point", back_populates="casevac")
    cot = relationship("CoT", back_populates="casevac")
    zmist = relationship("ZMIST", back_populates="casevac", uselist=False)
    eud = relationship("EUD", back_populates="casevacs")

    def serialize(self):
        return {
            'sender_uid': self.sender_uid,
            'uid': self.uid,
            'timestamp': self.timestamp,
            'ambulatory': self.ambulatory,
            'casevac': self.casevac,
            'child': self.child,
            'enemy': self.enemy,
            'epw': self.epw,
            'equipment_detail': self.equipment_detail,
            'equipment_none': self.equipment_none,
            'equipment_other': self.equipment_other,
            'extraction_equipment': self.extraction_equipment,
            'freq': self.freq,
            'friendlies': self.friendlies,
            'hlz_marking': self.hlz_marking,
            'hlz_remarks': self.hlz_remarks,
            'hoist': self.hoist,
            'litter': self.litter,
            'marked_by': self.marked_by,
            'medline_remarks': self.medline_remarks,
            'nonus_civilian': self.nonus_civilian,
            'nonus_military': self.nonus_military,
            'obstacles': self.obstacles,
            'priority': self.priority,
            'routine': self.routine,
            'security': self.security,
            'terrain_loose': self.terrain_loose,
            'terrain_other': self.terrain_other,
            'terrain_other_detail': self.terrain_other_detail,
            'terrain_detail': self.terrain_detail,
            'terrain_none': self.terrain_none,
            'terrain_rough': self.terrain_rough,
            'terrain_slope': self.terrain_slope,
            'terrain_slope_dir': self.terrain_slope_dir,
            'title': self.title,
            'urgent': self.urgent,
            'us_civilian': self.us_civilian,
            'us_military': self.us_military,
            'ventilator': self.ventilator,
            'winds_are_from': self.winds_are_from,
            'zone_prot_selection': self.zone_prot_selection,
            'eud': self.eud,
        }

    def to_json(self):
        icon = db.session.execute(db.session.query(Icon).filter(Icon.filename == 'red_crs.png')).first()[0]
        return {
            'sender_uid': self.sender_uid,
            'uid': self.uid,
            'timestamp': iso8601_string_from_datetime(self.timestamp),
            'ambulatory': self.ambulatory,
            'casevac': self.casevac,
            'child': self.child,
            'enemy': self.enemy,
            'epw': self.epw,
            'equipment_detail': self.equipment_detail,
            'equipment_none': self.equipment_none,
            'equipment_other': self.equipment_other,
            'extraction_equipment': self.extraction_equipment,
            'freq': self.freq,
            'friendlies': self.friendlies,
            'hlz_marking': self.hlz_marking,
            'hlz_remarks': self.hlz_remarks,
            'hoist': self.hoist,
            'litter': self.litter,
            'marked_by': self.marked_by,
            'medline_remarks': self.medline_remarks,
            'nonus_civilian': self.nonus_civilian,
            'nonus_military': self.nonus_military,
            'obstacles': self.obstacles,
            'priority': self.priority,
            'routine': self.routine,
            'security': self.security,
            'terrain_loose': self.terrain_loose,
            'terrain_other': self.terrain_other,
            'terrain_other_detail': self.terrain_other_detail,
            'terrain_detail': self.terrain_detail,
            'terrain_none': self.terrain_none,
            'terrain_rough': self.terrain_rough,
            'terrain_slope': self.terrain_slope,
            'terrain_slope_dir': self.terrain_slope_dir,
            'title': self.title,
            'urgent': self.urgent,
            'us_civilian': self.us_civilian,
            'us_military': self.us_military,
            'ventilator': self.ventilator,
            'winds_are_from': self.winds_are_from,
            'zone_prot_selection': self.zone_prot_selection,
            'zmist': self.zmist.serialize() if self.zmist else None,
            'eud': self.eud,
            'point': self.point.to_json() if self.point else None,
            'icon': icon.to_json(),
            'start': iso8601_string_from_datetime(self.cot.start) if self.cot else None,
            'stale': iso8601_string_from_datetime(self.cot.stale) if self.cot else None,
        }
