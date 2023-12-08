from opentakserver.extensions import Base
from sqlalchemy import Integer, String, ForeignKey, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship


class CasEvac(Base):
    __tablename__ = 'casevac'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_uid: Mapped[str] = mapped_column(String, ForeignKey("eud.id"))
    uid: Mapped[str] = mapped_column(String, unique=True)
    timestamp: Mapped[str] = mapped_column(String)

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
