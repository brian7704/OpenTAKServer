from extensions import db
from sqlalchemy import Integer, String, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship


class DataPackage(db.Model):
    __tablename__ = 'data_packages'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String, unique=True)
    hash: Mapped[str] = mapped_column(String, unique=True)
    creator_uid: Mapped[str] = mapped_column(String, ForeignKey("eud.uid"))
    submission_time: Mapped[str] = mapped_column(String)
    submission_user: Mapped[str] = mapped_column(String, nullable=True)
    keywords: Mapped[str] = mapped_column(String, nullable=True)
    mime_type: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(String, nullable=True)
    expiration: Mapped[str] = mapped_column(String, nullable=True)
    # eud: Mapped["EUD"] = relationship(back_populates="data_packages")
