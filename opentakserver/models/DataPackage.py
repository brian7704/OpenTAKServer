from dataclasses import dataclass

from extensions import db
from sqlalchemy import Integer, String, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class DataPackage(db.Model):
    __tablename__ = 'data_packages'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String, unique=True)
    hash: Mapped[str] = mapped_column(String, unique=True)
    creator_uid: Mapped[str] = mapped_column(String, ForeignKey("eud.uid"))
    submission_time: Mapped[str] = mapped_column(String)
    submission_user: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=True)
    keywords: Mapped[str] = mapped_column(String, nullable=True)
    mime_type: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(String, nullable=True)
    expiration: Mapped[str] = mapped_column(String, nullable=True)
    eud: Mapped["EUD"] = relationship(back_populates="data_packages")

    def serialize(self):
        return {
            'data_package': {
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
                'eud': self.eud.serialize() if self.eud else None
            }
        }