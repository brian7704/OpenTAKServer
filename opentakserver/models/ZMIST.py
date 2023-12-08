from opentakserver.extensions import Base
from sqlalchemy import Integer, String, ForeignKey, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship


class ZMIST(Base):
    __tablename__ = 'zmist'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    i: Mapped[str] = mapped_column(String, nullable=True)  # injury_sustained
    m: Mapped[str] = mapped_column(String, nullable=True)  # mechanism_of_injury
    s: Mapped[str] = mapped_column(String, nullable=True)  # symptoms_and_signs
    t: Mapped[str] = mapped_column(String, nullable=True)  # treatment_given
    title: Mapped[str] = mapped_column(String, nullable=True)
    z: Mapped[int] = mapped_column(Integer, nullable=True)  # zap_number
    casevac_id: Mapped[int] = mapped_column(Integer, ForeignKey("casevac.id"))
