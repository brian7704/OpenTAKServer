from typing import List

from opentakserver.extensions import Base
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship


class EUD(Base):
    __tablename__ = "eud"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    callsign: Mapped[str] = mapped_column(String, nullable=True)
    device: Mapped[str] = mapped_column(String, nullable=True)
    os: Mapped[str] = mapped_column(String, nullable=True)
    platform: Mapped[str] = mapped_column(String, nullable=True)
    version: Mapped[str] = mapped_column(String, nullable=True)
    phone_number: Mapped[int] = mapped_column(Integer, nullable=True)
    points: Mapped[List["Point"]] = relationship(back_populates="eud")
    cots: Mapped[List["CoT"]] = relationship(back_populates="eud")
    # data_packages: Mapped[List["DataPackage"]] = relationship(back_populates="eud")
