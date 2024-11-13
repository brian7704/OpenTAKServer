import datetime
import uuid
from dataclasses import dataclass

from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.extensions import db
from sqlalchemy import Integer, String, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class MissionContent(db.Model):
    __tablename__ = "mission_content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keywords: Mapped[JSON] = mapped_column(JSON, nullable=True)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=True)
    submission_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    submitter: Mapped[str] = mapped_column(String(255), nullable=True)
    uid: Mapped[str] = mapped_column(String(255), unique=True, default=str(uuid.uuid4()))
    creator_uid: Mapped[str] = mapped_column(String(255), nullable=True)
    hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    size: Mapped[int] = mapped_column(Integer, nullable=True)
    expiration: Mapped[int] = mapped_column(Integer, nullable=True)
    mission_changes = relationship("MissionChange", back_populates="content_resource")
    mission = relationship("Mission", secondary="mission_content_mission", back_populates="contents")

    def serialize(self):
        return {
            "keywords": self.keywords,
            "mime_type": self.mime_type,
            "filename": self.filename,
            "submission_time": self.submission_time,
            "submitter": self.submitter,
            "uid": self.uid,
            "creator_uid": self.creator_uid,
            "hash": self.hash,
            "size": self.size,
            "expiration": self.expiration
        }

    def to_json(self):
        return {
            "data": {
                "keywords": self.keywords if self.keywords else [],
                "mimeType": self.mime_type,
                "name": self.filename,
                "submissionTime": iso8601_string_from_datetime(self.submission_time),
                "submitter": self.submitter,
                "uid": self.uid,
                "creator_uid": self.creator_uid,
                "hash": self.hash,
                "size": self.size,
                "expiration": self.expiration
            },
            "timestamp": iso8601_string_from_datetime(self.submission_time),
            "creatorUid": self.creator_uid
        }
