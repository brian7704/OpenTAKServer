from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class VideoRecording(db.Model):
    __tablename__ = 'video_recordings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_path: Mapped[str] = mapped_column(String, unique=True)
    path: Mapped[str] = mapped_column(String, ForeignKey("video_streams.path"))
    in_progress: Mapped[bool] = mapped_column(Boolean)
    start_time: Mapped[DateTime] = mapped_column(DateTime, nullable=True)
    stop_time: Mapped[DateTime] = mapped_column(DateTime, nullable=True)
    duration: Mapped[int] = mapped_column(Integer, nullable=True)
    video_stream = relationship("VideoStream", back_populates="recordings")

    def serialize(self):
        return {
            'segment_path': self.segment_path,
            'path': self.path,
            'in_progress': self.in_progress
        }

    def to_json(self):
        return {
            'segment_path': self.segment_path,
            'path': self.path,
            'in_progress': self.in_progress,
            'video_stream': self.video_stream.to_json() if self.video_stream else None
        }