from datetime import datetime, timedelta

import xml.etree.ElementTree as ET
from flask_security import current_user

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, Boolean, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.forms.casevac_form import CasEvacForm
from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.models.Icon import Icon


class CasEvac(db.Model):
    __tablename__ = 'casevac'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_uid: Mapped[str] = mapped_column(String(255), ForeignKey("euds.uid", ondelete="CASCADE"))
    uid: Mapped[str] = mapped_column(String(255), unique=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)

    # The following are taken from CoT attributes generated from ATAK
    ambulatory: Mapped[int] = mapped_column(Integer, nullable=True)
    casevac: Mapped[bool] = mapped_column(Boolean, nullable=True)
    child: Mapped[int] = mapped_column(Integer, nullable=True)
    enemy: Mapped[str] = mapped_column(String(255), nullable=True)
    epw: Mapped[int] = mapped_column(Integer, nullable=True)
    equipment_detail: Mapped[str] = mapped_column(String(255), nullable=True)
    equipment_none: Mapped[bool] = mapped_column(Boolean, nullable=True)
    equipment_other: Mapped[bool] = mapped_column(Boolean, nullable=True)
    extraction_equipment: Mapped[bool] = mapped_column(Boolean, nullable=True)
    freq: Mapped[float] = mapped_column(Float, nullable=True)
    friendlies: Mapped[str] = mapped_column(String(255), nullable=True)
    hlz_marking: Mapped[int] = mapped_column(Integer, nullable=True)
    hlz_remarks: Mapped[str] = mapped_column(String(255), nullable=True)
    hoist: Mapped[bool] = mapped_column(Boolean, nullable=True)
    litter: Mapped[int] = mapped_column(Integer, nullable=True)
    marked_by: Mapped[str] = mapped_column(String(255), nullable=True)
    medline_remarks: Mapped[str] = mapped_column(String(255), nullable=True)
    nonus_civilian: Mapped[int] = mapped_column(Integer, nullable=True)
    nonus_military: Mapped[int] = mapped_column(Integer, nullable=True)
    obstacles: Mapped[str] = mapped_column(String(255), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=True)
    routine: Mapped[int] = mapped_column(Integer, nullable=True)
    security: Mapped[int] = mapped_column(Integer, nullable=True)
    terrain_loose: Mapped[bool] = mapped_column(Boolean, nullable=True)
    terrain_other: Mapped[bool] = mapped_column(Boolean, nullable=True)
    terrain_other_detail: Mapped[bool] = mapped_column(String(255), nullable=True)
    terrain_detail: Mapped[str] = mapped_column(String(255), nullable=True)
    terrain_none: Mapped[bool] = mapped_column(Boolean, nullable=True)
    terrain_rough: Mapped[bool] = mapped_column(Boolean, nullable=True)
    terrain_slope: Mapped[bool] = mapped_column(Boolean, nullable=True)
    terrain_slope_dir: Mapped[str] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    urgent: Mapped[int] = mapped_column(Integer, nullable=True)
    us_civilian: Mapped[int] = mapped_column(Integer, nullable=True)
    us_military: Mapped[int] = mapped_column(Integer, nullable=True)
    ventilator: Mapped[bool] = mapped_column(Boolean, nullable=True)
    winds_are_from: Mapped[str] = mapped_column(String(255), nullable=True)
    zone_prot_selection: Mapped[int] = mapped_column(Integer, nullable=True)
    point_id: Mapped[int] = mapped_column(Integer, ForeignKey("points.id", ondelete="CASCADE"), nullable=True)
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id", ondelete="CASCADE"), nullable=True)
    point = relationship("Point", back_populates="casevac")
    cot = relationship("CoT", back_populates="casevac")
    zmist = relationship("ZMIST", back_populates="casevac", uselist=False, cascade="all, delete")
    eud = relationship("EUD", back_populates="casevacs")

    def from_wtforms(self, form: CasEvacForm):
        self.uid = form.uid.data
        self.timestamp = form.timestamp.data
        self.ambulatory = form.ambulatory.data
        self.casevac = form.casevac.data
        self.child = form.child.data
        self.enemy = form.enemy.data
        self.epw = form.epw.data
        self.equipment_detail = form.equipment_detail.data
        self.equipment_none = form.equipment_none.data
        self.equipment_other = form.equipment_other.data
        self.extraction_equipment = form.extraction_equipment.data
        self.freq = form.freq.data
        self.friendlies = form.friendlies.data
        self.hlz_marking = form.hlz_marking.data
        self.hlz_remarks = form.hlz_remarks.data
        self.hoist = form.hoist.data
        self.litter = form.litter.data
        self.marked_by = form.marked_by.data
        self.medline_remarks = form.medline_remarks.data
        self.nonus_military = form.nonus_military.data
        self.nonus_civilian = form.nonus_civilian.data
        self.obstacles = form.obstacles.data
        self.priority = form.priority.data
        self.routine = form.routine.data
        self.security = form.security.data
        self.terrain_loose = form.terrain_loose.data
        self.terrain_other = form.terrain_other.data
        self.terrain_other_detail = form.terrain_other_detail.data
        self.terrain_detail = form.terrain_detail.data
        self.terrain_none = form.terrain_none.data
        self.terrain_rough = form.terrain_rough.data
        self.terrain_slope = form.terrain_slope.data
        self.terrain_slope_dir = form.terrain_slope_dir.data
        self.title = form.title.data
        self.urgent = form.urgent.data
        self.us_military = form.us_military.data
        self.us_civilian = form.us_civilian.data
        self.ventilator = form.ventilator.data
        self.winds_are_from = form.winds_are_from.data
        self.zone_prot_selection = form.zone_prot_selection.data

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
            'eud': self.eud.to_json() if self.eud else None,
            'point': self.point.to_json() if self.point else None,
            'icon': icon.to_json(),
            'start': iso8601_string_from_datetime(self.cot.start) if self.cot else None,
            'stale': iso8601_string_from_datetime(self.cot.stale) if self.cot else None,
        }

    def to_cot(self):
        event = ET.Element("event")
        event.set("type", "b-r-f-h-c")
        event.set("version", "2.0")
        event.set("how", "h-g-i-g-o")
        event.set("uid", self.uid)
        event.set("time", iso8601_string_from_datetime(self.point.timestamp))
        event.set("start", iso8601_string_from_datetime(self.point.timestamp))
        event.set("stale", iso8601_string_from_datetime(self.point.timestamp + timedelta(days=365)))

        cot_point = ET.SubElement(event, "point")
        cot_point.set("ce", str(self.point.ce))
        cot_point.set("hae", str(self.point.hae))
        cot_point.set("le", str(self.point.le))
        cot_point.set("lat", str(self.point.latitude))
        cot_point.set("lon", str(self.point.longitude))

        detail = ET.SubElement(event, "detail")

        status = ET.SubElement(detail, "status")
        status.set("readiness", "false")

        contact = ET.SubElement(detail, "contact")
        contact.set("callsign", current_user.username)

        link = ET.SubElement(detail, "link")
        link.set("parent_callsign", current_user.username)
        link.set("production_time", iso8601_string_from_datetime(self.point.timestamp))
        link.set("relation", "p-p")
        link.set("type", "b-r-f-h-c")
        link.set("uid", self.uid)

        medevac = ET.SubElement(detail, "_medevac_")
        medevac.set("title", self.title)
        if self.casevac is not None:
            medevac.set("casevac", str(self.casevac).lower())
        if self.child is not None:
            medevac.set("child", str(self.child))
        if self.enemy is not None:
            medevac.set("enemy", str(self.enemy))
        if self.friendlies is not None:
            medevac.set("friendlies", str(self.friendlies))
        if self.nonus_military is not None:
            medevac.set("nonus_military", str(self.nonus_military))
        if self.nonus_civilian is not None:
            medevac.set("nonus_civilian", str(self.nonus_civilian))
        if self.us_civilian is not None:
            medevac.set("us_civilian", str(self.us_civilian))
        if self.us_military is not None:
            medevac.set("us_military", str(self.us_military))
        if self.epw is not None:
            medevac.set("epw", str(self.epw))
        if self.freq != None:
            medevac.set("freq", str(self.freq))
        if self.extraction_equipment is not None:
            medevac.set("extraction_equipment", str(self.extraction_equipment).lower())
        if self.equipment_detail:
            medevac.set("equipment_detail", self.equipment_detail)
        if self.equipment_other is not None:
            medevac.set("equipment_other", str(self.equipment_other).lower())
        if self.equipment_none is not None:
            medevac.set("equipment_none", str(self.equipment_none).lower())
        if self.hoist is not None:
            medevac.set("hoist", str(self.hoist).lower())
        if self.litter is not None:
            medevac.set("litter", str(self.litter))
        if self.marked_by:
            medevac.set("marked_by", self.marked_by)
        if self.hlz_marking is not None:
            medevac.set("hlz_marking", str(self.hlz_marking))
        if self.hlz_remarks:
            medevac.set("hlz_remarks", self.hlz_remarks)
        if self.medline_remarks:
            medevac.set("medline_remarks", self.medline_remarks)
        if self.security is not None:
            medevac.set("security", str(self.security))
        if self.terrain_detail:
            medevac.set("terrain_detail", self.terrain_detail)
        if self.terrain_other_detail is not None:
            medevac.set("terrain_other_detail", str(self.terrain_other_detail).lower())
        if self.terrain_loose is not None:
            medevac.set("terrain_loose", str(self.terrain_loose).lower())
        if self.terrain_none is not None:
            medevac.set("terrain_none", str(self.terrain_none).lower())
        if self.terrain_rough is not None:
            medevac.set("terrain_rough", str(self.terrain_rough).lower())
        if self.terrain_slope is not None:
            medevac.set("terrain_slope", str(self.terrain_slope).lower())
        if self.terrain_slope_dir:
            medevac.set("terrain_slope_dir", self.terrain_slope_dir)
        if self.obstacles:
            medevac.set("obstacles", self.obstacles)
        if self.priority is not None:
            medevac.set("priority", str(self.priority))
        if self.routine is not None:
            medevac.set("routine", str(self.routine))
        if self.urgent is not None:
            medevac.set("urgent", str(self.urgent))
        if self.ventilator is not None:
            medevac.set("ventilator", str(self.ventilator).lower())
        if self.winds_are_from:
            medevac.set("winds_are_from", self.winds_are_from)
        if self.zone_prot_selection is not None:
            medevac.set("zone_prot_selection", str(self.zone_prot_selection))

        if self.zmist:
            zmist_map = ET.SubElement(medevac, "zMistsMap")
            zmist_tag = ET.SubElement(zmist_map, "zMist")
            if self.zmist.i:
                zmist_tag.set("i", self.zmist.i)
            else:
                zmist_tag.set("i", "")
            if self.zmist.m:
                zmist_tag.set("m", self.zmist.m)
            else:
                zmist_tag.set("m", "")
            if self.zmist.s:
                zmist_tag.set("s", self.zmist.s)
            else:
                zmist_tag.set("s", "")
            if self.zmist.t:
                zmist_tag.set("t", self.zmist.t)
            else:
                zmist_tag.set("t", "")
            if self.zmist.title:
                zmist_tag.set("title", self.zmist.title)
            else:
                zmist_tag.set("title", "ZMIST1")
            if self.zmist.z:
                zmist_tag.set("z", self.zmist.z)
            else:
                zmist_tag.set("z", "")

        return event
