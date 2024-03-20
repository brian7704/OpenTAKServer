from dataclasses import dataclass
from datetime import datetime

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.functions import iso8601_string_from_datetime


@dataclass
class DataPackage(db.Model):
    __tablename__ = 'data_packages'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String, unique=True)
    hash: Mapped[str] = mapped_column(String, unique=True)
    creator_uid: Mapped[str] = mapped_column(String, ForeignKey("euds.uid"))
    submission_time: Mapped[datetime] = mapped_column(DateTime)
    submission_user: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=True)
    keywords: Mapped[str] = mapped_column(String, nullable=True)
    mime_type: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(String, nullable=True)
    expiration: Mapped[str] = mapped_column(String, nullable=True)
    eud: Mapped["EUD"] = relationship(back_populates="data_packages")
    certificate = relationship("Certificate", back_populates="data_package", uselist=False)
    user = relationship("User", back_populates="data_packages")

    def serialize(self):
        return {
            'filename': self.filename,
            'hash': self.hash,
            'creator_uid': self.creator_uid,
            'submission_time': self.submission_time,
            'submission_user': self.submission_user,
            'keywords': self.keywords,
            'mime_type': self.mime_type,
            'size': self.size,
            'tool': self.tool,
            'expiration': self.expiration,
        }

    def to_json(self, include_eud=True):
        return {
            'filename': self.filename,
            'hash': self.hash,
            'creator_uid': self.creator_uid,
            'submission_time': iso8601_string_from_datetime(self.submission_time),
            'submission_user': self.user.username if self.user else None,
            'keywords': self.keywords,
            'mime_type': self.mime_type,
            'size': self.size,
            'tool': self.tool,
            'expiration': self.expiration,
            'eud': self.eud.to_json(False) if include_eud and self.eud else None
        }