from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship


class ZMIST(db.Model):
    __tablename__ = 'zmist'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    i: Mapped[str] = mapped_column(String, nullable=True)  # injury_sustained
    m: Mapped[str] = mapped_column(String, nullable=True)  # mechanism_of_injury
    s: Mapped[str] = mapped_column(String, nullable=True)  # symptoms_and_signs
    t: Mapped[str] = mapped_column(String, nullable=True)  # treatment_given
    title: Mapped[str] = mapped_column(String, nullable=True)
    z: Mapped[int] = mapped_column(Integer, nullable=True)  # zap_number
    casevac_uid: Mapped[str] = mapped_column(String, ForeignKey("casevac.uid"))
    casevac = relationship("CasEvac", back_populates="zmist")

    def serialize(self):
        return {
            'i': self.i,
            'm': self.m,
            's': self.s,
            't': self.t,
            'title': self.title,
            'z': self.z
        }

    def to_json(self):
        return self.serialize()
