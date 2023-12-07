from opentakserver.extensions import Base
from sqlalchemy import Integer, String, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship


class DataPackage(Base):
    __tablename__ = 'data_packages'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String)
    hash: Mapped[str] = mapped_column(String)
    creatorUid: Mapped[str] = mapped_column(String, ForeignKey("eud.uid"))
    eud: Mapped["EUD"] = relationship(back_populates="data_packages")
