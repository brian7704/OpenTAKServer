from extensions import db
from sqlalchemy import Integer, String, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Point(db.Model):
    __tablename__ = "points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
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
    eud: Mapped["EUD"] = relationship(back_populates="points")
